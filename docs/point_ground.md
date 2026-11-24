# Reconstruct buildings and ground from LiDAR

Supply GeoPackage footprints and LAS/LAZ/COPC observations. No terrain raster is
required. The same XYZ cloud supplies roof hypotheses and exterior terrain
hypotheses. LAS classifications are metadata, never evidence of ground or roof.

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

Choose the working CRS for the location. All source Z values must already share
compatible metre units and the declared vertical basis. Omit `dtm` for direct
point-based ground; a supplied compatible DTM explicitly selects raster ground.

```powershell
lodext validate build.json
lodext build build.json --output results/run-01
```

## Estimate local terrain geometrically

The building base is estimated from LiDAR observations on exposed ground around the footprint. On a slope, the flat LoD1 base uses the lowest supported exterior contact. Inspect the slope and elevation range in the `ground_plane` record when the base looks too low or too high.

### Interior parts without exposed ground

A part enclosed by other parts may have no exposed ground within any search
ring. Increasing the radius can reach another street at a different elevation.
Instead, missing bases can inherit an originally sampled base from an adjacent
part of the same explicitly identified building.

Look for `ground_method: adjacent_part_ground` in the object attributes. The `adjacent_ground` record identifies the reference part and elevation. If a measured base was revised, compare `original_ground_z` with the adopted value. Review parts flagged `adjacent_ground_disagreement` against the original points, particularly where adjoining parts face streets at different levels.

The optional `adjacent_ground` settings apply to both direct LiDAR and explicit
DTM workflows:

| Setting | Default | Effect |
|---|---|---|
| `enabled` | `true` | Infer missing bases and enable physically gated shared-boundary base reconciliation |
| `max_hops` | `8` | Maximum number of shared-boundary connections to a measured reference |
| `tolerance_m` | `0.002` | Boundary-gap tolerance in metres; not a wider ground-search radius |
| `min_shared_boundary_m` | `0.05` | Minimum shared length in metres; excludes isolated point contacts |
| `disagreement_m` | `1.5` | Reference elevation spread in metres above which uncertainty is flagged |

If no usable reference or roof is available, the part remains unresolved and
keeps a labelled footprint in the output. See [output representations](outputs.md#unresolved-parts-remain-visible).

## Bounded processing and terrain output

Use the following `ground` settings to adjust base sampling. Terrain display resolution is configured separately.

| Setting | Default | Meaning |
|---|---|---|
| `geometric_cell_size_m` | 2 m | XY cell size for base evidence, independent of display |
| `layer_step_m` | 0.5 m | Candidate elevation-layer width; representative XYZ remains original |
| `min_layer_returns` | 1 | Minimum local returns; independent spatial plane support is still required |
| `surface_residual_m` | 0.3 m | Local exterior-plane vertical tolerance |
| `max_slope_deg` | 60 | Maximum terrain plane slope |
| `max_histogram_bins` | 2000000 | Hard retained candidate-layer budget |

A separate reduction produces the display terrain TIN. `surface_cell_size_m`
controls its retained source representatives and `surface_max_edge_m` limits
triangles across gaps. Triangles through building footprints are omitted;
missing support is not filled by invented ground. `surface_scope: input_tiles`
includes declared tile extents, while `building_context` restricts reception to
building neighbourhoods. No Road or Bridge semantics are inferred by this TIN.

Set `export_surface: false` to omit the terrain files. Optional
`export_points: true` writes a source-order audit capped by `max_export_points`;
its original classes remain metadata and its rows are candidates, not certified
ground. Sources and earlier output directories remain unchanged.

Old configurations with `ground.classes: [2]` must replace the list with `null`
or omit it. Building reconstruction cannot be switched back to class filtering.
