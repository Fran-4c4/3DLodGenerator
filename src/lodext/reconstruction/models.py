"""Construct LoD0 surfaces and watertight LoD1 extrusion shells."""
from lodext import strings
from collections import Counter
from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon,MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from ..core.geometric_policy import has_touching_rings


def _lod1_components(polygons):
    """Return manifold extrusion components without changing the footprint set.

    Ordinary Polygon/MultiPolygon components pass through unchanged. When valid
    2D rings touch at isolated points, one extrusion would share a vertical edge
    among more than two faces. Constrained triangles partition only that source
    component into closed solids. Their union is checked before and after output
    quantisation by :func:`extrusion`; no buffer, coordinate shift or Z operation
    repairs the received footprint.
    """
    source=list(polygons.geoms) if polygons.geom_type == strings.PolygonGeometryType.MULTI_POLYGON else [polygons]
    expanded=[];partitioned=set()
    for source_index,original in enumerate(source):
        if not has_touching_rings(original):
            expanded.append((original,source_index));continue
        pieces=list(constrained_delaunay_triangles(original).geoms)
        union=unary_union(pieces) if pieces else Polygon()
        tolerance=max(1e-12,original.area*1e-12)
        if (not pieces or any(piece.geom_type!='Polygon' or not piece.is_valid or piece.interiors for piece in pieces)
                or abs(sum(piece.area for piece in pieces)-original.area)>tolerance
                or original.symmetric_difference(union).area>tolerance):
            raise ValueError('Touching-ring footprint cannot be partitioned without changing XY')
        expanded.extend((piece,source_index) for piece in pieces);partitioned.add(source_index)
    return source,expanded,partitioned


def extrusion(polygons, base_z, height_m, lod, vertex):
    """Return one CityJSON geometry and validate quantized polygon topology.

    polygons preserves disconnected parts; base_z is sampled DTM, not zero.
    height_m is required positive for LoD1, unused for LoD0. vertex encodes a
    world point to a shared CityJSON index; decoded coordinates validate rings.
    Ground faces point down, roofs up, walls outward (including courtyard walls).
    No parent volume or geometric repair is constructed implicitly.
    """
    source_components = list(polygons.geoms) if polygons.geom_type == strings.PolygonGeometryType.MULTI_POLYGON else [polygons]
    if lod==0:
        expanded=[(component,index) for index,component in enumerate(source_components)];partitioned=set()
    else:
        source_components,expanded,partitioned=_lod1_components(polygons)
    surfaces = []
    solids = []
    semantic_values = []
    quantized_components = []
    component_sources = []
    for original,source_index in expanded:
        polygon = orient(original,sign=1)
        rings = [list(polygon.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in polygon.interiors]
        bottom = [[vertex((x,y,base_z)) for x,y in ring] for ring in rings]
        decoded = [[vertex.decode(i)[:2] for i in ring] for ring in bottom]
        quantized = Polygon(decoded[0],decoded[1:])
        if not quantized.is_valid or quantized.area<=0 or any(len(set(r))!=len(r) for r in bottom):
            raise ValueError("Quantization collapses/invalidates a footprint; reduce precision_m")
        quantized_components.append(quantized)
        component_sources.append(source_index)
        if lod==0:
            surfaces.append(bottom)
            continue
        top = [[vertex((x,y,base_z+height_m)) for x,y in ring] for ring in rings]
        if any(a==b for ring_a,ring_b in zip(bottom,top) for a,b in zip(ring_a,ring_b)):
            raise ValueError("Quantization collapses height; reduce precision_m")
        faces = [[list(reversed(r)) for r in bottom],top]
        labels = [0,1]
        for low,high in zip(bottom,top):
            for i in range(len(low)):
                j = (i+1)%len(low)
                faces.append([[low[i],low[j],high[j],high[i]]])
                labels.append(2)
        edges = Counter()
        for face in faces:
            for ring in face:
                edges.update(zip(ring,ring[1:]+ring[:1]))
        if any(edges[(b,a)]!=n or n!=1 for (a,b),n in edges.items()):
            raise ValueError("Extrusion shell has unpaired or non-manifold directed edges")
        solids.append([faces])
        semantic_values.append([labels])
    quantized_sources=[]
    for source_index,source in enumerate(source_components):
        pieces=[quantized_components[i] for i,index in enumerate(component_sources) if index==source_index]
        combined=unary_union(pieces)
        if source_index in partitioned:
            oriented=orient(source,sign=1)
            rings=[list(oriented.exterior.coords)[:-1]]+[list(r.coords)[:-1] for r in oriented.interiors]
            decoded=[[vertex.decode(vertex((x,y,base_z)))[:2] for x,y in ring] for ring in rings]
            quantized_source=Polygon(decoded[0],decoded[1:])
            tolerance=max(1e-12,quantized_source.area*1e-12)
            if (not quantized_source.is_valid
                    or abs(sum(piece.area for piece in pieces)-combined.area)>tolerance
                    or quantized_source.symmetric_difference(combined).area>tolerance):
                raise ValueError('Quantization changes a touching-ring footprint partition; reduce precision_m')
        quantized_sources.append(combined)
    if len(quantized_sources)>1:
        if not MultiPolygon(quantized_sources).is_valid or any(
            source_components[i].distance(source_components[j])>0 and quantized_sources[i].distance(quantized_sources[j])==0
            for i in range(len(source_components)) for j in range(i)):
            raise ValueError("Quantization merges disconnected components; reduce precision_m")
    if lod==0:
        return {strings.CityJSONFields.TYPE:strings.CityJSONGeometryType.MULTI_SURFACE,strings.CityJSONFields.LOD:strings.CityModelLoD.LOD0,strings.CityJSONFields.BOUNDARIES:surfaces,
                strings.CityJSONFields.SEMANTICS:{strings.CityJSONFields.SURFACES:[{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.GROUND}],strings.CityJSONFields.VALUES:[0]*len(surfaces)}}
    if len(solids)==1:
        return {strings.CityJSONFields.TYPE:strings.CityJSONGeometryType.SOLID,strings.CityJSONFields.LOD:strings.CityModelLoD.LOD1,strings.CityJSONFields.BOUNDARIES:solids[0],
                strings.CityJSONFields.SEMANTICS:{strings.CityJSONFields.SURFACES:[{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.GROUND},{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.ROOF},{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.WALL}],strings.CityJSONFields.VALUES:semantic_values[0]}}
    return {strings.CityJSONFields.TYPE:strings.CityJSONGeometryType.MULTI_SOLID,strings.CityJSONFields.LOD:strings.CityModelLoD.LOD1,strings.CityJSONFields.BOUNDARIES:solids,
            strings.CityJSONFields.SEMANTICS:{strings.CityJSONFields.SURFACES:[{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.GROUND},{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.ROOF},{strings.CityJSONFields.TYPE:strings.CityJSONSurfaceSemantic.WALL}],strings.CityJSONFields.VALUES:semantic_values}}
