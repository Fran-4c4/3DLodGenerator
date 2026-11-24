# 3DLodExt working rules

## Scope and reading

These rules belong to 3DLodExt alone. Read [README.md](README.md),
[docs/index.md](docs/index.md) and the affected component's documentation.
Check implementation status in [supported outputs and limits](docs/capabilities.md).
Documentation is maintained **in English**. Distinguish requirements, reference
implementations and observed results; do not advertise proposals as capabilities.

The HTML site is an end-user manual for GIS users supplying local files and
generating 3D models, not a mirror of repository documentation. Before editing
its pages, navigation or publication sources, read
[the publication instructions](CONTRIBUTING.md#documentation-website). Keep design plans, development histories and chat transcripts outside this repository.
Use `docs/` for functional documentation. Introduce figures in the preceding
explanation and acknowledge upstream inspiration once.

Establish the reference surface behaviour before introducing new heuristics.
The HTML manual explains the product and process before installation.

## Independence

- The basic workflow uses local files and a CLI. After dependencies/data are
  installed it must process without network access.
- Do not require authentication, a task catalogue, database, private image
  registry or deployment service in the core.
- No import, symlink, script or setting may require another checkout, personal
  directory or external development environment.
- Documentation must stand alone. External references must be public. Do not
  copy operational notes, secrets or infrastructure paths. Use project/config
  relative paths.
- Read inputs without modification. Each run owns a new output directory;
  never replace earlier results silently.

## Geometric invariants

Valid identified building parts must remain spatially visible in inspection
outputs. Infer missing interior bases from documented same-parent adjacency
where supported; otherwise retain a labelled unresolved footprint rather than
inventing a solid or silently erasing the part. Keep the default visibility and
adjacent-ground policies enabled in current workflows unless the user explicitly
requests legacy omission. Conflicting references remain visible with uncertainty.

The received valid footprint is authoritative for building identity and boundary.
Use XYZ surface coherence, observed support and neighbouring structures to assess
roof ownership. An interior return is a candidate, not proof of a roof. Preserve
provider classifications only as provenance and optional display, and establish
building bases from independent geometric ground evidence.

Building reconstruction uses
XYZ geometry and received footprints, NEVER LAS class labels as selection,
rejection, weighting, confidence or fallback-routing evidence. This covers
roof candidates, roofs/regions, ground evidence used to establish building
bases, recovery and downstream calibration. Preserve original labels only for
provenance and optional display. Unknown ownership remains explicit; it cannot
be resolved by trusting a provider label.

A building acceptance test must hold XYZ, footprints and auxiliary attributes
fixed while permuting ONLY LAS classifications. Building geometry, height/base,
resolution status and selection method must remain invariant. Metadata/counts
of original classifications may change. Run
`python tools/check_building_label_invariance.py` before claiming compliance.
A failed audit blocks promotion regardless of the ordinary unit-test count.

The building pipeline implements this rule through geometric exterior ground
and mandatory full-footprint surface attribution. Explicit class allowlists are
rejected rather than ignored. Legacy standalone experiments are not the native
building pipeline. Keep the independent label-permutation acceptance gate passing.

Surface attribution must consider adjacent footprints and their reliably
observed surfaces, including other parents. A return's XY inclusion in a
footprint is candidate evidence, not proof of ownership. Separate competing
levels before evaluating support; a coherent roof need not explain a majority
of all ground/wall/upper-level returns in the crop. Do not use one global
explained-point percentage as sufficient acceptance or rejection. Account for
observed sampling spacing, footprint width/shape, occlusion and registration
uncertainty instead of introducing a fixed area cutoff. Sparse returns remain
uncertain; do not shift source footprints to maximise counts. Context must not
create circular height references or lift low parts to neighbouring towers.

Choose a metric working CRS appropriate to location/extent; do not measure in
degrees/Web Mercator or impose one UTM zone globally. Keep ground elevation,
roof elevation and visible height separate. Horizontal reprojection cannot
resolve an unknown vertical datum.

Reconstruct with known local up before ECEF placement. Preserve courtyards,
concavities, every multipart component and source identity. Parent relationships
are explicit: never infer them from suffixes or add part heights. Reliable LiDAR
precedes cadastral-storey fallback; record every inference, degradation and
exclusion. Do not assume all roofs are flat or delete small bodies by area alone.
Regional profiles are explicit and opt-in. Do not claim format, topology or LoD
conformance without the corresponding validation.

Internal roof-region reconstruction keeps the received source identity and
footprint within declared export precision. Inferred regions are never presented
as received cadastral parts. Preserve supported terraces and small towers;
isolated height maxima alone cannot establish a new region. Record per-region
elevations and original single-roof provenance. Region envelopes are calculated
after storey calibration and must not become new calibration anchors.

Spatial roof recovery must accept supported horizontal as well as inclined
planes by default. Mixed roof levels can weaken a height histogram without
invalidating the building. Estimate slopes from XYZ and retain spatial coverage,
residual and independent-ground checks; any positive minimum-inclination gate
must remain an explicit configuration restriction, never an implicit default.

## Contracts and verification

Every behaviour-controlling field has one owning type and one authoritative
default, with semantics/units documented there. Historical tables are references,
not configuration owners. Reject contradictions instead of silently normalising
to a different valid setting.

Document every typed class field beside its declaration, including required
fields without defaults and output/evidence attributes. A class-level field
summary supplements these comments; it does not replace them.
Document constants beside their definitions as well as class fields: explain
purpose, units/domains, consumers and the effect of changing them. Important
functions need English docstrings describing purpose, meaningful inputs/results,
side effects, failure conditions and geometric/numerical limitations. Explain
decisions rather than restating the function name. Documentation changes must
not silently change values, defaults or algorithm behaviour.

String ownership follows semantic domain and scope.
Use owner-qualified names such as `ReconstructionObjectStatus.RESOLVED`;
generic `STATUS_RESOLVED` or `Keys.STATUS` hide responsibility. Definitions
belong in the relevant module under `lodext.contracts`; `lodext.strings` is an
explicit namespace facade.
Do not restore flat aliases or merge different contracts because values match.
Keep single-class vocabulary
on the owning class as documented `ClassVar` constants, excluded from dataclass
fields and serialized configuration. Single-method/function text can stay local.
Do not equate different concepts just because their current strings match; do
not create competing defaults. Preserve external spellings and keep independent
test/schema expectations.

Test result-changing work with measurable physical/geometric cases; see
[tests](tests/README.md). Pure height tests must not require the entire LiDAR
stack. A successful external process is insufficient: verify output content,
coverage, CRS, IDs and geometry.

Reported objects are regression evidence, never IDs to special-case in an
algorithm. Pair each general correction with positive and negative synthetic
controls, including previously valid roofs, small rooms, sparse/irregular points
and lower parts beside taller siblings. Compare complete-run height and geometry
changes before promoting a new result; recovery counts alone do not establish
an improvement. Keep uncertain parts visible without inventing a height.

Keep functional documentation in `docs/` and project agent procedures here.
Documentation-only work does not require algorithm changes. Preserve third-party
authorship/provenance; consult [THIRD_PARTY.md](THIRD_PARTY.md).
