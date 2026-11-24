"""Bulk LAS reception retains exact per-polygon observations, including edges."""
import numpy as np
import pytest
from shapely import STRtree,intersects_xy
from shapely.geometry import Polygon,MultiPolygon,box

from lodext.io.sampling import _roof_point_groups


@pytest.mark.parametrize("allowed",[None])
def test_bulk_point_query_matches_independent_polygon_masks_and_order(allowed):
    shapes=[Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(3,3),(7,3),(7,7),(3,7)]]),
            box(5,0,12,12),MultiPolygon([box(14,0,16,2),box(18,0,20,2)])]
    rng=np.random.default_rng(18)
    xy=np.vstack((rng.uniform([-2,-2],[22,14],(2000,2)),
                  [[0,0],[10,0],[3,3],[5,5],[14,1],[20,2],[100,100]]))
    classes=np.resize([2,5,6],len(xy));z=np.arange(len(xy),dtype=float)+25
    actual=dict(_roof_point_groups(STRtree(shapes),xy[:,0],xy[:,1],z,classes,allowed))
    for index,geom in enumerate(shapes):
        mask=intersects_xy(geom,xy[:,0],xy[:,1])
        if allowed is not None:mask &= np.isin(classes,allowed)
        np.testing.assert_array_equal(actual.get(index,np.array([])),z[mask])


def test_no_selected_points_or_no_matching_polygons_yields_no_groups():
    a=np.array([100.]);tree=STRtree([box(0,0,1,1)])
    with pytest.raises(ValueError,match="metadata"):
        list(_roof_point_groups(tree,a,a,a,np.array([2]),[6]))
    assert not list(_roof_point_groups(tree,a,a,a,np.array([2]),None))
