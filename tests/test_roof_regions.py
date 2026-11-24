"""Stepped roofs, real small towers, noisy maxima and unchanged source identity."""
import json,math,hashlib
from pathlib import Path
import numpy as np
import pytest
from shapely.geometry import box,Polygon,shape
from shapely.ops import unary_union
from shapely.affinity import translate
from lodext.core.roof_regions import RoofRegionsConfig
from lodext.reconstruction.roof_regions import fit_roof_regions


def synthetic_cells(geometry,flat=False):
    """Independent 1 m cells with six returns, four true roof levels and noise."""
    cells={}
    for ix in range(40):
        for iy in range(40):
            x,y=ix+.5,iy+.5
            if not geometry.covers(box(ix,iy,ix+1,iy+1).centroid):continue
            z=25. if flat else 15. if ix<10 else 20. if ix<20 else 25.
            if not flat and 25<=ix<33 and 16<=iy<24:z=45.
            cells[ix,iy]={int(z):[6,6*z]}
    # A high outlier layer in a single cell cannot become a tower.
    cells[3,3][80]=[6,480.]
    return cells


@pytest.mark.parametrize('offset',[(0.,0.),(455000.00023,3110000.00017)])
def test_terraces_and_small_tower_keep_source_partition_and_reject_single_high_cell(offset):
    local=Polygon([(0,0),(40,0),(40,40),(0,40)],[[(12,8),(16,8),(16,12),(12,12)]])
    geometry=translate(local,xoff=offset[0],yoff=offset[1]);c=RoofRegionsConfig(enabled=True)
    result=fit_roof_regions(geometry,geometry,synthetic_cells(local),5.,25.,c,precision_m=.001,xy_origin=offset)
    assert result['accepted'],result
    regions=result['regions'];assert sorted(set(r['roof_z'] for r in regions))==[15.,20.,25.,45.]
    polygons=[shape(r['footprint']) for r in regions];union=unary_union(polygons)
    assert abs(sum(p.area for p in polygons)-union.area)<1e-6
    assert union.symmetric_difference(geometry).area<geometry.length*.002
    assert not union.covers(translate(box(13,9,15,11),xoff=offset[0],yoff=offset[1]))
    assert all(p.is_valid for p in polygons)
    tower=unary_union([shape(r['footprint']) for r in regions if r['roof_z']==45])
    assert 50<tower.area<90


def test_flat_roof_with_small_high_noise_stays_single_roof():
    g=box(0,0,40,40)
    r=fit_roof_regions(g,g,synthetic_cells(g,True),5.,25.,RoofRegionsConfig(),precision_m=.001,xy_origin=(0,0))
    assert not r['accepted']


def test_low_terrace_step_is_not_erased_by_a_large_higher_roof():
    g=box(0,0,40,40);cells={(ix,iy):{31 if ix<5 else 33:[6,6*(31.4 if ix<5 else 33.2)]} for ix in range(40) for iy in range(40)}
    r=fit_roof_regions(g,g,cells,25.,33.2,RoofRegionsConfig(),precision_m=.001,xy_origin=(0,0))
    assert r['accepted']
    assert sorted(set(round(p['roof_z'],1) for p in r['regions']))==[31.4,33.2]


def test_disordered_canopy_cannot_supply_supported_roof_regions():
    g=box(0,0,40,40);rng=np.random.default_rng(517)
    cells={(ix,iy):{int(z):[3,3*z]} for (ix,iy),z in zip(synthetic_cells(g),rng.uniform(10,55,1600))}
    r=fit_roof_regions(g,g,cells,5.,25.,RoofRegionsConfig(),precision_m=.001,xy_origin=(0,0))
    assert not r['accepted']


@pytest.mark.parametrize('bad',[{'enabled':1},{'cell_size_m':0},{'min_coverage':1.1},{'min_cell_points':True},{'max_regions':1},{'object_ids':[]},{'object_ids':['part7']},{'object_ids':['BuildingPart::a','BuildingPart::a']},{'simplify_m':-1}])
def test_invalid_configuration_rejected(bad):
    with pytest.raises(ValueError):RoofRegionsConfig(**bad)


@pytest.mark.parametrize('use_dtm',[False,True])
def test_native_pipeline_exports_several_roofs_under_original_id_and_both_ground_modes(tmp_path,use_dtm):
    import laspy
    from jsonschema import Draft7Validator
    from lodext.demo import create_demo
    from lodext.pipeline import run_build
    root=tmp_path/'inputs';create_demo(root)
    cfg=json.loads((root/'build.lidar.json').read_text())
    if use_dtm:cfg['dtm']='dtm.tif'
    cfg['roof_regions']={'enabled':True,'object_ids':['BuildingPart::court']}
    p=root/'cloud.las';cloud=laspy.read(p);x=np.asarray(cloud.x)-500000;y=np.asarray(cloud.y)-3100000;z=np.asarray(cloud.z).copy()
    mask=(np.asarray(cloud.classification)==6)&(x<20)&(y<20)
    z[mask]=np.where(x[mask]<6,31.,35.)
    z[mask&(x>15)&(y>6)&(y<14)]=44.
    cloud.z=z;cloud.write(p)
    before={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['cloud.las','footprints.gpkg','dtm.tif']}
    (root/'regions.json').write_text(json.dumps(cfg));run_build(root/'regions.json',tmp_path/'built')
    q=json.loads((tmp_path/'built/quality.json').read_text());row=next(r for r in q['objects'] if r['key']=='BuildingPart::court')
    assert row['roof_regions']['accepted'] and row['method']=='roof_regions'
    assert row['ground_z']==pytest.approx(25) and row['reconstructed_top_z']==pytest.approx(44) and row['height_m']==pytest.approx(19)
    assert min(r['roof_z'] for r in row['roof_regions']['regions'])==31
    model=json.loads((tmp_path/'built/model.lod1.city.json').read_text())
    Draft7Validator(json.loads(Path('tests/schemas/cityjson-2.0.1.schema.json').read_text())).validate(model)
    assert len(model['CityObjects'])==9
    obj=model['CityObjects']['BuildingPart::court'];assert len(obj['geometry'])>=3 and all(g['type']=='Solid' for g in obj['geometry'])
    assert obj['parents']==['Building::b-court']
    assert obj['attributes']['roof_regions']['accepted']
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    # Default omission preserves the historical one-flat-roof path.
    cfg.pop('roof_regions');(root/'flat.json').write_text(json.dumps(cfg));run_build(root/'flat.json',tmp_path/'flat')
    flat=json.loads((tmp_path/'flat/model.lod1.city.json').read_text());assert len(flat['CityObjects']['BuildingPart::court']['geometry'])==1
    if not use_dtm:
        cfg['roof_regions']={'enabled':True,'object_ids':['BuildingPart::unknown']}
        (root/'invalid.json').write_text(json.dumps(cfg))
        with pytest.raises(ValueError,match='Unknown roof_regions.object_ids'):run_build(root/'invalid.json',tmp_path/'invalid')
        assert not (tmp_path/'invalid').exists()
        cfg['roof_regions']={'enabled':True,'object_ids':['BuildingPart::court'],'max_cells_per_object':1}
        (root/'budget.json').write_text(json.dumps(cfg))
        with pytest.raises(ValueError,match='roof_regions cell budget'):run_build(root/'budget.json',tmp_path/'budget')
        assert not (tmp_path/'budget').exists()


def test_supported_regions_do_not_require_a_previous_flat_roof_height():
 g=box(0,0,40,40);r=fit_roof_regions(g,g,synthetic_cells(g),5.,None,RoofRegionsConfig(),precision_m=.001,xy_origin=(0,0))
 assert r['accepted'] and len(r['regions'])>=4
 assert r['remainder_reference_z'] in [15.,20.,25.,45.]
 assert all(part['roof_z']>5 for part in r['regions'])


def test_interior_base_returns_do_not_reject_supported_upper_roof_regions():
 g=box(0,0,40,40);cells=synthetic_cells(g)
 for ix in range(4):
  for iy in range(40):cells[ix,iy]={5:[6,30.]}
 r=fit_roof_regions(g,g,cells,5.,None,RoofRegionsConfig(),precision_m=.001,xy_origin=(0,0))
 assert r['accepted'] and all(part['roof_z']>5 for part in r['regions'])


def test_native_regions_recover_a_body_without_a_single_roof_solution(tmp_path,monkeypatch):
 import laspy,sqlite3
 from lodext.demo import create_demo
 from lodext.pipeline import run_build
 import lodext.io.building_surfaces as surfaces
 root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.lidar.json').read_text());cfg['external_height_fallback']=False
 cfg['roof_regions']={'enabled':True,'object_ids':['BuildingPart::court']}
 with sqlite3.connect(root/'footprints.gpkg') as db:db.execute("UPDATE building_parts SET storeys_above=NULL WHERE part_id='court'")
 cloud=laspy.read(root/'cloud.las');x=np.asarray(cloud.x)-500000;y=np.asarray(cloud.y)-3100000;z=np.asarray(cloud.z).copy()
 mask=(np.asarray(cloud.classification)==6)&(x<20)&(y<20);z[mask]=np.where(x[mask]<6,31.,35.);z[mask&(x>15)&(y>6)&(y<14)]=44.;cloud.z=z;cloud.write(root/'cloud.las')
 original=surfaces.sample_building_surfaces
 def ambiguous_flat(*args,**kwargs):
  original(*args,**kwargs);sample=args[3]['BuildingPart::court'];sample['roof_z']=[];sample['roof_surface']={'accepted':False,'roof_z':None}
 monkeypatch.setattr(surfaces,'sample_building_surfaces',ambiguous_flat)
 (root/'regions.json').write_text(json.dumps(cfg));run_build(root/'regions.json',tmp_path/'built')
 q=json.loads((tmp_path/'built/quality.json').read_text());row=next(r for r in q['objects'] if r['key']=='BuildingPart::court')
 assert row['status']=='resolved' and row['method']=='roof_regions'
 assert row['roof_regions']['original_roof_z'] is None
 assert row['reconstructed_top_z']==pytest.approx(44) and row['height_m']==pytest.approx(19)
 model=json.loads((tmp_path/'built/model.lod1.city.json').read_text());assert len(model['CityObjects']['BuildingPart::court']['geometry'])>=3


def test_native_overlayered_column_is_explicitly_unusable_not_a_citywide_failure(tmp_path):
 import laspy
 from lodext.demo import create_demo
 from lodext.pipeline import run_build
 root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.lidar.json').read_text())
 cfg['roof_regions']={'enabled':True,'object_ids':['BuildingPart::court'],'max_layers_per_cell':2}
 cloud=laspy.read(root/'cloud.las');x=np.asarray(cloud.x)-500000;y=np.asarray(cloud.y)-3100000;z=np.asarray(cloud.z).copy()
 mask=(np.asarray(cloud.classification)==6)&(x<20)&(y<20)
 z[mask]=np.where(x[mask]<6,31.,35.);z[mask&(x>15)&(y>6)&(y<14)]=44.
 indices=np.flatnonzero(mask&(x<1)&(y<1));assert len(indices)>=3
 z[indices[:2]]=[140.,141.];cloud.z=z;cloud.write(root/'cloud.las')
 digest=hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()
 (root/'regions.json').write_text(json.dumps(cfg));run_build(root/'regions.json',tmp_path/'built')
 row=next(r for r in json.loads((tmp_path/'built/quality.json').read_text())['objects'] if r['key']=='BuildingPart::court')
 assert row['roof_regions']['unusable_vertical_cells']>=1
 assert 'roof_regions_unusable_vertical_cells' in row['flags']
 assert row['roof_regions']['accepted'] and row['reconstructed_top_z']==pytest.approx(44)
 assert hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()==digest
