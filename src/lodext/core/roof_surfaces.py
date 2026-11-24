"""Authoritative policy for spatial roof envelopes of weak modal observations."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RoofSurfaceConfig:
    """Closed roof_surfaces JSON policy, independent of class-label recovery.

    Uses class-6 observations with weak modal support, adequate area/quantity,
    full coverage and a sampled or adjacency-inferred base independent of roof
    points. Storeys are not required and do not
    set height. Existing reliable direct measurements are preserved. Budgets
    abort rather than silently coarsen or sample source elevations by percentile.
    """
    enabled: bool = False  # Explicit opt-in; requires class-6 LiDAR heights and LoD1.
    min_area_m2: float = 0.0  # Nonnegative optional area restriction in m2; zero disables the size gate. Positive values are explicit legacy/workload restrictions, not roof-validity criteria.
    grid_axis: int = 24  # Integer >=4; at most axis**2 original XYZ representatives per candidate body.
    min_cell_size_m: float = 0.5  # Positive lower XY cell width per axis; prevents tiny normalized cells from understating support on small rooms. Original point coordinates are retained.
    max_total_cells: int = 500000  # Positive total retained-representative budget for the targeted second pass.
    min_points: int = 12  # Integer >=3; distinct XY representatives, still subject to coverage and per-plane support.
    min_plane_points: int = 6  # Integer in [3,min_points]; absolute inlier floor per fitted plane, preventing three-point fits on sparse small bodies.
    min_coverage: float = 0.5  # (0,1]; actual support-area fraction intersecting plane-supported XY cells.
    min_supported_fraction: float = 0.6  # (0,1]; union of attributable plane inliers / retained XY representatives; majority support tolerates roof edges and furniture.
    min_plane_fraction: float = 0.12  # (0,1]; minimum per-plane fraction of all representatives.
    residual_m: float = 0.18  # Positive inclusive vertical plane residual in source metres.
    # Degrees in [0,max); zero accepts coherent horizontal as well as inclined
    # planes. Positive values explicitly opt into the legacy inclination gate.
    # Sampling/fitting consumes this setting; it never scales a roof elevation.
    min_slope_deg: float = 0.0
    max_slope_deg: float = 60.0  # (min,90); reject wall-like hypotheses.
    trials: int = 384  # Positive deterministic RANSAC hypotheses per extracted plane.
    max_planes: int = 6  # Positive surface extraction bound, not an asserted physical roof count.

    def __post_init__(self):
        """Reject invalid settings without coercing values into another policy."""
        if type(self.enabled) is not bool:raise ValueError('roof_surfaces.enabled must be boolean')
        for key in ('grid_axis','max_total_cells','min_points','min_plane_points','trials','max_planes'):
            v=getattr(self,key);minimum=4 if key=='grid_axis' else 3 if key in ('min_points','min_plane_points') else 1
            if type(v) is not int or v<minimum:raise ValueError(f'Invalid roof_surfaces.{key}')
        if self.min_points>self.grid_axis**2:raise ValueError('Spatial point floor exceeds per-body budget')
        if self.min_plane_points>self.min_points:raise ValueError('Plane point floor exceeds surface point floor')
        for key in ('min_area_m2','min_cell_size_m','min_coverage','min_supported_fraction','min_plane_fraction','residual_m','min_slope_deg','max_slope_deg'):
            v=getattr(self,key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(f'Invalid roof_surfaces.{key}')
        if self.min_area_m2<0 or min(self.min_cell_size_m,self.residual_m)<=0 or not 0<=self.min_slope_deg<self.max_slope_deg<90:raise ValueError('Invalid spatial roof distance/slope')
        if any(not 0<getattr(self,k)<=1 for k in ('min_coverage','min_supported_fraction','min_plane_fraction')):raise ValueError('Invalid spatial roof fraction')


def separate_neighbour_planes(planes,ground_z,storeys,taller_roof_modes,height_policy):
    """Separate gross competing-height hypotheses; never invent a roof elevation.

    Plane mappings carry fitted_upper_z in source metres. Taller-roof modes
    are independent, reliable observations from explicit higher-storey siblings.
    Require a supported lower alternative AND a jump exceeding the target's
    permissive storey envelope before attributing a high plane to that neighbour.
    A sole tall industrial roof, missing storeys and ordinary rooftop rooms are
    retained. This is an exclusion diagnostic, not proof that the lower plane
    covers enough of the footprint: callers must recompute support afterwards.
    """
    if not storeys or storeys<=0 or not taller_roof_modes:return list(planes),[]
    span=storeys*height_policy.max_floor_height_m+height_policy.inferred_roof_tolerance_m
    lower=[p['fitted_upper_z'] for p in planes if 0<p['fitted_upper_z']-ground_z<=span]
    if not lower:return list(planes),[]
    base=max(lower);allowed=[];rejected=[]
    for plane in planes:
        top=plane['fitted_upper_z']
        competing=any(abs(top-z)<=height_policy.max_floor_height_m for z in taller_roof_modes)
        (rejected if top-base>span and competing else allowed).append(plane)
    return allowed,rejected
