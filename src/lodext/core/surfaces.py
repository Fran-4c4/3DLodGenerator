"""Authoritative contract for the first non-building surface workflow.

This is intentionally separate from BuildConfig/input 0.2. It does not accept
buildings, bridges or separators until their scene-interface contracts exist.
"""
from lodext import strings
from dataclasses import dataclass, fields, replace
from collections.abc import Mapping
import json
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

from .heights import finite_number


@dataclass(frozen=True)
class LiftingPolicy:
    """Per-class elevation selection, no implicit defaults inside this type.

    percentile: finite [0,100], zero-based rank min(n-1,floor(n*p/100)); no
      interpolation between observations. Affects boundary lifting and Water's
      common level. Matches the reviewed reference's rank convention, retaining
      native Z precision rather than its centimetre storage.
    las_classes: None accepts all classes; otherwise a nonempty unique tuple of
      integer ASPRS values 0..255. No automatic substitution when a class is
      absent. Selection affects boundary and interior samples, never source data.
    """
    percentile: float  # Required observed-rank percentage [0,100]; no interpolated quantile.
    las_classes: tuple[int, ...] | None  # Selected unique LAS classes 0..255; None accepts all.

    def __post_init__(self):
        """Validate observed-rank policy and freeze any supplied class sequence."""
        finite_number(self.percentile, strings.SurfaceLiftingPolicyFields.PERCENTILE)
        if not 0 <= self.percentile <= 100:
            raise ValueError("percentile must be in [0,100]")
        values = self.las_classes
        if values is not None:
            if (not isinstance(values, (list, tuple)) or not values
                    or any(type(v) is not int or not 0 <= v <= 255 for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError("las_classes must be null or unique integer classes 0..255")
            object.__setattr__(self, strings.SurfaceLiftingPolicyFields.LAS_CLASSES, tuple(values))


# Authoritative supported class keys and immutable default lifting policies.
# Each value is LiftingPolicy(percentile in [0,100], selected LAS classes).
# Class 2 = ground, 9 = water, 11 = road surface; Forest models the land surface,
# not canopy returns. The observed 50th rank is not an interpolated median;
# Water uses a lower observed rank for one horizontal level per object.
# SurfaceConfig merges explicit overrides without mutating this mapping. Readers
# also use its keys to reject unsupported classes. Changing keys or values affects
# accepted inputs, selected observations, lifted elevations and run provenance.
DEFAULT_LIFTING = MappingProxyType({
    strings.SurfaceObjectClass.ROAD: LiftingPolicy(50, (2, 11)),
    strings.SurfaceObjectClass.TERRAIN: LiftingPolicy(50, (2, 9)),
    strings.SurfaceObjectClass.FOREST: LiftingPolicy(50, (2, 9)),
    strings.SurfaceObjectClass.WATER: LiftingPolicy(10, (2, 9)),
})


@dataclass(frozen=True)
class SurfaceConfig:
    """JSON surface contract 0.1; standalone class lifting, NOT scene stitching.

    Required, no defaults: config_version='1', surface_contract='0.1', dataset_id
      nonempty text, polygons local GPKG path, nonempty lidar paths, working_epsg
      projected metre EPSG (Web Mercator rejected by reception), and nonempty
      vertical_reference declaring compatible metric Z for all clouds. XY may
      be transformed; Z is never converted. local_relative is not an absolute
      datum assertion. Relative paths resolve from the configuration directory.
    layer: nonempty GPKG layer name, default 'surfaces'; canonical surface_id and
      surface_class columns cannot be guessed/renamed. Supported class keys are
      owned by DEFAULT_LIFTING. Unsupported classes fail reception explicitly.
    lifting: None selects DEFAULT_LIFTING; an optional closed mapping of class
      keys to percentile/las_classes overrides or typed LiftingPolicy values.
      Frozen after validation; unknown
      keys and contradictory types fail rather than selecting another policy.
    radius_m: positive XY metres, default 1; vertex-neighbour search radius and
      input halo. max_points_per_feature >=1 bounds accumulated observations;
      max_tin_vertices >=3 bounds boundary+interior triangulation vertices.
      Exceeding either aborts, never thins. chunk_points >=1 controls sequential
      LAS batches and guards decoded COPC queries AFTER allocation. COPC uses
      spatial full-resolution queries; no pre-decode memory guarantee is made.
    coverage_tolerance_m >=0 expands header boxes only, default .002 metres for
      header quantisation. Does not fill missing observations or change geometry.
    missing_vertices: 'nearest_ring' default copies the nearest supported vertex
      by cyclic ring distance, ties toward the lower index; reports borrowing.
      An entirely unsupported ring remains unresolved. 'error' permits no copy.
    road_filter_outliers/road_flatten: booleans default True; fit a quadratic
      surface to each component's boundary vertices, requiring >=6 and full
      rank. Filter replaces detected outliers; flatten replaces every boundary
      elevation. Both False disable fitting. Rank/quantity failures retain raw
      values with explicit flags. max_outlier_fraction in [0,1), default .2,
      reverts the whole fit when exclusions exceed that fraction.
    unresolved_objects: 'omit' default retains report/identity without geometry
      and returns partial status; 'error' aborts before output creation.
    precision_m >0: shared XY/Z quantisation, default .001 metres. Collapsed or
      inverted triangles fail; precision is not a survey accuracy claim.

    These defaults are owned here, independently of building sampling policies.
    All effective values enter run.json. Inputs and previous outputs are read-only.
    """
    # Class-private vocabulary: only this contract's validation/serialization
    # consumes the field name and only this class names the non-error policy.
    # ClassVar keeps both constants out of dataclasses.fields and run.json.
    FIELD_LIFTING: ClassVar[str] = "lifting"  # External name of the merged policy mapping.
    MISSING_VERTEX_NEAREST_RING: ClassVar[str] = "nearest_ring"  # Borrow only within the same ring.

    config_version: str  # Required configuration version; only '1' is accepted.
    surface_contract: str  # Required surface input contract version; only '0.1' is accepted.
    dataset_id: str  # Nonempty identity used in generated model metadata.
    polygons: str  # Literal local GPKG path, relative to the configuration directory.
    lidar: tuple[str, ...]  # Nonempty local cloud file/directory paths; same path-resolution base.
    working_epsg: int  # Explicit positive EPSG; reception requires suitable projected metres.
    vertical_reference: str  # Declared shared metric Z reference; input Z is not converted.
    layer: str = strings.GeoPackageLayers.SURFACES  # Canonical GPKG surface fields within this layer.
    lifting: object = None  # None selects DEFAULT_LIFTING; validated overrides allowed.
    radius_m: float = 1.0  # XY metres for boundary support and input halo.
    max_points_per_feature: int = 100_000  # Retained observation cap; never auto-thin.
    max_tin_vertices: int = 2_000  # Boundary plus unique interior XY vertex budget.
    chunk_points: int = 500_000  # Sequential batch / post-decode COPC query cap.
    coverage_tolerance_m: float = 0.002  # Metres added to header boxes only.
    missing_vertices: str = MISSING_VERTEX_NEAREST_RING  # Explicit within-ring borrowing or error.
    road_filter_outliers: bool = True  # Replace rejected boundary Z by quadratic fit.
    road_flatten: bool = True  # Replace all boundary Z by fit; does not force horizontal.
    max_outlier_fraction: float = 0.2  # Exceeding this exclusion fraction reverts fitting.
    unresolved_objects: str = strings.InputFailurePolicy.OMIT  # Keep identity/report without mesh, or abort.
    precision_m: float = 0.001  # Shared XYZ quantisation step, not input accuracy.

    def __post_init__(self):
        """Validate the surface contract and freeze merged per-class policies."""
        if self.config_version != strings.InputContractVersion.CONFIG_VERSION or self.surface_contract != strings.InputContractVersion.SURFACE_CONTRACT_VERSION:
            raise ValueError(strings.ContractValidationMessages.CONTRACT_VERSIONS.format(
                config_field=strings.ConfigurationEnvelopeFields.VERSION, config_version=strings.InputContractVersion.CONFIG_VERSION,
                contract_field=strings.SurfaceConfigurationFields.SURFACE_CONTRACT, contract_version=strings.InputContractVersion.SURFACE_CONTRACT_VERSION))
        for name in (strings.DatasetIdentityFields.DATASET_ID, strings.GeospatialInputFields.POLYGONS, "layer", strings.GeospatialInputFields.VERTICAL_REFERENCE):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(strings.ContractValidationMessages.NONEMPTY_TEXT.format(name=name))
        if type(self.working_epsg) is not int or self.working_epsg <= 0:
            raise ValueError("working_epsg must be a positive EPSG integer")
        if not isinstance(self.lidar, (list, tuple)) or not self.lidar:
            raise ValueError("lidar must be a nonempty list of local paths")
        for value in (self.polygons, *self.lidar):
            if (not isinstance(value, str) or not value.strip() or "://" in value
                    or "$" in value or "%" in value or value.startswith("~")):
                raise ValueError("Use literal local paths without URL/environment expansion")
        for name in (strings.SurfaceConfigurationFields.RADIUS_M, strings.ModelQuantizationFields.PRECISION_M, strings.HeaderCoveragePolicyFields.TOLERANCE_M, "max_outlier_fraction"):
            finite_number(getattr(self, name), name)
        if self.radius_m <= 0 or self.precision_m <= 0 or self.coverage_tolerance_m < 0:
            raise ValueError("Positive radius/precision and nonnegative coverage tolerance required")
        if not 0 <= self.max_outlier_fraction < 1:
            raise ValueError("max_outlier_fraction must be in [0,1)")
        for name, minimum in (("max_points_per_feature", 1), ("max_tin_vertices", 3), (strings.LidarReadBudgetFields.CHUNK_POINTS, 1)):
            if type(getattr(self, name)) is not int or getattr(self, name) < minimum:
                raise ValueError(strings.ContractValidationMessages.INTEGER_MINIMUM.format(name=name, minimum=minimum))
        for name in ("road_filter_outliers", "road_flatten"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if self.missing_vertices not in (self.MISSING_VERTEX_NEAREST_RING, strings.InputFailurePolicy.ERROR):
            raise ValueError("missing_vertices must be nearest_ring or error")
        if self.unresolved_objects not in (strings.InputFailurePolicy.OMIT, strings.InputFailurePolicy.ERROR):
            raise ValueError("unresolved_objects must be omit or error")
        overrides = {} if self.lifting is None else self.lifting
        if not isinstance(overrides, Mapping) or set(overrides) - set(DEFAULT_LIFTING):
            raise ValueError("lifting must contain supported class names only")
        policies = dict(DEFAULT_LIFTING)
        for kind, values in overrides.items():
            if isinstance(values, LiftingPolicy):
                policies[kind] = values
                continue
            if not isinstance(values, dict) or set(values) - {f.name for f in fields(LiftingPolicy)}:
                raise ValueError(f"Unknown lifting fields for {kind}")
            policies[kind] = replace(DEFAULT_LIFTING[kind], **values)
        object.__setattr__(self, self.FIELD_LIFTING, MappingProxyType(policies))
        object.__setattr__(self, strings.GeospatialInputFields.LIDAR, tuple(self.lidar))

    @classmethod
    def read(cls, path):
        """Read closed UTF-8 JSON settings; resource reception happens later.

        An optional BOM is accepted. Relative input paths remain relative to
        this configuration file, as resolved by run_surfaces.
        """
        data = json.loads(Path(path).read_text(encoding=strings.TextFileEncoding.UTF8_BOM))
        if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown SurfaceConfig fields")
        return cls(**data)

    def effective(self):
        """Return serialisable effective settings including every merged policy.

        MappingProxyType is expanded explicitly for run.json; defaults are read
        from their owners, never reconstructed independently by the exporter.
        """
        result = {f.name: getattr(self, f.name) for f in fields(self) if f.name != self.FIELD_LIFTING}
        result[self.FIELD_LIFTING] = {k: {strings.SurfaceLiftingPolicyFields.PERCENTILE: p.percentile, strings.SurfaceLiftingPolicyFields.LAS_CLASSES: p.las_classes}
                             for k, p in self.lifting.items()}
        return result
