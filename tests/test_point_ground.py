"""Physical and provenance checks for the DTM-free reconstruction path."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pytest
import laspy
from jsonschema import Draft7Validator
from shapely import from_wkb,intersects_xy
from shapely.geometry import Polygon
from shapely.ops import unary_union

from lodext.demo import create_demo
from lodext.core.config import BuildConfig
from lodext.core.ground import PointGroundConfig
from lodext.pipeline import run_build
from lodext.io.footprints import read_footprints


def inputs(tmp_path,**changes):
    """Remove the test raster physically: a successful build cannot read it."""
    root=tmp_path/'inputs';create_demo(root)
    data=json.loads((root/'build.json').read_text());data.pop('dtm');data['roof_classes']=None;data.update(changes)
    (root/'dtm.tif').unlink();(root/'build.json').write_text(json.dumps(data))
    return root


def rows(output):
    return {r['source_id']:r for r in json.loads((output/'quality.json').read_text())['objects'] if r['kind']=='BuildingPart'}


def test_direct_ground_builds_known_nonzero_base_audit_and_combined_scene(tmp_path):
    root=inputs(tmp_path,ground={'export_points':True});output=tmp_path/'result'
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    result=run_build(root/'build.json',output)
    assert result['status']=='complete' and result['resolved_units']==5
    assert all(r['ground_z']==pytest.approx(25) and r['ground_method']=='geometric_exterior_plane' for r in rows(output).values())
    assert not list(output.glob('*.tif'))
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    schema=json.loads(Path('tests/schemas/cityjson-2.0.1.schema.json').read_text())
    for name in ['model.lod0.city.json','model.lod1.city.json','ground.city.json','scene.lod1.city.json']:
        model=json.loads((output/name).read_text());Draft7Validator(schema).validate(model)
    building=json.loads((output/'model.lod1.city.json').read_text());scene=json.loads((output/'scene.lod1.city.json').read_text())
    assert building['vertices']==scene['vertices'][:len(building['vertices'])]
    assert all(scene['CityObjects'][k]==v for k,v in building['CityObjects'].items())
    with sqlite3.connect(output/'ground.sample.gpkg') as db:
        assert db.execute('select count(*) from ground_points').fetchone()[0]>20
        assert {v[0] for v in db.execute('select distinct original_class from ground_points')}=={2,6}
        fid,blob,x,y,z,index=db.execute('select fid,geom,x,y,z,source_record from ground_points limit 1').fetchone()
        assert from_wkb(blob[8:]).coords[0]==(x,y,z)
        cloud=laspy.read(root/'cloud.las');assert (cloud.x[index],cloud.y[index],cloud.z[index])==(x,y,z)


def test_ground_class_inside_building_is_audited_without_reclassifying_or_using_it(tmp_path):
    root=inputs(tmp_path,ground={'export_points':True});cloud=laspy.read(root/'cloud.las')
    i=np.flatnonzero(np.asarray(cloud.classification)==6)[0]
    cloud.classification[i]=2;cloud.z[i]=999;cloud.write(root/'cloud.las')
    output=tmp_path/'result';run_build(root/'build.json',output)
    assert all(r['ground_z']==pytest.approx(25) for r in rows(output).values())
    with sqlite3.connect(output/'ground.sample.gpkg') as db:
        decision,z,original=db.execute('select decision,z,original_class from ground_points where source_record=?',(int(i),)).fetchone()
        assert (decision,z,original)==('inside_building',999,2)
    assert laspy.read(root/'cloud.las').classification[i]==2
    assert json.loads((output/'quality.json').read_text())['cloud']['ground_points']['inside_building']>0


def test_sloping_ground_uses_lowest_coherent_exterior_contact_for_flat_lod1_base(tmp_path):
    root=inputs(tmp_path,ground={'surface_cell_size_m':8,'surface_max_edge_m':20})
    cloud=laspy.read(root/'cloud.las');g=np.asarray(cloud.classification)==2
    z=np.asarray(cloud.z).copy();z[g]=25+.02*(np.asarray(cloud.x)[g]-cloud.header.offsets[0]);cloud.z=z;cloud.write(root/'cloud.las')
    cfg=BuildConfig.read(root/'build.json');features,_=read_footprints(cfg,root);obstacles=unary_union([f.geometry for f in features])
    output=tmp_path/'result';run_build(root/'build.json',output)
    for f in features:
        if f.kind!='BuildingPart':continue
        r=rows(output)[f.id];free=f.geometry.buffer(r['ground_radius_m']).difference(obstacles)
        keep=g&intersects_xy(free,np.asarray(cloud.x),np.asarray(cloud.y))&~intersects_xy(obstacles,np.asarray(cloud.x),np.asarray(cloud.y))
        assert r['ground_z']==pytest.approx(r['ground_min_z'],abs=1e-9)
        assert r['ground_z']<25+.02*(f.geometry.representative_point().x-cloud.header.offsets[0])
        assert r['ground_samples']>=3
        assert r['ground_plane']['rmse_m']<.001


def test_terrain_never_bridges_occupied_footprints_or_exceeds_edge_limit(tmp_path):
    root=inputs(tmp_path);output=tmp_path/'result';run_build(root/'build.json',output)
    cfg=BuildConfig.read(root/'build.json');features,_=read_footprints(cfg,root);occupied=unary_union([f.geometry for f in features])
    for name in ['ground.city.json','scene.lod1.city.json']:
        model=json.loads((output/name).read_text());xyz=np.asarray(model['vertices'])*model['transform']['scale']+model['transform']['translate']
        faces=model['CityObjects']['Terrain::lidar-ground']['geometry'][0]['boundaries']
        assert faces
        for face in faces:
            p=xyz[face[0]];assert not Polygon(p[:,:2]).intersects(occupied)
            assert np.linalg.norm(p[:,:2]-np.roll(p[:,:2],1,axis=0),axis=1).max()<=6.002
            assert np.allclose(p[:,2],25,atol=1e-9)


@pytest.mark.parametrize('mode',['lod0','known'])
def test_ground_points_are_still_read_without_roof_estimation(tmp_path,mode):
    changes={'lods':[0]} if mode=='lod0' else {'height_source':'known','external_height_fallback':False}
    root=inputs(tmp_path,**changes);output=tmp_path/'result';run_build(root/'build.json',output)
    assert all(r['ground_z']==pytest.approx(25) for r in rows(output).values())
    assert all(r['n_points']==0 for r in rows(output).values())
    assert all(r['method']==('lidar_ground_surface' if mode=='lod0' else 'known_height') for r in rows(output).values())


def test_missing_ground_is_not_zero_and_does_not_use_roofs(tmp_path):
    root=inputs(tmp_path);cloud=laspy.read(root/'cloud.las');cloud.points=cloud.points[np.asarray(cloud.classification)!=2];cloud.write(root/'cloud.las')
    output=tmp_path/'result';result=run_build(root/'build.json',output)
    assert result['unresolved_units']==5
    assert all(r['ground_z'] is None and r['height_m'] is None for r in rows(output).values())
    assert not (output/'ground.city.json').exists()


def test_negative_ground_uses_same_z_basis_for_roofs(tmp_path):
    root=inputs(tmp_path);cloud=laspy.read(root/'cloud.las');cloud.z=np.asarray(cloud.z)-30;cloud.write(root/'cloud.las')
    output=tmp_path/'result';run_build(root/'build.json',output)
    assert all(r['ground_z']==pytest.approx(-5) for r in rows(output).values())
    assert rows(output)['terrace']['reconstructed_top_z']==pytest.approx(-3.0)  # Existing 0.5 m modal bin; no zero-ground clamp.


def test_optional_terrain_and_audit_outputs_can_be_disabled_explicitly(tmp_path):
    root=inputs(tmp_path,ground={'export_points':False,'export_surface':False});output=tmp_path/'result';run_build(root/'build.json',output)
    assert set(p.name for p in output.iterdir())=={'model.lod0.city.json','model.lod1.city.json','quality.json','objects.csv','run.json'}


@pytest.mark.parametrize('settings',[{'max_surface_vertices':3},{'max_histogram_bins':3}])
def test_explicit_point_budgets_abort_without_partial_output(tmp_path,settings):
    root=inputs(tmp_path,ground=settings);output=tmp_path/'result'
    with pytest.raises(ValueError,match='exceed'):run_build(root/'build.json',output)
    assert not output.exists()


@pytest.mark.parametrize('settings',[{'classes':[]},{'classes':[True]},{'export_surface':'false'},{'surface_cell_size_m':0},{'max_surface_vertices':False}])
def test_invalid_direct_ground_settings_are_rejected(settings):
    with pytest.raises(ValueError):PointGroundConfig(**settings)


def test_missing_dtm_requires_lidar_even_for_known_or_lod0_and_rejects_competing_ground_sources():
    data={'config_version':'1','contract_version':'0.2','dataset_id':'test','geometry_mode':'parts','footprints':'input.gpkg','working_epsg':25828,'vertical_reference':'local_relative','lods':[0]}
    with pytest.raises(ValueError,match='direct ground'):BuildConfig(**data)
    with pytest.raises(ValueError,match='choose one ground source'):BuildConfig(**data,lidar=['a.las'],dtm='a.tif',ground={})


def test_default_never_duplicates_point_cloud_and_histograms_do_not_grow_with_repeated_returns(tmp_path):
    root=inputs(tmp_path,ground={'export_surface':False});cloud=laspy.read(root/'cloud.las')
    run_build(root/'build.json',tmp_path/'baseline')
    baseline=json.loads((tmp_path/'baseline/quality.json').read_text())['cloud']['ground_statistics']
    cloud.points=laspy.ScaleAwarePointRecord(np.repeat(cloud.points.array,20),cloud.header.point_format,cloud.header.scales,cloud.header.offsets)
    cloud.write(root/'cloud.las');output=tmp_path/'result';run_build(root/'build.json',output)
    report=json.loads((output/'quality.json').read_text());stats=report['cloud']['ground_statistics']
    assert report['cloud']['points_decoded']>100000
    assert stats['retained_histogram_bins']==baseline['retained_histogram_bins'] and stats['peak_histogram_bins']==baseline['peak_histogram_bins']
    assert stats['complete_point_cache'] is False and stats['exported_debug_points']==0
    assert not list(output.glob('*.gpkg'))
    assert all(r['ground_z']==pytest.approx(25) for r in rows(output).values())


def test_histogram_resolution_has_explicit_metre_error_bound_without_changing_source_z(tmp_path):
    root=inputs(tmp_path,ground={'quantile_step_m':0.01,'export_surface':False});cloud=laspy.read(root/'cloud.las')
    ground=np.asarray(cloud.classification)==2;z=np.asarray(cloud.z).copy();z[ground]=25.004;cloud.z=z;cloud.write(root/'cloud.las')
    output=tmp_path/'result';run_build(root/'build.json',output)
    for r in rows(output).values():
        assert r['ground_median_error_bound_m'] is None
        assert r['ground_z']==pytest.approx(25.004,abs=1e-9)
        assert r['ground_plane']['rmse_m']<1e-9
        assert r['ground_min_z']==pytest.approx(25.004)
    assert np.allclose(np.asarray(laspy.read(root/'cloud.las').z)[ground],25.004)


def test_debug_point_export_is_explicit_and_capped(tmp_path):
    root=inputs(tmp_path,ground={'export_points':True,'max_export_points':5,'export_surface':False})
    output=tmp_path/'result';run_build(root/'build.json',output)
    with sqlite3.connect(output/'ground.sample.gpkg') as db:assert db.execute('select count(*) from ground_points').fetchone()[0]==5
    assert json.loads((output/'quality.json').read_text())['cloud']['ground_statistics']['exported_debug_points']==5


def test_input_tile_terrain_keeps_ground_far_from_buildings_without_changing_bases(tmp_path):
    root=inputs(tmp_path)
    cloud=laspy.read(root/'cloud.las')
    extra=laspy.LasData(cloud.header.copy())
    x,y=np.meshgrid(np.arange(500040,500060,2),np.arange(3100100,3100120,2))
    extra.points=laspy.ScaleAwarePointRecord.zeros(x.size,header=extra.header)
    extra.x=x.ravel();extra.y=y.ravel();extra.z=np.full(x.size,30.)
    extra.classification=np.full(x.size,2,dtype=np.uint8);extra.write(root/'distant.las')
    cfg=json.loads((root/'build.json').read_text());cfg['lidar'].append('distant.las')
    (root/'build.json').write_text(json.dumps(cfg));run_build(root/'build.json',tmp_path/'context')
    old=rows(tmp_path/'context')
    cfg['ground']={'surface_scope':'input_tiles'};(root/'build.json').write_text(json.dumps(cfg));run_build(root/'build.json',tmp_path/'tiles')
    new=rows(tmp_path/'tiles');assert {k:r['ground_z'] for k,r in new.items()}=={k:r['ground_z'] for k,r in old.items()}
    for directory,expected in [('context',False),('tiles',True)]:
        model=json.loads((tmp_path/directory/'ground.city.json').read_text())
        xyz=np.array(model['vertices'])*model['transform']['scale']+model['transform']['translate']
        assert bool(np.any((xyz[:,1]>=3100100)&(xyz[:,2]==30)))==expected
    assert json.loads((tmp_path/'tiles/run.json').read_text())['configuration']['ground']['surface_scope']=='input_tiles'


@pytest.mark.parametrize('policy',[{'surface_scope':'invalid'},{'surface_scope':'input_tiles','export_surface':False}])
def test_invalid_surface_scope_fails(policy):
    with pytest.raises(ValueError):PointGroundConfig(**policy)
