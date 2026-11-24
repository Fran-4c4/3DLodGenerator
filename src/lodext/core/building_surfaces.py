"""Authoritative geometry-only building surface attribution policy."""
from dataclasses import dataclass
import math
from typing import TypedDict


@dataclass(frozen=True)
class BuildingSurfaceConfig:
    """Metric surface hypotheses, independent of LAS classifications/storey units.

    Active for every LiDAR LoD1 build. No switch restores provider-class selection.
    Bounds cap retained original observations. Global overflow fails explicitly;
    individual cells preserve deterministic lower and upper vertical evidence
    within their configured layer budget.
    """
    workers: int = 1  # Positive worker-thread count; 1 is sequential. Only independent object fits/attributions run concurrently against frozen context; results remain ordered and equivalent. Does not change source resolution or logical layer budgets; transient fitting memory grows with active workers.
    grid_axis: int = 32  # Positive maximum XY cells per footprint axis; cell width adapts to footprint extent.
    min_cell_size_m: float = 0.5  # Positive minimum sampling cell width; preserves small bodies without inward erosion.
    layer_step_m: float = 0.5  # Positive Z-layer width, metres; different roof/ground layers retain separate original points.
    max_layers_per_cell: int = 16  # Positive retained Z-layer cap per XY cell. Overflow keeps the lowest ceil(cap/2) and highest floor(cap/2) observed bands, independent of input order; increasing it retains more intermediate levels and consumes more of max_total_layers.
    max_total_layers: int = 3000000  # Positive run-wide hard cap on retained XYZ representatives; overflow aborts explicitly.
    residual_m: float = 0.2  # Positive metre vertical residual for supported planes, not a class confidence.
    registration_m: float = 0.5  # Nonnegative horizontal uncertainty, metres; expands evidence tolerance, never moves source footprints.
    max_slope_deg: float = 60.0  # [0,90) accepted plane slopes; horizontal roofs remain valid.
    min_plane_points: int = 3  # Integer >=3 independently occupied XY cells needed for a plane; three is only the mathematical minimum.
    min_plane_fraction: float = 0.08  # (0,1] candidate extraction floor relative to remaining points after each plane; never a global roof acceptance percentage.
    trials: int = 192  # Positive deterministic RANSAC trials; affects hypothesis search cost.
    max_planes: int = 8  # Positive number of competing local plane hypotheses retained.

    def __post_init__(self):
        """Reject invalid numerical/budget domains without silent normalisation."""
        for name in ('workers','grid_axis','max_layers_per_cell','max_total_layers','min_plane_points','trials','max_planes'):
            if type(getattr(self,name)) is not int or getattr(self,name)<(3 if name=='min_plane_points' else 1):
                raise ValueError('Invalid building_surfaces.'+name)
        for name in ('min_cell_size_m','layer_step_m','residual_m','registration_m','max_slope_deg','min_plane_fraction'):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid building_surfaces.'+name)
        if min(self.min_cell_size_m,self.layer_step_m,self.residual_m)<=0 or self.registration_m<0 or not 0<=self.max_slope_deg<90 or not 0<self.min_plane_fraction<=1:
            raise ValueError('Invalid building_surfaces distance, slope or fraction')


class BuildingSurfaceEvidence(TypedDict,total=False):
    """Metric local hypotheses and selection evidence; native builds emit certificates.

    Boolean certificates are computed from actual observations, not defaults.
    Older payloads lacking certificates cannot override a qualified roof band.
    """
    selection_policy: str  # Geometry/footprint/context policy identifier; never a provider classification policy.
    accepted: bool  # At least one governing observed surface has usable spatial support.
    original_representatives: int  # Bounded original XYZ representatives before local plane extraction; not all source returns.
    retained_surface_representatives: int  # Original XYZ representatives retained for native attribution after local fitting.
    spacing_m: float  # Effective observation/grid spacing in working metres.
    planes: list[dict]  # All coherent local hypotheses, including non-governing levels, with source-Z coefficients and support counts.
    candidates: list[dict]  # Group-level visible/support areas, controls, acceptance and inward-seed evidence. Inward evidence uses local boundary-depth progression and compatible exterior continuation; it is not a global explained-point percentage or confidence.
    rejected_neighbour_planes: list[dict]  # Observations explained by independent adjacent structures.
    neighbour_ids: list[str]  # Exact class-qualified keys providing frozen geometric context.
    source_classes_used: bool  # Always false for native building decisions; source labels are metadata only.
    independent_interior_support: bool  # At least three noncollinear actual controls beyond spacing+registration from the source perimeter; pipeline requires this to supersede a qualified modal/band reference.
    inclined_continuous_roof: bool  # Fitted variation across the governing continuous group exceeds twice residual_m; not an absolute degree threshold.
    geometry_envelope_required: bool  # Significant incline or multiple comparable flat levels makes a narrow modal band inadequate; consumes independent_interior_support for promotion.
    sibling_calibration_allowed: bool  # True lets accepted attributed XYZ replace the independent roof sample and calibrate same-parent siblings. False confines the accepted surface to reconstructing this part; native evidence always emits the field and absence grants no permission.
    selection_basis: str  # spatial_support, neighbour_storeys or comparable_flat_levels; describes selection, not measured accuracy.
    context_floor_height_m: float | None  # Observed neighbouring roof-minus-base per declared storey, used only to rank ambiguous surface groups. None means no supported contextual reference; never a forced height.
    roof_z: float | None  # Governing fitted upper elevation in original survey metres; None means no accepted group.


class RoofEnvelopeEvidence(TypedDict,total=False):
    """Observed spatial LoD1 envelope; accepted does not imply it governs height."""
    accepted: bool  # Surface attribution accepted a governing group.
    reason: str  # Stable geometric selection explanation.
    roof_z: float  # Fitted upper source-Z elevation in metres, not a relative storey height.
    planes: list[dict]  # Selected plane hypotheses; excludes non-governing point votes.
    retained_cells: int  # Unique actual XYZ observations voting for this envelope, deduplicated across facet seams.
    storeys_used: bool  # Auxiliary neighbouring storeys ranked ambiguous groups; roof_z still comes from observations.
    applied_to_height: bool  # Set by the pipeline: true only when this envelope supplies the final selected height. False preserves the qualified mode/band or contextual inference; absence means not yet considered.
