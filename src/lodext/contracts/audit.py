"""String contracts owned by the audit boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class AuditCropFields:
    """Requested metric XY extent of the optional cropped audit fixture."""

    BBOX_XY: Final[str] = 'bbox_xy'  # Wire key for working-CRS XY bounds.


class HeightTrialFields:
    """Separate height trial profiles, comparison statistics and entity collections."""

    PROFILE: Final[str] = 'profile'  # Wire key for named trial class-selection policy.
    PROFILES: Final[str] = 'profiles'  # Wire key for separate trial results.
    PARTS: Final[str] = 'parts'  # Wire key for part records; not a reconstruction mode.
    BUILDINGS: Final[str] = 'buildings'  # Wire key for building records; not a layer/mode.
    DELTA_FROM_REFERENCE_M: Final[str] = 'delta_from_reference_m'  # Wire key for estimated minus reference height in metres.
    MAX_ABSOLUTE_DIFFERENCE_M: Final[str] = 'max_absolute_difference_m'  # Wire key for maximum absolute comparison difference.
    MEAN_ABSOLUTE_DIFFERENCE_M: Final[str] = 'mean_absolute_difference_m'  # Wire key for mean absolute comparison difference.
    PARTS_OVER_0_5M: Final[str] = 'parts_over_0_5m'  # Wire key for strict over-0.5-m comparison count.
    HEIGHT_CONFIG: Final[str] = 'height_config'  # Wire key for effective height-estimation settings.
    SAMPLING_CONFIG: Final[str] = 'sampling_config'  # Wire key for effective trial sampling settings.


class SyntheticControlFields:
    """Original fixture design controls; not estimated or surveyed truth."""

    DESCRIPTION: Final[str] = 'description'  # Wire key for descriptive metadata.
    BASE_Z_M: Final[str] = 'base_z_m'  # Wire key for control base elevation.
    COMPONENT_COUNT: Final[str] = 'components'  # Number of disconnected original footprint components in a fixture control.


class HeightTrialClassProfile:
    """Explicit classification filter names used by both height audit runners."""

    ALL_CLASSES: Final[str] = 'all_classes'  # Trial keeps all supplied point classifications.
    BUILDING_CLASS_6: Final[str] = 'building_class_6'  # Trial explicitly selects building-class observations.


class SyntheticInputFiles:
    """Portable original fixture inputs and their runnable configuration filenames."""

    FOOTPRINTS: Final[str] = 'footprints.gpkg'  # Portable synthetic/audit footprint filename.
    DTM: Final[str] = 'dtm.tif'  # Synthetic terrain raster filename.
    CLOUD: Final[str] = 'cloud.las'  # Synthetic classified observation filename.
    BUILD_CONFIG: Final[str] = 'build.json'  # Default synthetic building configuration filename.
    KNOWN_CONFIG: Final[str] = 'build.known.json'  # Synthetic explicit known-height configuration filename.
    LOD0_CONFIG: Final[str] = 'build.lod0.json'  # Synthetic ground-only configuration filename.
    SURFACE_CONFIG: Final[str] = 'surfaces.json'  # Synthetic surface configuration filename.
    TRUTH: Final[str] = 'truth.json'  # Independent synthetic control-dimension filename.


class AuditFixtureFiles:
    """Optional audit fixture declarations."""

    CROP_REQUEST: Final[str] = 'crop_request.json'  # Audit fixture crop/context declaration filename.


class FixtureInspectionFields:
    """Read-only fixture inspection evidence, not reconstruction configuration."""

    SAMPLING_POLICY: Final[str] = 'sampling'  # Effective audit sampling policy; not collected elevation observations.
    LIDAR_EVIDENCE: Final[str] = 'lidar'  # Read-only cloud inventory/count evidence; not configured cloud paths.
    DTM_EVIDENCE: Final[str] = 'dtm'  # Read-only raster metadata/coverage evidence; not a raster path.


class HeightTrialBuildingFields:
    """Per-building aggregation evidence in the full height trial."""

    STATUS: Final[str] = 'status'  # Whole-building aggregation outcome in the full height trial.


class HeightTrialBuildingStatus:
    """Full-trial building aggregation outcomes; not object reconstruction or source-error codes."""

    MISSING_GEOMETRY: Final[str] = 'missing_geometry'  # Aggregation cannot evaluate a building without its source footprint.


class ShowcasePresentationFields:
    """Original documentation renderer payload; not CityJSON or glTF."""

    POINTS: Final[str] = 'points'  # Wire key for observation payload.
    MESHES: Final[str] = 'meshes'  # Wire key for mesh payload.
    POINT_CLASS_VALUES: Final[str] = 'classes'  # One LAS class per displayed observation; not a class-frequency mapping.


class ShowcaseReportFields:
    """Composition-only documentation run summaries; never stitched scene status."""

    BUILDING_RUN: Final[str] = 'buildings'  # Building run summary used in a composition-only documentation scene.
    SURFACE_RUN: Final[str] = 'surfaces'  # Surface run summary used in a composition-only documentation scene.
    BUILDING_OBJECT_COUNT: Final[str] = 'buildings'  # Building source-object count in the showcase generator console summary.

