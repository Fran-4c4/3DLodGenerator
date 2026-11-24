"""Read canonical input contract from GeoPackage without GDAL CLI or services."""
from lodext import strings
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from pyproj import CRS, Transformer
from shapely import from_wkb
from shapely.ops import transform


@dataclass
class Feature:
    """Internal source identity and geometry, never inferred from its name.

    kind/id: Building or BuildingPart + original text ID; identity is their pair.
    parent_id: explicit source building ID for parts, None for buildings.
    geometry: working-CRS Polygon/MultiPolygon, or None for missing/invalid data.
      A source footprint never becomes a sampling erosion.
    properties: canonical storeys and reference height provenance, unmodified.
    issues: stable reception codes; any issue excludes geometry from reconstruction.
      With invalid_objects='error', reception aborts before sampling/output.
    """
    kind: str  # Canonical 'Building' or 'BuildingPart'; qualifies identity in key.
    id: str  # Original nonempty source text ID; unique within its kind.
    parent_id: str | None  # Explicit source building ID for a part; None for a building.
    geometry: object | None  # Full working-metre XY polygon(s); None when unavailable/unreadable.
    properties: dict  # Canonical storey/reference-height fields and their provenance.
    issues: list[str]  # Reception reason codes; any issue excludes this feature from reconstruction.
    # Computed XY evidence -> quality.objects[].parent_relation; never source attributes.
    # None (sole default) means building or unavailable/invalid parent geometry,
    # not zero overflow. outside_area_m2 >=0 measures part area outside its parent
    # in m²; overlap_fraction in [0,1] is intersection/part area. Partial overflow
    # has no implicit tolerance, exclusion, clipping or reparenting policy.
    # Zero overlap is rejected separately. Changing these keys affects reports.
    parent_relation: dict | None = None

    @property
    def key(self):
        """Return the class-qualified key used by samples, reports and CityJSON."""
        return f"{self.kind}{strings.SourceObjectIdentity.IDENTITY_SEPARATOR}{self.id}"


def quote(name):
    """Quote a SQLite identifier, escaping embedded double quotes.

    For layer/column names in SQL only; bind data values through SQL parameters.
    """
    return '"'+name.replace('"','""')+'"'


def gpkg_geometry(blob):
    """Decode standard GeoPackage geometry bytes, skipping the declared envelope.

    None returns None. Reject short/invalid headers, nonzero encoding versions,
    extended geometries and unknown envelope indicators before WKB decoding.
    This helper does not validate layer CRS agreement or polygon suitability;
    reception checks those separately and never repairs source geometry.
    """
    if blob is None:
        return None
    if len(blob) < 8 or blob[:2] != b"GP":
        raise ValueError("Invalid GeoPackage geometry header")
    flags = blob[3]
    if blob[2] != 0 or flags & 32:
        raise ValueError("Unsupported GeoPackage geometry encoding")
    envelope = (flags >> 1) & 7
    if envelope > 4:
        raise ValueError("Invalid GeoPackage envelope indicator")
    offset = 8 + (0,32,48,48,64)[envelope]
    return from_wkb(blob[offset:])


def metric_working_crs(epsg):
    """Return a projected-metre PyProj CRS for the explicitly supplied EPSG.

    Reject geographic/non-metre CRSs and Web Mercator. This is a unit/projection
    guard, not an automatic choice of a suitable local zone or a vertical datum.
    Both building and surface reception use it before any metric geometry work.
    """
    working = CRS.from_epsg(epsg)
    if not working.is_projected or not working.axis_info or any(abs(a.unit_conversion_factor-1)>1e-10 for a in working.axis_info[:2]):
        raise ValueError("working_epsg must be a projected metre CRS")
    if working.to_epsg() in (3857,900913) or (working.coordinate_operation and "pseudo mercator" in working.coordinate_operation.method_name.lower()):
        raise ValueError("Web Mercator cannot be the metric working CRS; choose a suitable local projection")
    return working


def read_footprints(config, root):
    """Receive canonical building/part polygons read-only; return (features, CRS).

    root resolves config's input paths. Read layer CRS and required canonical
    fields, transform XY to the explicit metric working CRS, and preserve every
    source ID, ring and component. Diagnose geometry, height/storey provenance
    and explicit parent relationships. Optional inventory verifies the GPKG hash
    and accounts for identities with missing geometry.

    Duplicate/ambiguous IDs, missing layers and invalid CRS always abort. Per-row
    issues either abort under invalid_objects='error' or remain on excluded
    Feature records. No inferred parentage, geometry repair or source writes.
    """
    path = (Path(root)/config.footprints).resolve()
    if not path.is_file():
        raise ValueError("GeoPackage input does not exist")
    working = metric_working_crs(config.working_epsg)
    result = []
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as connection:
        connection.row_factory = sqlite3.Row
        layers = [(config.buildings_layer,strings.BuildingObjectType.BUILDING,strings.SourceObjectIdentity.BUILDING_ID)]
        if config.geometry_mode == strings.BuildingGeometryMode.PARTS:
            layers.append((config.parts_layer,strings.BuildingObjectType.BUILDING_PART,strings.SourceObjectIdentity.PART_ID))
        for layer,kind,id_field in layers:
            info = connection.execute(strings.GeoPackageMetadataQueries.GEOMETRY_METADATA,(layer,)).fetchone()
            if not info:
                raise ValueError(f"Missing geometry layer: {layer}")
            column,srid,declared,z_dim,m_dim = info
            if declared.upper() not in ("POLYGON","MULTIPOLYGON") or z_dim or m_dim:
                raise ValueError(f"Layer {layer} must declare Polygon/MultiPolygon XY")
            srs = connection.execute(strings.GeoPackageMetadataQueries.CRS_METADATA,(srid,)).fetchone()
            if not srs:
                raise ValueError(f"Missing declared layer CRS: {layer}")
            source = CRS.from_epsg(srs[1]) if str(srs[0]).upper() == "EPSG" else CRS.from_wkt(srs[2])
            converter = Transformer.from_crs(source,working,always_xy=True)
            names = {row[1] for row in connection.execute(f"PRAGMA table_info({quote(layer)})")}
            required = {id_field,column} | ({strings.SourceObjectIdentity.BUILDING_ID} if kind == strings.BuildingObjectType.BUILDING_PART else set())
            if not required <= names:
                raise ValueError(f"Missing canonical columns in {layer}: {sorted(required-names)}")
            seen = set()
            for row in connection.execute(f"SELECT * FROM {quote(layer)}"):
                identifier = row[id_field]
                if not isinstance(identifier,str) or not identifier.strip() or identifier in seen:
                    raise ValueError(f"Empty, non-text or duplicate identity in {layer}")
                seen.add(identifier)
                issues = []
                parent = row[strings.SourceObjectIdentity.BUILDING_ID] if kind == strings.BuildingObjectType.BUILDING_PART else None
                props = {k:row[k] if k in names else None for k in (
                    strings.BuildingInputFields.STOREYS_ABOVE,strings.BuildingInputFields.STOREYS_BELOW,strings.BuildingInputFields.REFERENCE_HEIGHT_M,strings.BuildingInputFields.REFERENCE_HEIGHT_METHOD,strings.BuildingInputFields.REFERENCE_HEIGHT_SOURCE)}
                for k in (strings.BuildingInputFields.STOREYS_ABOVE,strings.BuildingInputFields.STOREYS_BELOW):
                    v = props[k]
                    if v is not None and (type(v) is not int or v < 0):
                        issues.append("invalid_"+k)
                h = props[strings.BuildingInputFields.REFERENCE_HEIGHT_M]
                if h is not None:
                    if isinstance(h,bool) or not isinstance(h,(int,float)) or not math.isfinite(h) or h <= 0:
                        issues.append("invalid_reference_height")
                    if any(not isinstance(props[k],str) or not props[k].strip() for k in (strings.BuildingInputFields.REFERENCE_HEIGHT_METHOD,strings.BuildingInputFields.REFERENCE_HEIGHT_SOURCE)):
                        issues.append("incomplete_reference_provenance")
                elif any(props[k] is not None for k in (strings.BuildingInputFields.REFERENCE_HEIGHT_METHOD,strings.BuildingInputFields.REFERENCE_HEIGHT_SOURCE)):
                    issues.append("reference_provenance_without_height")
                try:
                    geom = gpkg_geometry(row[column])
                    if geom is None or geom.is_empty:
                        issues.append(strings.SourceReceptionReason.MISSING_GEOMETRY)
                    elif geom.geom_type not in (strings.PolygonGeometryType.POLYGON,strings.PolygonGeometryType.MULTI_POLYGON) or geom.has_z or getattr(geom,"has_m",False) or not geom.is_valid or geom.area <= 0:
                        issues.append("invalid_geometry")
                    else:
                        geom = transform(converter.transform,geom)
                        if not geom.is_valid or not all(math.isfinite(v) for v in geom.bounds):
                            issues.append("invalid_transformed_geometry")
                except Exception as exc:
                    geom = None
                    issues.append("unreadable_geometry:"+type(exc).__name__)
                result.append(Feature(kind,identifier,parent,geom,props,issues))
    if not result:
        raise ValueError("No source objects in GeoPackage")
    parents = {f.id:f for f in result if f.kind == strings.BuildingObjectType.BUILDING}
    if config.geometry_mode == strings.BuildingGeometryMode.PARTS:
        counts = {key:0 for key in parents}
        for feature in [f for f in result if f.kind == strings.BuildingObjectType.BUILDING_PART]:
            parent = parents.get(feature.parent_id)
            if parent is None:
                feature.issues.append("missing_parent")
            else:
                counts[parent.id] += 1
                if feature.geometry is not None and parent.geometry is not None and not feature.geometry.is_empty and not parent.geometry.is_empty:
                    if feature.geometry.is_valid and parent.geometry.is_valid:
                        overlap = feature.geometry.intersection(parent.geometry).area
                        feature.parent_relation = {
                            "outside_area_m2":feature.geometry.difference(parent.geometry).area,
                            "overlap_fraction":max(0.0,min(1.0,overlap/feature.geometry.area)),
                        }
                        if overlap <= 0:
                            feature.issues.append("outside_declared_parent")
                if parent.issues:
                    feature.issues.append("invalid_parent")
        for parent in parents.values():
            if counts[parent.id] == 0:
                parent.issues.append("no_parts")
    if config.source_inventory:
        inventory = json.loads((Path(root)/config.source_inventory).read_text(encoding=strings.TextFileEncoding.UTF8))
        if inventory.get("snapshot_version") != strings.InputContractVersion.SNAPSHOT_VERSION or inventory.get(strings.SourceInventoryFields.GEOPACKAGE_SHA256) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("Source inventory version/hash does not match the GeoPackage")
        existing = {(f.kind,f.id) for f in result}
        identities = set()
        for obj in inventory[strings.SourceInventoryFields.OBJECTS]:
            if obj.get(strings.SourceObjectIdentity.KIND) not in (strings.BuildingObjectType.BUILDING,strings.BuildingObjectType.BUILDING_PART) or not isinstance(obj.get(strings.SourceObjectIdentity.OBJECT_ID),str) or not obj[strings.SourceObjectIdentity.OBJECT_ID].strip() or not isinstance(obj.get(strings.SourceInventoryFields.GEOMETRY_AVAILABLE),bool):
                raise ValueError("Source inventory requires Building/BuildingPart text IDs and explicit geometry availability")
            key = obj[strings.SourceObjectIdentity.KIND],obj[strings.SourceObjectIdentity.OBJECT_ID]
            if key in identities:
                raise ValueError("Duplicate source inventory identity")
            identities.add(key)
            if key not in existing:
                if obj.get(strings.SourceInventoryFields.GEOMETRY_AVAILABLE):
                    raise ValueError("Inventory declares geometry missing from selected GeoPackage layers")
                parent_ids = obj.get("parent_ids",[])
                if key[0]==strings.BuildingObjectType.BUILDING_PART and (not isinstance(parent_ids,list) or len(parent_ids)!=1 or not isinstance(parent_ids[0],str)):
                    raise ValueError("Missing-geometry part inventory requires one explicit parent ID")
                result.append(Feature(*key,parent_ids[0] if key[0]==strings.BuildingObjectType.BUILDING_PART else None,None,{},[strings.SourceReceptionReason.MISSING_GEOMETRY]))
        if not existing <= identities:
            raise ValueError("GeoPackage identity missing from source inventory")
    bad = [f for f in result if f.issues]
    if bad and config.invalid_objects == strings.InputFailurePolicy.ERROR:
        sample = "; ".join(f"{f.key}: {','.join(f.issues)}" for f in bad[:5])
        raise ValueError(f"Input rejected: {len(bad)} objects have contract violations. {sample}")
    return result,working
