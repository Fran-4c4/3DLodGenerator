"""Wrong vegetation labels: restore coherent roofs, reject spatial contradictions."""
from dataclasses import replace
import hashlib,json
import numpy as np
import pytest
import laspy
from shapely.geometry import box
from lodext.core.heights import HeightConfig
from lodext.core.roof_recovery import RoofRecoveryConfig
from lodext.core.config import BuildConfig
from lodext.io.footprints import Feature
from lodext.io.roof_recovery import RoofRecoveryAccumulator
from lodext.demo import create_demo
from lodext.pipeline import run_build


def roof(kind='flat'):
    """5 points/m2; roof surface above a ground Z of 4, deliberately class 5."""
    x,y=np.meshgrid(np.arange(.2,20,.45),np.arange(.2,12,.45));x=x.ravel();y=y.ravel()
    z=np.full(len(x),12.5)+np.random.default_rng(2).normal(0,.025,len(x))
    if kind=='umbrellas':
        for cx,cy in [(4,4),(10,4),(16,4)]:
            distance=np.hypot(x-cx,y-cy);keep=distance<1.4;z[keep]=15.5-.7*distance[keep]
    elif kind=='slope':z=11+.15*x+.02*y
    elif kind=='tree':z=np.random.default_rng(5).uniform(7,18,len(x))
    elif kind=='canopy-volume':
        z=15-.025*((x-10)**2+(y-6)**2)
        x=np.repeat(x,3);y=np.repeat(y,3)
        z=np.repeat(z,3)-np.random.default_rng(5).uniform(0,6,len(x))
    return np.column_stack((x,y,z)),box(0,0,20,12)


def accumulator(xyz,g,policy=None,parts=None,chunks=1):
    policy=policy or RoofRecoveryConfig(enabled=True)
    f=Feature('BuildingPart','part','parent',g,{'storeys_above':2},[])
    units=parts or [f];a=RoofRecoveryAccumulator(units,[(p.geometry,'not_attempted') for p in units],policy)
    for arr in np.array_split(xyz,chunks):a.add(arr[:,0],arr[:,1],arr[:,2],np.full(len(arr),5))
    return a


@pytest.mark.parametrize('kind',['flat','umbrellas','slope'])
def test_wrong_class_roof_is_recovered_from_geometry_not_a_storey_multiplier(kind):
    xyz,g=roof(kind);a=accumulator(xyz,g);r=a.estimate(0,4,2,HeightConfig(),0,True)
    assert r['accepted'] and r['area_coverage']>.6
    assert r['roof_z']==pytest.approx(12.5 if kind!='slope' else xyz[:,2].max(),abs=.25)
    assert r['source_class_counts']=={5:len(xyz)} and r['source_classes_preserved']
    assert a.estimate(0,4.2,2,HeightConfig(),0,True)['roof_z']==r['roof_z']


@pytest.mark.parametrize('kind',['tree','canopy-volume'])
def test_tree_scatter_is_not_reclassified_despite_matching_footprint_and_storeys(kind):
    xyz,g=roof(kind);r=accumulator(xyz,g).estimate(0,4,2,HeightConfig(),0,True)
    assert not r['accepted'] and r['roof_z'] is None


@pytest.mark.parametrize('ground,storeys,primary,coverage,reason',[(None,2,0,True,'missing_ground'),(4,None,0,True,'missing_positive_storeys'),(4,0,0,True,'missing_positive_storeys'),(4,2,1,True,'primary_roof_points_present'),(4,2,0,False,'incomplete_lidar_coverage'),(4,10,0,True,'storey_height_conflict')])
def test_recovery_requires_independent_context(ground,storeys,primary,coverage,reason):
    xyz,g=roof();r=accumulator(xyz,g).estimate(0,ground,storeys,HeightConfig(),primary,coverage)
    assert not r['accepted'] and r['reason']==reason


def test_dense_corner_tree_does_not_supply_footprint_area_coverage():
    xyz,g=roof();xyz=xyz[(xyz[:,0]<6)&(xyz[:,1]<6)];xyz=np.repeat(xyz,40,axis=0)
    r=accumulator(xyz,g).estimate(0,4,2,HeightConfig(),0,True)
    assert not r['accepted']


def test_identical_stacked_flat_surfaces_cannot_be_semantically_disambiguated_from_xyz_alone():
    # This deliberately ambiguous geometry is also compatible with roof/deck
    # layers. No algorithm using only XYZ/footprint/storeys can certify trees
    # versus a building when those inputs are geometrically identical.
    xyz,g=roof();stack=np.vstack((xyz,xyz-[0,0,2],xyz-[0,0,5]))
    result=accumulator(stack,g).estimate(0,4,2,HeightConfig(),0,True)
    assert result['accepted'] and result['source_classes_preserved']


def test_overlapping_sibling_area_cannot_supply_independent_roof_support():
    xyz,g=roof()
    f=Feature('BuildingPart','a','parent',g,{'storeys_above':2},[])
    other=Feature('BuildingPart','b','parent',g,{'storeys_above':2},[])
    a=accumulator(xyz,g,parts=[f,other])
    assert not a.estimate(0,4,2,HeightConfig(),0,True)['accepted']


def test_chunking_and_input_order_do_not_change_decision_or_top():
    xyz,g=roof('umbrellas');a=accumulator(xyz,g);b=accumulator(xyz[::-1],g,chunks=7)
    ra=a.estimate(0,4,2,HeightConfig(),0,True);rb=b.estimate(0,4,2,HeightConfig(),0,True)
    assert ra['accepted']==rb['accepted'] and ra['roof_z']==pytest.approx(rb['roof_z'],abs=1e-9)
    assert ra['retained_cells']==rb['retained_cells']


def test_explicit_cell_budgets_never_silently_coarsen():
    xyz,g=roof();a=accumulator(xyz,g,RoofRecoveryConfig(enabled=True,max_cells_per_object=12))
    assert a.estimate(0,4,2,HeightConfig(),0,True)['reason']=='representative_budget_exceeded'
    with pytest.raises(ValueError,match='max_total_cells'):
        accumulator(xyz,g,RoofRecoveryConfig(enabled=True,max_total_cells=10))


@pytest.mark.parametrize('bad',[{'enabled':1},{'candidate_classes':[256,5]},{'cell_size_m':0},{'local_std_m':-1},{'min_coverage':2},{'min_cells':2},{'max_cells_per_object':3},{'max_slope_deg':90}])
def test_invalid_settings_fail(bad):
    with pytest.raises(ValueError):RoofRecoveryConfig(**bad)


@pytest.mark.parametrize('use_dtm',[False,True])
@pytest.mark.parametrize('source_class',[2,5])
def test_build_restores_originally_misclassified_roofs_with_provenance(tmp_path,use_dtm,source_class):
    root=tmp_path/'inputs';create_demo(root);cfg=json.loads((root/'build.json').read_text())
    if not use_dtm:cfg.pop('dtm')
    cfg.update(roof_classes=None,roof_recovery={'enabled':True})
    path=root/'build.json';path.write_text(json.dumps(cfg))
    cloud=laspy.read(root/'cloud.las');classes=np.asarray(cloud.classification).copy();classes[classes==6]=source_class;cloud.classification=classes;cloud.write(root/'cloud.las')
    before=hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()
    output=tmp_path/'on';run_build(path,output)
    q=json.loads((output/'quality.json').read_text());rows=[r for r in q['objects'] if r.get('building_surfaces',{}).get('accepted')]
    assert len(rows)==4 and q['summary']['resolved_units']==5
    assert rows and all(r['status']=='resolved' and r['building_surfaces']['accepted'] for r in rows)
    model=json.loads((output/'model.lod1.city.json').read_text())
    for r in rows:
        obj=model['CityObjects'][r['key']];assert obj['geometry'] and obj['attributes']['building_surfaces']['source_classes_used'] is False
        assert r['reconstructed_top_z']==r['roof_reference_z'] and r['height_m']==pytest.approx(r['roof_reference_z']-r['ground_z'])
    assert hashlib.sha256((root/'cloud.las').read_bytes()).hexdigest()==before
    cfg['roof_recovery']['enabled']=False;path.write_text(json.dumps(cfg));run_build(path,tmp_path/'off')
    off={r['key']:r for r in json.loads((tmp_path/'off/quality.json').read_text())['objects']}
    assert all(off[r['key']]['height_m']==r['height_m'] for r in rows)
