"""Production integration: measured pitched roofs must survive as flat LoD1."""
import hashlib,json,sqlite3
from dataclasses import replace
import numpy as np
import pytest
import laspy
from shapely import intersects_xy
from lodext.demo import create_demo
from lodext.pipeline import run_build
from lodext.core.config import BuildConfig
from lodext.core.roof_surfaces import RoofSurfaceConfig
from lodext.io.footprints import read_footprints
from jsonschema import Draft7Validator
from pathlib import Path


@pytest.mark.parametrize('shape',['gable','asymmetric','double','flat_steps','gentle','steep'])
@pytest.mark.parametrize('use_dtm',[False,True])
def test_native_builder_recovers_inclined_courtyard_without_storeys_or_lod2(tmp_path,shape,use_dtm):
    root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.json').read_text())
    if not use_dtm:cfg.pop('dtm')
    cfg.update(roof_classes=None,roof_surfaces={'enabled':True},external_height_fallback=False)
    config=root/'build.json';config.write_text(json.dumps(cfg))
    with sqlite3.connect(root/'footprints.gpkg') as db:db.execute("UPDATE building_parts SET storeys_above=NULL WHERE part_id='court'")
    features,_=read_footprints(BuildConfig.read(config),root);f=next(f for f in features if f.id=='court')
    p=laspy.read(root/'cloud.las');x,y=np.asarray(p.x),np.asarray(p.y);mask=(np.asarray(p.classification)==6)&intersects_xy(f.geometry,x,y)
    local=x[mask]-500000
    if shape=='gable':roof=40-.6*np.abs(local-10)
    elif shape=='asymmetric':roof=np.where(local<8,40-.6*(8-local),40-.4*(local-8))
    elif shape=='double':roof=40-.8*np.abs((local%10)-5)
    elif shape=='flat_steps':roof=np.where(local<10,37.,40.)
    elif shape=='gentle':roof=40-.02*np.abs(local-10)
    else:roof=40-1.0*np.abs(local-10)
    z=np.asarray(p.z).copy();z[mask]=roof;p.z=z;p.write(root/'cloud.las')
    before=hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()
    output=tmp_path/'on';run_build(config,output)
    rows={r['source_id']:r for r in json.loads((output/'quality.json').read_text())['objects'] if r['kind']=='BuildingPart'}
    row=rows['court'];assert row['method']==('direct' if shape=='gentle' else 'roof_surface') and row['status']=='resolved'
    if shape=='gentle':
        assert row['roof_reference_z']==pytest.approx(40,abs=.5)
    else:
        assert row['roof_reference_z']==pytest.approx(float(np.median(roof)),abs=1.5)
        assert row['roof_surface']['lod1_reduction']=='spatial_cell_upper_median'
    assert row['height_m']==pytest.approx(row['roof_reference_z']-25)
    assert row['floor_height_m'] is None and row['reference_part_id'] is None
    if shape!='gentle':assert not row['roof_surface']['storeys_used'] and row['roof_surface']['accepted']
    model=json.loads((output/'model.lod1.city.json').read_text());Draft7Validator(json.loads(Path('tests/schemas/cityjson-2.0.1.schema.json').read_text())).validate(model)
    obj=model['CityObjects']['BuildingPart::court'];assert obj['geometry']
    if shape!='gentle':assert obj['attributes']['roof_surface']['accepted']
    assert all(g['lod']=='1' for g in obj['geometry'])
    cfg['roof_surfaces']['enabled']=False;config.write_text(json.dumps(cfg));run_build(config,tmp_path/'off')
    old={r['source_id']:r for r in json.loads((tmp_path/'off/quality.json').read_text())['objects'] if r['kind']=='BuildingPart'}
    assert old['court']['height_m']==row['height_m']  # Geometry attribution is mandatory; legacy opt-in cannot disable it.
    assert rows['terrace']['height_m']==old['terrace']['height_m']==pytest.approx(2.0)
    assert hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()==before
    if shape=='flat_steps':
        # A positive minimum remains an explicit legacy restriction; the new
        # authoritative default accepts coherent horizontal observations.
        assert RoofSurfaceConfig().min_slope_deg==0
        cfg['roof_surfaces'].update(enabled=True,min_slope_deg=3)
        config.write_text(json.dumps(cfg));run_build(config,tmp_path/'legacy')
        legacy=next(r for r in json.loads((tmp_path/'legacy/quality.json').read_text())['objects'] if r['source_id']=='court')
        assert legacy['height_m']==row['height_m']  # Retired slope restriction cannot erase a valid flat roof.


@pytest.mark.parametrize('bad',[{'grid_axis':True},{'min_points':10000},{'max_total_cells':0},{'min_slope_deg':60},{'max_slope_deg':90},{'min_coverage':1.1},{'residual_m':float('nan')}])
def test_invalid_spatial_roof_policy_fails(bad):
    with pytest.raises(ValueError):RoofSurfaceConfig(**bad)


def test_spatial_roof_budget_is_explicit_and_strong_flat_roofs_are_preserved(tmp_path):
    root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.json').read_text());cfg.update(roof_classes=None,building_surfaces={'max_total_layers':100000})
    config=root/'build.json';config.write_text(json.dumps(cfg));run_build(config,tmp_path/'flat')
    assert not any(r.get('method')=='roof_surface' for r in json.loads((tmp_path/'flat/quality.json').read_text())['objects'])
    p=laspy.read(root/'cloud.las');x=np.asarray(p.x);z=np.asarray(p.z).copy();mask=(np.asarray(p.classification)==6)&(x<500020);z[mask]=40-.6*np.abs(x[mask]-500010);p.z=z;p.write(root/'cloud.las')
    cfg['building_surfaces']['max_total_layers']=1;config.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='max_total_layers'):run_build(config,tmp_path/'exhausted')
    assert not (tmp_path/'exhausted').exists()


def test_irregular_class6_points_do_not_become_a_roof_merely_because_footprint_exists(tmp_path):
    root=tmp_path/'inputs';create_demo(root)
    cfg=json.loads((root/'build.json').read_text());cfg.update(roof_classes=None,roof_surfaces={'enabled':True},external_height_fallback=False)
    config=root/'build.json';config.write_text(json.dumps(cfg))
    with sqlite3.connect(root/'footprints.gpkg') as db:db.execute("UPDATE building_parts SET storeys_above=NULL WHERE part_id='court'")
    features,_=read_footprints(BuildConfig.read(config),root);f=next(f for f in features if f.id=='court')
    p=laspy.read(root/'cloud.las');mask=(np.asarray(p.classification)==6)&intersects_xy(f.geometry,np.asarray(p.x),np.asarray(p.y))
    z=np.asarray(p.z).copy();z[mask]=np.random.default_rng(42).uniform(30,45,mask.sum());p.z=z;p.write(root/'cloud.las')
    run_build(config,tmp_path/'out')
    row=next(r for r in json.loads((tmp_path/'out/quality.json').read_text())['objects'] if r['source_id']=='court')
    assert row['status']=='unresolved' and not row['building_surfaces']['accepted']
    obj=json.loads((tmp_path/'out/model.lod1.city.json').read_text())['CityObjects']['BuildingPart::court']
    assert obj['attributes']['height_m'] is None and obj['geometry'][0]['lod']=='0'


@pytest.mark.parametrize('edge_only',[False,True])
def test_small_rooftop_room_keeps_two_supported_levels_without_an_area_exception(tmp_path,edge_only):
    from shapely.geometry import box
    from shapely import to_wkb
    root=tmp_path/'inputs';create_demo(root)
    cfg=json.loads((root/'build.json').read_text());cfg.update(roof_classes=None,roof_surfaces={'enabled':True},external_height_fallback=False)
    config=root/'build.json';config.write_text(json.dumps(cfg))
    room=box(500001,3100001,500005,3100005)
    with sqlite3.connect(root/'footprints.gpkg') as db:
        blob=db.execute("SELECT geom FROM building_parts WHERE part_id='court'").fetchone()[0]
        header=bytearray(blob[:8]);header[3]&=0xf1
        db.execute("UPDATE building_parts SET geom=?,storeys_above=NULL WHERE part_id='court'",(bytes(header)+to_wkb(room),))
    p=laspy.read(root/'cloud.las');mask=(np.asarray(p.classification)==6)&intersects_xy(room,np.asarray(p.x),np.asarray(p.y))
    z=np.asarray(p.z).copy();z[mask]=np.where(np.asarray(p.x)[mask]<500003,34.,37.);p.z=z
    if edge_only:
        remove=mask&(np.asarray(p.x)>=500001.5)&(np.asarray(p.x)<=500004.5)
        p.points=p.points[~remove]
    p.write(root/'cloud.las')
    run_build(config,tmp_path/'out')
    row=next(r for r in json.loads((tmp_path/'out/quality.json').read_text())['objects'] if r['source_id']=='court')
    if edge_only:
        assert row['status']=='unresolved' and row['height_m'] is None
        assert not row['building_surfaces']['accepted']
    else:
        assert row['method']=='roof_surface' and row['status']=='resolved'
        assert row['reconstructed_top_z']==pytest.approx(37,abs=.01)
        assert any(c['coverage']>=.5 for c in row['building_surfaces']['candidates'])


def test_spatial_envelope_does_not_replace_an_attributed_target_band(tmp_path,monkeypatch):
    import lodext.pipeline as pipeline
    import lodext.io.building_surfaces as surfaces
    root=tmp_path/'inputs';create_demo(root)
    cfg=json.loads((root/'build.json').read_text());cfg.update(roof_classes=None,roof_surfaces={'enabled':True},external_height_fallback=False)
    config=root/'build.json';config.write_text(json.dumps(cfg))
    original=pipeline.estimate_building
    def estimates(observations,policy):
        return [replace(r,method='roof_band') if r.part_id=='BuildingPart::court' else r for r in original(observations,policy)]
    original_surfaces=surfaces.sample_building_surfaces
    def conflicting_surface(config,root,features,samples,working,progress):
        original_surfaces(config,root,features,samples,working,progress)
        samples['BuildingPart::court']['roof_surface']={'accepted':True,'roof_z':80.,'reason':'adversarial_higher_envelope'}
    monkeypatch.setattr(pipeline,'estimate_building',estimates)
    monkeypatch.setattr(surfaces,'sample_building_surfaces',conflicting_surface)
    run_build(config,tmp_path/'out')
    row=next(r for r in json.loads((tmp_path/'out/quality.json').read_text())['objects'] if r['source_id']=='court')
    assert row['method']=='roof_band' and row['height_m']==6
    assert row['reconstructed_top_z']==31
