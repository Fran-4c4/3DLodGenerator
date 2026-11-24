# Generate buildings from your own data

Prepare a GeoPackage and LiDAR files covering your buildings. Keep
nearby terrain and neighbouring footprints: ground sampling needs context outside
individual buildings.

## 1. Prepare the GeoPackage

In QGIS or another GIS application, export valid XY Polygon/MultiPolygon features
with a declared CRS. Preserve courtyards and all disconnected components.

Choose how to represent the buildings:

| Your data | Required layers and identifiers |
|---|---|
| One footprint per building | `buildings`, with a unique nonempty text `building_id` |
| Separate bodies with different heights | `buildings` plus `building_parts`; each part has a unique text `part_id` and the parent's `building_id` |

Set `geometry_mode` to `buildings` or `parts` to match. Optional fields such as
`storeys_above` and `reference_height_m` belong to the body being reconstructed;
assigning the parent's height to every terrace gives incorrect geometry.
See [the field types and relationships](input_contract_v0_2.md) before exporting.

## 2. Prepare elevation files

Supply LAS/LAZ/COPC files containing ground observations around the buildings
and the roof observations you need. Keep neighbouring ground and footprints so
geometric inference can exclude occupied areas and compare nearby surfaces.
Provider classifications are metadata, not selection filters. No DTM is required.

The [direct ground workflow](point_ground.md) preserves candidate points and
their selection decisions, and generates a terrain surface alongside buildings.
All source Z values must use compatible metre units and a vertical reference.
A horizontal CRS declaration alone does not establish a height datum.

A compatible single-band DTM GeoTIFF remains an explicit alternative: supplying
`dtm` selects raster ground instead. See [optional DTM preparation](dtm_preparation.md).
For deliberate extrusion from supplied heights, use `height_source: "known"`;
without a DTM, LiDAR is still needed to establish the ground.

## 3. Create a configuration

[Surface attribution](building_recovery.md) automatically separates XYZ levels
and compares candidate surfaces with footprints and neighbouring structures.
Storey counts are optional auxiliary evidence; no classification-based recovery
switch is needed.

For a GeoPackage with individual building footprints, save this as `build.json`
beside your input files:

```json
{
  "config_version": "1",
  "contract_version": "0.2",
  "dataset_id": "my-buildings",
  "geometry_mode": "buildings",
  "footprints": "footprints.gpkg",
  "lidar": ["lidar"],
  "working_epsg": 25828,
  "vertical_reference": "local_relative",
  "lods": [0, 1]
}
```

Replace the paths and choose a **projected metric working CRS appropriate to your
area**; 25828 is only an example. The `lidar` entry can point to files or a directory.
Paths are resolved relative to the JSON file. `local_relative` declares local
height use; it does not reconcile incompatible datums. See
[commands and configuration](cli_reference.md) for other options.

## 4. Validate and build

After [installation](installation.md), run from the project root:

```powershell
.\.venv\Scripts\python.exe -m lodext validate C:/my-data/build.json
.\.venv\Scripts\python.exe -m lodext build C:/my-data/build.json --output outputs/my-buildings-01
```

Choose a new output directory. A partial build returns exit code 3 and records
excluded or unresolved objects; review these before treating the output as complete.

## 5. Open the model and review the report

Open `outputs/my-buildings-01/scene.lod1.city.json` in a CityJSON viewer. Inspect
low terraces, courtyards and separate bodies, then check `objects.csv` and
`quality.json` for unsupported or inferred heights. See [view and check your
model](viewer_validation.md) and [output files](outputs.md).

For globe display, [convert the model to 3D Tiles](cesium.md) and choose its
vertical placement independently of the height estimation.
