"""Physical controls for class-neutral surfaces and exterior terrain continuity."""
from dataclasses import replace
import numpy as np
import pytest
from shapely.geometry import box
from lodext.core.roof_recovery import RoofRecoveryConfig
from lodext.core.heights import HeightConfig
from lodext.io.footprints import Feature
from lodext.io.roof_recovery import RoofRecoveryAccumulator
from lodext.io.footprint_surfaces import check_exterior


def decision(slope=0.,roof_height=3.6,roof_class=2,continuous=False,exterior=True,seed=0):
    """A mapped 20x12 body beside independent low ground, or continuous hillside."""
    g=box(0,0,20,12);c=RoofRecoveryConfig(enabled=True)
    feature=Feature('BuildingPart','target','family',g,{'storeys_above':1},[])
    ring=g.buffer(c.context_m).difference(g)
    a=RoofRecoveryAccumulator([feature],[(g,'not_attempted')],c)
    b=RoofRecoveryAccumulator([replace(feature,geometry=ring)],[(ring,'not_attempted')],c)
    x,y=np.meshgrid(np.arange(-2.8,22.9,.45),np.arange(-2.8,14.9,.45));x=x.ravel();y=y.ravel()
    interior=(x>0)&(x<20)&(y>0)&(y<12)
    z=15.8+slope*x+np.where(interior|continuous,roof_height,0.)
    z+=np.random.default_rng(seed).normal(0,.025,len(z))
    a.add(x,y,z,np.full(len(z),roof_class))
    if exterior:b.add(x,y,z,np.full(len(z),roof_class))
    result=a.estimate(0,15.8,1,HeightConfig(),0,True)
    return check_exterior(result,b,0,c)


@pytest.mark.parametrize('label',[0,1,2,3,4,5,6,7,12,17,255])
def test_identical_geometry_is_independent_of_provider_class(label):
    r=decision(roof_class=label)
    assert r['accepted'] and 19.3<r['roof_z']<19.5
    assert r['source_classes_preserved'] and set(r['source_class_counts'])=={label}
    assert r['exterior_continuity_fraction']==0


@pytest.mark.parametrize('slope',[0.,.12,-.12])
def test_continuous_raised_or_sloping_terrain_is_not_a_roof(slope):
    r=decision(slope=slope,continuous=True)
    assert not r['accepted'] and r['reason']=='surface_continues_into_exterior'
    assert r['roof_z'] is None


def test_real_sloped_roof_above_independent_exterior_is_retained():
    r=decision(slope=.12)
    assert r['accepted'] and r['roof_z']>21


def test_missing_exterior_does_not_certify_a_roof():
    r=decision(exterior=False)
    assert not r['accepted'] and r['reason']=='insufficient_exterior_context'


@pytest.mark.parametrize('bad',[{'candidate_classes':[]},{'candidate_classes':[2,2]},{'candidate_classes':[-1]},{'candidate_classes':[True]},{'context_m':0},{'max_exterior_continuity':0},{'max_exterior_continuity':1.1}])
def test_invalid_class_neutral_contract_is_rejected(bad):
    with pytest.raises(ValueError):RoofRecoveryConfig(**bad)


def test_explicit_legacy_class_filter_requires_migration():
    with pytest.raises(ValueError,match='must be null'):
        RoofRecoveryConfig(enabled=True,candidate_classes=[3,4,5])


def test_interior_and_exterior_share_the_hard_cell_budget():
    c=RoofRecoveryConfig(enabled=True,max_total_cells=5,min_cells=3)
    g=box(0,0,10,10);f=Feature('BuildingPart','target','family',g,{'storeys_above':1},[])
    a=RoofRecoveryAccumulator([f],[(g,'not_attempted')],c)
    b=RoofRecoveryAccumulator([f],[(g,'not_attempted')],c,budget=a.budget)
    x=np.array([.2,1.2,2.2]);y=np.full(3,.2);z=np.full(3,19.4);labels=np.full(3,2)
    a.add(x,y,z,labels)
    with pytest.raises(ValueError,match='max_total_cells'):b.add(x,y,z,labels)
    assert a.total+b.total==a.budget[0]==5
