# Tests and acceptance matrix

Public synthetic tests require no private dataset or database. Las Canteras
regression checks use local campaign outputs when available.
LoD2 and advanced-scale cases below are acceptance targets, not claims
that every listed scenario is already implemented.

## Existing test groups

| Tests | Evidence |
|---|---|
| `test_building_surface_attribution.py` | Full-footprint attribution, interior-to-boundary level ownership with observed exterior continuation, isolated sub-resolution strip/perimeter rejection, constrained local shared-boundary storey and absolute-roof evidence, repeated facade families, descending rooftop-equipment correction, calibration isolation, deep-interior setback terraces, spatial-cell-upper-median LoD1 reduction under uneven point density and lower vertical layers, rooftop-room occlusion, real edge terraces, pitched roofs, low bodies next to towers, beam gaps, irregular canopy, sparse/thin support, source coverage, streaming compression equivalence, nested parts, displaced sibling roofs, and tall single-storey halls with deep controls |
| `test_geometric_ground.py` | Sloping exterior ground, low outliers, occupied-area exclusion, source-order/chunk and label invariance |
| `test_building_worker_equivalence.py` | Sequential/four-worker native models, quality and terrain are identical |
| `test_building_label_invariance.py` | Native/DTM geometry and height/base/status/method invariance; explicit rejection of label filters |
| `test_height_estimator.py` | Pure modal/reliability/fallback calculation, multistorey local-reference ranking, independent-parent coherence and pre-alignment calibration isolation |
| `test_roof_planes.py` | Experimental spatial roof fits: symmetric/asymmetric/repeated gables, contamination rejection, coverage and coordinate invariance; not integrated into build |
| `test_roof_surface_pipeline.py` | Native label-independent flat-level, pitched/asymmetric/repeated, gentle and steep roof recovery; irregular-cloud rejection, nonzero ground, missing storeys, source preservation, flat LoD1 schema, budgets and both ground modes |
| `test_roof_ownership.py` | Lower part beside a tower, ordinary rooftop rooms, tall halls, missing contextual evidence, and no default area cutoff; these are physical controls without real-world IDs in the algorithm |
| `test_roof_regions.py` | Internal terraces and small towers, low steps, isolated high noise, irregular canopy rejection, nonzero/large coordinates, courtyard preservation, default/targeted policies, unknown IDs, budgets and native LiDAR/DTM exports under original identities |
| `test_footprint_surfaces.py` | Class-neutral XYZ evidence under arbitrary LAS labels, continuous flat/sloping terrain rejection, independent exterior support, unknown context and explicit legacy filters |
| `test_roof_recovery.py` | Legacy standalone roof-recovery controls and mandatory native geometric attribution: terrace layers, irregular trees, footprint coverage, storey contradictions, bounded streaming and both ground modes |
| `test_resource_sampling.py` | Numerical sampling and parameter validation |
| `test_vertical_consistency.py` | Offset, dispersion, pairing and insufficient evidence |
| `test_full_height_trial.py` | Synthetic checks for cell ownership and invalid-parent quarantine |
| `test_build_pipeline.py` | Public workflow, official schema, geometry and policies |
| `test_point_ground.py` | DTM-free builds, official schema, geometric exterior planes and independent display reduction, occupied-area exclusion, bounded histogram growth, capped opt-in point sample, terrain limits and unchanged inputs |
| `test_adjacent_ground.py` | Same-parent shared-boundary base transfer, slopes/conflicts, frozen measured references, bounded paths, native LiDAR/DTM workflows and visible unresolved footprints without invented heights |
| `test_tiles_export.py` | GLB, frames, quantisation and bounds |
| `test_surface_pipeline.py` | Individual Road/Terrain/Forest/Water, constrained TIN, schema, coordinates, policies and tiles; not global stitching |
| `test_string_contracts.py` | Shared diagnostics, class constants excluded from input/output fields, resource resolution, source IDs containing the delimiter and independent status-field wiring across object/run/vertical/road-fit records |


## Heights and sampling acceptance

- Preserve measured 4.3 m height despite two storeys; do not reduce a tall
  one-storey warehouse to a generic dwelling height.
- Preserve deep-interior roofs in stepped/setback buildings; a local storey
  comparison may choose only a lower observed structural level and may not
  flatten a genuine terrace sequence.
- Prefer a physically adjacent multistorey reference over a one-storey ground
  floor or rooftop body, without assuming a fixed residential floor height.
- Resist a sparse high-neighbour tail; diagnose similarly strong separated
  modes and small-part incoherence rather than silently choosing a neighbour.
- Preserve a 3.8 mÃ‚Â² shed with 22 points and a genuine roughly 1.8 m terrace.
- Exercise the actual below-12-point density route with an explicit statistical
  minimum, support-area denominator and deterministic modal ties.
- Preserve all erosion components/BBOX; distinguish empty erosion from an empty
  source footprint. Sampling support never replaces exported geometry.
- Missing/out-of-extent/NoData DTM must not become zero or roof-derived ground.
- Unknown, zero and below-ground storeys remain distinct. Missing-data fallback
  and invalid configuration are different states.

## Data, CRS and geometry acceptance

- Require explicit parentage, canonical types and reversible class-qualified IDs;
  no suffix inference or numeric-`fid` substitution. Reject duplicates/empty IDs,
  fractional storeys and heights without provenance.
- Retain neighbour context beyond output selection. Diagnose orphan/outside-parent
  parts without silently changing mode, clipping or reparenting.
- Preserve courtyard/concave area, multipolygon components and adjacent parts;
  adjacency alone does not prove stacking.
- Check equivalent physical results in different appropriate CRSs, another zone
  and hemisphere. Do not measure in geographic/Web Mercator coordinates.
- Separate orthometric Z from ECEF ellipsoidal placement; require a justified
  operation or explicit failure. Evaluate slopes against control elevations.
- Quantisation must preserve rings, separation and height. Planned pitched-LoD2
  cases must triangulate in their planes with coherent normals/volumes.

## Engines and export acceptance

LoD0 must work without roof points or a LoD2 engine. LoD1 parts must not duplicate
the parent box. A future LoD2 adapter must record actual output level, fallback,
omission and zero-output failures; test nonzero ground and all covering cloud
tiles, including verified COPC spatial capability and incomplete coverage.
CityJSONSeq collection must preserve header transforms, IDs and relations.

Tile conversion must accept supported external CityJSON independently of height
estimation. Check GLB headers/alignment/indices/normals, local-to-ECEF recovery
and actual-content bounds. Planned feature tables require stable source-ID
picking; future hierarchies require composed transforms, valid relative URIs,
object ownership and no duplicates. These pending items are not established by
a successful initial single-tile render.

## Independence and operation

`test_native_environment.py` exercises an already-initialised foreign PROJ
search path and verifies EPSG:4083 GeoTIFF read/write. `test_raster_sampling.py`
compares bounded block reads with independent per-point sampling, including
rotated grids, reprojection, masks, scale/offset, boundaries and non-finite input.
The public pipeline tests also cover both a boundary-touching part and a fully
displaced part: strict reception rejects them, while explicit exclusion retains
their identity and reason without geometry or reassignment.
Point-touching courtyard/exterior and courtyard/courtyard rings are partitioned
into exact non-overlapping closed LoD1 solids while LoD0 retains the original
polygon. The tests validate union equivalence through CityJSON quantisation. A half-outside part checks
measured parent overlap and report serialization without clipping or reassignment.
`test_roof_spatial_queries.py` compares bulk indexed selection against independent
polygon masks for boundaries, holes, multipart geometry, overlaps and LAS-class
filters, including original observation order.

Acceptance includes clean installation without other checkouts/personal files,
offline processing after installation, paths containing spaces/non-ASCII,
unchanged inputs, no silent output replacement and complete per-ID reports.
Do not require the full LiDAR/LoD2 chain for pure-height tests. The broader
acceptance matrix does not become verified merely because it is documented.


## Mandatory building label-invariance acceptance

Run `.venv/Scripts/python.exe tools/check_building_label_invariance.py` (or the
active Python executable) from the repository root. This uses public synthetic
XYZ and footprints, changing only provider classifications. It returns 1 when
building height/base changes. It is a separate acceptance gate, not evidence
supplied by the ordinary passing unit suite. The geometric pipeline passes the
original, roof-label-only, exterior-label-only and random-all-label variants,
including geometry, height/base, status and method invariance. Native LiDAR and
DTM integration tests also exercise noise, unclassified and arbitrary labels.

## Bounded real-data campaigns

Use `tools/create_case_subset.py` before repeating a large real reconstruction.
One or more known part IDs select their complete parent buildings; a metric
context buffer adds intersecting buildings with all their parts. The generated
GeoPackage and configuration use the ordinary pipeline, original LiDAR paths
and `building_context` terrain scope. IDs are campaign evidence only and never
enter reconstruction logic.

Run synthetic tests first, then the bounded campaign, and reserve a complete
dataset build for a stable candidate. A campaign only validates its selected
objects and surroundings; passing it is not evidence that every source part in
the city has been reviewed.
