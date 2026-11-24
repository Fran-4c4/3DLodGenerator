"""Legacy standalone footprint-surface experiment; native attribution is mandatory and class-neutral."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RoofRecoveryConfig:
    """Authoritative roof_recovery JSON settings, effective in run provenance.

    Used for fully covered unresolved LoD1 LiDAR bodies. Only null candidate_classes is accepted. Native builds use BuildingSurfaceConfig;
    these settings remain available to standalone historical experiments.
    Does not overwrite source classes or a resolved height. Storeys check an
    observed elevation range, never multiply a reference to manufacture a roof.
    Resource/coverage failures reject recovery, never silently coarsen cells.
    """
    enabled: bool = False  # Legacy standalone switch; native builds always use BuildingSurfaceConfig and never class filtering.
    candidate_classes: tuple[int, ...] | None = None  # None selects class-neutral, targeted recovery after ordinary estimates. Non-null sequences are rejected explicitly; labels remain original metadata.
    context_m: float = 3.0  # Positive exterior comparison distance in metres for class-neutral recovery; occupied footprints are excluded. No exterior evidence means unresolved, not an invented roof.
    max_exterior_continuity: float = 0.6  # (0,1]; reject when at least this fraction of exterior cell/layer representatives continues the candidate planes within residual_m. Prevents lifting continuous flat/sloped ground.
    cell_size_m: float = 1.0  # Positive metric XY cell size; one original point nearest its centre survives.
    max_cells_per_object: int = 1024  # Positive hard retained-cell cap per body and role (interior or exterior); overflow disables its recovery.
    max_total_cells: int = 250000  # Positive run-wide occupied-cell cap, pooled across interior/exterior in class-neutral recovery; overflow aborts explicitly.
    min_cells: int = 12  # Integer >=3; minimum independently occupied cells, including on small bodies.
    min_coverage: float = 0.6  # (0,1]; fraction of support area in cells explained by accepted planes.
    residual_m: float = 0.2  # Positive inclusive vertical plane residual; source Z is not rounded/replaced.
    local_std_m: float = 0.2  # Positive maximum Z standard deviation within a cell's elevation layer; separate roof/furniture layers are not pooled. Single observations still need spatial support.
    layer_step_m: float = 1.0  # Positive metre Z-bin width inside each XY cell; bins retain separate original observations, not averaged heights.
    max_layers_per_cell: int = 8  # Positive cap on retained elevation layers; overflowing cells supply no recovery support.
    min_plane_fraction: float = 0.15  # (0,1]; a fitted surface must explain this fraction of spatial cells.
    min_supported_fraction: float = 0.6  # (0,1]; explained XY/Z-layer representatives / all retained layers, independently of area coverage. Default requires a strict majority, allowing terrace/furniture edges to remain unexplained.
    max_slope_deg: float = 15.0  # [0,90); low-slope surface acceptance for flat roofs/terrace furniture, not generic tree conversion.
    trials: int = 192  # Positive deterministic RANSAC trials per surface; controls fitting cost.
    max_planes: int = 4  # Positive extraction limit; isolated small surfaces cannot define the output top.
    storey_tolerance_m: float = 1.5  # Nonnegative metre slack outside HeightConfig floor-range times declared storeys.

    def __post_init__(self):
        """Reject contradictory domains and freeze the external class sequence."""
        if type(self.enabled) is not bool:raise ValueError('roof_recovery.enabled must be boolean')
        if self.candidate_classes is not None:raise ValueError('roof_recovery.candidate_classes must be null: classifications are metadata')
        for key in ('max_cells_per_object','max_total_cells','max_layers_per_cell','min_cells','trials','max_planes'):
            v=getattr(self,key)
            if type(v) is not int or v<(3 if key=='min_cells' else 1):raise ValueError(f'Invalid roof_recovery.{key}')
        if self.min_cells>self.max_cells_per_object:raise ValueError('Recovery minimum exceeds cell budget')
        for key in ('context_m','max_exterior_continuity','cell_size_m','layer_step_m','min_coverage','residual_m','local_std_m','min_plane_fraction','min_supported_fraction','max_slope_deg','storey_tolerance_m'):
            v=getattr(self,key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(f'Invalid roof_recovery.{key}')
        if min(self.context_m,self.cell_size_m,self.layer_step_m,self.residual_m,self.local_std_m)<=0 or self.storey_tolerance_m<0 or not 0<=self.max_slope_deg<90:raise ValueError('Invalid recovery distance/slope')
        if any(not 0<getattr(self,k)<=1 for k in ('max_exterior_continuity','min_coverage','min_plane_fraction','min_supported_fraction')):raise ValueError('Invalid recovery fraction')
