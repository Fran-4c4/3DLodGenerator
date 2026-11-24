# Run outputs

`build` creates a new directory and reads inputs without modifying them.

| File | Content |
|---|---|
| `model.lod0.city.json` | Footprint surfaces at representative ground bases, plus labelled unresolved footprints |
| `model.lod1.city.json` | Resolved solids with walls, base, roof and courtyards; unresolved units retain LoD0 footprint markers |
| `quality.json` | Status, method, evidence and issues for every input identity |
| `objects.csv` | The same objects as a review/comparison table |
| `run.json` | Effective configuration, versions, configuration/GPKG hashes and summary |

Direct point-ground builds write `ground.city.json` (observed-point TIN) and,
with LoD1, `scene.lod1.city.json` (buildings plus terrain). A capped diagnostic
`ground.sample.gpkg` is written only when explicitly requested; it is disabled
by default. Terrain export can also be disabled; see [ground from LiDAR](point_ground.md).
The terrain is neither a classified road layer nor a stitched building interface.

Only requested levels are generated. Models use **CityJSON 2.0**, tested against
the official 2.0.1 schema. Each level has its own file to avoid overlapping
representations in viewers without a level selector.

## Identity and geometry

Export IDs reversibly combine class and source ID. A Building organises its
BuildingParts without adding a duplicate parent box. A disconnected part keeps
multiple Solid geometries within the same object. Courtyards retain interior
rings and courtyard walls.

Coordinates use the metric working CRS with `transform.scale/translate`
quantisation. The step is not a source accuracy claim. Geometry collapse after
quantisation produces an error.

LoD0 has a representative horizontal base per unit, not a continuous DTM mesh.
LoD1 has a flat roof per body. Optional [internal roof regions](roof_regions.md)
can represent terraces and towers with several flat volumes under one source ID.
For method `roof_regions`, aggregate height/top Z refer to the highest region;
the evidence includes individual roof elevations and inferred XY boundaries.
The LoD1 export represents each roof region with a horizontal top surface.

## Unresolved parts remain visible

Valid identified parts retain geometry even when a reliable base or roof cannot
be established. Where the requested level cannot be reconstructed, the default
output includes their footprint as an LoD0 `MultiSurface`, labelled
`representation: unresolved_footprint`. It is a
location marker, not a reconstructed building volume. A nominal LoD1 file can
therefore contain these explicitly labelled LoD0 geometries alongside solids.

In 3dLodViewer these markers appear in amber with their perimeter and respect
3D occlusion. The optional X-ray display reveals hidden markers; prefer a top
view to avoid misleading perspective overlap. Search by the original object ID to inspect the
missing-height explanation. This diagnostic overlay identifies the footprint;
its colour and visibility do not assert a measured ground or roof elevation.

Placement uses the part's sampled or inferred ground when available. Otherwise
it uses the observed roof mode or, if neither is available, the export origin's
Z as a display reference only. Attributes `display_placement` and
`display_reference_z` identify that choice. Unknown `ground_z` and `height_m`
remain null; the marker has no asserted ground-surface semantics.

`show_unresolved_footprints: false` explicitly restores geometry omission for
unresolved levels. `unresolved_objects: error` still stops the build instead of
producing a partial result. Invalid or explicitly excluded source geometries
remain reported without invented replacement shapes.

## Status and provenance

Objects may be resolved, unresolved, excluded or semantic parents. Objects
without geometry still count; an orphan is reported without fictitious parentage.
Declared object counts must not be confused with visible mesh counts.

Part records in `quality.json` include `parent_relation` when both geometries
are valid: `outside_area_m2` measures the part outside its declared parent,
and `overlap_fraction` is the intersection area divided by part area.
Zero outside area means containment; small positive values may reflect boundary
differences. A null relation means unavailable evidence or a semantic parent.
Partial overflow preserves the source geometry and declared relationship.

Methods distinguish `direct`, `floor_share`, `regional`, `external_height`,
`known_height`, `dtm_surface`, `lidar_ground_surface` and `unresolved`. Inference is not labelled as
measurement. `ground_z`, `height_m` and `reconstructed_top_z` separate ground,
visible height and reconstructed absolute roof elevation.
`roof_band` identifies a context-attributed target LiDAR band: the upper observed
Z of its selected stable peak becomes `roof_reference_z`, and the visible height
is that reference minus ground. Storeys help select the band, not multiply its
elevation. `direct` records its modal reference in the same field. A null value
means no attributable local roof reference is available.
CityJSON attributes also include `reference_part_id`, `floor_height_m`,
`roof_mode_z` and `roof_strength`, so a viewer can distinguish the reference
used for inference from the ambiguous roof observations that prompted it.
`inferred_roof_support_fraction` records the fraction of usable target returns
near a tested inferred roof. Null means not checked; zero means checked with no
support. It is not an accuracy score. The corresponding CSV columns include
reference ID, floor height and this support diagnostic.

`reference_role: input` means a supplied height was used in reconstruction.
Agreement with that value is not an independent accuracy check.

`ground_method: geometric_exterior_plane` identifies a base projected from a
coherent exterior XYZ plane. `ground_plane` records its local coefficients,
origin, slope, residual and observed elevation range. This is not a histogram
median; `ground_median_error_bound_m` is null. Candidate/sample counts and
observed min/max remain separate from the roof method. The terrain display
reduction is never used to estimate those bases.

`ground_method: adjacent_part_ground` identifies an inferred base from original
measured references connected through shared boundaries of the same building.
`adjacent_ground` records the reference IDs, elevations and paths. Such a base
has no numerical measurement-error bound and cannot calibrate other parts'
storey heights. Conflicting references add a review flag rather than hiding the
part. See [interior base estimation](point_ground.md#interior-parts-without-exposed-ground).

In the explicit raster workflow, geometric-ground/DTM checks assess local numerical compatibility when sufficient support
exists. They identify neither a vertical datum nor common survey provenance.

## GLB and tileset

`tiles` consumes supported CityJSON and creates a separate directory:

```text
model.glb          triangulated meshes with small local positions
tileset.json       3D Tiles 1.1, bounding box and local-to-ECEF transform
conversion.json    vertical placement, counts and measured numerical error
```

Serve it over static HTTP without an API, catalogue or session. Mesh IDs travel
in glTF nodes; the report/CityJSON retain the complete inventory, including
objects without meshes. Quantized-mesh terrain is not generated. See
[Cesium](cesium.md).
