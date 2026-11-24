"""Keep pip-wheel PROJ data separate from other installed GIS distributions.

Call before importing Rasterio/PyProj in this test-tool process. If Rasterio
ships its own proj.db, discard inherited PROJ_DATA/PROJ_LIB overrides so that
each wheel discovers its bundled database. System environments without bundled
data are left unchanged. This changes only this Python process, never Windows
user/system settings or configuration files. Returns removed variable names;
their path values are deliberately not logged.

Rationale: another GIS installation can set PROJ_LIB to an older proj.db.
The wheel then fails even to resolve EPSG:4326. Rasterio's official FAQ prescribes
unsetting these overrides for wheels:
https://rasterio.readthedocs.io/en/latest/faq.html
"""
from importlib.util import find_spec
import os
from pathlib import Path


def isolate_wheel_proj_data():
    """Prefer bundled Rasterio PROJ data and return removed override variable names.

    Clear PROJ_DATA/PROJ_LIB in this process only when the installed wheel has
    its own proj.db; otherwise return (). Diagnostic callers record names, never
    former values. No user/machine configuration or geospatial data is modified.
    """
    spec = find_spec("rasterio")
    if spec is None or spec.origin is None:
        return ()
    if not (Path(spec.origin).parent / "proj_data" / "proj.db").is_file():
        return ()
    removed = tuple(name for name in ("PROJ_DATA", "PROJ_LIB") if name in os.environ)
    for name in removed:
        os.environ.pop(name)
    return removed
