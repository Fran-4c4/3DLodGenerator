# Supported outputs and limits

| Task | Available output |
|---|---|
| Building footprints | LoD0 surfaces at a representative ground elevation per body |
| Geometric LiDAR ground | Bounded streaming exterior-plane evidence, an observed-point TIN and a combined building/ground scene |
| Buildings and building parts | LoD1 closed volumes with one flat roof per body |
| Several roof levels within one footprint | Optional supported roof-region partition with stepped LoD1 volumes under the original identity |
| Interior parts without exposed ground | Missing-base inference through shared boundaries of the same building |
| Valid parts with unresolved elevations | Labelled footprint markers remain visible without invented volumes |
| Courtyards and disconnected bodies | Holes and separate components retained |
| Road polygons | Individual lifted surfaces, with optional smoothing |
| Terrain and forest-ground polygons | Triangulated surfaces with interior elevation support |
| Water polygons | A common level per object |
| File exchange | CityJSON 2.0, quality reports and review tables |
| Cesium display | GLB and a 3D Tiles 1.1 tileset |

## Limits that affect your result

- **Roof shape:** LoD1 does not reconstruct pitched planes or roof furniture.
  LoD2 is unavailable. Use building-part footprints when different bodies need
  different heights.
- **Scene connections:** buildings and other surfaces are processed separately.
  Neighbouring edges are not automatically stitched; the outputs are not a
  continuous watertight terrain/city mesh. Bridges and wall features are unsupported.
- **Input preparation:** use valid XY Polygon/MultiPolygon GeoPackage layers with
  the required fields. Provider-specific column mapping is not automatic.
- **Elevation:** a sampled or adjacency-inferred base is required for a volume;
  LiDAR geometry is the default source, with a supplied DTM as an explicit alternative. Horizontal reprojection
  does not convert vertical datums. Globe placement requires a separate decision.
- **Scale:** the surface workflow has point/mesh budgets and is intended for small
  areas. The tile converter creates one tile, without a spatial hierarchy, and
  rejects extents over 100 km projected diagonal.
- **Interpretation:** a completed run means the requested objects were processed;
  it does not certify survey accuracy. Review the evidence and geometry for your use.

See [input requirements](input_contract_v0_2.md), [configuration](cli_reference.md)
and [troubleshooting](troubleshooting.md) before processing your own data.
