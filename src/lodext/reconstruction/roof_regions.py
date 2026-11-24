"""Partition one received footprint into supported internal roof regions."""
from collections import defaultdict
import numpy as np
from shapely import STRtree,points,voronoi_polygons,set_precision,box,area,intersection
from shapely.geometry import MultiPoint,mapping,shape
from shapely.ops import unary_union
from lodext.core.roof_regions import RoofRegion,RoofRegionsEvidence


def fit_roof_regions(geometry,support,cells,ground_z,original_roof_z,policy,*,precision_m,xy_origin):
    """Return an auditable XY partition from bounded cell/layer observations.

    cells maps metric (ix,iy) to Z-layer -> [count,sumZ], or None for a
    column explicitly rejected by the vertical-layer budget. Highest sufficiently
    sampled layers form a surface graph. Tiny disconnected components are
    rejected before nearest-cell interpolation; a local neighbour median sets
    each region's upper envelope without isolated maxima. Voronoi boundaries
    are simplified, clipped and subtracted in height order. A fallback remainder
    keeps the source footprint complete. No source IDs, Z or ground are changed.
    """
    c=policy;result=RoofRegionsEvidence(accepted=False,reason='insufficient_supported_regions',retained_cells=len(cells))
    tops={}
    for key,layers in cells.items():
        if layers is None:continue
        eligible=[(layer,total/count) for layer,(count,total) in layers.items() if count>=c.min_cell_points and total/count>ground_z+precision_m]
        if eligible:tops[key]=max(eligible)[1]
    remaining=set(tops);groups=[]
    neighbours=[(dx,dy) for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy]
    while remaining:
        seed=min(remaining);remaining.remove(seed);stack=[seed];group=[]
        while stack:
            key=stack.pop();group.append(key)
            for dx,dy in neighbours:
                other=(key[0]+dx,key[1]+dy)
                if other in remaining and abs(tops[other]-tops[key])<=c.neighbour_height_m:
                    remaining.remove(other);stack.append(other)
        if len(group)<c.min_region_cells or len(group)*c.cell_size_m**2<c.min_region_area_m2:continue
        members=set(group);local=[]
        for key in group:
            adjacent=[tops[(key[0]+dx,key[1]+dy)] for dx,dy in [(0,0),*neighbours] if (key[0]+dx,key[1]+dy) in members]
            if len(adjacent)>=3:local.append(float(np.median(adjacent)))
        if local:groups.append((sorted(group),max(local)))
    if len(groups)<2:return result
    if len(groups)>c.max_regions:result['reason']='too_many_regions';return result
    if max(z for _,z in groups)-min(z for _,z in groups)<c.min_level_separation_m:result['reason']='single_roof_level';return result
    if original_roof_z is None:
        # An unresolved single-roof approximation is not a missing building.
        # Use the most spatially supported observed region for any unsampled
        # remainder, recording this inference instead of a storey multiplier.
        original_roof_z=max(groups,key=lambda group:(len(group[0]),-group[1]))[1]
        result['remainder_reference_z']=float(original_roof_z)
    occupied_keys=np.asarray([key for group,_ in groups for key in group])
    corners=np.asarray(support.bounds[:2])+occupied_keys*c.cell_size_m
    occupied=box(corners[:,0],corners[:,1],corners[:,0]+c.cell_size_m,corners[:,1]+c.cell_size_m)
    coverage=min(1.,float(np.sum(area(intersection(occupied,support))))/support.area)
    result['support_coverage']=coverage
    if coverage<c.min_coverage:result['reason']='insufficient_spatial_coverage';return result
    # Local coordinates prevent loss of precision in Voronoi construction.
    from shapely.affinity import translate
    origin=np.asarray(xy_origin);site_offset=np.asarray(support.bounds[:2])-origin
    local_geometry=set_precision(translate(geometry,xoff=-origin[0],yoff=-origin[1]),precision_m)
    sites=[];labels=[]
    for i,(group,z) in enumerate(groups):
        for ix,iy in group:sites.append(tuple(site_offset+[(ix+.5)*c.cell_size_m,(iy+.5)*c.cell_size_m]));labels.append(i)
    sites=np.asarray(sites);site_tree=STRtree(points(sites[:,0],sites[:,1]))
    cells_geo=voronoi_polygons(MultiPoint(sites),extend_to=local_geometry.envelope)
    grouped=defaultdict(list)
    for polygon in cells_geo.geoms:
        # A Voronoi cell contains its generator. query_nearest avoids relying on
        # GEOS ordered-cell support or undefined collection iteration order.
        ix=int(site_tree.nearest(polygon.representative_point()));grouped[labels[ix]].append(polygon)
    remainder=local_geometry;regions=[]
    for i in sorted(grouped,key=lambda i:(-groups[i][1],i)):
        polygon=set_precision(unary_union(grouped[i]).simplify(c.simplify_m,preserve_topology=True),precision_m)
        # Limit extrapolation from each region's own accepted observations.
        seeds=MultiPoint([tuple(site_offset+[(ix+.5)*c.cell_size_m,(iy+.5)*c.cell_size_m]) for ix,iy in groups[i][0]])
        polygon=polygon.intersection(set_precision(seeds.buffer(c.max_extrapolation_m),precision_m)).intersection(remainder)
        if polygon.is_empty or polygon.area<c.min_region_area_m2:continue
        if polygon.geom_type not in ('Polygon','MultiPolygon'):
            polygon=unary_union([g for g in polygon.geoms if g.geom_type in ('Polygon','MultiPolygon')])
        if polygon.is_empty:continue
        remainder=remainder.difference(polygon)
        world=translate(polygon,xoff=origin[0],yoff=origin[1])
        regions.append(RoofRegion(footprint=mapping(world),roof_z=groups[i][1],support_cells=len(groups[i][0]),area_m2=world.area))
    if not remainder.is_empty:
        polygon=translate(remainder,xoff=origin[0],yoff=origin[1])
        if polygon.geom_type not in ('Polygon','MultiPolygon'):
            polygon=unary_union([g for g in polygon.geoms if g.geom_type in ('Polygon','MultiPolygon')])
        if not polygon.is_empty:regions.append(RoofRegion(footprint=mapping(polygon),roof_z=original_roof_z,support_cells=0,area_m2=polygon.area))
    # Node every boundary together once. Independent snap-rounded intersections
    # can otherwise create microscopic overlaps along diagonal shared edges.
    # A common planar graph assigns each atomic face to precisely one region.
    from shapely import union_all,polygonize
    local_source=set_precision(local_geometry,0)
    region_polys=[translate(shape(r['footprint']),xoff=-origin[0],yoff=-origin[1]) for r in regions]
    graph=union_all([local_source.boundary,*[p.boundary for p in region_polys]],grid_size=precision_m)
    faces=polygonize(list(graph.geoms) if hasattr(graph,'geoms') else [graph])
    assigned=defaultdict(list)
    for face in faces.geoms:
        point=face.representative_point()
        if not local_source.covers(point):continue
        owner=next((i for i,p in enumerate(region_polys) if p.covers(point)),None)
        if owner is None:
            owner=len(regions)
        assigned[owner].append(set_precision(face,0))
    cleaned=[]
    for i,polys in assigned.items():
        polygon=unary_union(polys)
        world=translate(polygon,xoff=origin[0],yoff=origin[1])
        roof=regions[i]['roof_z'] if i<len(regions) else original_roof_z
        count=regions[i]['support_cells'] if i<len(regions) else 0
        cleaned.append(RoofRegion(footprint=mapping(world),roof_z=roof,support_cells=count,area_m2=world.area))
    regions=cleaned
    if len(regions)>c.max_regions:result['reason']='too_many_regions';return result
    if len(regions)<2 or any(r['roof_z']<=ground_z for r in regions):result['reason']='invalid_region_height';return result
    polygons=[shape(r['footprint']) for r in regions];combined=unary_union(polygons)
    # Translation changes the grid origin; discard GEOS's origin-zero precision
    # tag before comparing world polygons. The integer export grid still uses
    # the explicitly supplied xy_origin, not the absolute global origin.
    quantized_source=set_precision(translate(local_geometry,xoff=origin[0],yoff=origin[1]),0)
    from shapely.validation import explain_validity
    result['partition_issues']=[explain_validity(p) for p in polygons if not p.is_valid]
    result['partition_error_m2']=combined.symmetric_difference(geometry).area
    result['partition_gap_m2']=combined.symmetric_difference(quantized_source).area
    if result['partition_issues'] or result['partition_error_m2']>geometry.length*precision_m*2+1e-6 or result['partition_gap_m2']>geometry.length*precision_m*2+1e-6:
        result['reason']='invalid_partition';return result
    if abs(sum(p.area for p in polygons)-combined.area)>max(1e-6,geometry.area*1e-9):result['reason']='overlapping_partition';return result
    result.update(accepted=True,reason='supported_internal_roof_levels',regions=regions)
    return result
