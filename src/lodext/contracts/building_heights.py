"""String contracts owned by the building heights boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class BuildingInputFields:
    """Canonical building storeys and qualified auxiliary-height input fields."""

    STOREYS_ABOVE: Final[str] = 'storeys_above'  # Wire key for known above-ground storey count.
    STOREYS_BELOW: Final[str] = 'storeys_below'  # Wire key for known basement count.
    REFERENCE_HEIGHT_M: Final[str] = 'reference_height_m'  # Wire key for qualified auxiliary height.
    REFERENCE_HEIGHT_METHOD: Final[str] = 'reference_height_method'  # Wire key for qualified auxiliary-height method.
    REFERENCE_HEIGHT_SOURCE: Final[str] = 'reference_height_source'  # Wire key for qualified auxiliary-height provenance.


class BuildingHeightFields:
    """Per-body physical height and roof-support evidence, not surface-fit metadata."""

    HEIGHT_M: Final[str] = 'height_m'  # Wire key for visible height in metres.
    GROUND_Z: Final[str] = 'ground_z'  # Wire key for sampled ground elevation.
    N_POINTS: Final[str] = 'n_points'  # Wire key for roof observation count.
    SAMPLE_AREA_M2: Final[str] = 'sample_area_m2'  # Wire key for actual roof support area.
    DENSITY_POINTS_M2: Final[str] = 'density_points_m2'  # Wire key for roof support density.
    RECONSTRUCTED_TOP_Z: Final[str] = 'reconstructed_top_z'  # Wire key for ground plus reconstructed height.
    METHOD: Final[str] = 'method'  # Wire key for estimation or reconstruction route.
    METHODS: Final[str] = 'methods'  # Wire key for counts by estimation method.
    FLAGS: Final[str] = 'flags'  # Wire key for stable diagnostic codes.
    REFERENCE_PART_ID: Final[str] = 'reference_part_id'  # Wire key for same-building fallback anchor.
    REFERENCE_ROLE: Final[str] = 'reference_role'  # Wire key for auxiliary-height input/comparison role.
    ROOF_Z: Final[str] = 'roof_z'  # Wire key for roof elevations.
    ROOF_RECOVERY: Final[str] = 'roof_recovery'  # Per-body alternative-class selection decision, source-class counts and spatial/storey checks; absent when disabled, never a source LAS class rewrite.
    BUILDING_SURFACES: Final[str] = 'building_surfaces'  # Geometry-only candidate/ownership evidence: source XYZ support, neighbouring IDs, accepted/rejected planes and uncertainty; no LAS classes used.
    ROOF_SURFACE: Final[str] = 'roof_surface'  # Per-body weak-modal class-6 spatial plane evidence; absent when disabled/not a candidate, no storey multiplier.
    ROOF_REGIONS: Final[str] = 'roof_regions'  # Internal supported roof-region partition and provenance; same source identity, no new floor-height anchors.
    ADJACENT_GROUND: Final[str] = 'adjacent_ground'  # Missing-base or implausible-base evidence: original same-parent references, shared-boundary paths, disagreement and optional rejected base; absent without transfer.
    ROOF_MODE_Z: Final[str] = 'roof_mode_z'  # Modal roof elevation in metres on the source Z basis, before reliability/fallback; exported for inspection, not itself a certified roof height.
    FLOOR_HEIGHT_M: Final[str] = 'floor_height_m'  # Wire key for measured or inferred storey height.
    ROOF_STRENGTH: Final[str] = 'roof_strength'  # Wire key for penalised modal support fraction.
    INFERRED_ROOF_SUPPORT_FRACTION: Final[str] = 'inferred_roof_support_fraction'  # Checked fraction [0,1] around inferred absolute roof; null means not checked. Evidence, not accuracy/confidence.
    ROOF_REFERENCE_Z: Final[str] = 'roof_reference_z'  # Attributed roof Z in source metres: mode, local band or fitted spatial envelope. Null without an own roof reference. Drives roof-minus-ground height, never a raw-point maximum.
    BASE_Z: Final[str] = 'base_z'  # Wire key for reconstruction base elevation.
    SAMPLING_EVIDENCE: Final[str] = 'sampling'  # Per-part roof/ground sampling evidence attached to a height trial result.


class RoofSupportFields:
    """Derived sampling support geometry and erosion evidence."""

    EROSION: Final[str] = 'erosion'  # Wire key for roof-support erosion status.
    SAMPLE_COMPONENTS: Final[str] = 'sample_components'  # Wire key for sampling support component count.


class HeightEstimationMethod:
    """Pure height-estimator route; independent of object/run status."""

    DIRECT: Final[str] = 'direct'  # Height estimated from reliable roof-minus-ground evidence.
    FOOTPRINT_RECOVERY: Final[str] = 'footprint_roof_recovery'  # Pipeline roof height from coherent alternative-class surfaces inside the received footprint; original classes and decision evidence retained.
    ROOF_SURFACE: Final[str] = 'roof_surface'  # Pipeline flat LoD1 envelope from coherent inclined class-6 surfaces; observed roof minus ground, not LoD2 or a floor-height anchor.
    ROOF_BAND: Final[str] = 'roof_band'  # Own observed Z band disambiguated by a same-building reference; height is band Z minus ground, not storeys times floor size.
    BOUNDARY_SHARED_ROOF: Final[str] = 'boundary_shared_roof'  # Absolute roof Z supported across a positive-length same-parent boundary when a sub-resolution cadastral part has no observed level compatible with its declared storey step. It is not storeys multiplied by a floor height and cannot calibrate siblings.
    FLOOR_SHARE: Final[str] = 'floor_share'  # Height inferred from an explicit same-building anchor.
    REGIONAL: Final[str] = 'regional'  # Height inferred with an explicitly supplied regional profile.
    UNRESOLVED: Final[str] = 'unresolved'  # No height-estimation route produced a usable result.


class BuildingReconstructionMethod:
    """Additional pipeline routes outside the pure height estimator."""

    ROOF_REGIONS: Final[str] = 'roof_regions'  # Pipeline-only several flat roof volumes per source part; aggregate height is upper region envelope above existing ground.
    KNOWN_HEIGHT: Final[str] = 'known_height'  # Deliberate supplied-height extrusion.
    EXTERNAL_HEIGHT: Final[str] = 'external_height'  # Qualified external fallback after unresolved estimation.
    DTM_SURFACE: Final[str] = 'dtm_surface'  # Ground-only LoD0 representation, without roof estimation.


class BuildingHeightSource:
    """Configured building height evidence mode."""

    KNOWN: Final[str] = 'known'  # Explicit known-height input mode.
    LIDAR: Final[str] = 'lidar'  # Estimate heights from cloud evidence under explicit policies.


class AuxiliaryHeightRole:
    """Whether supplied height participated or was comparison-only."""

    INPUT: Final[str] = 'input'  # Supplied height participated in reconstruction.
    COMPARISON: Final[str] = 'comparison_only'  # Supplied height was retained only for comparison.


class BuildingHeightReason:
    """Stable missing-elevation reason emitted by building height estimation."""

    MISSING_GROUND: Final[str] = 'missing_ground'  # No accepted terrain elevation; no zero substitute.
    GROUND_INFERRED_FROM_ADJACENT_PARTS: Final[str] = 'ground_inferred_from_adjacent_parts'  # Missing base supplied from original same-parent shared-boundary evidence.
    GROUND_RECONCILED_FROM_ADJACENT_PARTS: Final[str] = 'ground_reconciled_from_adjacent_parts'  # Inconsistent measured base replaced by a strict-majority same-parent base cluster.
    ADJACENT_GROUND_DISAGREEMENT: Final[str] = 'adjacent_ground_disagreement'  # Accepted adjacent references span more than the configured disagreement distance.
    SPATIAL_ROOF_REJECTED: Final[str] = 'spatial_roof_rejected'  # Rejected planes occupy the contextual fallback's vertical layer. The observed plane cannot own the roof, but a separately established contextual height remains visible with this uncertainty flag. Producer: build pipeline; consumers: quality/CSV review.
    ADJACENT_ROOF_STOREY_CONFLICT: Final[str] = 'adjacent_roof_storey_conflict'  # An incoherent storey ratio and a selected plane continuous with neighbouring roofs block spatial-envelope promotion.
    ADJACENT_FLOOR_REFERENCE: Final[str] = 'adjacent_floor_reference'  # A boundary-dominated part used a measured same-parent part sharing a source boundary as its storey-height reference instead of the parent-wide fallback. Producer: height estimator; consumers: quality/CSV review.
    BOUNDARY_SHARED_ROOF: Final[str] = 'boundary_shared_roof'  # A sub-resolution part used an absolute roof plane observed across a positive-length same-parent boundary because no target plane supported the cadastral storey step. Producer: build pipeline; consumers: quality/CSV review.
    WALL_LIKE_FALLBACK_REJECTED: Final[str] = 'wall_like_fallback_rejected'  # A geometrically isolated sub-resolution footprint had no owned roof; storey multiplication was suppressed so it remains a visible unresolved footprint instead of a tall wall-like solid. Producer: build pipeline; consumers: quality/CSV review.


class RoofSupportErosionStatus:
    """Outcome of deriving roof support from a complete footprint."""

    APPLIED: Final[str] = 'applied'  # Roof support successfully eroded.
    EMPTY_RETAINED: Final[str] = 'empty_retained_original'  # Empty erosion retained complete original support.


class BuildingGeometryMode:
    """Selection of parent/body reconstruction units, not GPKG layer names."""

    BUILDINGS: Final[str] = 'buildings'  # Reconstruct complete parent footprints.
    PARTS: Final[str] = 'parts'  # Reconstruct explicitly related building parts.


class BuildingSurfaceFields:
    """Geometry evidence controlling roof-envelope promotion, not source labels."""
    INDEPENDENT_INTERIOR: Final[str] = 'independent_interior_support'  # True requires noncollinear actual controls beyond the uncertain perimeter; pipeline uses absence as unproven, not as a positive certificate.
    INCLINED_CONTINUOUS: Final[str] = 'inclined_continuous_roof'  # Selected connected facets vary in fitted Z by more than twice residual_m; no fixed slope angle.
    ENVELOPE_REQUIRED: Final[str] = 'geometry_envelope_required'  # Multiple comparable flat levels or a significantly inclined group require a spatial envelope instead of an eave-sized modal band.
    LOD1_REDUCTION: Final[str] = 'lod1_reduction'  # Method reducing attributed structural roof cells to the single flat elevation required by LoD1; consumed by quality/model audits, never by attribution.
    LOD1_SPATIAL_CELLS: Final[str] = 'lod1_spatial_cells'  # Positive count of uniformly indexed XY cells contributing one upper attributed structural elevation each to the final median.
    SIBLING_CALIBRATION_ALLOWED: Final[str] = 'sibling_calibration_allowed'  # Boolean owned-surface certificate consumed by the height pipeline. True permits attributed XYZ to replace this part's independent roof sample and calibrate same-parent siblings. False means the surface may reconstruct only its own part; it is emitted when deep interior support rescues a multilevel roof otherwise ambiguous across a strict majority of attached neighbours. Native attribution always emits the field; absence is not a positive certificate.
    TALL_SIBLING_CONFLICT: Final[str] = 'tall_sibling_conflict'  # Boolean emitted by native attribution when the selected full surface exceeds height.max_floor_height_m per declared target storey and continues into a larger, higher-storey same-parent part. It cannot calibrate siblings or override a valid contextual owner height; without another valid height it remains the owner's anti-disappearance fallback. Absence means false for compatibility.
    INWARD_SEED_SUPPORT: Final[str] = 'inward_seed_support'  # Candidate-group boolean: at least one control reaches a local maximum of footprint-boundary depth before a competing level. Producer: native attribution; consumer: edge-contamination ownership only. It is not roof confidence.
    MAX_BOUNDARY_DEPTH_M: Final[str] = 'max_boundary_depth_m'  # Maximum metric distance from this candidate group's controls to the active footprint boundary. Audit evidence only; no fixed acceptance distance is derived from it.
    DEEPER_INTERIOR_CONTROLS: Final[str] = 'deeper_interior_controls'  # Count of candidate controls whose local inward neighbourhood contains a competing control deeper inside the footprint. Zero means no observed inward continuation, not proof of roof ownership.
    OBSERVED_EXTERIOR_NEIGHBOURS: Final[str] = 'observed_exterior_neighbour_ids'  # Adjacent footprint IDs with the statistical minimum of compatible original controls immediately across this candidate's boundary. Used only with inward progression to reject edge contamination; it does not replace general neighbour continuity.
    LOCAL_STOREY_NEIGHBOURS: Final[str] = 'local_storey_neighbour_ids'  # Class-qualified same-parent part IDs selected from positive-length source-boundary neighbours. Boundary-dominated targets retain the complete physical list; an elongated target without an owned roof may name one measured neighbour with the closest compatible storey count. A multistorey target prefers listed multistorey candidates with a different, then closest, storey count because equal-storey terraces can have different bases. Empty means no local preference, never no neighbours in general.
    LOCAL_STOREY_ALIGNED: Final[str] = 'local_storey_aligned'  # Boolean evidence that the selected target-owned roof level was chosen among multiple LiDAR candidates using one physically adjacent part's measured storey scale. Producer: building-surface attribution. Consumers: parent-wide and explicit-local calibration gates. True reconstructs this target but forbids the derived level from recalibrating any sibling; false is the authoritative ordinary-owned-surface state.
    CALIBRATION_ROOF_Z: Final[str] = 'calibration_roof_z'  # Optional absolute roof elevation in the declared vertical metre basis from the target-owned level that would have calibrated siblings without local storey alignment. Producer: building-surface attribution; consumer: height-estimator anchor selection. None is authoritative when no independent pre-alignment level survives. It can calibrate other same-parent parts but never resolves or changes its own part.
    BOUNDARY_SHARED_ROOF_Z: Final[str] = 'boundary_shared_roof_z'  # Optional absolute metre Z for a sub-resolution target. Evidence is either a target plane matching a dominant positive-boundary same-parent roof differing by at most two storeys, or two compatible neighbours exactly one storey below/above an unobserved target whose shared edges cover at least 75% of its perimeter. A lower-storey target additionally needs two matching same-storey shape peers and a separate higher target level, so this contract can lower but not invent a raised facade roof. No target plane may support the declared storey step. Producer: surface attribution; consumer: build pipeline. None is authoritative absence. It resolves only this part and never calibrates siblings.
    BOUNDARY_SHARED_ROOF_NEIGHBOURS: Final[str] = 'boundary_shared_roof_neighbour_ids'  # Ordered class-qualified same-parent IDs supporting BOUNDARY_SHARED_ROOF_Z; strongest evidence is first and becomes the audit reference. Empty is authoritative when no shared roof exists. Producer: surface attribution; consumer: build pipeline and quality review.


class LoD1RoofReductionMethod:
    """Stable method identifiers for reducing an owned roof to one LoD1 top."""

    SPATIAL_CELL_UPPER_MEDIAN: Final[str] = 'spatial_cell_upper_median'  # Median of each XY cell's upper attributed structural Z; cell size is the observed attribution spacing in metres, raw point density cannot add weight, and lower wall/ground layers cannot lower a roof cell.


class LoD1RoofReductionReason:
    """Stable outcome reasons for the final flat LoD1 roof reduction."""

    REPRESENTATIVE_NEAR_GROUND: Final[str] = 'spatial_representative_near_ground'  # The area-oriented representative is not above ground by height.near_zero_m; it cannot override another valid estimator or create a near-zero LoD1 solid.


class BuildingSurfaceRejectionReason:
    """Stable reasons why fitted XYZ cannot own a building-part roof."""

    BOUNDARY_CONTINUITY: Final[str] = 'boundary_continuous_with_adjacent_structures'  # Boundary-dominated incomplete support continues into adjacent structures.
    MULTILEVEL_NEIGHBOUR_CONTINUITY: Final[str] = 'multiple_levels_continuous_with_adjacent_structures'  # Competing levels are explained by a strict majority of adjacent footprints.
    SIBLING_STOREY_CONFLICT: Final[str] = 'sibling_storey_surface_conflict'  # A boundary-only candidate implies the storey count of a much taller same-parent sibling rather than the target's count.
    TALL_SIBLING_OWNS_FULL_SURFACE: Final[str] = 'tall_sibling_owns_full_surface'  # A deep full-footprint upper level is incompatible with the target's declared storeys, continues into larger taller same-parent parts, and has a separately supported lower target-compatible alternative. Producer: native surface attribution; consumer: quality audit. It rejects only the upper level and never blocks the lower owned surface.
    HIGHER_SIBLING_BOUNDARY_SURFACE: Final[str] = 'higher_sibling_boundary_surface'  # A secondary facet rises above the target's dominant roof and terminates at the independently observed roof of a higher-storey sibling; it is an ownership boundary, not the target roof envelope.
    EDGE_LEVEL_CONTINUES_OUTSIDE: Final[str] = 'edge_level_continues_outside'  # A level stops before a competing level along the inward observation graph and continues through an independently supported adjacent footprint. It is boundary contamination, not the target roof.
    ISOLATED_WALL_LIKE_SURFACE: Final[str] = 'isolated_wall_like_surface'  # A strongly non-compact footprint is narrower than the local observation-uncertainty diameter, has no deep controls and no adjacent reliably observed body. A tall extrusion would be wall-like and remains unresolved.
    SUBRESOLUTION_SINGLE_STOREY_ABOVE_SIBLINGS: Final[str] = 'subresolution_single_storey_above_siblings'  # A one-storey part has no interior beyond local observation uncertainty and its boundary-only roof lies above every adjacent multistorey sibling by more than the roof tolerance while implying more than height.max_floor_height_m. The plane cannot own the target roof; contextual fallback remains allowed.
