# LiDAR, terrain and auxiliary heights

The footprint identifies each body. LiDAR coordinates supply both roof observations
and exterior ground observations needed to calculate its height. Known heights and storey
counts can help when roof observations are insufficient.

| Source | What it contributes |
|---|---|
| Footprints and building parts | Shape, identity and relationships |
| LiDAR | Separate ground/roof observations, original classes and point support |
| Optional DTM | Explicit alternative to direct point-ground estimation |
| Known heights or storeys | Optional information for explicitly enabled fallback |

## Elevation and height

Building height is the difference between roof elevation and ground elevation.
A supplied `reference_height_m` is a height above ground, not an absolute roof
Z value. All selected ground and roof observations must share compatible metre Z.
An optional DTM must use that same vertical basis. See [direct ground sampling](point_ground.md).

## Density, resolution and accuracy

The tool is intended to support workflows around 5 points/m², but usable support
must be assessed on each body. Small terraces, class filters and occlusion can
leave a part with few observations even in a well-covered tile.

Uniform 5 points/m² corresponds to a nominal spacing of about 0.45 m. A 0.50 m
DTM pixel is a raster resolution; it does not imply the same LiDAR spacing or
vertical accuracy. Finer rasterisation does not create new observations.

## Choose how supplied heights are used

- With `height_source: "lidar"`, reliable roof observations take priority.
  Storey fallback needs a suitable same-building reference or an explicitly
  configured regional height.
- Enable `external_height_fallback: true` to allow a supplied height to resolve
  a body that remains unresolved. Valid ground and height provenance are required.
- Set `height_source: "known"` to deliberately construct bodies from supplied
  heights rather than estimate their roofs from LiDAR.

These are explicit configuration choices. Parent heights are not inherited by
every part. Reports identify supplied or inferred heights so you can distinguish
them from direct estimates. See [input fields](input_contract_v0_2.md),
[configuration](cli_reference.md) and [output reports](outputs.md).
