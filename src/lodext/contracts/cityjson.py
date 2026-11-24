"""String contracts owned by the cityjson boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class CityJSONFields:
    """CityJSON 2.0 standard document/object/geometry wire fields."""

    TYPE: Final[str] = 'type'  # Wire key for external geometry/object type.
    VERSION: Final[str] = 'version'  # Wire key for format or library version.
    GEOMETRY: Final[str] = 'geometry'  # Wire key for geometry payload.
    ATTRIBUTES: Final[str] = 'attributes'  # Wire key for CityJSON object attributes.
    BOUNDARIES: Final[str] = 'boundaries'  # Wire key for CityJSON ring nesting.
    SCALE: Final[str] = 'scale'  # Wire key for per-axis transform scale.
    TRANSFORM: Final[str] = 'transform'  # Wire key for declared coordinate transform.
    TRANSLATE: Final[str] = 'translate'  # Wire key for per-axis transform translation.
    VERTICES: Final[str] = 'vertices'  # Wire key for coordinate table.
    CITY_OBJECTS: Final[str] = 'CityObjects'  # Wire key for CityJSON object table.
    LOD: Final[str] = 'lod'  # Wire key for semantic geometry level.
    METADATA: Final[str] = 'metadata'  # Wire key for model metadata.
    REFERENCE_SYSTEM: Final[str] = 'referenceSystem'  # Wire key for CityJSON CRS URI.
    SEMANTICS: Final[str] = 'semantics'  # Wire key for surface semantic labels.
    SURFACES: Final[str] = 'surfaces'  # Wire key for semantic surfaces or composed surface evidence.
    VALUES: Final[str] = 'values'  # Wire key for semantic or numeric values.
    GEOGRAPHICAL_EXTENT: Final[str] = 'geographicalExtent'  # Wire key for model XYZ extent.
    IDENTIFIER: Final[str] = 'identifier'  # Wire key for model identifier.
    TITLE: Final[str] = 'title'  # Wire key for human-readable model title.


class CityJSONReconstructionAttributes:
    """Application-specific CityJSON attributes preserving source identity/status."""

    SOURCE_CLASS: Final[str] = 'sourceClass'  # Wire key for original semantic class.
    SOURCE_ID: Final[str] = 'sourceId'  # Wire key for original source identity.
    KEY_RECONSTRUCTION_STATUS: Final[str] = 'reconstructionStatus'  # Wire key for CityJSON per-object status.
    REPRESENTATION: Final[str] = 'representation'  # Optional 'unresolved_footprint' display marker; never a resolved solid or ground assertion.
    DISPLAY_REFERENCE_Z: Final[str] = 'display_reference_z'  # Marker plane elevation in source Z metres, possibly display-only; does not fill missing ground/height.
    DISPLAY_PLACEMENT: Final[str] = 'display_placement'  # Marker provenance: sampled_or_inferred_ground, observed_roof_mode or display_reference_only; exporter-owned selection order.


class CityJSONObjectType:
    """External CityJSON non-building object type names."""

    TIN_RELIEF: Final[str] = 'TINRelief'  # CityJSON terrain object type.
    PLANT_COVER: Final[str] = 'PlantCover'  # CityJSON land-cover object type.
    WATER_BODY: Final[str] = 'WaterBody'  # CityJSON water object type.
    ROAD: Final[str] = 'Road'  # Supported road surface class and CityJSON road type.


class CityJSONGeometryType:
    """External CityJSON surface and solid boundary nesting kinds."""

    MULTI_SURFACE: Final[str] = 'MultiSurface'  # CityJSON surface collection boundary nesting.
    COMPOSITE_SURFACE: Final[str] = 'CompositeSurface'  # CityJSON connected-surface nesting for terrain.
    SOLID: Final[str] = 'Solid'  # CityJSON solid shell boundary nesting.
    MULTI_SOLID: Final[str] = 'MultiSolid'  # Internal/general converter multipart solid nesting.


class CityJSONSurfaceSemantic:
    """External CityJSON face semantic labels."""

    GROUND: Final[str] = 'GroundSurface'  # CityJSON ground-face semantic type.
    ROOF: Final[str] = 'RoofSurface'  # CityJSON roof-face semantic type.
    WALL: Final[str] = 'WallSurface'  # CityJSON wall-face semantic type.
    WATER: Final[str] = 'WaterSurface'  # CityJSON water-face semantic type.
    TRAFFIC: Final[str] = 'TrafficArea'  # CityJSON road traffic-area semantic type.


class CityJSONFormat:
    """CityJSON format identity, version and standard CRS identifier prefix."""

    FORMAT: Final[str] = 'CityJSON'  # External CityJSON format identifier.
    VERSION: Final[str] = '2.0'  # Generated/accepted CityJSON version, independent of glTF.
    CRS_EPSG_URI_PREFIX: Final[str] = 'https://www.opengis.net/def/crs/EPSG/0/'  # OGC URI prefix shared by model exporters.


class CityModelLoD:
    """Semantic CityJSON level identifiers, not tile refinement levels."""

    LOD0: Final[str] = '0'  # CityJSON ground/footprint level identifier.
    LOD1: Final[str] = '1'  # CityJSON extrusion/surface level identifier.
