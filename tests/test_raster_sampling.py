"""Bounded raster block reads preserve the former per-point sample semantics."""
import numpy as np
import pytest
import rasterio
from affine import Affine
from pyproj import CRS,Transformer

from lodext.io.native import configure_native_environment
from lodext.io.sampling import raster_values


@pytest.mark.parametrize("rotation",[0,8])
@pytest.mark.parametrize("working_epsg",[4083,32629])
def test_block_samples_equal_point_reads_with_masks_edges_scale_and_reprojection(tmp_path,rotation,working_epsg):
    configure_native_environment()
    angle=np.deg2rad(rotation)
    affine=Affine(.5*np.cos(angle),.5*np.sin(angle),456000,.5*np.sin(angle),-.5*np.cos(angle),3113000)
    data=np.arange(35*34,dtype="int16").reshape(35,34)
    data[4:12,7:16]=-9999
    path=tmp_path/"ground.tif"
    with rasterio.open(path,'w',driver='GTiff',width=34,height=35,count=1,dtype='int16',
                       crs='EPSG:4083',transform=affine,nodata=-9999,tiled=True,blockxsize=16,blockysize=16) as dst:
        dst.write(data,1);dst.scales=(.25,);dst.offsets=(7.,)
    rng=np.random.default_rng(8)
    cols=np.r_[rng.uniform(-3,37,500),0,34,0,34,.5,.5]
    rows=np.r_[rng.uniform(-3,38,500),0,0,35,35,.5,.5]
    xy=np.column_stack((affine.a*cols+affine.b*rows+affine.c,affine.d*cols+affine.e*rows+affine.f))
    working=CRS.from_epsg(working_epsg)
    x,y=Transformer.from_crs(4083,working,always_xy=True).transform(xy[:,0],xy[:,1])
    x,y=np.r_[x,np.nan,np.inf],np.r_[y,np.nan,np.inf]
    with rasterio.open(path) as src:
        tx,ty=Transformer.from_crs(working,src.crs,always_xy=True).transform(x,y)
        tx,ty=np.asarray(tx),np.asarray(ty)
        bounds=src.bounds
        inside=np.isfinite(tx)&np.isfinite(ty)&(tx>=bounds.left)&(tx<bounds.right)&(ty>bounds.bottom)&(ty<=bounds.top)
        expected=np.full(len(x),np.nan)
        for index,sample in zip(np.flatnonzero(inside),src.sample(zip(tx[inside],ty[inside]),indexes=1,masked=True)):
            if not np.ma.getmaskarray(sample)[0] and np.isfinite(float(sample[0])):
                expected[index]=float(sample[0])*.25+7
        actual=raster_values(src,x,y,working)
        np.testing.assert_allclose(actual,expected,rtol=0,atol=0,equal_nan=True)
        assert raster_values(src,[],[],working).size==0
