# Troubleshooting and limitations

| Symptom | Check |
|---|---|
| Unknown configuration/version | Config v1, input contract 0.2, exact keys and actual numeric types |
| File not found | Relative paths start at the JSON file, not the current directory |
| Missing layer/ID | Canonical fields/layers; numeric QGIS `fid` is not a source ID |
| Part outside parent | Verify source relation/geometry; do not assign the nearest parent just to pass |
| Geographic working CRS | Select an appropriate projected metric CRS; do not measure/extrude degrees |
| DTM lacks CRS/NoData | Prepare an explicit single-band GeoTIFF; do not replace missing ground with zero |
| DTM/LiDAR mismatch | Check Z units, vertical basis and survey; diagnostics reject offset/dispersion without automatic adjustment |
| Sparse roof points | Review geometric support, coverage, neighbouring surfaces and footprint/cloud dates; source classes do not select building points |
| Unresolved object | Inspect flags, ground and storey anchor; supplied heights require explicit policy/provenance |
| Flat footprint without building volume | Check `coverage_complete` and `incomplete_lidar_coverage`; include every intersecting tile in the configured LiDAR paths |
| Missing terrain inside the area | Check the actual selected tile extents and ground returns; the terrain edge limit deliberately leaves unsupported gaps |
| Exit code 3 | Review excluded/unresolved counts before using partial output |
| Output already exists | Select a new directory; previous runs are not overwritten |
| Quantisation collapse | Reduce `precision_m` and inspect source geometry; no silent repair |
| PROJ conflict | Isolate the environment; wheel-owned CRS data must not inherit incompatible overrides |
| Invisible Cesium model | HTTP/URI/CORS, actual GLB request, camera and vertical placement; CityJSON is not a tileset |

## Current limits

Only files named by the configuration are processed. A tile in another download
folder is not automatically included. To complete coverage for existing
footprints, keep the GeoPackage extent fixed and add the intersecting LiDAR
tiles, including the surrounding ground-search context. Extend the GeoPackage
only when extending the desired output area: cloud coverage cannot create
building identities or footprints that were never received.

A flat unresolved footprint does not always mean a missing tile. With
`coverage_complete: true`, roof observations may still be absent, mixed or
rejected as unreliable. Inspect the object's flags before downloading more data.
Tile headers can cover locations with no actual returns; distinguish these
source gaps from missing files before changing height or terrain settings.
3dLodViewer highlights unresolved footprints in amber and keeps them searchable
by ID. Its explicit X-ray option reveals hidden markers for review; use Top
view to avoid misleading perspective overlap with roofs.

- Vector input: canonical-field XY Polygon/MultiPolygon GeoPackage.
- Levels: LoD0/LoD1; requesting LoD2 explicitly fails.
- Representative horizontal bases per body, without terrain stitching.
- Regular LiDAR is read in batches; COPC uses full-resolution cell queries.
  Query limits are checked after decoding; per-object samples accumulate.
  No silent thinning. Header coverage alone does not prove point/class support.
- Tiles accept the supported metric-projected CityJSON subset, producing one
  tile up to 100 km diagonal without advanced partitioning.
- Explicit constant vertical placement is neither geoid conversion nor
  individual adaptation to a viewer's terrain.
- Local validation is not a universal geometric certification. Schema,
  shell/volume, input evidence and visual review are distinct checks.

See [supported outputs and limits](capabilities.md).
