# Installation

3DLodExt is a local Python application. LoD0/LoD1 requires no Docker, database,
authentication, GDAL CLI, PDAL, roofer or other source checkout. Geospatial
libraries are installed as Python wheels. Avoid mixing DLLs and PROJ databases
from unrelated desktop GIS installations.

## Requirements

- **64-bit Python 3.12** reproduces the tested environment.
- Space for input files and a new directory for each run.
- Network access to install dependencies. Processing then uses local files.
- A CityJSON viewer for visual review; a viewer is not an engine dependency.

Clone or download the project and open its root directory.

### Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints/python312.txt ".[geo]"
.\.venv\Scripts\python.exe -m lodext --help
```

### Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints/python312.txt '.[geo]'
.venv/bin/python -m lodext --help
```

Windows is the verified platform. The Linux commands use the same dependencies,
but a Linux run has not yet been verified. Keep the virtual environment isolated
from other GIS installations to avoid native-library conflicts.

## Check the environment

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m lodext validate examples/first_run/build.json
```

`validate` checks the vector contract and resource headers. Actual coverage,
numerical support and local ground compatibility are evaluated during `build`.
Input validation errors return code 2 without modifying the input files.

Continue with [the first-run tutorial](first_run.md). For PROJ conflicts use an
isolated environment and consult [troubleshooting](troubleshooting.md).
