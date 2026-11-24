"""Physical boundary graphs, slopes, missing evidence and visible source identities."""
from types import SimpleNamespace
from pathlib import Path
import json
import numpy as np
import pytest
from shapely.geometry import box,Polygon
from lodext.io.footprints import Feature
from lodext.core.adjacent_ground import AdjacentGroundConfig
from lodext.io.adjacent_ground import infer_adjacent_ground,reconcile_inconsistent_ground
from lodext.core.heights import PartObservation,estimate_building,HeightConfig
from lodext.core.config import BuildConfig
from lodext.demo import create_demo
from lodext.pipeline import run_build
from jsonschema import Draft7Validator


def feature(key,g,parent='p'):
    return Feature('BuildingPart',key,parent,g,{},[])


def roof_feature(key,g,storeys,parent='p'):
    return Feature('BuildingPart',key,parent,g,{'storeys_above':storeys,'storeys_below':0},[])


def reconcile(fs,grounds,roofs,enabled=True):
    samples={f.key:{'ground_z':ground,'roof_z':list(roof),'coverage_complete':True} for f,ground,roof in zip(fs,grounds,roofs)}
    cfg=SimpleNamespace(adjacent_ground=AdjacentGroundConfig(enabled=enabled),geometry_mode='parts',height=HeightConfig())
    reconcile_inconsistent_ground(cfg,fs,samples);return samples


def transfer(fs,zs,**settings):
    samples={f.key:{'ground_z':z,'ground_samples':20 if z is not None else 0} for f,z in zip(fs,zs)}
    cfg=SimpleNamespace(adjacent_ground=AdjacentGroundConfig(enabled=True,**settings),geometry_mode='parts')
    infer_adjacent_ground(cfg,fs,samples);return samples


def test_surrounded_part_uses_adjacent_shell_base_and_preserves_measured_ground():
    outer=feature('shell',Polygon([(0,0),(30,0),(30,30),(0,30)],[[(10,10),(20,10),(20,20),(10,20)]]));inner=feature('inside',box(10,10,20,20))
    s=transfer([outer,inner],[8.22,None]);assert s[inner.key]['ground_z']==8.22
    assert s[outer.key]['ground_z']==8.22 and 'adjacent_ground' not in s[outer.key]
    assert s[inner.key]['ground_method']=='adjacent_part_ground' and s[inner.key]['ground_samples']==0
    assert s[inner.key]['ground_median_error_bound_m'] is None
    assert s[inner.key]['adjacent_ground']['references'][0]['id']==outer.key


def test_slope_disagreement_is_explicit_without_borrowing_an_unrelated_building():
    fs=[feature('left',box(0,0,10,10)),feature('middle',box(10,0,20,10)),feature('right',box(20,0,30,10)),feature('other',box(10,-10,20,0),'foreign')]
    s=transfer(fs,[2,None,8,100]);r=s[fs[1].key]
    assert r['ground_z'] in (2,8) and r['adjacent_ground']['conflicting_references']
    assert r['adjacent_ground']['reference_spread_m']==6
    assert {x['id'] for x in r['adjacent_ground']['references']}=={fs[0].key,fs[2].key}


def test_boundary_length_weights_local_reference_and_not_global_parent_median():
    fs=[feature('base',box(0,0,10,10)),feature('target',box(10,0,20,10)),feature('short-contact',box(20,0,25,1)),feature('distant',box(100,0,110,10))]
    s=transfer(fs,[8,None,2,100]);assert s[fs[1].key]['ground_z']==8


def test_paths_only_end_in_original_measured_references_and_hops_are_bounded():
    fs=[feature(str(i),box(i*10,0,(i+1)*10,10)) for i in range(3)]
    s=transfer(fs,[4,None,None]);assert s[fs[2].key]['ground_z']==4
    assert s[fs[2].key]['adjacent_ground']['hops']==2
    assert [x['id'] for x in s[fs[2].key]['adjacent_ground']['references']]==[fs[0].key]
    assert transfer(fs,[4,None,None],max_hops=1)[fs[2].key]['ground_z'] is None


def test_point_contacts_positive_overlaps_and_missing_anchors_do_not_create_ground():
    for geom in [box(10,10,20,20),box(5,5,15,15),box(50,50,60,60)]:
        fs=[feature('a',box(0,0,10,10)),feature('b',geom)]
        assert transfer(fs,[3,None])[fs[1].key]['ground_z'] is None
        assert transfer(fs,[None,None])[fs[1].key]['ground_z'] is None


def test_explicitly_disabled_policy_preserves_missing_base():
    fs=[feature('a',box(0,0,10,10)),feature('b',box(10,0,20,10))]
    samples={fs[0].key:{'ground_z':4},fs[1].key:{'ground_z':None}}
    cfg=SimpleNamespace(adjacent_ground=AdjacentGroundConfig(enabled=False),geometry_mode='parts')
    infer_adjacent_ground(cfg,fs,samples)
    assert samples[fs[1].key]=={'ground_z':None}


def test_implausible_roof_level_base_uses_majority_same_parent_ground_cluster():
    fs=[roof_feature('left',box(0,0,10,10),8),roof_feature('target',box(10,0,20,10),8),roof_feature('right',box(20,0,30,10),7)]
    samples=reconcile(fs,[5,32,5.4],[[30]*30,[30]*30,[29]*30]);target=samples[fs[1].key]
    assert target['ground_z']==5
    assert target['adjacent_ground']['selection']=='reconciled_shared_boundary_ground'
    assert target['adjacent_ground']['original_ground_z']==32
    assert target['adjacent_ground']['trigger']=='roof_not_above_ground'


def test_roof_below_sparse_measured_base_uses_adjacent_ground_without_storeys():
    fs=[feature('left',box(0,0,10,10)),feature('target',box(10,0,20,10)),feature('right',box(20,0,30,10))]
    samples=reconcile(fs,[5,18,5.4],[[16]*30,[17]*30,[16.5]*30]);target=samples[fs[1].key]
    assert target['ground_z']==5
    assert target['adjacent_ground']['selection']=='reconciled_shared_boundary_ground'
    assert target['adjacent_ground']['original_ground_z']==18
    assert target['adjacent_ground']['trigger']=='roof_not_above_ground'


def test_physically_contradictory_part_can_use_an_attached_building_access_level():
    target=roof_feature('target',box(10,0,20,10),2,'target-building')
    neighbour=roof_feature('neighbour',box(0,0,10,10),2,'adjacent-building')
    samples=reconcile([target,neighbour],[18,5],[[17]*30,[12]*30])
    assert samples[target.key]['ground_z']==5
    assert samples[target.key]['adjacent_ground']['selected_reference_id']==neighbour.key
    assert samples[target.key]['adjacent_ground']['trigger']=='roof_not_above_ground'


def test_small_ground_adjustment_is_allowed_when_it_resolves_a_roof_contradiction():
    fs=[roof_feature('target',box(10,0,20,10),1),roof_feature('access',box(0,0,10,10),1)]
    samples=reconcile(fs,[10,9],[[10.5]*30,[13]*30])
    assert samples[fs[0].key]['ground_z']==9
    assert samples[fs[0].key]['adjacent_ground']['trigger']=='roof_not_above_ground'


def test_storey_ratio_can_reveal_roof_level_ground_without_normalising_tall_hall():
    fs=[roof_feature('left',box(0,0,10,10),8),roof_feature('target',box(10,0,20,10),9),roof_feature('right',box(20,0,30,10),1)]
    samples=reconcile(fs,[5,31.5,5.2],[[30]*30,[36]*30,[25]*30]);target=samples[fs[1].key]
    assert target['ground_z']==5
    assert target['adjacent_ground']['trigger']=='implausible_storey_ratio'
    assert samples[fs[2].key]['ground_z']==5.2 and 'adjacent_ground' not in samples[fs[2].key]


def test_low_terrace_and_ambiguous_neighbour_bases_are_not_reconciled():
    terrace=[roof_feature('left',box(0,0,10,10),2),roof_feature('target',box(10,0,20,10),2)]
    samples=reconcile(terrace,[5,5],[[12]*30,[7]*30]);assert samples[terrace[1].key]['ground_z']==5 and 'adjacent_ground' not in samples[terrace[1].key]
    split=[roof_feature('left',box(0,0,10,10),4),roof_feature('target',box(10,0,20,10),8),roof_feature('right',box(20,0,30,10),4)]
    samples=reconcile(split,[5,32,20],[[20]*30,[30]*30,[35]*30]);assert samples[split[1].key]['ground_z']==32 and 'adjacent_ground' not in samples[split[1].key]


def test_disabled_policy_does_not_reconcile_measured_base():
    fs=[roof_feature('left',box(0,0,10,10),8),roof_feature('target',box(10,0,20,10),8)]
    samples=reconcile(fs,[5,32],[[30]*30,[30]*30],enabled=False)
    assert samples[fs[1].key]['ground_z']==32 and 'adjacent_ground' not in samples[fs[1].key]


def test_inferred_base_cannot_supply_a_measured_floor_multiplier():
    parts=[PartObservation('measured','p',100,100,(10.,)*30,4,False,2),PartObservation('inferred','p',200,200,(11.,)*30,4,False,1,ground_is_measured=False),PartObservation('missing','p',20,20,(),4,False,6)]
    r={x.part_id:x for x in estimate_building(parts)}
    assert r['inferred'].height_m==7 and r['missing'].height_m==18 and r['missing'].reference_part_id=='measured'


@pytest.mark.parametrize('bad',[{'enabled':1},{'max_hops':0},{'tolerance_m':-1},{'min_shared_boundary_m':0},{'disagreement_m':float('nan')}])
def test_invalid_policy_fails(bad):
    with pytest.raises(ValueError):AdjacentGroundConfig(**bad)


@pytest.mark.parametrize('use_dtm',[False,True])
def test_native_pipeline_transfers_base_before_roof_estimation(tmp_path,use_dtm):
    from lodext.io.footprints import read_footprints
    from shapely import intersects_xy
    import laspy
    root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.json').read_text())
    if not use_dtm:cfg.pop('dtm')
    cfg.update(roof_classes=None,external_height_fallback=False)
    (root/'build.json').write_text(json.dumps(cfg));policy=BuildConfig.read(root/'build.json');features,working=read_footprints(policy,root)
    court=next(f.geometry for f in features if f.id=='court');ring=court.buffer(25)
    if not use_dtm:
        cloud=laspy.read(root/'cloud.las');classes=np.asarray(cloud.classification).copy()
        missing=(classes==2)&intersects_xy(ring,np.asarray(cloud.x),np.asarray(cloud.y));cloud.points=cloud.points[~missing];cloud.write(root/'cloud.las')
    else:
        import rasterio
        with rasterio.open(root/'dtm.tif','r+') as raster:
            data=raster.read(1);rr,cc=np.indices(data.shape);x,y=rasterio.transform.xy(raster.transform,rr.ravel(),cc.ravel())
            data.reshape(-1)[intersects_xy(ring.buffer(1),np.asarray(x),np.asarray(y))]=raster.nodata;raster.write(data,1)
    run_build(root/'build.json',tmp_path/'built')
    rows={r['key']:r for r in json.loads((tmp_path/'built/quality.json').read_text())['objects']};row=rows['BuildingPart::court']
    assert row['ground_z']==pytest.approx(25) and row['status']=='resolved' and row['reconstructed_top_z']==pytest.approx(31)
    assert row['ground_method']=='adjacent_part_ground' and 'ground_inferred_from_adjacent_parts' in row['flags']
    assert row['adjacent_ground']['selected_reference_id']=='BuildingPart::terrace'


def test_valid_unresolved_parts_have_visible_non_solid_footprints_without_false_heights(tmp_path):
    import laspy
    root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.json').read_text());cfg.pop('dtm');cfg.update(roof_classes=None,external_height_fallback=False)
    cloud=laspy.read(root/'cloud.las');cloud.points=cloud.points[np.asarray(cloud.classification)!=2];cloud.write(root/'cloud.las')
    (root/'build.json').write_text(json.dumps(cfg));run_build(root/'build.json',tmp_path/'built')
    model=json.loads((tmp_path/'built/model.lod1.city.json').read_text());Draft7Validator(json.loads(Path('tests/schemas/cityjson-2.0.1.schema.json').read_text())).validate(model)
    for obj in model['CityObjects'].values():
        if obj['type']!='BuildingPart':continue
        assert obj['geometry'] and obj['geometry'][0]['type']=='MultiSurface' and obj['geometry'][0]['lod']=='0'
        assert obj['attributes']['representation']=='unresolved_footprint'
        assert obj['attributes']['reconstructionStatus']=='unresolved' and obj['attributes']['height_m'] is None
        assert obj['attributes']['ground_z'] is None and 'semantics' not in obj['geometry'][0]
