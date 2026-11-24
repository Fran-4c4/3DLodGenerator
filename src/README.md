# Implementation

The `lodext` package implements the public CityJSON and GLB/3D Tiles workflow:

```text
core/              pure heights and validated settings
io/                GeoPackage, raster, LAS/LAZ/COPC and native environment
reconstruction/    LoD0 surfaces and LoD1 extrusion
export/            CityJSON, triangulation, GLB and tileset
cli/               public commands
pipeline.py        coordination and per-object accounting
demo.py            reproducible synthetic example
```

The first non-building flow adds `core/surfaces.py`, `io/surfaces.py`,
`reconstruction/surfaces.py`, `surface_pipeline.py` and `surface_demo.py`.
It reconstructs individual Road/Terrain/Forest/Water, without scene stitching.

Owning types document defaults, fields and units locally. Readers import no
external applications or trial utilities. See [supported outputs](../docs/capabilities.md) and [commands](../docs/cli_reference.md).
