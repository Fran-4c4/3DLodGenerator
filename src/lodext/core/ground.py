"""Authoritative settings for direct geometric-point ground reconstruction."""
from dataclasses import dataclass
from .heights import finite_number


@dataclass(frozen=True)
class PointGroundConfig:
    """Building bases use streamed exterior-point statistics, never the display surface.

    Ground candidates keep their original classes. Points intersecting any
    received valid building footprint are excluded from estimation and counted
    for review, not reclassified. SamplingConfig owns buffer/sample thresholds.
    Geometric base selection retains supported lower layers and local planes.
    Surface selection retains an actual observation nearest each display cell centre;
    it is an explicit display reduction, not a raster or a new measured height.
    Invalid settings fail; budgets never trigger silent additional thinning.
    """

    classes: None = None  # Compatibility key: only null is valid. LAS classifications are metadata, never ground-selection criteria.
    geometric_cell_size_m: float = 2.0  # Positive XY metres for independent base evidence; separate from display TIN resolution.
    layer_step_m: float = 0.5  # Positive source-Z metres per streaming candidate layer; source representatives retain actual XYZ.
    min_layer_returns: int = 1  # Positive minimum returns in a cell/layer; sparse single returns still need independent spatial-plane support. Never a class or storey rule.
    surface_residual_m: float = 0.3  # Positive vertical metre residual for local exterior-plane coherence.
    max_slope_deg: float = 60.0  # [0,90): maximum terrain plane slope, preserving hills while rejecting wall-like patches.
    export_points: bool = False  # Opt-in bounded original-point debug sample; never duplicate the whole cloud by default.
    export_surface: bool = True  # Write a bounded terrain TIN and a combined building/terrain scene.
    surface_scope: str = 'building_context'  # 'building_context' retains building-buffer sampling extent; 'input_tiles' reads all declared cloud extents for the terrain TIN. Only with export_surface=True. Neither changes ground-ring estimates or supplies road/bridge semantics.
    surface_cell_size_m: float = 2.0  # Positive working-XY metres; one actual point nearest each cell centre.
    surface_max_edge_m: float = 6.0  # Positive inclusive XY edge limit; longer triangles are omitted as gaps.
    max_surface_vertices: int = 250_000  # At least 3 retained cells; exceeding the budget aborts explicitly.
    quantile_step_m: float = 0.001  # Legacy histogram resolution, metres, retained for standalone historical statistics; geometric base fitting does not quantise Z or claim this error bound.
    max_histogram_bins: int = 2_000_000  # Global candidate XY/Z-layer budget; exceeding aborts instead of increasing the step.
    max_export_points: int = 10_000  # Positive maximum debug-sample size in source order; only with export_points=True.

    def __post_init__(self):
        """Validate classes, explicit output switches, metric limits and budgets."""
        if self.classes is not None:raise ValueError('ground.classes must be null: building bases use XYZ and footprints, not LAS labels')
        if type(self.min_layer_returns) is not int or self.min_layer_returns<1:raise ValueError('ground.min_layer_returns must be positive integer')
        finite_number(self.max_slope_deg,'ground.max_slope_deg')
        if not 0<=self.max_slope_deg<90:raise ValueError('Invalid ground.max_slope_deg')
        for name in ('export_points','export_surface'):
            if type(getattr(self,name)) is not bool:raise ValueError(f'ground.{name} must be boolean')
        if self.surface_scope not in ('building_context','input_tiles'):raise ValueError('ground.surface_scope must be building_context or input_tiles')
        if self.surface_scope=='input_tiles' and not self.export_surface:raise ValueError('input_tiles surface_scope requires export_surface=true')
        for name in ('geometric_cell_size_m','layer_step_m','surface_residual_m','surface_cell_size_m','surface_max_edge_m','quantile_step_m'):
            finite_number(getattr(self,name),'ground.'+name)
            if getattr(self,name)<=0:raise ValueError(f'ground.{name} must be positive metres')
        for name in ('max_surface_vertices','max_histogram_bins'):
            if type(getattr(self,name)) is not int or getattr(self,name)<3:
                raise ValueError(f'ground.{name} must be an integer >=3')

        if type(self.max_export_points) is not int or self.max_export_points<1:raise ValueError('ground.max_export_points must be an integer >=1')
