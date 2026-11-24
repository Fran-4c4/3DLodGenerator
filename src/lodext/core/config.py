"""Public build configuration and its authoritative defaults (JSON v1)."""
from lodext import strings
from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path

from .heights import HeightConfig, finite_number
from .ground import PointGroundConfig
from .roof_recovery import RoofRecoveryConfig
from .roof_surfaces import RoofSurfaceConfig
from .adjacent_ground import AdjacentGroundConfig
from .roof_regions import RoofRegionsConfig
from .building_surfaces import BuildingSurfaceConfig


@dataclass(frozen=True)
class SamplingConfig:
    """Sampling in projected metres; defaults owned here, not in the CLI.

    erode_m >=0: inward roof crop at/above erode_min_area_m2 (>0 m²). An empty
      erosion retains the original polygon and is flagged; output never eroded.
    ground_buffers_m: positive strictly increasing radii; first free zone with
      min_ground_samples (integer >=1) valid samples wins (original ground-return counts in direct mode, raster
      samples in explicit DTM mode). grid_step_m >0 metres
      and min_free_area_m2 >0 m² control that DTM grid. Neighbours are excluded.
    cell_size_m >0: COPC grid cells; half-open membership prevents duplicate
      reads at cell edges. chunk_points >=1: LAS/LAZ sequential batch size and
      decoded COPC query guard (not a pre-decode memory allocation guarantee).
    coverage_tolerance_m >=0: header footprint expansion only, for quantization
      gaps, never crop expansion or a substitute for a missing tile.
    vertical_check_limit_m/vertical_check_p95_m >0: reject median offset or p95
      absolute DTM/class-2 residual beyond these limits when >=min_vertical_pairs
      (>=3) independent 5 m cells exist. Median alone can hide symmetric scatter.
      A low sample count is explicitly unverified, not evidence of equivalence.
    All distances/areas are effective working-CRS quantities. Changing them
      changes samples and confidence; every effective value enters run metadata.
    """

    erode_m: float = 1.0  # Metres: inward crop; zero disables erosion.
    erode_min_area_m2: float = 40.0  # Footprint-area gate, also the small-part gate.
    ground_buffers_m: tuple[float, ...] = (8.0, 14.0, 25.0)  # Ordered metre search radii.
    grid_step_m: float = 2.0  # Metres between candidate DTM samples.
    min_free_area_m2: float = 5.0  # Minimum unoccupied area for a candidate ring.
    min_ground_samples: int = 3  # Required accepted raw returns, or valid raster samples in explicit DTM mode.
    cell_size_m: float = 128.0  # Metres per spatial COPC query cell.
    chunk_points: int = 500_000  # Batch/decoded-query limit, not total retained points.
    coverage_tolerance_m: float = 0.002  # Header-box tolerance, not crop expansion.
    vertical_check_limit_m: float = 0.1  # Maximum absolute median DTM-minus-LiDAR residual.
    vertical_check_p95_m: float = 0.25  # Maximum p95 absolute residual, in metres.
    min_vertical_pairs: int = 20  # Independent pairs required to judge consistency.

    def __post_init__(self):
        """Validate sampling ranges and freeze ordered ground-search radii."""
        for name in ("erode_m", "erode_min_area_m2", "grid_step_m", "min_free_area_m2",
                     "cell_size_m", strings.HeaderCoveragePolicyFields.TOLERANCE_M, "vertical_check_limit_m", "vertical_check_p95_m"):
            value = getattr(self, name)
            finite_number(value, name)
            if value < 0 or (name not in ("erode_m", strings.HeaderCoveragePolicyFields.TOLERANCE_M) and value == 0):
                raise ValueError(f"Invalid sampling parameter: {name}")
        if not self.ground_buffers_m or any(isinstance(v, bool) or not isinstance(v, (int,float))
                                           or not math.isfinite(v) or v <= 0 for v in self.ground_buffers_m):
            raise ValueError("ground_buffers_m must contain positive finite radii")
        if any(a >= b for a,b in zip(self.ground_buffers_m,self.ground_buffers_m[1:])):
            raise ValueError("Ground buffers must be strictly increasing")
        object.__setattr__(self,"ground_buffers_m",tuple(self.ground_buffers_m))
        for name, minimum in ((strings.LidarReadBudgetFields.CHUNK_POINTS,1),("min_ground_samples",1),("min_vertical_pairs",3)):
            v = getattr(self,name)
            if isinstance(v,bool) or not isinstance(v,int) or v < minimum:
                raise ValueError(strings.ContractValidationMessages.INTEGER_MINIMUM.format(name=name, minimum=minimum))


def from_mapping(owner, data):
    """Construct a contract dataclass from a closed mapping of external keys.

    Reject non-dicts and unknown keys; owner validates required fields/values.
    Omitted optional fields retain only that type's authoritative defaults.
    """
    if not isinstance(data,dict) or set(data) - {f.name for f in fields(owner)}:
        raise ValueError(strings.ContractValidationMessages.UNKNOWN_FIELDS.format(owner=owner.__name__))
    return owner(**data)


@dataclass(frozen=True)
class BuildConfig:
    """External config v1, input contract 0.2; paths relative to config file.

    Required (no defaults): config_version='1', contract_version='0.2', dataset_id
      nonempty text, geometry_mode='buildings'|'parts', footprints a nonempty local path, working_epsg positive integer suitable projected metre CRS (not Web Mercator), and
      vertical_reference a nonempty declaration shared by all Z sources in m.
      'local_relative' explicitly makes no absolute vertical datum assertion.
      Naming a datum declares the input basis; no vertical conversion is implied.
    dtm: optional local single-band raster path, default None. Omission/null
      selects direct LiDAR ground for every requested level, including LoD0 and
      known-height mode; these modes therefore still require LiDAR. A supplied
      DTM explicitly selects the existing raster-ground workflow without a
      silent fallback to points. Original source Z is preserved in either mode.
    ground: None selects PointGroundConfig defaults; a closed mapping/typed
      policy controls geometric exterior surfaces, audit outputs and display TIN.
      Used only without dtm; explicitly supplied ground settings with dtm fail.
    lidar: paths to LAS/LAZ files or directories (recursive), default empty.
      Required for height_source='lidar' when LoD1 requested, except explicit
      external fallback can resolve absence per object. No URLs/glob expansion.
    lods: unique nonempty subset of (0,1), default (0,1); one model per level.
      2 is rejected, never silently labelled/extruded as LoD2.
    height_source: 'lidar' default; 'known' deliberately uses reference_height_m
      for LoD1, recorded as known_height, never as a measurement validation.
    external_height_fallback: bool false default; only with lidar mode. Allows
      a qualified reference height after lidar/floor inference is unresolved;
      never overrides a resolved result or invents ground. Contract 0.2 adds
      this explicit use; prior experiments remain comparison-only.
    roof_classes: null/omitted only. Explicit class filters are rejected;
      building decisions use XYZ/footprints and classes remain metadata.
    invalid_objects: 'error' default aborts structural/geometry violations;
      'exclude' retains each rejected ID/reason without its geometry. Duplicate
      identities, missing layers or CRS always abort (unambiguous accounting).
    unresolved_objects: 'omit' default writes partial models/reports; 'error'
      aborts if a requested level has objects without sufficient evidence.
    precision_m: >0 metres, default .001 quantization for XY/Z. Collapse or
      invalid geometry after quantization is an error, never repaired.
    buildings_layer/parts_layer: canonical defaults; field names are canonical
      contract names. A different layer name does not change field semantics.
    source_inventory: optional snapshot v1 path; default None. Checks GPKG hash
      and accounts for source identities lacking a GPKG row. Not required for
      normal independent input and never authorizes malformed relationships.
    height/sampling: None selects the owning HeightConfig/SamplingConfig defaults;
      mappings are closed and validated. Changing these affects results, while
      CLI only overrides output location. Inputs are always read-only.
    """

    config_version: str  # Required JSON configuration version; only '1' is accepted.
    contract_version: str  # Required canonical input-field contract; only '0.2' is accepted.
    dataset_id: str  # Nonempty dataset identity used in model/run provenance.
    geometry_mode: str  # 'buildings' reconstructs parents; 'parts' reconstructs explicit bodies.
    footprints: str  # Literal local GPKG path, resolved from the configuration directory.
    working_epsg: int  # Explicit positive EPSG for suitable projected-metre calculations.
    vertical_reference: str  # Declares the common metric Z basis; does not perform datum conversion.
    dtm: str | None = None  # None selects direct point ground; a path explicitly opts into raster ground.
    ground: PointGroundConfig | None = None  # Direct-mode policy; None delegates to its sole default owner.
    lidar: tuple[str,...] = ()  # Local files/directories; necessity depends on level/mode.
    lods: tuple[int,...] = (0,1)  # Requested semantic levels; LoD2 is rejected.
    height_source: str = strings.BuildingHeightSource.LIDAR  # Estimation versus deliberate known-height use.
    external_height_fallback: bool = False  # Qualified height only after unresolved estimation.
    roof_classes: None = None  # Compatibility key: only null; building point selection is geometric, original LAS labels are metadata.
    invalid_objects: str = strings.InputFailurePolicy.ERROR  # Reception policy: abort or exclude bad objects.
    unresolved_objects: str = strings.InputFailurePolicy.OMIT  # Missing-evidence policy: partial result or abort.
    precision_m: float = 0.001  # Shared XY/Z grid step; not survey accuracy.
    buildings_layer: str = strings.GeoPackageLayers.BUILDINGS  # GPKG layer with canonical building fields.
    parts_layer: str = strings.GeoPackageLayers.BUILDING_PARTS  # Read only in explicit parts mode.
    source_inventory: str | None = None  # Optional local identity/hash audit declaration.
    height: HeightConfig | None = None  # None delegates defaults to HeightConfig.
    sampling: SamplingConfig | None = None  # None delegates defaults to SamplingConfig.
    roof_recovery: RoofRecoveryConfig | None = None  # None delegates to disabled RoofRecoveryConfig. Legacy standalone recovery settings; mandatory native attribution is owned by building_surfaces. Requires LiDAR LoD1 when enabled; does not disable or replace the mandatory stage. Source classes remain unchanged; evidence is exported per object.
    roof_surfaces: RoofSurfaceConfig | None = None  # None delegates to disabled RoofSurfaceConfig. Legacy spatial-fit settings; native attribution uses building_surfaces. Does not disable mandatory geometry. Requires LiDAR LoD1 when enabled.
    adjacent_ground: AdjacentGroundConfig | None = None  # Closed missing-base sharing policy; None delegates to enabled owner defaults. Same-parent boundary graph only, measured bases preserved.
    show_unresolved_footprints: bool = True  # True exports valid unresolved units as explicitly labelled LoD0 display surfaces in each requested model; never a resolved volume or a measured ground assertion. False explicitly requests historical geometry omission; strict unresolved_objects=error still aborts.
    building_surfaces: BuildingSurfaceConfig | None = None  # None delegates to mandatory class-neutral surface ownership policy; replaces inward/class-based building roof selection.
    roof_regions: RoofRegionsConfig | None = None  # None delegates to disabled owner defaults. Closed opt-in for supported internal stepped LoD1 regions; preserves source IDs/XY, requires LiDAR LoD1, never calibrates floor anchors.

    def __post_init__(self):
        """Reject contradictory modes/paths and materialise typed policy owners."""
        if self.config_version != strings.InputContractVersion.CONFIG_VERSION or self.contract_version != strings.InputContractVersion.BUILDING_CONTRACT_VERSION:
            raise ValueError(strings.ContractValidationMessages.CONTRACT_VERSIONS.format(
                config_field=strings.ConfigurationEnvelopeFields.VERSION, config_version=strings.InputContractVersion.CONFIG_VERSION,
                contract_field=strings.BuildConfigurationFields.CONTRACT_VERSION, contract_version=strings.InputContractVersion.BUILDING_CONTRACT_VERSION))
        for name in (strings.DatasetIdentityFields.DATASET_ID,strings.GeospatialInputFields.VERTICAL_REFERENCE,strings.GeospatialInputFields.FOOTPRINTS,"buildings_layer","parts_layer"):
            if not isinstance(getattr(self,name),str) or not getattr(self,name).strip():
                raise ValueError(strings.ContractValidationMessages.NONEMPTY_TEXT.format(name=name))
        if self.geometry_mode not in (strings.BuildingGeometryMode.BUILDINGS,strings.BuildingGeometryMode.PARTS) or self.height_source not in (strings.BuildingHeightSource.LIDAR,strings.BuildingHeightSource.KNOWN):
            raise ValueError("Invalid geometry_mode or height_source")
        if isinstance(self.working_epsg,bool) or not isinstance(self.working_epsg,int) or self.working_epsg <= 0:
            raise ValueError("working_epsg must be an explicit positive EPSG integer")
        if not isinstance(self.external_height_fallback,bool) or (self.external_height_fallback and self.height_source != strings.BuildingHeightSource.LIDAR):
            raise ValueError("External fallback is a boolean for lidar mode only")
        if type(self.show_unresolved_footprints) is not bool:raise ValueError('show_unresolved_footprints must be boolean')
        object.__setattr__(self,'adjacent_ground',AdjacentGroundConfig() if self.adjacent_ground is None else from_mapping(AdjacentGroundConfig,self.adjacent_ground) if isinstance(self.adjacent_ground,dict) else self.adjacent_ground)
        if not isinstance(self.adjacent_ground,AdjacentGroundConfig):raise ValueError('Invalid adjacent-ground policy')
        if self.invalid_objects not in (strings.InputFailurePolicy.ERROR,strings.InputFailurePolicy.EXCLUDE) or self.unresolved_objects not in (strings.InputFailurePolicy.ERROR,strings.InputFailurePolicy.OMIT):
            raise ValueError("Invalid error policy")
        if not isinstance(self.lods,(list,tuple)) or not self.lods or any(type(v) is not int or v not in (0,1) for v in self.lods) or len(set(self.lods)) != len(self.lods):
            raise ValueError("lods must be a unique nonempty subset of [0,1]; LoD2 is not implemented")
        if not isinstance(self.lidar,(list,tuple)) or any(not isinstance(p,str) or not p.strip() for p in self.lidar):
            raise ValueError("lidar must be a list of local paths")
        if 1 in self.lods and self.height_source == strings.BuildingHeightSource.LIDAR and not self.lidar and not self.external_height_fallback:
            raise ValueError("LiDAR sources required for lidar heights")
        if self.dtm is None and not self.lidar:
            raise ValueError('LiDAR sources required for direct ground, including LoD0/known heights')
        if self.dtm is not None and self.ground is not None:
            raise ValueError('ground settings require omitted/null dtm; choose one ground source')
        for p in [self.footprints,*([self.dtm] if self.dtm is not None else []),*self.lidar,*([self.source_inventory] if self.source_inventory is not None else [])]:
            if not isinstance(p,str) or not p.strip() or "://" in p or "$" in p or "%" in p or p.startswith("~"):
                raise ValueError("Use literal local input paths, without URL/environment expansion")
        if self.roof_classes is not None and (not isinstance(self.roof_classes,(list,tuple)) or not self.roof_classes
                or any(type(c) is not int or not 0 <= c <= 255 for c in self.roof_classes)
                or len(set(self.roof_classes)) != len(self.roof_classes)):
            raise ValueError("roof_classes must be null or unique class integers 0..255")
        finite_number(self.precision_m,strings.ModelQuantizationFields.PRECISION_M)
        if self.precision_m <= 0:
            raise ValueError("precision_m must be positive")
        object.__setattr__(self,strings.BuildConfigurationFields.LODS,tuple(self.lods))
        object.__setattr__(self,strings.GeospatialInputFields.LIDAR,tuple(self.lidar))
        if self.roof_classes is not None:raise ValueError('roof_classes must be null: buildings use XYZ and footprints, not LAS labels')
        if self.dtm is None:
            object.__setattr__(self,'ground',PointGroundConfig() if self.ground is None else from_mapping(PointGroundConfig,self.ground) if isinstance(self.ground,dict) else self.ground)
            if not isinstance(self.ground,PointGroundConfig):raise ValueError('Invalid direct ground policy')
        object.__setattr__(self,'roof_recovery',RoofRecoveryConfig() if self.roof_recovery is None else from_mapping(RoofRecoveryConfig,self.roof_recovery) if isinstance(self.roof_recovery,dict) else self.roof_recovery)
        if not isinstance(self.roof_recovery,RoofRecoveryConfig):raise ValueError('Invalid roof recovery policy')
        if self.roof_recovery.enabled and (self.height_source!=strings.BuildingHeightSource.LIDAR or 1 not in self.lods):
            raise ValueError('Roof recovery requires lidar heights and LoD1')
        object.__setattr__(self,'roof_surfaces',RoofSurfaceConfig() if self.roof_surfaces is None else from_mapping(RoofSurfaceConfig,self.roof_surfaces) if isinstance(self.roof_surfaces,dict) else self.roof_surfaces)
        if not isinstance(self.roof_surfaces,RoofSurfaceConfig):raise ValueError('Invalid spatial roof policy')
        if self.roof_surfaces.enabled and (self.height_source!=strings.BuildingHeightSource.LIDAR or 1 not in self.lods):
            raise ValueError('Spatial roofs require lidar heights and LoD1')
        object.__setattr__(self,'building_surfaces',BuildingSurfaceConfig() if self.building_surfaces is None else from_mapping(BuildingSurfaceConfig,self.building_surfaces) if isinstance(self.building_surfaces,dict) else self.building_surfaces)
        if not isinstance(self.building_surfaces,BuildingSurfaceConfig):raise ValueError('Invalid building surface policy')
        object.__setattr__(self,'roof_regions',RoofRegionsConfig() if self.roof_regions is None else from_mapping(RoofRegionsConfig,self.roof_regions) if isinstance(self.roof_regions,dict) else self.roof_regions)
        if not isinstance(self.roof_regions,RoofRegionsConfig):raise ValueError('Invalid roof regions policy')
        if self.roof_regions.enabled and (self.height_source!=strings.BuildingHeightSource.LIDAR or 1 not in self.lods):
            raise ValueError('Roof regions require lidar heights and LoD1')
        object.__setattr__(self,"height",HeightConfig() if self.height is None else from_mapping(HeightConfig,self.height) if isinstance(self.height,dict) else self.height)
        object.__setattr__(self,strings.BuildConfigurationFields.SAMPLING,SamplingConfig() if self.sampling is None else from_mapping(SamplingConfig,self.sampling) if isinstance(self.sampling,dict) else self.sampling)
        if not isinstance(self.height,HeightConfig) or not isinstance(self.sampling,SamplingConfig):
            raise ValueError("Invalid typed height or sampling configuration")

    @classmethod
    def read(cls, path):
        """Read UTF-8 JSON (optional BOM), rejecting unknown keys/invalid values.

        Paths remain literal; the pipeline resolves them from this file's
        directory. This step does not open or validate the geospatial resources.
        """
        return from_mapping(cls,json.loads(Path(path).read_text(encoding=strings.TextFileEncoding.UTF8_BOM)))

    def effective(self):
        """Return nested effective settings for run provenance, without file I/O."""
        return asdict(self)
