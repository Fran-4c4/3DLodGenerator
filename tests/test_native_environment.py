"""A foreign desktop-GIS environment must not corrupt serialized CRS reception."""
import os
from pathlib import Path
import subprocess
import sys


def test_cached_foreign_proj_paths_are_reset_before_reading_regcan95(tmp_path):
    script=r'''
import os,sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio._env import set_proj_data_search_path
from rasterio.transform import from_origin
from pyproj import CRS
from lodext.io.native import configure_native_environment

# Simulate a native library initialised by an unrelated GIS before the CLI runs.
set_proj_data_search_path(sys.argv[1])
try:rasterio.crs.CRS.from_epsg(4083)
except rasterio.errors.CRSError:pass
configure_native_environment()
path=Path(sys.argv[2])
with rasterio.open(path,'w',driver='GTiff',width=2,height=2,count=1,dtype='float32',
                   crs='EPSG:4083',transform=from_origin(456000,3113000,.5,.5),nodata=-9999) as dst:
    dst.write(np.full((2,2),25,dtype='float32'),1)
# A later external override must not survive repeated setup either.
os.environ['PROJ_LIB']=sys.argv[1]
set_proj_data_search_path(sys.argv[1])
configure_native_environment()
with rasterio.open(path) as src:
    assert src.crs.to_epsg()==4083
    assert CRS.from_user_input(src.crs).equals(CRS.from_epsg(4083))
    assert float(src.read(1)[0,0])==25
assert 'PROJ_LIB' not in os.environ
'''
    foreign=tmp_path/"foreign-data";foreign.mkdir()
    env={**os.environ,"PROJ_LIB":str(foreign),"PROJ_DATA":str(foreign),"GDAL_DATA":str(foreign)}
    result=subprocess.run([sys.executable,"-c",script,str(foreign),str(tmp_path/"ground.tif")],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr[-2500:]
