# GeoPackage and elevation inputs

The building commands read local GeoPackage, GeoTIFF and LiDAR files. Use
`contract_version: "0.2"` in the build configuration and the layer fields below.

## Input package

1. A **GeoPackage** with footprints and canonical IDs.
2. **LAS/LAZ/COPC** files containing ground observations and, for estimated
   LoD1 heights, roof observations.
3. JSON configuration declaring a metric working CRS and shared vertical basis.
   Paths may be relative to this JSON file.

Omit `dtm` to estimate ground geometrically from point coordinates. Original ground
candidates and footprint exclusions remain inspectable; a terrain TIN and a
combined scene are generated separately. See [ground from LiDAR](point_ground.md).

A supplied single-band **DTM GeoTIFF** with CRS, NoData and metre Z explicitly
selects the raster-ground route instead. Only with a DTM can LoD0/known-height
workflows omit LiDAR entirely. Existing configurations that supply `dtm` retain
that choice; there is no automatic switch between ground sources.

Missing ground is never replaced with zero or a low roof percentile. Readers
transform XY into the metric working CRS, without transforming Z.
`local_relative` declares uncertainty about absolute placement; it does not
convert a datum. All elevation sources must already have compatible metre Z.

## Vector layers

Geometry must be valid, nonempty XY Polygon/MultiPolygon with positive area.
The reader uses GeoPackage geometry metadata, without treating numeric `fid`
as a semantic ID. Z/M sources require an explicit preparation step.

| Mode | Required layers | Reconstruction |
|---|---|---|
| `buildings` | `buildings` | One unit per building, preserving all components |
| `parts` | `buildings` and `building_parts` | One unit per part; semantic parent without a duplicate box |

`buildings.building_id` is unique nonempty TEXT. `building_parts.part_id` is
unique nonempty TEXT and its `building_id` references a parent. IDs need only
be unique within their class. Export preserves identities as `Building::<ID>`
and `BuildingPart::<ID>`.

Target parents in parts mode must have parts. Every part must intersect its
declared parent with positive area; a boundary touch is insufficient.
Partial overflow is measured in `quality.json` as `parent_relation`: the area
outside the parent in square metres and the fraction overlapping it. Tiny
boundary differences are retained as evidence; partial overflow does not
silently clip, exclude or reassign the part.
Parentage is never inferred from an ID suffix. Layer names are configurable;
field names are canonical. Automatic provider-column mapping is not available.

## Attributes of the reconstructed unit

These belong to the part in parts mode and the building in buildings mode.
Parent heights/storeys are not inherited by every terrace or body.

| Field | Meaning and validation |
|---|---|
| `storeys_above` | INTEGER ≥0 or NULL; only >0 supports storey fallback; known zero differs from unknown |
| `storeys_below` | INTEGER ≥0 or NULL; does not increase visible height or generate a basement |
| `reference_height_m` | Finite REAL >0 or NULL; metres above ground, never absolute roof elevation |
| `reference_height_method` | Required nonempty text when height exists; otherwise NULL |
| `reference_height_source` | Required nonempty provenance when height exists; otherwise NULL; no secrets/personal paths |

Missing optional fields mean NULL. Fractional storeys, numeric strings,
sentinels, NaN, negative heights and incomplete provenance are rejected.
Precomputed area, centroid, erosion, BBOX and final height are not required.

## Supplied heights

- `height_source: "lidar"`: reliable measurement, then same-building storey
  fallback. An external height is normally comparison-only.
- `external_height_fallback: true`: a supplied height with provenance may
  resolve a still-unresolved unit with valid ground. It is labelled
  `external_height` and ceases to be an independent comparison. It never
  replaces a resolved height.
- `height_source: "known"`: deliberately use the supplied height for LoD1,
  without roof LiDAR; method `known_height`.

No column-name heuristic silently activates these policies. Peak disambiguation
using an external-height search band is not yet implemented.

## Errors and partial outputs

`invalid_objects: "error"` is the default and aborts before reconstruction for
malformed objects. Explicit `"exclude"` retains ID and reason without geometry.
Where courtyard rings touch at a point, one LoD1 part can contain several closed solids. They share the source ID and preserve the footprint and courtyards. LoD0 retains the original polygon.
Duplicates, missing CRS/layers and ambiguous identities always abort.
An orphaned part is reported without writing an invalid parentless CityJSON part.

`unresolved_objects: "omit"` retains the object without a volume when ground
or height is unavailable. `"error"` aborts. Partial builds return code 3;
do not describe them as complete coverage. See [outputs](outputs.md).

## Preparation in QGIS or another tool

Export footprints to GeoPackage, preserve courtyards/components and create
fields using the types above. Map IDs and relationships from the actual source.
Do not replace footprints with rectangles or give every part the parent's height.
Record the provenance of supplied heights.

Keep sufficient neighbouring context: ground is sampled outside buildings,
and a tight extraction must not remove obstacles from that calculation.
Do not flatten the DTM to make a rendered scene fit.
