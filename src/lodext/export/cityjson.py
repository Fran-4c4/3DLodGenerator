"""CityJSON 2.0 writer: identities, integer vertices, relationships and QA."""
from lodext import strings
import math
from ..reconstruction.models import extrusion


class Vertices:
    """One quantizer owner per model: explicit metre precision and local origin.

    precision >0; origin=(x,y,z), finite world-coordinate translation. Neither
    changes vertical datum. __call__ rounds once to integer grid, decode reverses
    that transform. Shared keys deduplicate vertices without merging object IDs.
    """
    def __init__(self,precision,origin):
        """Create an empty shared integer grid with a metre step and XYZ origin."""
        self.precision,self.origin = precision,origin
        self.vertices,self.index = [],{}

    def __call__(self,point):
        """Quantise world XYZ once and return its deduplicated vertex index.

        Uses ties-to-even rounding; a new grid key appends to this model's
        mutable vertex table. Topology collapse is checked by geometry writers.
        """
        key = tuple(round((float(v)-self.origin[i])/self.precision) for i,v in enumerate(point))
        if key not in self.index:
            self.index[key] = len(self.vertices)
            self.vertices.append(list(key))
        return self.index[key]

    def decode(self,index):
        """Recover quantised world XYZ for topology checks; no datum conversion."""
        return tuple(v*self.precision+self.origin[i] for i,v in enumerate(self.vertices[index]))


def build_cityjson(features, records, config, lod):
    """Assemble one building CityJSON model at the requested available level.

    features contains received source identities; records is keyed by Feature.key
    with sampled ground, estimated height and provenance. LoD0 needs ground;
    LoD1 solids also need a resolved height. Valid unresolved units retain
    labelled LoD0 markers by default; invalid objects keep identity without
    invented geometry. Orphan parts are omitted from CityJSON.
    Parent objects retain explicit children rather than duplicating part volumes.

    Quantise in working-CRS metres using config.precision_m, preserve holes and
    represent disconnected components as separate Solid geometries on one object.
    Return a dict without writing files or clamping/translating the vertical datum.
    Extrusion/quantisation violations raise instead of repairing the footprint.
    """
    valid = [f for f in features if f.geometry is not None and not f.issues]
    bases = [r[strings.BuildingHeightFields.GROUND_Z] for r in records.values() if r.get(strings.BuildingHeightFields.GROUND_Z) is not None]
    origin = (min((f.geometry.bounds[0] for f in valid),default=0),
              min((f.geometry.bounds[1] for f in valid),default=0),min(bases,default=0))
    vertex = Vertices(config.precision_m,origin)
    objects = {}
    parents = {f.id:f.key for f in features if f.kind==strings.BuildingObjectType.BUILDING}
    for feature in features:
        record = records.get(feature.key,{})
        attributes = {strings.CityJSONReconstructionAttributes.SOURCE_ID:feature.id,strings.CityJSONReconstructionAttributes.SOURCE_CLASS:feature.kind,
                      strings.CityJSONReconstructionAttributes.KEY_RECONSTRUCTION_STATUS:record.get(strings.ReconstructionObjectFields.STATUS,strings.ReconstructionObjectStatus.PARENT if config.geometry_mode==strings.BuildingGeometryMode.PARTS and feature.kind==strings.BuildingObjectType.BUILDING and not feature.issues else strings.ReconstructionObjectStatus.EXCLUDED),
                      strings.ReconstructionObjectFields.ISSUES:feature.issues+record.get(strings.BuildingHeightFields.FLAGS,[])}
        if record:
            if strings.BuildingHeightFields.ROOF_REGIONS in record:
                attributes[strings.BuildingHeightFields.ROOF_REGIONS]=record[strings.BuildingHeightFields.ROOF_REGIONS]
            if strings.BuildingHeightFields.ADJACENT_GROUND in record:
                attributes[strings.BuildingHeightFields.ADJACENT_GROUND]=record[strings.BuildingHeightFields.ADJACENT_GROUND]
            if strings.BuildingHeightFields.BUILDING_SURFACES in record:
                attributes[strings.BuildingHeightFields.BUILDING_SURFACES]=record[strings.BuildingHeightFields.BUILDING_SURFACES]
            if strings.PointGroundFields.PLANE in record:
                attributes[strings.PointGroundFields.PLANE]=record[strings.PointGroundFields.PLANE]  # Local exterior XYZ plane in source metres; diagnostics, not a datum assertion.
            if strings.BuildingHeightFields.ROOF_SURFACE in record:
                attributes[strings.BuildingHeightFields.ROOF_SURFACE]=record[strings.BuildingHeightFields.ROOF_SURFACE]
            if strings.BuildingHeightFields.ROOF_RECOVERY in record:
                attributes[strings.BuildingHeightFields.ROOF_RECOVERY]=record[strings.BuildingHeightFields.ROOF_RECOVERY]
            attributes.update({k:record.get(k) for k in (strings.BuildingHeightFields.HEIGHT_M,strings.BuildingHeightFields.GROUND_Z,strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z,strings.BuildingHeightFields.METHOD,strings.BuildingHeightFields.N_POINTS,strings.BuildingHeightFields.DENSITY_POINTS_M2,
                              strings.PointGroundFields.METHOD,strings.PointGroundFields.EXCLUDED_INSIDE,strings.PointGroundFields.Z_MIN,strings.PointGroundFields.Z_MAX,strings.PointGroundFields.MEDIAN_ERROR_BOUND,strings.BuildingHeightFields.REFERENCE_PART_ID,strings.BuildingHeightFields.FLOOR_HEIGHT_M,strings.BuildingHeightFields.ROOF_MODE_Z,strings.BuildingHeightFields.ROOF_STRENGTH,strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION,strings.BuildingHeightFields.ROOF_REFERENCE_Z)})
        attributes.update({k:v for k,v in feature.properties.items() if v is not None})
        if lod == 0:
            # A footprint has a placement elevation but no extruded height.
            attributes.pop(strings.BuildingHeightFields.HEIGHT_M, None)
            attributes.pop(strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z, None)
        obj = {strings.CityJSONFields.TYPE:feature.kind,strings.CityJSONFields.ATTRIBUTES:attributes,strings.CityJSONFields.GEOMETRY:[]}
        if feature.kind==strings.BuildingObjectType.BUILDING_PART:
            if feature.parent_id in parents:
                obj["parents"] = [parents[feature.parent_id]]
            else:
                # Orphans stay in the report, not as illegal second-level objects.
                continue
        elif config.geometry_mode==strings.BuildingGeometryMode.PARTS:
            obj["children"] = [f.key for f in features if f.kind==strings.BuildingObjectType.BUILDING_PART and f.parent_id==feature.id]
        if record.get(strings.BuildingHeightFields.GROUND_Z) is not None and not feature.issues and feature.geometry is not None:
            if lod==0 or record.get(strings.BuildingHeightFields.HEIGHT_M) is not None:
                geometry = extrusion(feature.geometry,record[strings.BuildingHeightFields.GROUND_Z],record.get(strings.BuildingHeightFields.HEIGHT_M),lod,vertex)
                if geometry[strings.CityJSONFields.TYPE]==strings.CityJSONGeometryType.MULTI_SOLID:
                    # CityJSON's Building/BuildingPart schema permits Solid,
                    # CompositeSolid or surfaces, not MultiSolid. Disconnected
                    # components are separate Solids with the same object/LoD.
                    obj[strings.CityJSONFields.GEOMETRY] = [{strings.CityJSONFields.TYPE:strings.CityJSONGeometryType.SOLID,strings.CityJSONFields.LOD:geometry[strings.CityJSONFields.LOD],strings.CityJSONFields.BOUNDARIES:solid,
                        strings.CityJSONFields.SEMANTICS:{strings.CityJSONFields.SURFACES:geometry[strings.CityJSONFields.SEMANTICS][strings.CityJSONFields.SURFACES],
                                     strings.CityJSONFields.VALUES:geometry[strings.CityJSONFields.SEMANTICS][strings.CityJSONFields.VALUES][i]}}
                        for i,solid in enumerate(geometry[strings.CityJSONFields.BOUNDARIES])]
                else:
                    obj[strings.CityJSONFields.GEOMETRY] = [geometry]
        regions=record.get(strings.BuildingHeightFields.ROOF_REGIONS)
        if lod==1 and regions and regions['accepted']:
            from shapely.geometry import shape
            obj[strings.CityJSONFields.GEOMETRY]=[]
            for region in regions['regions']:
                geometry=extrusion(shape(region['footprint']),record['ground_z'],region['roof_z']-record['ground_z'],1,vertex)
                if geometry['type']=='MultiSolid':
                    for i,solid in enumerate(geometry['boundaries']):
                        obj['geometry'].append({'type':'Solid','lod':'1','boundaries':solid,'semantics':{'surfaces':geometry['semantics']['surfaces'],'values':geometry['semantics']['values'][i]}})
                else:obj['geometry'].append(geometry)
        if config.show_unresolved_footprints and not obj['geometry'] and not feature.issues and feature.geometry is not None and record.get('status')=='unresolved':
            # A visible source-outline marker, never an invented solid/base.
            # Prefer own observed placement. The last display-only plane makes
            # a source identity spatially inspectable even with no Z evidence.
            display_z=record.get('ground_z')
            placement='sampled_or_inferred_ground'
            if display_z is None:
                display_z=record.get('roof_mode_z');placement='observed_roof_mode'
            if display_z is None:
                display_z=origin[2];placement='display_reference_only'
            marker=extrusion(feature.geometry,display_z,None,0,vertex)
            marker.pop('semantics',None)  # Unknown placement is not a GroundSurface assertion.
            obj['geometry']=[marker]
            attributes[strings.CityJSONReconstructionAttributes.REPRESENTATION]='unresolved_footprint'
            attributes[strings.CityJSONReconstructionAttributes.DISPLAY_REFERENCE_Z]=display_z
            attributes[strings.CityJSONReconstructionAttributes.DISPLAY_PLACEMENT]=placement
        objects[feature.key] = obj
    coords = [vertex.decode(i) for i in range(len(vertex.vertices))]
    extent = [min((v[i] for v in coords),default=0) for i in range(3)]+[max((v[i] for v in coords),default=0) for i in range(3)]
    return {strings.CityJSONFields.TYPE:strings.CityJSONFormat.FORMAT,strings.CityJSONFields.VERSION:strings.CityJSONFormat.VERSION,
            strings.CityJSONFields.TRANSFORM:{strings.CityJSONFields.SCALE:[config.precision_m]*3,strings.CityJSONFields.TRANSLATE:list(origin)},
            strings.CityJSONFields.METADATA:{strings.CityJSONFields.IDENTIFIER:config.dataset_id+f"-lod{lod}",strings.CityJSONFields.TITLE:f"{config.dataset_id} LoD{lod}",
                        strings.CityJSONFields.REFERENCE_SYSTEM:f"{strings.CityJSONFormat.CRS_EPSG_URI_PREFIX}{config.working_epsg}",strings.CityJSONFields.GEOGRAPHICAL_EXTENT:extent},
            strings.CityJSONFields.CITY_OBJECTS:objects,strings.CityJSONFields.VERTICES:vertex.vertices,
            "lodext":{strings.GeospatialInputFields.VERTICAL_REFERENCE:config.vertical_reference,strings.ModelElevationUnits.Z_UNIT:strings.ModelElevationUnits.UNIT_METRES,strings.TileConversionFields.CLAMPING_APPLIED:False,
                      strings.BuildConfigurationFields.HEIGHT_SOURCE:config.height_source,"input_contract":strings.InputContractVersion.BUILDING_CONTRACT_VERSION}}


def validate_cityjson(data):
    """Validate our output subset's structure, indices, relationships and shells.

    This is not a general CityJSON schema or geometric validity certification.
    External schema and geometric tests supplement it. Returns counted evidence.
    """
    from collections import Counter
    if data.get(strings.CityJSONFields.TYPE)!=strings.CityJSONFormat.FORMAT or data.get(strings.CityJSONFields.VERSION)!=strings.CityJSONFormat.VERSION:
        raise ValueError("Expected CityJSON 2.0")
    scale,translation = data[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.SCALE],data[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.TRANSLATE]
    if len(scale)!=3 or len(translation)!=3 or any(not math.isfinite(v) for v in scale+translation) or min(scale)<=0:
        raise ValueError("Invalid transform")
    vertices,objects = data[strings.CityJSONFields.VERTICES],data[strings.CityJSONFields.CITY_OBJECTS]
    if any(len(v)!=3 or any(type(n) is not int for n in v) for v in vertices):
        raise ValueError("Vertices must be integer triples")
    meshes = shells = faces = 0
    for identifier,obj in objects.items():
        for parent in obj.get("parents",[]):
            if parent not in objects or identifier not in objects[parent].get("children",[]):
                raise ValueError("Inconsistent parent/child relation")
        for child in obj.get("children",[]):
            if child not in objects or identifier not in objects[child].get("parents",[]):
                raise ValueError("Inconsistent child/parent relation")
        if obj[strings.CityJSONFields.TYPE]==strings.BuildingObjectType.BUILDING_PART and len(obj.get("parents",[]))!=1:
            raise ValueError("BuildingPart requires one parent")
        for geom in obj.get(strings.CityJSONFields.GEOMETRY,[]):
            meshes += 1
            if geom[strings.CityJSONFields.TYPE] in (strings.CityJSONGeometryType.MULTI_SURFACE, strings.CityJSONGeometryType.COMPOSITE_SURFACE):
                groups = [geom[strings.CityJSONFields.BOUNDARIES]]
                closed = False
            elif geom[strings.CityJSONFields.TYPE]==strings.CityJSONGeometryType.SOLID:
                groups,closed = geom[strings.CityJSONFields.BOUNDARIES],True
            elif geom[strings.CityJSONFields.TYPE]==strings.CityJSONGeometryType.MULTI_SOLID:
                groups,closed = [shell for solid in geom[strings.CityJSONFields.BOUNDARIES] for shell in solid],True
            else:
                raise ValueError("Unsupported geometry in local output validator")
            for group in groups:
                edges = Counter()
                for surface in group:
                    faces += 1
                    for ring in surface:
                        if len(ring)<3 or len(set(ring))!=len(ring) or any(type(v) is not int or not 0<=v<len(vertices) for v in ring):
                            raise ValueError("Invalid surface ring/index")
                        edges.update(zip(ring,ring[1:]+ring[:1]))
                if closed:
                    shells += 1
                    if any(n!=1 or edges[(b,a)]!=1 for (a,b),n in edges.items()):
                        raise ValueError("Shell is not a closed oriented two-manifold")
    return {strings.MeshValidationFields.OBJECT_COUNT:len(objects),strings.MeshValidationFields.GEOMETRY_COUNT:meshes,"closed_shells":shells,strings.MeshValidationFields.FACE_COUNT:faces,strings.CityJSONFields.VERTICES:len(vertices)}
