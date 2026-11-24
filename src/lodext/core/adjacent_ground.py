"""Settings for auditable same-building ground transfer across shared boundaries."""
from dataclasses import dataclass
from typing import TypedDict,Literal,NotRequired
import math


class AdjacentGroundSelection:
    """Closed selection vocabulary for same-parent ground transfer evidence."""

    MISSING_BASE: str = 'shared_boundary_weighted_median'  # Missing target base supplied by the nearest measured-reference frontier.
    IMPLAUSIBLE_BASE: str = 'reconciled_shared_boundary_ground'  # Physically inconsistent measured target base replaced by a strict-majority neighbouring base cluster.


class AdjacentGroundTrigger:
    """Geometry/storey contradictions that can request measured-base review."""

    ROOF_NOT_ABOVE_GROUND: str = 'roof_not_above_ground'  # Dominant own-footprint Z is not at least near_zero_m above the measured base.
    EXTERIOR_PLANE: str = 'adjacent_exterior_plane'  # Sparse elevated plane contradicted by adjacent ground, or peripheral strip sampling only the upper end of a shared exterior slope.
    IMPLAUSIBLE_STOREY_RATIO: str = 'implausible_storey_ratio'  # Positive roof-minus-base divided by declared storeys is below min_floor_height_m/coherence_max_ratio.


class AdjacentGroundReference(TypedDict):
    """Original measured reference exported in per-part base-transfer evidence."""
    id: str  # Class-qualified source part identity; must share the target's explicit parent.
    ground_z: float  # Original measured base in source Z metres; never an inferred reference value.
    boundary_weight_m: float  # Positive minimum shared-boundary length along this path, used as median weight.
    path: list[str]  # Target-to-reference identities including both endpoints; edge count equals evidence hops.


class AdjacentGroundEvidence(TypedDict):
    """quality.json/CityJSON adjacent_ground payload; present only on accepted inference.

    Absence means no base transfer, not a rejected or failed measurement. The
    sampling reader produces it; reconstruction flags and CityJSON expose it.
    Changing keys or selection semantics changes the exported evidence contract.
    """
    accepted: Literal[True]  # Emitted transfers are accepted estimates, not measurement/accuracy claims.
    hops: int  # Positive nearest anchored frontier distance, bounded by configured max_hops.
    selection: Literal['shared_boundary_weighted_median','reconciled_shared_boundary_ground']  # Missing-base transfer or strict-majority reconciliation; exact half-weight ties choose lower Z.
    selected_reference_id: str  # Identity whose original measured ground supplies the target base.
    reference_spread_m: float  # Nonnegative max-minus-min Z among nearest-frontier measured references.
    conflicting_references: bool  # True precisely when reference_spread_m exceeds configured disagreement_m.
    references: list[AdjacentGroundReference]  # Nonempty frozen measured references; no later inferred base is reused.
    original_ground_z: NotRequired[float]  # Rejected original measured base in source Z metres; present only for reconciliation.
    trigger: NotRequired[Literal['roof_not_above_ground','implausible_storey_ratio','adjacent_exterior_plane']]  # Measured-base review reason.


@dataclass(frozen=True)
class AdjacentGroundConfig:
    """Closed adjacent_ground policy, independent of exterior search radii.

    Missing bases are inferred. A measured base changes only when own-footprint
    roof evidence makes it physically inconsistent and a strict-majority cluster
    of plausible original same-parent bases exists on the nearest shared-boundary
    frontier. References must be originally sampled parts connected by positive
    shared boundary. Inferred/reconciled bases never become measured anchors.
    """
    enabled: bool = True  # Missing-base inference and physically gated base reconciliation are enabled by default; false requests strict exterior-ground-only sampling.
    max_hops: int = 8  # Positive graph-edge limit; nearest measured-anchor frontier wins, never a global parent median.
    tolerance_m: float = 0.002  # Nonnegative metric boundary-gap tolerance for quantization, not a neighbour search radius.
    min_shared_boundary_m: float = 0.05  # Positive shared-boundary length; point contact alone cannot transfer a base.
    disagreement_m: float = 1.5  # Nonnegative reference-ground spread above which inference is explicitly flagged as conflicting, not silently discarded.

    def __post_init__(self):
        """Reject invalid graph, distance and switch domains."""
        if type(self.enabled) is not bool:raise ValueError('adjacent_ground.enabled must be boolean')
        if type(self.max_hops) is not int or self.max_hops<1:raise ValueError('adjacent_ground.max_hops must be positive integer')
        for key in ('tolerance_m','min_shared_boundary_m','disagreement_m'):
            v=getattr(self,key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or (key=='min_shared_boundary_m' and v==0):raise ValueError(f'Invalid adjacent_ground.{key}')
