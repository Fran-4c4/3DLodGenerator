"""Direct point-ground provenance and output contracts; no policy defaults."""
from typing import Final


class PointGroundFields:
    """Per-object evidence for the ground estimator, independent of roof method."""
    PLANE: Final[str] = 'ground_plane'  # Supported local exterior XYZ plane: source-metre coefficients/origin, slope, residual and inlier evidence; absent when unavailable, not a datum or survey-accuracy certificate.
    METHOD: Final[str] = 'ground_method'  # Ground estimation route; never the roof-height method key.
    EXCLUDED_INSIDE: Final[str] = 'ground_excluded_inside_buildings'  # Candidate ground points excluded by occupied footprints in the search neighbourhood.
    MEDIAN_ERROR_BOUND: Final[str] = 'ground_median_error_bound_m'  # Half histogram step, an algorithmic bound rather than survey accuracy.
    Z_MIN: Final[str] = 'ground_min_z'  # Lowest accepted raw ground Z in source metres; null if absent.
    Z_MAX: Final[str] = 'ground_max_z'  # Highest accepted raw ground Z in source metres; null if absent.


class PointGroundMethod:
    """Ground estimation methods, not source classification or confidence."""
    GEOMETRIC_EXTERIOR_PLANE: Final[str] = 'geometric_exterior_plane'  # Class-neutral lower exterior surface projected locally to the footprint; independent of display TIN.
    ADJACENT: Final[str] = 'adjacent_part_ground'  # Missing base inferred from original measured same-parent graph references; not a raw-point median at the target.
    HISTOGRAM_MEDIAN: Final[str] = 'lidar_histogram_median'  # Streaming median of quantized raw exterior-ground Z counts; error bounded by half quantile_step_m.
    LOD0: Final[str] = 'lidar_ground_surface'  # Building LoD0 based on raw exterior ground, without roof-height estimation.


class PointGroundFiles:
    """Files emitted only by the DTM-free building workflow."""
    POINTS: Final[str] = 'ground.sample.gpkg'  # Optional size-capped debug sample; original class and source linkage preserved.
    TERRAIN: Final[str] = 'ground.city.json'  # Reduced observed-point TIN; no faces through building footprints.
    SCENE: Final[str] = 'scene.lod1.city.json'  # Buildings plus terrain for one-file inspection; no stitching claim.


class GroundPointDecision:
    """Candidate-selection results, never replacement ASPRS classes."""
    GEOMETRY_CANDIDATE: Final[str] = 'geometry_candidate'  # Unoccupied source return admitted to geometric analysis, not certified ground or a rewritten LAS class.
    ACCEPTED: Final[str] = 'accepted'  # Configured ground class outside all occupied footprints.
    INSIDE_BUILDING: Final[str] = 'inside_building'  # Configured ground class intersects an occupied footprint; review required.
