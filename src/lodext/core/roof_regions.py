"""Authoritative opt-in policy and evidence for internal stepped LoD1 roofs."""
from dataclasses import dataclass
from typing import TypedDict
import math


@dataclass(frozen=True)
class RoofRegionsConfig:
    """Closed roof_regions JSON policy; never modifies received IDs/footprints.

    Source XYZ observations establish XY-connected upper surfaces in metric cells.
    Only fully covered LiDAR bodies with an independent base and supported levels are
    subdivided. Each region is extruded from the existing base, under the same
    CityObject identity. Disabled omission preserves historical flat extrusion.
    The reader, region fitter and exporter consume this policy; no CLI defaults.
    """
    enabled: bool = False  # Opt into multi-volume LoD1; requires LiDAR heights and requested LoD1.
    object_ids: tuple[str,...] | None = None  # None considers all eligible objects; a nonempty unique list/tuple selects exact class-qualified source keys for targeted reconstruction. Unknown keys fail at reception; does not assign heights or change inference criteria.
    cell_size_m: float = 1.0  # Positive metric XY cell edge; controls observation aggregation and inferred boundary resolution.
    layer_step_m: float = 1.0  # Positive source-Z bin edge, separating stacked observations before upper-surface selection.
    min_cell_points: int = 2  # Positive original-return count per eligible XY/Z cell layer; single isolated returns cannot create roofs.
    neighbour_height_m: float = 1.5  # Positive inclusive Z difference across 8-neighbour cells; separates steps while retaining connected inclined caps.
    min_region_cells: int = 8  # Integer >=3 spatial cells per accepted connected surface; smaller components cannot become roof bodies.
    min_region_area_m2: float = 8.0  # Positive occupied-cell area gate in square metres; never deletes a received body.
    min_level_separation_m: float = 1.5  # Positive roof-Z range required to replace one flat extrusion with several regions; preserves typical low terrace steps above the neighbour-link threshold.
    min_coverage: float = 0.6  # Fraction (0,1] of sampling support covered by retained region cells; insufficient evidence keeps previous geometry.
    max_extrapolation_m: float = 3.0  # Positive observed-region extension bound before simplify_m boundary simplification; unsupported remainder retains the original roof.
    simplify_m: float = 0.75  # Nonnegative simplification distance for internal region boundaries; exterior is re-clipped to the source polygon.
    max_cells_per_object: int = 100000  # Positive retained XY cell budget per candidate; excess aborts, never silently changes resolution.
    max_total_cells: int = 2000000  # Positive total retained XY cell budget across candidates; excess requires explicit budget increase or partitioning.
    max_layers_per_cell: int = 16  # Positive vertical-layer budget per XY cell. On excess the entire column becomes unusable, with an explicit evidence count/flag; do not retain an order-dependent first subset. Global XY-cell budgets still abort.
    max_regions: int = 128  # Integer >=2 output connected-surface budget per source object; excess keeps previous flat geometry with rejection evidence.

    def __post_init__(self):
        """Reject invalid domains and budgets without coercing settings."""
        if type(self.enabled) is not bool:raise ValueError('roof_regions.enabled must be boolean')
        if self.object_ids is not None:
            if not isinstance(self.object_ids,(list,tuple)) or not self.object_ids or any(not isinstance(v,str) or not v.startswith(('Building::','BuildingPart::')) or not v.split('::',1)[1].strip() for v in self.object_ids) or len(set(self.object_ids))!=len(self.object_ids):raise ValueError('roof_regions.object_ids must be nonempty unique class-qualified keys or null')
            object.__setattr__(self,'object_ids',tuple(self.object_ids))
        for name in ('cell_size_m','layer_step_m','neighbour_height_m','min_region_area_m2','min_level_separation_m','max_extrapolation_m','simplify_m','min_coverage'):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 or (name!='simplify_m' and value==0):raise ValueError(f'Invalid roof_regions.{name}')
        if self.min_coverage>1:raise ValueError('roof_regions.min_coverage must be <=1')
        for name,minimum in [('min_cell_points',1),('min_region_cells',3),('max_cells_per_object',1),('max_total_cells',1),('max_layers_per_cell',1),('max_regions',2)]:
            if type(getattr(self,name)) is not int or getattr(self,name)<minimum:raise ValueError(f'Invalid roof_regions.{name}')


class RoofRegion(TypedDict):
    """One inferred region in quality/CityJSON, not a new cadastral part."""
    footprint: dict  # GeoJSON Polygon/MultiPolygon in working-CRS metric XY; partitions the received footprint including holes within declared export precision.
    roof_z: float  # Absolute flat roof elevation in original source Z metres; not relative to another roof.
    support_cells: int  # Number of connected accepted source-observation cells; zero for the original-roof fallback remainder.
    area_m2: float  # Positive region footprint area before export quantization.


class RoofRegionsEvidence(TypedDict,total=False):
    """Per-object roof_regions result, exported unchanged by reports/CityJSON.

    Rejected results carry accepted=false and a reason; regions appear only on
    accepted partitions. Original method/roof remain provenance, not new anchors.
    """
    accepted: bool  # True only after support, separation and full source-partition checks pass.
    reason: str  # Stable explanation of acceptance/rejection; absence of this payload means not attempted.
    retained_cells: int  # Bounded metric XY columns encountered, including unusable columns counted separately.
    support_coverage: float  # Accepted occupied-cell area / sampling area, capped at one; not an accuracy score.
    original_method: str  # Previous single-roof reconstruction route; new region envelopes do not recalibrate storey anchors.
    original_roof_z: float | None  # Previous absolute flat roof or None when unresolved; retained as provenance, never fabricated to permit region recovery.
    remainder_reference_z: float  # Present when original_roof_z was None: source-Z envelope of the most spatially supported accepted region, used only for unsampled remainder; an explicit inference, not a calibration anchor.
    original_flags: list[str]  # Previous flat-roof diagnostics retained before region recovery; they do not describe the newly accepted partition.
    unusable_vertical_cells: int  # XY columns rejected in full for exceeding max_layers_per_cell; zero means none. Other supported cells may still reconstruct the object.
    retained_source_returns: int  # Original returns counted in retained ROI layers, including competing/base layers and provider overlap; not unique pulses or accepted-roof counts.
    regions: list[RoofRegion]  # Nonoverlapping XY partition under the original identity; all roof Z values exceed the existing ground.
    partition_issues: list[str]  # Derived-region topology diagnostics on rejection; never a change to source geometry.
    partition_error_m2: float  # Symmetric-difference area between the derived partition and source footprint, in square metres.
    partition_gap_m2: float  # Symmetric-difference area against the source on the export grid; bounded by perimeter times twice export precision because newly noded boundary intersections also round.
