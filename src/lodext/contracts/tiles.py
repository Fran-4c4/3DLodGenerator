"""String contracts owned by the tiles boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class TileConversionFields:
    """Tile placement and its explicit clamping provenance."""

    PLACEMENT: Final[str] = 'placement'  # Wire key for explicit tile placement settings.
    CLAMPING_APPLIED: Final[str] = 'clamping_applied'  # Wire key for explicit placement provenance.
    METADATA_NOTE: Final[str] = 'metadata'  # Explanatory conversion text; not a CityJSON metadata object.


class GlTFFormat:
    """External glTF asset version, independent of CityJSON."""

    VERSION: Final[str] = '2.0'  # Generated glTF asset version, independent of CityJSON.


class GlTFFields:
    """External glTF wire fields; separate from CityJSON and 3D Tiles."""

    MESHES: Final[str] = 'meshes'  # Wire key for mesh payload.
    ASSET_VERSION: Final[str] = 'version'  # glTF asset version field; independent of CityJSON and 3D Tiles.
    ACCESSOR_TYPE: Final[str] = 'type'  # External glTF accessor shape, for example VEC3; not an object class.


class TilesetFields:
    """External 3D Tiles wire fields; independent of glTF."""

    ASSET_VERSION: Final[str] = 'version'  # 3D Tiles asset version field; independent of embedded glTF.
