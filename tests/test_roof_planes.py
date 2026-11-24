"""Synthetic industrial roofs: spatial evidence, not cadastral-storey inference."""
import numpy as np
import pytest
from shapely.geometry import box
from shapely.affinity import rotate,translate
from lodext.io.roof_planes import RoofPlaneReviewConfig,review_roof_planes


def industrial_roof(kind='gable',noise=.03):
    """5 returns/m2 over 60 by 40 m, in metres on a nonzero ground basis."""
    x,y=np.meshgrid(np.arange(.25,60,.45),np.arange(.25,40,.45));x=x.ravel();y=y.ravel()
    if kind=='gable':z=16-.25*np.abs(x-30)
    elif kind=='asymmetric':z=np.where(x<24,16-.3*(24-x),16-.2*(x-24))
    elif kind=='double':z=16-.3*np.abs((x%30)-15)
    elif kind=='random':z=np.random.default_rng(7).uniform(8,24,len(x))
    elif kind=='flat-mixture':z=np.where(x<30,10,24)
    else:raise ValueError(kind)
    z=z+np.random.default_rng(1).normal(0,noise,len(z))
    return np.column_stack((x,y,z)),box(0,0,60,40)


@pytest.mark.parametrize('kind',['gable','asymmetric','double'])
def test_industrial_slopes_survive_without_storeys_or_a_narrow_modal_peak(kind):
    xyz,g=industrial_roof(kind);r=review_roof_planes(xyz,g)
    assert r['accepted'] and r['supported_fraction']>.9
    assert r['proposed_lod1_roof_z']==pytest.approx(16,abs=.5)
    assert len(r['planes'])>=2 and not r['ownership_established']


def test_isolated_antenna_and_dense_small_high_patch_do_not_set_roof():
    xyz,g=industrial_roof();rng=np.random.default_rng(3)
    contaminant=np.column_stack((rng.uniform(20,23,5000),rng.uniform(5,8,5000),rng.uniform(40,60,5000)))
    r=review_roof_planes(np.vstack((xyz,contaminant,[[30,20,150]])),g)
    assert r['accepted'] and r['proposed_lod1_roof_z']<16.5
    assert r['representatives']<=24**2


@pytest.mark.parametrize('kind',['random','flat-mixture'])
def test_irregular_cloud_and_separate_flat_roofs_are_not_certified_as_sloping(kind):
    xyz,g=industrial_roof(kind);r=review_roof_planes(xyz,g)
    assert not r['accepted'] and r['proposed_lod1_roof_z'] is None


def test_large_footprint_does_not_rescue_sparse_or_corner_only_support():
    xyz,g=industrial_roof()
    for limited in (xyz[:10],xyz[(xyz[:,0]<10)&(xyz[:,1]<10)]):
        assert not review_roof_planes(limited,g)['accepted']


def test_translation_rotation_input_order_and_source_z_offset():
    xyz,g=industrial_roof('double');base=review_roof_planes(xyz,g)
    t=np.radians(31);matrix=np.array([[np.cos(t),-np.sin(t)],[np.sin(t),np.cos(t)]])
    transformed=xyz.copy();transformed[:,:2]=xyz[:,:2]@matrix.T+[455000,3114000];transformed[:,2]+=100
    shape=translate(rotate(g,31,origin=(0,0)),455000,3114000)
    changed=review_roof_planes(transformed[::-1],shape)
    assert changed['accepted'] and changed['proposed_lod1_roof_z']-100==pytest.approx(base['proposed_lod1_roof_z'],abs=.6)
    assert review_roof_planes(xyz[::-1],g)==base


@pytest.mark.parametrize('fields',[{'grid_axis':True},{'residual_m':0},{'min_supported_fraction':1.1},{'max_slope_deg':90},{'min_points':2}])
def test_invalid_review_contract_is_rejected(fields):
    with pytest.raises(ValueError):RoofPlaneReviewConfig(**fields)
