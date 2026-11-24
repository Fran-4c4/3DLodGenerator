"""CityJSON -> GLB and a static, single-content 3D Tiles 1.1 tileset."""
from lodext import strings
from dataclasses import asdict,dataclass
import hashlib
import json
import math
from pathlib import Path
import struct

import numpy as np
from pyproj import CRS,Transformer
from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon

from ..core.heights import finite_number
from .cityjson import validate_cityjson


# Display-only RGBA factors in [0,1], owned here. Class identity remains in
# sourceClass/node extras; colour is not a reconstruction or quality decision.
# Building/BuildingPart retain the initial material. No hidden per-user styles.
# Keys are CityJSON object types, not surface-contract class names (Terrain
# exports as TINRelief). write_tiles creates one material per encountered key;
# absent keys keep the default building material. Changing these linear glTF
# factors affects appearance only, never geometry, classification or placement.
SURFACE_COLOURS = {strings.CityJSONObjectType.ROAD: (.32,.34,.36,1), strings.CityJSONObjectType.TIN_RELIEF: (.58,.46,.30,1),
                   strings.CityJSONObjectType.PLANT_COVER: (.20,.48,.22,1), strings.CityJSONObjectType.WATER_BODY: (.10,.40,.72,1)}


@dataclass(frozen=True)
class TileConfig:
    """Explicit placement, never a guessed vertical transformation.

    z_offset_m: REQUIRED finite metres, added to source Z to obtain declared
      ellipsoidal height for this localized placement. Zero is an explicit
      assertion that source Z already has that basis. A constant offset is not
      a geoid grid transformation and must be supplied from justified control.
      Synthetic example: source ground 25 -> ellipsoidal 0 requires -25.
    max_span_m: positive projected metres, default 100000; maximum source XY
      diagonal for this one-tile exporter. Larger areas require partitioning.
    max_roundtrip_error_m: positive metres, default .01; reject float32 output
      whose recovered ECEF vertices exceed this numerical error. Not accuracy
      of source survey or the chosen vertical placement.
    Defaults owned here; CLI references this type. No clamping or silent datum
      correction. Source CityJSON and prior outputs are never modified.
    """
    z_offset_m: float  # Required source-Z to declared ellipsoidal-height offset.
    max_span_m: float = 100_000.0  # Metre XY diagonal limit for a single tile.
    max_roundtrip_error_m: float = 0.01  # Metre float32 placement-error ceiling.

    def __post_init__(self):
        """Reject non-finite placement values and nonpositive numerical budgets."""
        for name in ("z_offset_m","max_span_m","max_roundtrip_error_m"):
            finite_number(getattr(self,name),name)
        if self.max_span_m<=0 or self.max_roundtrip_error_m<=0:
            raise ValueError("Tile span and roundtrip tolerance must be positive")


def surfaces(geometry):
    """Yield ring lists from supported CityJSON surface/solid boundary nesting.

    Preserve face order, holes and source vertex indices. MultiSurface,
    CompositeSurface, Solid and MultiSolid are supported; other types raise.
    This iterator does not triangulate, transform or validate shell topology.
    """
    kind,b = geometry[strings.CityJSONFields.TYPE],geometry[strings.CityJSONFields.BOUNDARIES]
    if kind in (strings.CityJSONGeometryType.MULTI_SURFACE, strings.CityJSONGeometryType.COMPOSITE_SURFACE):
        yield from b
    elif kind==strings.CityJSONGeometryType.SOLID:
        for shell in b:
            yield from shell
    elif kind==strings.CityJSONGeometryType.MULTI_SOLID:
        for solid in b:
            for shell in solid:
                yield from shell
    else:
        raise ValueError("Unsupported CityJSON geometry for conversion")


def triangulate_surface(surface, vertices):
    """Constrained triangulation in the face plane, retaining holes/orientation.

    Original world-coordinate indices are returned. Newell normal chooses the
    dominant projection plane. Triangles must cover the polygon area within
    1e-8 absolute / 1e-9 relative numerical tolerance; not a repair permission.
    Nonplanar surfaces are not repaired; the generated LoD0/1 faces are planar.
    """
    outer = vertices[surface[0]]
    local = outer-outer[0]
    normal = np.cross(local,np.roll(local,-1,axis=0)).sum(axis=0)
    if np.linalg.norm(normal)<1e-12:
        raise ValueError("Degenerate face cannot be triangulated")
    axis = int(np.argmax(np.abs(normal)))
    axes = [i for i in range(3) if i!=axis]
    lookup = {}
    rings = []
    for ring in surface:
        projected = []
        for index in ring:
            point = tuple((vertices[index]-outer[0])[axes])
            if point in lookup and lookup[point]!=index:
                raise ValueError("Distinct vertices collapse in face projection")
            lookup[point] = index
            projected.append(point)
        rings.append(projected)
    polygon = Polygon(rings[0],rings[1:])
    if not polygon.is_valid or polygon.area<=0:
        raise ValueError("Invalid face polygon; conversion does not repair geometry")
    triangles = list(constrained_delaunay_triangles(polygon).geoms)
    if not math.isclose(sum(t.area for t in triangles),polygon.area,rel_tol=1e-9,abs_tol=1e-8):
        raise ValueError("Triangulation does not preserve face area")
    result = []
    for triangle in triangles:
        indices = [lookup[tuple(p)] for p in list(triangle.exterior.coords)[:3]]
        a,b,c = vertices[indices]
        if np.dot(np.cross(b-a,c-a),normal)<0:
            indices[1],indices[2] = indices[2],indices[1]
        result.extend(indices)
    return result


def write_tiles(cityjson_file,output,config):
    """Return conversion evidence and write GLB plus one static 3D Tiles content.

    Read and validate projected-metre CityJSON; undo its per-axis quantisation,
    triangulate faces with holes, apply the explicitly supplied Z offset and
    place float32 vertices in a local frame anchored in ECEF. Reject excessive
    XY span, collapsed triangles or coordinate round-trip error before creating
    the output directory. An existing directory is always rejected.

    Object IDs/attributes go into glTF node extras, not a semantic picking table.
    Write model.glb, tileset.json and conversion.json without editing the source.
    This is a single-content exporter: no partitioning, geoid transformation,
    terrain clamp, height estimation or geometry repair is performed.
    """
    from ..pipeline import dump
    cityjson_file,output = Path(cityjson_file),Path(output)
    if output.exists():
        raise ValueError(strings.OutputDirectoryMessages.OUTPUT_EXISTS)
    data = json.loads(cityjson_file.read_text(encoding=strings.TextFileEncoding.UTF8))
    checks = validate_cityjson(data)
    if not checks[strings.MeshValidationFields.GEOMETRY_COUNT]:
        raise ValueError("CityJSON has no geometry to convert")
    source = CRS.from_user_input(data[strings.CityJSONFields.METADATA][strings.CityJSONFields.REFERENCE_SYSTEM])
    if not source.is_projected or any(abs(a.unit_conversion_factor-1)>1e-10 for a in source.axis_info[:2]):
        raise ValueError("Tile conversion requires a declared projected metre source CRS")
    world = np.asarray(data[strings.CityJSONFields.VERTICES],dtype=float)*data[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.SCALE]+data[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.TRANSLATE]
    extent = np.ptp(world[:,:2],axis=0)
    if np.linalg.norm(extent)>config.max_span_m:
        raise ValueError("Model exceeds the one-tile extent budget; partition it first")
    xy = np.mean([world[:,:2].min(axis=0),world[:,:2].max(axis=0)],axis=0)
    to_lonlat = Transformer.from_crs(source,4326,always_xy=True)
    lon,lat = to_lonlat.transform(world[:,0],world[:,1])
    anchor_lon,anchor_lat = to_lonlat.transform(*xy)
    to_ecef = Transformer.from_crs(4979,4978,always_xy=True)
    ecef = np.column_stack(to_ecef.transform(lon,lat,world[:,2]+config.z_offset_m))
    origin = np.asarray(to_ecef.transform(anchor_lon,anchor_lat,0.0))
    lam,phi = math.radians(anchor_lon),math.radians(anchor_lat)
    east = [-math.sin(lam),math.cos(lam),0]
    north = [-math.sin(phi)*math.cos(lam),-math.sin(phi)*math.sin(lam),math.cos(phi)]
    up = [math.cos(phi)*math.cos(lam),math.cos(phi)*math.sin(lam),math.sin(phi)]
    basis = np.column_stack((east,north,up))
    enu = (ecef-origin)@basis
    # glTF Y-up -> tile Z-up recovers E,N,U as required by 3D Tiles.
    positions = (enu[:,[0,2,1]]*np.array([1,1,-1])).astype("<f4")
    recovered_enu = positions.astype(float)[:,[0,2,1]]*np.array([1,-1,1])
    recovered_ecef = recovered_enu@basis.T+origin
    error = float(np.linalg.norm(recovered_ecef-ecef,axis=1).max())
    if not math.isfinite(error) or error>config.max_roundtrip_error_m:
        raise ValueError("Float32 GLB roundtrip exceeds explicit coordinate tolerance")
    gltf = {"asset":{strings.GlTFFields.ASSET_VERSION:strings.GlTFFormat.VERSION,"generator":strings.ApplicationIdentity.NAME},"scene":0,"scenes":[{"nodes":[]}],
            "nodes":[],strings.GlTFFields.MESHES:[],"buffers":[],"bufferViews":[],"accessors":[],
            "materials":[{"name":strings.BuildingObjectType.BUILDING,"pbrMetallicRoughness":{"baseColorFactor":[.72,.58,.42,1],"metallicFactor":0,"roughnessFactor":.85}}]}
    binary = bytearray()
    def accessor(array):
        """Append a float32 VEC3 array with four-byte alignment and return its accessor.

        Mutates only the current GLB buffer/tables; records component bounds for
        positions or normals. The caller supplies nonempty float32 triples.
        """
        while len(binary)%4:
            binary.append(0)
        view = len(gltf["bufferViews"])
        gltf["bufferViews"].append({"buffer":0,"byteOffset":len(binary),"byteLength":array.nbytes,"target":34962})
        binary.extend(array.tobytes())
        result = len(gltf["accessors"])
        gltf["accessors"].append({"bufferView":view,"componentType":5126,"count":len(array),strings.GlTFFields.ACCESSOR_TYPE:"VEC3",
                                  "min":array.min(axis=0).tolist(),"max":array.max(axis=0).tolist()})
        return result
    triangle_count = 0
    material_indices = {}
    for identifier,obj in data[strings.CityJSONFields.CITY_OBJECTS].items():
        indices = []
        for geometry in obj.get(strings.CityJSONFields.GEOMETRY,[]):
            for face in surfaces(geometry):
                indices.extend(triangulate_surface(face,world))
        if not indices:
            continue
        p = positions[indices]
        triangles = p.reshape((-1,3,3)).astype(float)
        normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        lengths = np.linalg.norm(normals,axis=1)
        if np.any(lengths<1e-12):
            raise ValueError("Float32 collapses a triangle")
        normals = np.repeat(normals/lengths[:,None],3,axis=0).astype("<f4")
        triangle_count += len(triangles)
        material = 0
        kind = obj.get(strings.CityJSONFields.TYPE)
        if kind in SURFACE_COLOURS:
            if kind not in material_indices:
                material_indices[kind] = len(gltf["materials"])
                gltf["materials"].append({"name":kind,"pbrMetallicRoughness":{
                    "baseColorFactor":list(SURFACE_COLOURS[kind]),"metallicFactor":0,"roughnessFactor":.85}})
            material = material_indices[kind]
        mesh = len(gltf[strings.GlTFFields.MESHES])
        gltf[strings.GlTFFields.MESHES].append({"name":identifier,"primitives":[{"mode":4,"material":material,strings.CityJSONFields.ATTRIBUTES:{"POSITION":accessor(p),"NORMAL":accessor(normals)}}]})
        node = len(gltf["nodes"])
        gltf["nodes"].append({"name":identifier,"mesh":mesh,"extras":{"objectId":identifier,**obj.get(strings.CityJSONFields.ATTRIBUTES,{})}})
        gltf["scenes"][0]["nodes"].append(node)
    if not gltf[strings.GlTFFields.MESHES]:
        raise ValueError("No triangles were produced")
    gltf["buffers"] = [{"byteLength":len(binary)}]
    encoded = json.dumps(gltf,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode(strings.TextFileEncoding.UTF8)
    encoded += b" "*((-len(encoded))%4)
    binary.extend(b"\x00"*((-len(binary))%4))
    glb = struct.pack("<4sII",b"glTF",2,12+8+len(encoded)+8+len(binary))+struct.pack("<I4s",len(encoded),b"JSON")+encoded+struct.pack("<I4s",len(binary),b"BIN\x00")+binary
    minimum,maximum = recovered_enu.min(axis=0)-.001,recovered_enu.max(axis=0)+.001
    center,half = (minimum+maximum)/2,(maximum-minimum)/2
    bounds = [*center,half[0],0,0,0,half[1],0,0,0,half[2]]
    transform = np.eye(4)
    transform[:3,:3],transform[:3,3] = basis,origin
    # Tileset-level error describes omitting the entire model, not leaf mesh
    # approximation. Zero here makes Cesium skip traversal/content requests.
    # The full box diagonal bounds this omission scale; the full-detail leaf is 0.
    tileset = {"asset":{strings.TilesetFields.ASSET_VERSION:"1.1"},"geometricError":float(np.linalg.norm(half)*2),
               "root":{"boundingVolume":{"box":list(map(float,bounds))},"geometricError":0,"refine":"ADD",
                       strings.CityJSONFields.TRANSFORM:transform.T.ravel().tolist(),"content":{"uri":"model.glb"}}}
    summary = {"objects_with_mesh":len(gltf[strings.GlTFFields.MESHES]),strings.MeshValidationFields.TRIANGLE_COUNT:triangle_count,"glb_bytes":len(glb),
               "max_ecef_roundtrip_error_m":error,"source_cityjson_sha256":hashlib.sha256(cityjson_file.read_bytes()).hexdigest(),
               "source_crs":source.to_string(),"source_vertical_reference":data.get("lodext",{}).get(strings.GeospatialInputFields.VERTICAL_REFERENCE),
               strings.TileConversionFields.PLACEMENT:asdict(config),"vertical_operation":"explicit_constant_offset_not_geoid_transformation",
               "anchor_lonlat":[anchor_lon,anchor_lat],strings.TileConversionFields.CLAMPING_APPLIED:False,
               strings.TileConversionFields.METADATA_NOTE:"Object IDs and attributes in glTF node extras; no EXT_mesh_features picking table."}
    output.mkdir(parents=True,exist_ok=False)
    (output/"model.glb").write_bytes(glb)
    dump(output/"tileset.json",tileset)
    dump(output/"conversion.json",summary)
    return summary
