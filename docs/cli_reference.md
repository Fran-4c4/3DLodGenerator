# Commands and configuration

`lodext` and `python -m lodext` invoke the same application. JSON configuration
v1 uses input contract 0.2. No `.env`, credentials or inherited service settings
are required.

## Commands

```text
lodext demo --output <new-directory>
lodext validate <config.json>
lodext build <config.json> --output <new-directory>
lodext validate-cityjson <model.city.json>
lodext tiles <model.city.json> --output <new-directory> --z-offset-m <metres>
lodext demo-surfaces --output <new-directory>
lodext validate-surfaces <surfaces.json>
lodext build-surfaces <surfaces.json> --output <new-directory>
```

| Exit code | Meaning |
|---|---|
| 0 | Completed; a build has no excluded or unresolved objects |
| 2 | Configuration, input, capability or conversion error; inspect stderr |
| 3 | Partial build: outputs exist, with exclusions/unresolved objects in the report |

Existing output directories are rejected. Progress uses small JSON messages
on stdout. Full models and tables are written to files, not dumped to console.

Surface commands use a separate additive contract, not the building settings
below. They support individual Road/Terrain/Forest/Water without scene stitching.
See [surface workflow](surface_workflow.md) for inputs and stage-specific status.

## Minimal LiDAR configuration

```json
{
  "config_version": "1",
  "contract_version": "0.2",
  "dataset_id": "my-area",
  "geometry_mode": "parts",
  "footprints": "footprints.gpkg",
  "lidar": ["lidar"],
  "working_epsg": 25828,
  "vertical_reference": "local_relative",
  "lods": [0, 1]
}
```

Choose `working_epsg` for the data location; **25828 is only an example**.
`vertical_reference` declares a shared Z basis; it does not transform elevations.
Relative paths are resolved from the JSON. LiDAR files/directories can be
referenced through `..`. Processing does not accept URLs, expand environment
variables or download data.

## Settings

See [parameter comparisons](parameter_examples.md) for runnable examples of
horizontal uncertainty, label independence, height evidence and surface settings.

| Field | Purpose |
|---|---|
| `geometry_mode` | Required `buildings` or `parts` |
| `buildings_layer`, `parts_layer` | Configurable layer names; canonical names by default |
| `dtm` | Optional raster path; omission/null uses original LiDAR ground points. A supplied path explicitly selects raster ground |
| `ground` | Geometric ground, audit and terrain-TIN controls; see [ground from LiDAR](point_ground.md). Cannot be combined with `dtm` |
| `adjacent_ground` | Enabled by default: infer missing interior bases from original measured bases connected by shared boundaries of the same building; applies to both ground workflows. See [interior parts](point_ground.md#interior-parts-without-exposed-ground) |
| `height_source` | `lidar` by default, or explicit `known` |
| `external_height_fallback` | Permission to use supplied fallback heights; disabled by default |
| `building_surfaces` | Adaptive full-footprint XY/Z layers, plane fits, support, neighbouring ownership and memory budgets; see [surface attribution](building_recovery.md) |
| `roof_classes` | Null/omission only; explicit class filters are rejected |
| `roof_recovery` | Legacy settings accepted for migration; do not enable or disable native geometric attribution. Explicit candidate-class lists are rejected |
| `roof_surfaces` | Legacy settings; mandatory attribution is controlled by `building_surfaces` |
| `roof_regions` | Optional supported internal regions under the original identity; requires LiDAR LoD1 and an independent base. Optional `object_ids` limits selection. See [terraces](roof_regions.md) |
| `invalid_objects` | `error` by default, or explicit `exclude` |
| `unresolved_objects` | `omit` by default: omit unresolved volumes while retaining labelled footprint markers; `error` stops the build |
| `show_unresolved_footprints` | `true` by default: include valid unresolved units as labelled LoD0 footprint markers in each requested model. `false` explicitly restores historical geometry omission |
| `precision_m` | Metric quantisation step, default 0.001; not measurement accuracy |
| `height` | Closed estimator overrides: histogram, reliability, storeys, regional fallback |
| `sampling` | Closed overrides: ground rings/grid, batches/cells and vertical diagnostics; legacy erosion does not trim mandatory roof attribution |
| `source_inventory` | Optional snapshot v1 inventory with GPKG hash, accounting for IDs without geometry rows |

Explicit overrides can be added to a complete configuration:

```json
{
  "roof_classes": null,
  "sampling": {"cell_size_m": 64, "chunk_points": 500000},
  "height": {"regional_floor_height_m": null}
}
```

This fragment is not a standalone configuration. Original class labels are
metadata. Unknown keys, explicit class filters and contradictory settings produce
errors rather than silent corrections.

`lods` accepts 0 and 1. Requesting 2 fails instead of relabelling an LoD1 box.
See [supported outputs and limits](capabilities.md).

## Tile conversion

`--z-offset-m` is mandatory, including zero. It declares
`ellipsoidal_height = source_Z + offset`: a constant local placement adjustment,
**not a geoid transformation**. The conversion records this declaration and
measures float32 encoding loss.

The initial exporter emits one tile up to 100 km projected diagonal and rejects
larger spans. It provides no hierarchy or compression. IDs/attributes are stored
in glTF node `extras`; Cesium semantic picking through `EXT_mesh_features` is
not yet available. See [Cesium](cesium.md).
