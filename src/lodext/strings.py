"""Explicit facade for domain-owned string contracts.

Definitions live beside related contracts under lodext.contracts. Import the
responsibility-qualified namespace (or use strings.Namespace.MEMBER); do not
restore flat KEY_/STATUS_ aliases or aliases that erase the owner. Namespaces
contain documented plain strings, not dataclass fields or runtime enum objects.
Equal wire text does not imply semantic identity or nominal runtime type safety.
"""

from .contracts.application import (
    TextFileEncoding,
    ProgressEventFields,
    ApplicationIdentity,
    OutputDirectoryMessages,
    CommandLineArguments,
)

from .contracts.audit import (
    ShowcasePresentationFields,
    ShowcaseReportFields,
    AuditCropFields,
    HeightTrialFields,
    SyntheticControlFields,
    HeightTrialClassProfile,
    SyntheticInputFiles,
    AuditFixtureFiles,
    FixtureInspectionFields,
    HeightTrialBuildingFields,
    HeightTrialBuildingStatus,
)

from .contracts.building_heights import (
    BuildingInputFields,
    BuildingHeightFields,
    BuildingSurfaceFields,
    BuildingSurfaceRejectionReason,
    LoD1RoofReductionMethod,
    LoD1RoofReductionReason,
    RoofSupportFields,
    HeightEstimationMethod,
    BuildingReconstructionMethod,
    BuildingHeightSource,
    AuxiliaryHeightRole,
    BuildingHeightReason,
    RoofSupportErosionStatus,
    BuildingGeometryMode,
)

from .contracts.cityjson import (
    CityJSONFields,
    CityJSONReconstructionAttributes,
    CityJSONObjectType,
    CityJSONGeometryType,
    CityJSONSurfaceSemantic,
    CityJSONFormat,
    CityModelLoD,
)

from .contracts.configuration import (
    BuildConfigurationFields,
    SurfaceConfigurationFields,
    SurfaceLiftingPolicyFields,
    InputFailurePolicy,
    InputContractVersion,
    ContractValidationMessages,
    LidarReadBudgetFields,
    HeaderCoveragePolicyFields,
    ModelQuantizationFields,
    ConfigurationEnvelopeFields,
    ReconstructionFailurePolicyFields,
)

from .contracts.reconstruction import (
    GroundSamplingFields,
    ReconstructionObjectFields,
    InputReceptionSummaryFields,
    ReconstructionRunFields,
    QualityReportFields,
    ValidationReportFields,
    LidarSamplingFields,
    SurfaceReconstructionFields,
    MeshValidationFields,
    VerticalConsistencyFields,
    ModelElevationUnits,
    BuildingObjectType,
    SurfaceObjectClass,
    ReconstructionObjectStatus,
    ReconstructionRunStatus,
    GroundSamplingStatus,
    VerticalConsistencyStatus,
    VerticalReferenceDeclaration,
    ReconstructionOutputFiles,
    RoadFitFields,
    ReportEnvelopeFields,
    ReportSchemaVersion,
)

from .contracts.sources import (
    SourceObjectIdentity,
    GeoPackageMetadataQueries,
    GeoPackageLayers,
    GeospatialInputFields,
    DatasetIdentityFields,
    SourceInventoryFields,
    LidarInventoryFields,
    GeoJSONFields,
    GeoPackageGeometryFields,
    PolygonGeometryType,
    PolygonFootprintFields,
    SourceReceptionReason,
)

from .contracts.tiles import (
    TileConversionFields,
    GlTFFormat,
    GlTFFields,
    TilesetFields,
)

from .contracts.ground import (PointGroundFields, PointGroundMethod, PointGroundFiles, GroundPointDecision)
