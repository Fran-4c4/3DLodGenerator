"""Isolate bundled Rasterio PROJ from unrelated desktop GIS environment overrides."""
import importlib.util
import os
from pathlib import Path


def configure_native_environment():
    """Select matching Rasterio wheel data, including already-initialised PROJ.

    Prevent a desktop GIS database from overriding the installed wheel's native
    dependency data. Clearing environment overrides alone does not reset native
    search paths cached before this call: a valid GeoTIFF can otherwise be read
    as LOCAL_CS and repeatedly trigger slow/invalid coordinate operations.
    Mutates this process's PROJ overrides, GDAL_DATA and Rasterio PROJ search
    paths only. Does nothing when no bundled database is found. No machine/user settings,
    input data, CRS declarations or vertical coordinates are changed.
    """
    spec = importlib.util.find_spec("rasterio")
    if spec and spec.origin and (Path(spec.origin).parent / "proj_data" / "proj.db").exists():
        for name in ("PROJ_DATA","PROJ_LIB"):
            os.environ.pop(name,None)
        from rasterio._env import GDALDataFinder, set_proj_data_search_path
        data = GDALDataFinder().search_wheel()
        if data:
            os.environ["GDAL_DATA"] = data
        set_proj_data_search_path(str(Path(spec.origin).parent / "proj_data"))
