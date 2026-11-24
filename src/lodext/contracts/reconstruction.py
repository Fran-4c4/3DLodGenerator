"""String contracts owned by the reconstruction boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class InputReceptionSummaryFields:
    """Object counts reported by input validation, before any mesh exists."""

    OBJECT_COUNT: Final[str] = 'objects'  # Received input identity count, not a CityJSON model count.
    EXCLUDED_COUNT: Final[str] = 'excluded'  # Rejected source identity count, not a status code.


class GroundSamplingFields:
    """Accepted/missing ground sampling evidence from the audit workflows."""

    Z_MEDIAN: Final[str] = 'z_median'  # Wire key for sampled median ground elevation.
    FREE_AREA_M2: Final[str] = 'free_area_m2'  # Wire key for unoccupied ground support area.
    GRID_CANDIDATES: Final[str] = 'grid_candidates'  # Wire key for ground sample candidate count.
    VALID_SAMPLES: Final[str] = 'valid_samples'  # Wire key for valid ground sample count.
    GROUND: Final[str] = 'ground'  # Wire key for ground evidence; not a progress phase.
    STATUS: Final[str] = 'status'  # Acceptance/missing-support state of a ground sample, not an object or run.
    SEARCH_RADIUS_M: Final[str] = 'radius_m'  # Metre radius of the accepted unoccupied DTM search ring.


class ReconstructionObjectFields:
    """Quality-record identity, reception diagnoses and per-object reconstruction state."""

    STATUS: Final[str] = 'status'  # Per-object state; values belong to ReconstructionObjectStatus.
    ISSUES: Final[str] = 'issues'  # Wire key for input reception diagnoses.


class ReconstructionRunFields:
    """Run-level summary/provenance, never per-object state."""

    SOURCE_OBJECTS: Final[str] = 'source_objects'  # Wire key for source identity count.
    SUMMARY: Final[str] = 'summary'  # Wire key for processing summary.
    CREATED_AT_UTC: Final[str] = 'created_at_utc'  # Wire key for UTC run timestamp.
    VERSIONS: Final[str] = 'versions'  # Wire key for software version inventory.
    COMMAND: Final[str] = 'command'  # Wire key for executed command.
    CONFIG: Final[str] = 'config'  # Wire key for effective surface settings.
    INPUTS: Final[str] = 'inputs'  # Wire key for run input provenance.
    CLOUD: Final[str] = 'cloud'  # Wire key for LiDAR evidence summary.
    STATUS: Final[str] = 'status'  # Requested-stage completion; values belong to ReconstructionRunStatus.
    SURFACE_CLASS_COUNTS: Final[str] = 'classes'  # Counts of source surface objects by semantic class; not LAS classifications.
    SURFACE_SAMPLING_EVIDENCE: Final[str] = 'sampling'  # Recorded surface cloud-sampling statistics, not a configuration mapping.


class QualityReportFields:
    """Quality report object-record collection, not a count."""

    OBJECTS: Final[str] = 'objects'  # Per-source quality records; not an object-count scalar.


class ValidationReportFields:
    """Explicit capability/validation scope declarations."""

    SCOPE: Final[str] = 'scope'  # Wire key for reported capability scope.


class LidarSamplingFields:
    """Decoded cloud observation statistics, not surface object classes."""

    CLASSES: Final[str] = 'classes'  # Wire key for observed point classes.
    COVERAGE_COMPLETE: Final[str] = 'coverage_complete'  # Wire key for header-envelope coverage.
    FILES_SCANNED: Final[str] = 'files_scanned'  # Wire key for resource scan count.
    FILES_SELECTED: Final[str] = 'files_selected'  # Wire key for selected resource count.
    PEAK_BATCH_POINTS: Final[str] = 'peak_batch_points'  # Wire key for largest decoded point batch.
    POINTS_DECODED: Final[str] = 'points_decoded'  # Wire key for decoded point count.


class SurfaceReconstructionFields:
    """Individual lifted-surface method, components and retained observations."""

    SAMPLE_POINTS: Final[str] = 'sample_points'  # Wire key for surface observation count.
    COMPONENTS: Final[str] = 'components'  # Wire key for geometry components or component evidence.
    METHOD: Final[str] = 'method'  # Surface lifting route (flat/boundary rank/TIN), not building height inference.


class MeshValidationFields:
    """Geometry validation counts, distinct from geometry arrays."""

    OBJECT_COUNT: Final[str] = 'objects'  # Number of validated CityJSON identities, including relationship-only parents.
    TRIANGLE_COUNT: Final[str] = 'triangles'  # Triangle count; not a triangle-coordinate array.
    FACE_COUNT: Final[str] = 'faces'  # Number of geometry faces checked, before any triangle conversion.
    GEOMETRY_COUNT: Final[str] = 'geometry_objects'  # Number of geometry entries; may exceed the number of object identities.


class VerticalConsistencyFields:
    """Local terrain/cloud Z assessment; no named-datum certification."""

    ABSOLUTE_VERTICAL_DATUM: Final[str] = 'absolute_vertical_datum'  # Wire key for absolute-datum assertion.
    ASSESSMENT: Final[str] = 'assessment'  # Wire key for consistency assessment.
    STATUS: Final[str] = 'status'  # Local DTM/cloud consistency assessment, not reconstruction state.


class ModelElevationUnits:
    """Metric Z declaration shared by models and their provenance."""

    Z_UNIT: Final[str] = 'z_unit'  # Wire key for source elevation units.
    UNIT_METRES: Final[str] = 'm'  # Declared source Z units; not a datum or accuracy claim.




class BuildingObjectType:
    """Canonical building/source object kinds and their CityJSON counterparts."""

    BUILDING: Final[str] = 'Building'  # Canonical building object class; not a reconstruction mode.
    BUILDING_PART: Final[str] = 'BuildingPart'  # Canonical part class with an explicit parent.


class SurfaceObjectClass:
    """Supported input surface classes; not CityJSON output types."""

    ROAD: Final[str] = 'Road'  # Supported road surface class and CityJSON road type.
    TERRAIN: Final[str] = 'Terrain'  # Input terrain class; exported as TINRelief.
    FOREST: Final[str] = 'Forest'  # Input land-cover class; exported as PlantCover.
    WATER: Final[str] = 'Water'  # Input water class; exported as WaterBody.


class ReconstructionObjectStatus:
    """State of one received building/body/surface; not completion of a run."""

    RESOLVED: Final[str] = 'resolved'  # Object has sufficient evidence for requested geometry.
    UNRESOLVED: Final[str] = 'unresolved'  # Object lacks sufficient evidence; distinct from an inferred height.
    EXCLUDED: Final[str] = 'excluded'  # Source violates reception policy and is excluded.
    PARENT: Final[str] = 'parent'  # Relationship-only building in explicit parts mode.


class ReconstructionRunStatus:
    """Completion state of a requested stage; never seven-class certification."""

    COMPLETE: Final[str] = 'complete'  # Requested stage completed; not seven-class scene certification.
    PARTIAL: Final[str] = 'partial'  # Requested stage retains unresolved/excluded objects.


class GroundSamplingStatus:
    """Acceptance of a representative ground-elevation sample."""

    SAMPLED: Final[str] = 'sampled'  # Ground evidence accepted by a trial sampling policy.


class VerticalConsistencyStatus:
    """Local DTM/cloud numerical agreement; not an absolute datum assertion."""

    LOCALLY_CONSISTENT: Final[str] = 'locally_consistent'  # Local DTM/cloud check passed; not a datum certificate.
    OFFSET_OR_MISMATCH: Final[str] = 'offset_or_mismatch_detected'  # Local vertical check detected disagreement.


class VerticalReferenceDeclaration:
    """Source Z reference declaration, with no implicit conversion."""

    LOCAL_RELATIVE: Final[str] = 'local_relative'  # Local relative Z declaration; no absolute datum assertion.


class ReconstructionOutputFiles:
    """Stable filenames shared by reconstruction report consumers."""

    QUALITY: Final[str] = 'quality.json'  # Run object-quality evidence filename.
    OBJECTS_CSV: Final[str] = 'objects.csv'  # Run object-review table filename.
    RUN: Final[str] = 'run.json'  # Effective run metadata filename.


class RoadFitFields:
    """Road-boundary quadratic-fit diagnostics, not object reconstruction status."""

    STATUS: Final[str] = 'status'  # Quadratic road-boundary fit outcome, not object reconstruction success.




class ReportEnvelopeFields:
    """Report envelope version field; each report schema has its own version value."""

    VERSION: Final[str] = 'report_version'  # Report schema discriminator field; use the version value belonging to that report.


class ReportSchemaVersion:
    """Independently versioned quality, audit and run schemas; equal values are not aliases."""

    BUILDING_RUN: Final[str] = '1'  # Current building run-manifest schema version.
    QUALITY: Final[str] = '1'  # Current reconstruction quality-report schema version.
    VERTICAL_CONSISTENCY: Final[str] = '1'  # Current local vertical-consistency assessment report schema version.
    FIXTURE_INSPECTION: Final[str] = '1'  # Current optional fixture-inspection report schema version.
    FULL_HEIGHT_TRIAL: Final[str] = '1'  # Current full-scope height-trial report schema version.
    SMALL_HEIGHT_TRIAL: Final[str] = '1'  # Current cropped height-trial report schema version.
