"""String contracts owned by the sources boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class PolygonFootprintFields:
    """Physical footprint measurements shared by building and surface evidence."""

    AREA_M2: Final[str] = 'area_m2'  # Original XY polygon area in square metres; not an eroded support area.


class SourceObjectIdentity:
    """Canonical source identity and class qualification."""

    IDENTITY_SEPARATOR: Final[str] = '::'  # Class/source-ID delimiter; split once, never infer parentage.
    SOURCE_ID: Final[str] = 'source_id'  # Wire key for reported source identity.
    SOURCE_CLASS: Final[str] = 'source_class'  # Wire key for reported semantic source class.
    OBJECT_ID: Final[str] = 'object_id'  # Wire key for source inventory identity.
    KIND: Final[str] = 'kind'  # Wire key for source object kind.
    BUILDING_ID: Final[str] = 'building_id'  # Wire key for explicit source building identity.
    PART_ID: Final[str] = 'part_id'  # Wire key for part identity.


class GeoPackageMetadataQueries:
    """Bound-parameter metadata queries for canonical polygon reception."""

    GEOMETRY_METADATA: Final[str] = 'SELECT column_name,srs_id,geometry_type_name,z,m FROM gpkg_geometry_columns WHERE table_name=?'  # Layer geometry type, dimensions and CRS.
    CRS_METADATA: Final[str] = 'SELECT organization,organization_coordsys_id,definition FROM gpkg_spatial_ref_sys WHERE srs_id=?'  # Declared layer CRS authority/WKT.


class GeoPackageLayers:
    """Default input layers; these names do not select reconstruction modes."""

    BUILDINGS: Final[str] = 'buildings'  # Canonical default GPKG building layer.
    BUILDING_PARTS: Final[str] = 'building_parts'  # Canonical default GPKG part layer.
    SURFACES: Final[str] = 'surfaces'  # Canonical default GPKG surface layer.
    CONTEXT_BUILDINGS: Final[str] = 'context_buildings'  # Audit-only surrounding obstacle layer.


class GeospatialInputFields:
    """Local resources and shared metric reference declarations, not sampling evidence."""

    FOOTPRINTS: Final[str] = 'footprints'  # Wire key for local footprint resource.
    DTM: Final[str] = 'dtm'  # Wire key for terrain resource or terrain evidence.
    DTM_FILE: Final[str] = 'dtm_file'  # Wire key for declared terrain raster path.
    POLYGONS: Final[str] = 'polygons'  # Wire key for surface polygon resource.
    LIDAR: Final[str] = 'lidar'  # Wire/attribute key for cloud inputs/evidence; not a height-source mode.
    LIDAR_DIRECTORY: Final[str] = 'lidar_directory'  # Wire key for declared cloud directory.
    SOURCE_INVENTORY: Final[str] = 'source_inventory'  # Wire key for source audit inventory path.
    WORKING_EPSG: Final[str] = 'working_epsg'  # Wire key for declared metric working CRS.
    VERTICAL_REFERENCE: Final[str] = 'vertical_reference'  # Wire key for declared input Z reference.


class DatasetIdentityFields:
    """Stable dataset identity carried across input and run provenance."""

    DATASET_ID: Final[str] = 'dataset_id'  # Wire key for dataset identity.


class SourceInventoryFields:
    """Source snapshot geometry availability and integrity evidence."""

    GEOMETRY_AVAILABLE: Final[str] = 'geometry_available'  # Wire key for explicit source geometry availability.
    GEOPACKAGE_SHA256: Final[str] = 'geopackage_sha256'  # Wire key for source GPKG content digest.
    OBJECTS: Final[str] = 'objects'  # Source identity records, including explicit missing-geometry declarations.


class LidarInventoryFields:
    """Cloud inventory identity, selection, bounds and spatial-query capabilities."""

    FILE: Final[str] = 'file'  # Wire key for resource file identity.
    SELECTED: Final[str] = 'selected'  # Wire key for resource selection decision.
    SELECTED_FILES: Final[str] = 'selected_files'  # Wire key for selected resource identities.
    BOUNDS_XY: Final[str] = 'bounds_xy'  # Wire key for resource XY bounds.
    CRS_WKT: Final[str] = 'crs_wkt'  # Wire key for declared CRS WKT.
    IS_COPC: Final[str] = 'is_copc'  # Wire key for cloud spatial-index capability.
    LIDAR_FILES: Final[str] = 'lidar_files'  # Wire key for cloud file count or list.


class GeoJSONFields:
    """Standard GeoJSON feature reception fields for optional audit tools."""

    FEATURES: Final[str] = 'features'  # GeoJSON feature array key, not a GPKG data-type value.
    GEOMETRY: Final[str] = 'geometry'  # Wire key for geometry payload.


class GeoPackageGeometryFields:
    """Canonical GPKG geometry column name."""

    GEOM: Final[str] = 'geom'  # Wire key for canonical GPKG geometry column.


class PolygonGeometryType:
    """Single/multipart polygon geometry kinds used during source reception."""

    POLYGON: Final[str] = 'Polygon'  # Shapely/GeoJSON single-polygon type.
    MULTI_POLYGON: Final[str] = 'MultiPolygon'  # Shapely/GeoJSON multipart-polygon type.


class SourceReceptionReason:
    """Stable missing-source reason, distinct from height-estimation methods."""

    MISSING_GEOMETRY: Final[str] = 'missing_geometry'  # No source geometry for an accounted identity.
