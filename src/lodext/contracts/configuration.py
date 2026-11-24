"""String contracts owned by the configuration boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class BuildConfigurationFields:
    """Fields controlling building reconstruction modes and configured policies."""

    CONTRACT_VERSION: Final[str] = 'contract_version'  # Wire key for building input contract version.
    LODS: Final[str] = 'lods'  # Wire key for requested levels.
    GEOMETRY_MODE: Final[str] = 'geometry_mode'  # Wire key for building/part reconstruction mode.
    HEIGHT_SOURCE: Final[str] = 'height_source'  # Wire key for selected height evidence mode.
    EXTERNAL_HEIGHT_FALLBACK: Final[str] = 'external_height_fallback'  # Wire key for explicit auxiliary fallback permission.
    SAMPLING: Final[str] = 'sampling'  # Wire key for sampling policy or evidence.


class SurfaceConfigurationFields:
    """Fields belonging to the standalone surface configuration contract."""

    SURFACE_CONTRACT: Final[str] = 'surface_contract'  # Wire key for surface contract version.
    RADIUS_M: Final[str] = 'radius_m'  # Wire key for metre search radius.


class SurfaceLiftingPolicyFields:
    """Observed-rank and LAS-class policy shared by surface configuration types."""

    PERCENTILE: Final[str] = 'percentile'  # Observed-rank percentage, governed by LiftingPolicy.
    LAS_CLASSES: Final[str] = 'las_classes'  # Explicit LAS class selection; None accepts all.


class InputFailurePolicy:
    """Explicit abort/exclusion/omission actions, not processing statuses."""

    ERROR: Final[str] = 'error'  # Abort the relevant stage on the policy violation.
    EXCLUDE: Final[str] = 'exclude'  # Record invalid identities without reconstructed geometry.
    OMIT: Final[str] = 'omit'  # Keep unresolved identity/report while omitting unsupported geometry.


class InputContractVersion:
    """Independently versioned application input/reception contracts."""

    CONFIG_VERSION: Final[str] = '1'  # Supported application configuration schema version.
    BUILDING_CONTRACT_VERSION: Final[str] = '0.2'  # Supported canonical building input contract.
    SURFACE_CONTRACT_VERSION: Final[str] = '0.1'  # Supported independent surface input contract.
    DATASET_VERSION: Final[str] = '1'  # Supported local audit dataset declaration version.
    SNAPSHOT_VERSION: Final[str] = '1'  # Supported source identity snapshot version.


class ContractValidationMessages:
    """Named input-contract errors shared by validation types."""

    CONTRACT_VERSIONS: Final[str] = "Expected {config_field} '{config_version}' and {contract_field} '{contract_version}'"  # Version-pair rejection; preserve field names and quoted values.
    FINITE_NUMBER: Final[str] = '{name} must be a finite number'  # Named numeric-contract rejection template.
    NONEMPTY_TEXT: Final[str] = '{name} must be nonempty text'  # Named required-text rejection template.
    INTEGER_MINIMUM: Final[str] = '{name} must be an integer >= {minimum}'  # Named inclusive integer-floor rejection template.
    UNKNOWN_FIELDS: Final[str] = 'Unknown or invalid fields for {owner}'  # Closed contract-mapping rejection template.


class LidarReadBudgetFields:
    """Decoded cloud batch/query budget fields shared by input contracts."""

    CHUNK_POINTS: Final[str] = 'chunk_points'  # Wire key for decoded batch/query budget.


class HeaderCoveragePolicyFields:
    """Header-box coverage tolerance; never observation or geometry support."""

    TOLERANCE_M: Final[str] = 'coverage_tolerance_m'  # Wire key for header-only metre tolerance.


class ModelQuantizationFields:
    """Metric serialization grid policy shared by building/surface exporters."""

    PRECISION_M: Final[str] = 'precision_m'  # Wire key for metre quantisation step.


class ConfigurationEnvelopeFields:
    """Application configuration envelope; domain input contracts are separately versioned."""

    VERSION: Final[str] = 'config_version'  # Wire key for configuration version.


class ReconstructionFailurePolicyFields:
    """Configured handling of unresolved reconstruction objects."""

    UNRESOLVED_OBJECTS: Final[str] = 'unresolved_objects'  # Wire key for missing-evidence policy.
