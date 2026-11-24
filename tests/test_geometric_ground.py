"""Class-neutral exterior planes: hills, low outliers, missing ground and chunking."""
from pathlib import Path
import numpy as np
import pytest
from pyproj import CRS
from shapely import STRtree,points
from shapely.geometry import box,MultiPolygon
from lodext.core.ground import PointGroundConfig
from lodext.core.config import SamplingConfig
from lodext.io.footprints import Feature
from lodext.io.geometric_ground import GeometricGroundAccumulator


def store(tmp_path):
 f=Feature('BuildingPart','body','parent',MultiPolygon([box(0,0,10,10)]),{'storeys_above':1},[])
 return GeometricGroundAccumulator(tmp_path/'unused.gpkg',CRS.from_epsg(4083),PointGroundConfig(export_surface=False),[f.geometry],[f],SamplingConfig())


def terrain():
 x,y=np.meshgrid(np.arange(-12,22,.5),np.arange(-12,22,.5));x=x.ravel();y=y.ravel()
 z=5+.1*x+.2*y;z[(x>=0)&(x<=10)&(y>=0)&(y<=10)]+=12
 return np.vstack((np.column_stack((x,y,z)),[[-4.1,-4.1,-100]]))


@pytest.mark.parametrize('label',[0,2,5,7,17,255])
def test_hill_base_uses_lowest_coherent_contact_and_resists_an_isolated_low_return(tmp_path,label):
 a=store(tmp_path);q=terrain();labels=np.full(len(q),label)
 a.add(*q.T,labels,'test',CRS.from_epsg(4083),[None]*len(q),*q.T);a.finish()
 r=a.estimate(0)
 assert r['ground_z']==pytest.approx(4.3,abs=1e-8)
 assert r['ground_z']==pytest.approx(r['ground_min_z'],abs=1e-8)
 assert r['ground_method']=='geometric_exterior_plane'
 assert r['ground_plane']['slope_deg']>10
 assert r['ground_plane']['rmse_m']<1e-8


def test_chunking_and_order_do_not_change_selected_exterior_points(tmp_path):
 q=terrain();a=store(tmp_path);b=store(tmp_path)
 for cloud,target,chunks in [(q,a,1),(q[::-1],b,31)]:
  for p in np.array_split(cloud,chunks):target.add(*p.T,np.full(len(p),5),'test',CRS.from_epsg(4083),[None]*len(p),*p.T)
  target.finish()
 np.testing.assert_array_equal(a.ground_xyz,b.ground_xyz)
 assert a.estimate(0)['ground_z']==b.estimate(0)['ground_z']


def test_only_interior_returns_cannot_supply_building_ground(tmp_path):
 a=store(tmp_path);q=np.array([[1.,1.,12.],[2.,1.,12.],[1.,2.,12.]])
 a.add(*q.T,np.full(len(q),2),'test',CRS.from_epsg(4083),[None]*len(q),*q.T);a.finish()
 assert a.estimate(0)['ground_z'] is None


def test_exact_three_nearby_controls_defer_to_a_validated_wider_ground_plane(tmp_path):
 a=store(tmp_path)
 high=np.array([[-1.,1.,17.],[-1.,5.,17.],[1.,-1.,17.],[11.,-9.,17.]])
 low=np.array([[-2.,-9.,5.],[1.,-9.,5.],[4.,-9.,5.],[7.,-9.,5.],[10.,-9.,5.]])
 a.ground_xyz=np.vstack((high,low));a.ground_tree=STRtree(points(a.ground_xyz[:,:2]))
 result=a.estimate(0)
 assert result['ground_z']==pytest.approx(5)
 assert result['ground_samples']>=4
 assert result['ground_radius_m']>a.sampling.ground_buffers_m[0]
