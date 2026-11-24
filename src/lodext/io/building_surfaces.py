"""Joint geometric surface hypotheses for building parts and their neighbours."""
from pathlib import Path
from lodext import strings
from dataclasses import replace
import numpy as np
import laspy
from laspy.copc import Bounds
from pyproj import Transformer
from shapely import STRtree,points,union_all,buffer,distance
from shapely.geometry import box,Polygon
from shapely.ops import unary_union
from .sampling import lidar_files
from .roof_recovery_fit import fit_recovery_planes
from ..core.geometric_policy import (LOCAL_STOREY_FALLBACK_COMPACTNESS_MAX,LOCAL_STOREY_FOOTPRINT_MAX,
    NONCOMPACT_FOOTPRINT_MAX,footprint_compactness,has_touching_rings)
from ..core.geometric_policy import (BOUNDARY_SHARED_MIN_PERIMETER_FRACTION,
    REPEATED_FACADE_SHAPE_RATIO_MAX)


def _map_bounded(function,indices,workers):
    """Yield independent results in input order with at most workers live tasks.

    Source decoding and budget commits stay on the caller thread. Each batch
    bounds transient matrices; exceptions propagate instead of partial promotion.
    Frozen neighbouring evidence may be read concurrently but never recalibrated.
    """
    if workers==1:
        yield from map(function,indices);return
    from concurrent.futures import ThreadPoolExecutor
    from itertools import islice
    iterator=iter(indices)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while batch:=list(islice(iterator,workers)):
            yield from executor.map(function,batch)


def observed_spacing(xyz,minimum):
    """Median independent XY nearest-neighbour spacing; duplicate returns add no confidence."""
    xy=np.unique(xyz[:,:2],axis=0)
    if len(xy)<2:return minimum
    tree=STRtree(points(xy[:,0],xy[:,1]))
    _,distance=tree.query_nearest(points(xy[:,0],xy[:,1]),exclusive=True,return_distance=True)
    good=distance[np.isfinite(distance)&(distance>0)]
    return max(minimum,float(np.median(good))) if len(good) else minimum


def retain_vertical_extremes(layers,band,value,limit):
    """Retain bounded low/high Z evidence in one XY cell deterministically.

    ``layers`` maps integer Z bands to their nearest original observation.
    Existing bands keep the lexicographically smallest representative. A new
    band beyond ``limit`` replaces an interior band only when it belongs to the
    lowest ceil(limit/2) or highest floor(limit/2) observed bands. The result is
    therefore independent of source/chunk order without storing every level.
    Return the change in retained-layer count (zero or one).
    """
    if band in layers:
        if value<layers[band]:layers[band]=value
        return 0
    if len(layers)<limit:
        layers[band]=value
        return 1
    candidates=sorted((*layers,band));lower=(limit+1)//2;upper=limit-lower
    retained=set(candidates[:lower])
    if upper:retained.update(candidates[-upper:])
    if band not in retained:return 0
    layers[band]=value
    for key in tuple(layers):
        if key not in retained:del layers[key]
    return 0


def fit_building_planes(xyz,policy):
    """Extract each next hypothesis relative to remaining observations.

    A rooftop room may occupy almost the whole crop. After removing its plane,
    exposed lower-roof evidence must not meet a fraction of the original room's
    point count. The owning policy still limits trials and total plane count.
    """
    remaining=xyz;planes=[];single=replace(policy,max_planes=1)
    for _ in range(policy.max_planes):
        if len(remaining)<policy.min_plane_points:break
        fitted=fit_recovery_planes(remaining,single)['planes']
        if not fitted:break
        plane=fitted[0];planes.append(plane)
        a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin']
        mask=np.abs(a*(remaining[:,0]-ox)+b*(remaining[:,1]-oy)+d-remaining[:,2])<=policy.residual_m
        remaining=remaining[~mask]
    return planes


def connected_observations(xyz,geometry,spacing):
    """Keep coherent significant patches in each source polygon component.

    Connectivity uses observed spacing, independently of registration tolerance.
    This prevents a wide uncertainty buffer from joining scattered canopy points
    or filling the gaps between beams. Original XYZ and footprint stay unchanged.
    """
    if len(xyz)<3:return xyz
    point_geometries=points(xyz[:,0],xyz[:,1])
    patches=union_all(buffer(point_geometries,spacing,quad_segs=2))
    pieces=list(patches.geoms) if hasattr(patches,'geoms') else [patches]
    domains=list(geometry.geoms) if hasattr(geometry,'geoms') else [geometry]
    piece_tree=STRtree(pieces);pairs=piece_tree.query(point_geometries,predicate='intersects')
    counts=np.bincount(pairs[1],minlength=len(pieces)) if pairs.shape[1] else np.zeros(len(pieces),dtype=int)
    selected=set()
    for domain in domains:
        candidates=[int(i) for i in piece_tree.query(domain,predicate='intersects') if counts[int(i)]>0]
        if not candidates:continue
        compactness=footprint_compactness(domain)
        if compactness>NONCOMPACT_FOOTPRINT_MAX:
            selected.add(max(candidates,key=lambda i:(counts[i],-i)))
        else:
            threshold=max(1,int(np.ceil(np.sqrt(max(counts[i] for i in candidates)))))
            selected.update(i for i in candidates if counts[i]>=threshold)
    if not selected:return np.empty((0,3),dtype=float)
    selected=np.fromiter(sorted(selected),dtype=int);keep=np.isin(pairs[1],selected)
    return xyz[np.unique(pairs[0,keep])]


def supported_patch(xyz,geometry,spacing,policy):
    """Test support against observable interior, not all competing Z layers.

    Small bodies lose an uncertainty-width edge in the evidence test only.
    Disks preserve gaps between beams; a convex hull would invent coverage.
    Source footprints and output volumes are never eroded or translated.
    """
    radius=policy.registration_m+spacing
    patch=union_all(buffer(points(xyz[:,0],xyz[:,1]),radius,quad_segs=2)).intersection(geometry)
    interior=geometry.buffer(-radius)
    coverage=patch.area/geometry.area if geometry.area else 0.
    # A tiny body still requires noncollinear observed support; the caller's
    # fitted-plane rank/count checks establish that mathematical minimum.
    if interior.is_empty:
        rectangle=np.asarray(geometry.minimum_rotated_rectangle.exterior.coords)[:4]
        edges=np.array([rectangle[1]-rectangle[0],rectangle[2]-rectangle[1]])
        lengths=np.linalg.norm(edges,axis=1);axes=edges/lengths[:,None]
        span=np.ptp(xyz[:,:2]@axes.T,axis=0)
        # Even a narrow body needs observed extent along its long direction.
        # Numerical slack is far below the source/export precision.
        supported=not patch.is_empty and bool(np.all(span+2*radius>=lengths-1e-8))
    else:
        supported=not patch.is_empty and interior.difference(patch).buffer(-spacing).is_empty
        if not supported and len(xyz)>=policy.min_plane_points and _interior_controls(xyz,geometry,spacing,policy):
            # A large concave/multi-wing footprint can contain real unsampled
            # gaps while observations still span the complete body. Require
            # support across both oriented extents and enough independent
            # controls for the observed perimeter at this data resolution.
            rectangle=np.asarray(geometry.minimum_rotated_rectangle.exterior.coords)[:4]
            edges=np.array([rectangle[1]-rectangle[0],rectangle[2]-rectangle[1]])
            lengths=np.linalg.norm(edges,axis=1);axes=edges/lengths[:,None]
            span=np.ptp(xyz[:,:2]@axes.T,axis=0)
            perimeter_controls=int(np.ceil(geometry.length/max(2*radius,spacing)))
            distributed_fraction=max(.25,min(.5,4*radius/max(lengths)))
            supported=bool(coverage>=distributed_fraction and np.all(span+2*radius>=lengths-1e-8)
                           and len(xyz)>=max(policy.min_plane_points,perimeter_controls))
    return supported,coverage,patch


def local_hypotheses(f,xyz,sample,config,*,primary=None):
    """Fit a completed object's observations once, before neighbour attribution.

    All source tiles intersecting the footprint must have been consumed. Return
    frozen plane masks and independent spacing; source XYZ/order is unchanged.
    """
    c=config.building_surfaces
    # Vertical layers can place several representatives close together inside
    # one XY cell. Their nearest-neighbour distance must not hide the coarser
    # adaptive grid that separates independently sampled columns on large roofs.
    width=np.maximum((np.array(f.geometry.bounds[2:])-np.array(f.geometry.bounds[:2]))/c.grid_axis,c.min_cell_size_m)
    spacing=observed_spacing(xyz,float(np.max(width))) if len(xyz) else float(np.max(width))
    # Missing observations cannot inflate support beyond configured grid scale.
    spacing=min(spacing,float(np.linalg.norm(width)))
    ground=sample['ground_z']
    if not sample.get('coverage_complete',False):return [],spacing
    fit=[]
    if len(xyz)>=c.min_plane_points and ground is not None:
        source=primary if primary is not None and len(primary)>=c.min_plane_points else xyz
        fit=fit_building_planes(source,c)
        if primary is not None and len(fit)<c.max_planes:
            explained=np.zeros(len(xyz),dtype=bool)
            for plane in fit:
                a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin']
                explained|=np.abs(a*(xyz[:,0]-ox)+b*(xyz[:,1]-oy)+d-xyz[:,2])<=c.residual_m
            remaining=xyz[~explained]
            if len(remaining)>=c.min_plane_points:
                fit.extend(fit_building_planes(remaining,replace(c,max_planes=c.max_planes-len(fit))))
    planes=[]
    for p in fit:
        a,b,d=p['local_coefficients'];ox,oy=p['xy_origin']
        mask=np.abs(a*(xyz[:,0]-ox)+b*(xyz[:,1]-oy)+d-xyz[:,2])<=c.residual_m
        if p['fitted_upper_z']>ground+config.height.near_zero_m:
            patch=connected_observations(xyz[mask],f.geometry,spacing)
            keys={tuple(v) for v in patch}
            coherent=np.array([tuple(v) in keys for v in xyz])&mask
            if coherent.sum()>=c.min_plane_points:
                p=dict(p);p['raw_plane_inliers']=p['cells'];p['cells']=int(coherent.sum());p['observed_z_range']=[float(xyz[coherent,2].min()),float(xyz[coherent,2].max())]
                p['fitted_upper_z']=float((p['local_coefficients'][0]*(xyz[coherent,0]-p['xy_origin'][0])+p['local_coefficients'][1]*(xyz[coherent,1]-p['xy_origin'][1])+p['local_coefficients'][2]).max())
                if p["fitted_upper_z"]>ground+config.height.near_zero_m:planes.append((p,coherent))
    return planes,spacing


def _plane_values(plane,xy):
    """Evaluate a metric local plane without changing source observations."""
    a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin']
    return a*(xy[:,0]-ox)+b*(xy[:,1]-oy)+d


def _exclude_enclosed_sibling_boundary_facets(group,enclosed_roofs,tolerance):
    """Remove secondary facets that terminate at an enclosed higher sibling.

    The most-observed facet anchors the enclosing part. A less-supported facet
    may remain part of the roof below ``tolerance``; one rising beyond that
    anchor and ending at an independently fitted enclosed sibling is an
    ownership boundary. The source footprint and the retained observations are
    unchanged.
    """
    if not enclosed_roofs or len(group)<2:return group,[]
    anchor=max(group,key=lambda piece:int(piece[0].get('raw_plane_inliers',piece[0]['cells'])))
    anchor_top=anchor[0]['fitted_upper_z'];retained=[];rejected=[]
    for piece in group:
        top=piece[0]['fitted_upper_z']
        owners=sorted({key for sibling_top,key in enclosed_roofs if abs(top-sibling_top)<=tolerance})
        if top>anchor_top+tolerance and owners:
            rejected.append({'roof_z':top,'reason':strings.BuildingSurfaceRejectionReason.HIGHER_SIBLING_BOUNDARY_SURFACE,'neighbour_ids':owners})
        else:retained.append(piece)
    return retained or group,rejected


def _spatial_cell_upper_median_z(xyz,geometry,spacing):
    """Return one area-oriented LoD1 elevation from owned structural cells.

    Points are indexed on a deterministic square grid anchored at the source
    footprint bounds. Each occupied XY cell contributes its upper attributed
    structural Z, so lower wall/ground layers cannot lower that roof cell and
    denser returns cannot add statistical weight. The median across cells is
    the flat representative elevation; it is not the global maximum, a
    percentile of raw returns, or regional storey calibration.
    """
    if not len(xyz):raise ValueError('Owned roof observations are required')
    origin=np.asarray(geometry.bounds[:2],dtype=float)
    keys=np.floor((xyz[:,:2]-origin)/spacing+1e-12).astype(np.int64)
    order=np.lexsort((keys[:,1],keys[:,0]));keys=keys[order];z=xyz[order,2]
    starts=np.r_[0,np.flatnonzero(np.any(keys[1:]!=keys[:-1],axis=1))+1]
    ends=np.r_[starts[1:],len(z)]
    cell_z=np.asarray([np.max(z[start:end]) for start,end in zip(starts,ends)],dtype=float)
    return float(np.median(cell_z)),int(len(cell_z))


def _interior_controls(xyz,geometry,spacing,policy):
    """Require three noncollinear actual controls beyond the uncertain perimeter."""
    from shapely import intersects_xy
    core=geometry.buffer(-(spacing+policy.registration_m))
    if core.is_empty:return False
    selected=xyz[intersects_xy(core,xyz[:,0],xyz[:,1])]
    if len(selected)<3:return False
    xy=selected[:,:2]-selected[:,:2].mean(axis=0)
    return bool(np.linalg.matrix_rank(np.column_stack((xy,np.ones(len(xy)))))==3)


def _inward_context(all_xyz,geometry):
    """Build reusable boundary-depth evidence for all candidate controls."""
    all_xy=np.unique(all_xyz[:,:2],axis=0)
    if not len(all_xy) or geometry.is_empty:return None
    point_shapes=points(all_xy[:,0],all_xy[:,1])
    depths=np.asarray(distance(point_shapes,geometry.boundary),dtype=float)
    return all_xy,depths,STRtree(point_shapes)


def _inward_seed_evidence(xyz,context,spacing,policy):
    """Trace a candidate level from local interior seeds toward the boundary.

    Each unique candidate XY control compares its boundary depth with all
    competing-level controls in a local horizontal neighbourhood. The radius is
    derived from observed spacing plus registration uncertainty, not a fixed
    erosion distance. A control is an inward seed when no nearby competitor is
    deeper inside the active footprint. Several local maxima are allowed, so a
    concave body, separate wing or central rooftop room need not share one
    geometric centre. The result alone never rejects a surface: attribution
    also requires compatible continuation through an independently supported
    adjacent footprint.
    """
    candidate_xy=np.unique(xyz[:,:2],axis=0)
    if not len(candidate_xy) or context is None:return False,0.,0
    all_xy,all_depth,tree=context
    # Recover exact source-footprint depths for candidate XY already present in
    # the complete context; a point hull would change the ownership boundary.
    keys={tuple(value):index for index,value in enumerate(all_xy)}
    candidate_depth=np.asarray([all_depth[keys[tuple(value)]] for value in candidate_xy],dtype=float)
    neighbourhood=2*spacing+policy.registration_m
    pairs=tree.query(points(candidate_xy[:,0],candidate_xy[:,1]),predicate='dwithin',distance=neighbourhood)
    nearby_max=np.full(len(candidate_xy),-np.inf,dtype=float)
    if pairs.size:np.maximum.at(nearby_max,pairs[0],all_depth[pairs[1]])
    deeper=nearby_max>candidate_depth+1e-8
    return bool((~deeper).any()),float(candidate_depth.max()),int(deeper.sum())


def _has_reconstructable_interior_alternative(choices,ground,near_zero_m):
    """Return whether a non-edge candidate can still create positive volume."""
    if ground is None:return False
    return any(choice['valid'] and not choice['edge_contamination']
               and float(np.median(choice['xyz'][:,2]))>ground+near_zero_m
               for choice in choices)


def _observed_exterior_continuity(controls,other_geometry,other_planes,
                                  spacing,other_spacing,policy,height_policy):
    """Confirm a compatible observed level immediately across one boundary.

    Similar plane tops elsewhere in a neighbour are insufficient. This check
    requires original controls on both sides of the footprint boundary, within
    the spacing/registration uncertainty and the existing roof-Z tolerance.
    At least ``min_plane_points`` unique controls on each side must participate;
    sparse coincidence remains ambiguous and cannot remove a target level.
    """
    from shapely import intersects_xy
    radius=spacing+other_spacing+policy.registration_m
    inside=controls[intersects_xy(other_geometry.buffer(radius),controls[:,0],controls[:,1])]
    if len(inside)<policy.min_plane_points:return False
    for outside,tree in other_planes:
        pairs=tree.query(points(inside[:,0],inside[:,1]),predicate='dwithin',distance=radius)
        if not pairs.size:continue
        compatible=np.abs(inside[pairs[0],2]-outside[pairs[1],2])<=height_policy.inferred_roof_tolerance_m
        if (len(np.unique(pairs[0,compatible]))>=policy.min_plane_points
                and len(np.unique(pairs[1,compatible]))>=policy.min_plane_points):return True
    return False


def complementary_plane_groups(pieces,spacing,config):
    """Connect facets at geometrically continuous seams; steps remain separate.

    An effectively flat enclosing upper rim cannot establish a main roof.
    Inclination is significant when observed fitted variation exceeds twice
    the residual tolerance, rather than a fixed angle. Regular sampling holes
    in inclined facets must not be mistaken for an enclosing parapet.
    """
    from shapely.geometry import Polygon
    from shapely import intersects_xy
    patches=[unary_union(points(xyz[:,0],xyz[:,1]).tolist()).buffer(spacing) for _,xyz in pieces]
    retained=[]
    for i,(plane,xyz) in enumerate(pieces):
        enclosing=False
        if np.ptp(_plane_values(plane,xyz[:,:2]))<=2*config.residual_m:
            patch=patches[i];components=list(patch.geoms) if patch.geom_type=='MultiPolygon' else [patch]
            holes=[Polygon(ring) for component in components for ring in component.interiors]
            for j,(_,observations) in enumerate(pieces):
                if i==j:continue
                lower=_plane_values(plane,observations[:,:2])-observations[:,2]>2*config.residual_m
                if lower.any() and any(intersects_xy(hole,observations[lower,0],observations[lower,1]).any() for hole in holes):enclosing=True;break
        if not enclosing:retained.append(i)
    parent={i:i for i in retained}
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for n,i in enumerate(retained):
        p,xyz=pieces[i]
        for j in retained[:n]:
            q,other=pieces[j]
            pair,distance=STRtree(points(other[:,0],other[:,1])).query_nearest(points(xyz[:,0],xyz[:,1]),all_matches=False,return_distance=True)
            k=int(np.argmin(distance))
            if distance[k]>2*(spacing+config.registration_m):continue
            seam=((xyz[int(pair[0,k]),:2]+other[int(pair[1,k]),:2])/2).reshape(1,2)
            if abs(_plane_values(p,seam)[0]-_plane_values(q,seam)[0])<=2*config.residual_m:parent[find(i)]=find(j)
    groups={}
    for i in retained:groups.setdefault(find(i),[]).append(i)
    return [[pieces[i] for i in group] for group in groups.values()]


def _unique_observations(pieces):
    """One original XYZ observation casts one vote even at a facet seam."""
    return np.unique(np.vstack([xyz for _,xyz in pieces]),axis=0)


def _local_storey_reference(target_index,neighbours,units,samples,reliable,config):
    """Choose one physically adjacent multistorey reference for a target.

    The closest declared storey count is the relevant local building body.
    A one-storey ground-floor or rooftop body is not extrapolated to a
    multistorey target. Equally close references must predict compatible target
    tops; their strongest shared boundary then breaks the remaining tie.
    """
    target=units[target_index];floors=target.properties.get('storeys_above')
    if not floors or floors<=1 or samples[target.key]['ground_z'] is None:return None
    candidates=[]
    for j in neighbours:
        other=units[j];ofloors=other.properties.get('storeys_above')
        shared=target.geometry.boundary.intersection(other.geometry.boundary).length
        ground=samples[other.key]['ground_z']
        if other.parent_id!=target.parent_id or not ofloors or shared<=0 or ground is None or not reliable[j]:continue
        plane=max(reliable[j],key=lambda item:item['cells'])
        floor=(sum(plane['observed_z_range'])/2-ground)/ofloors
        if config.height.min_floor_height_m<=floor<=config.height.max_floor_height_m:
            candidates.append((plane['cells'],floor,ofloors,other.key,j,shared))
    if floors>1:
        candidates=[item for item in candidates if item[2]>1]
    if not candidates:return None
    distance=min(abs(item[2]-floors) for item in candidates)
    closest=[item for item in candidates if abs(item[2]-floors)==distance]
    middle=float(np.median([item[1] for item in closest]))
    if any(abs(item[1]-middle)*floors>config.height.inferred_roof_tolerance_m for item in closest):
        return None
    return max(closest,key=lambda item:(item[5],item[0],units[item[4]].geometry.area,-item[4]))


def _adjacent_dominant_roofs(target_index,neighbours,units,samples,reliable):
    """Return dominant measured roofs across positive same-parent boundaries.

    Each item retains absolute metre Z, independent-cell support, declared
    storeys, ground and shared-boundary length. A fitted plane is contextual
    evidence only; this helper does not assign it to either footprint.
    """
    target=units[target_index];result=[]
    for j in neighbours:
        other=units[j]
        shared=target.geometry.boundary.intersection(other.geometry.boundary).length
        floors=other.properties.get('storeys_above');ground=samples[other.key]['ground_z']
        if (other.parent_id!=target.parent_id or shared<=0 or not floors
                or ground is None or not reliable[j]):
            continue
        plane=max(reliable[j],key=lambda item:item['cells'])
        result.append({'index':j,'id':other.key,
            'roof_z':float(np.median(plane['observed_z_range'])),
            'cells':plane['cells'],'storeys':floors,'ground_z':ground,
            'shared_m':shared})
    return result


def _boundary_shared_roof(target_index,planes,cloud,adjacent_roofs,parent_indices,
                          reliable,spacings,spacing,units,samples,config):
    """Find an observed absolute cap for an inconsistent subdivision.

    The target must disappear when eroded by local spacing plus registration.
    One adjacent roof is sufficient only when a target plane matches it tightly
    and no target plane supports a difference of at most two declared storeys.
    With no target plane, two neighbours with compatible absolute roofs must be
    exactly one storey below and above the target. The result never supplies a
    floor-height calibration.
    """
    target=units[target_index];floors=target.properties.get('storeys_above')
    ground=samples[target.key]['ground_z'];c=config.building_surfaces
    radius=spacing+c.registration_m
    if (not floors or ground is None or not target.geometry.buffer(-radius).is_empty
            or not adjacent_roofs):
        return None
    target_levels=[(plane,mask,float(np.median(cloud[mask,2]))) for plane,mask in planes]
    def repeated_family(roof_z):
        """Return same-storey sub-resolution peers with matching shape and Z."""
        peers=[]
        for j in parent_indices:
            if j==target_index or not reliable[j]:continue
            other=units[j]
            if other.properties.get('storeys_above')!=floors:continue
            other_spacing=spacings[j]
            if not other.geometry.buffer(-(other_spacing+c.registration_m)).is_empty:continue
            area_ratio=max(target.geometry.area,other.geometry.area)/min(target.geometry.area,other.geometry.area)
            perimeter_ratio=max(target.geometry.length,other.geometry.length)/min(target.geometry.length,other.geometry.length)
            if (area_ratio>REPEATED_FACADE_SHAPE_RATIO_MAX
                    or perimeter_ratio>REPEATED_FACADE_SHAPE_RATIO_MAX):continue
            dominant=max(reliable[j],key=lambda item:item['cells'])
            other_z=float(np.median(dominant['observed_z_range']))
            if abs(other_z-roof_z)<=2*c.residual_m:
                peers.append((dominant['cells'],other.key))
        return sorted(peers,key=lambda item:(-item[0],item[1]))

    matched=[]
    for plane,mask,target_z in target_levels:
        if target_z<=ground+config.height.near_zero_m:continue
        for neighbour in adjacent_roofs:
            if (neighbour['storeys']==floors
                    or abs(neighbour['storeys']-floors)>2):continue
            if abs(target_z-neighbour['roof_z'])>2*c.residual_m:continue
            floor=(neighbour['roof_z']-neighbour['ground_z'])/neighbour['storeys']
            if not config.height.min_floor_height_m<=floor<=config.height.max_floor_height_m:continue
            expected=ground+floors*floor
            if any(abs(level-expected)<=config.height.inferred_roof_tolerance_m
                   for _,_,level in target_levels):
                continue
            facade_attachment=(neighbour['shared_m']>=
                                   BOUNDARY_SHARED_MIN_PERIMETER_FRACTION*target.geometry.length
                               and units[neighbour['index']].geometry.area>target.geometry.area)
            family=repeated_family(target_z)
            # A larger/higher body surrounding a lower-storey part is the
            # ordinary rooftop-room relation, not proof that the lower part
            # reaches the body's roof. Only a repeated same-storey facade
            # family can demonstrate that this cadastral split is inverted.
            if (neighbour['storeys']>floors
                    and (len(family)<2
                         or not any(level>target_z+2*c.residual_m
                                    for _,_,level in target_levels))):continue
            if not facade_attachment and len(family)<2:continue
            matched.append((neighbour['cells'],neighbour['shared_m'],plane['cells'],target_z,neighbour,family))
    if matched:
        *_,target_z,_,family=max(matched,key=lambda item:item[:3])
        supporters=sorted((item[-2] for item in matched
                           if abs(item[3]-target_z)<=2*c.residual_m),
                          key=lambda item:(-item['cells'],-item['shared_m'],item['id']))
        ids=[item['id'] for item in supporters]
        ids.extend(part_id for _,part_id in family if part_id not in ids)
        return target_z,ids
    if target_levels or len(adjacent_roofs)<2:return None
    pairs=[]
    for n,left in enumerate(adjacent_roofs):
        for right in adjacent_roofs[n+1:]:
            if (abs(left['storeys']-right['storeys'])!=2
                    or left['storeys']+right['storeys']!=2*floors):continue
            if abs(left['roof_z']-right['roof_z'])>config.height.inferred_roof_tolerance_m:continue
            if max(abs(left['ground_z']-ground),abs(right['ground_z']-ground))>config.height.inferred_roof_tolerance_m:continue
            if (left['shared_m']+right['shared_m']<
                    BOUNDARY_SHARED_MIN_PERIMETER_FRACTION*target.geometry.length):continue
            pairs.append((left['cells']+right['cells'],left['shared_m']+right['shared_m'],
                          float(np.median([left['roof_z'],right['roof_z']])),left,right))
    if not pairs:return None
    _,_,roof_z,left,right=max(pairs,key=lambda item:item[:2])
    supporters=sorted((left,right),key=lambda item:(-item['cells'],-item['shared_m'],item['id']))
    return roof_z,[item['id'] for item in supporters]


def attribute_surfaces(units,clouds,samples,config,*,prepared=None):
    """Fit all hypotheses first, then attribute competing surfaces using frozen neighbours.

    Larger well-observed bodies establish context but never scale another part's
    height. Smaller elevated overlapping bodies mask exposed roof area only;
    they do not remove the main volume. All neighbours participate, not just
    same-parent siblings. Unresolved ownership remains explicit.
    """
    c=config.building_surfaces;geometries=[f.geometry for f in units];tree=STRtree(geometries)
    parent_indices={}
    for index,unit in enumerate(units):parent_indices.setdefault(unit.parent_id,[]).append(index)
    if prepared is None:
        local=[local_hypotheses(f,xyz,samples[f.key],config) for f,xyz in zip(units,clouds)]
        hypotheses=[p for p,_ in local];spacings=[d for _,d in local];counts=[len(xyz) for xyz in clouds]
    else:
        hypotheses,spacings,counts=prepared
    # Freeze reliable local surfaces before cross-object ownership decisions.
    def reliable_for(i):
        f,xyz,planes,spacing=units[i],clouds[i],hypotheses[i],spacings[i]
        pieces=[(p,xyz[m]) for p,m in planes];valid=[]
        for group in complementary_plane_groups(pieces,spacing,c):
            if supported_patch(_unique_observations(group),f.geometry,spacing,c)[0]:valid.extend(p for p,_ in group)
        return valid
    reliable=list(_map_bounded(reliable_for,range(len(units)),c.workers))
    def attribute(i):
        f,xyz,planes=units[i],clouds[i],hypotheses[i];s=samples[f.key];spacing=spacings[i];ground=s['ground_z']
        s['sample_area_m2']=f.geometry.area;s['erosion']='not_applied_geometry_attribution'
        raw_neighbours=[int(k) for k in tree.query(f.geometry.buffer(c.registration_m),predicate='intersects') if int(k)!=i]
        floors=f.properties.get('storeys_above');sibling_refs=[];enclosed_higher_roofs=[]
        uncertainty_radius=spacing+c.registration_m
        boundary_dominated_shape=(footprint_compactness(f.geometry)<=LOCAL_STOREY_FOOTPRINT_MAX
                                  and f.geometry.buffer(-uncertainty_radius).is_empty)
        local_storey_fallback_shape=(footprint_compactness(f.geometry)<=LOCAL_STOREY_FALLBACK_COMPACTNESS_MAX
                                     and f.geometry.buffer(-uncertainty_radius).is_empty)
        # A polygon whose interior rings touch is reconstructed through an
        # exact LoD1 partition, but it is not an ordinary overlapping roof
        # neighbour. Let it provide context only to a boundary-dominated part
        # that physically shares a positive-length boundary. This preserves
        # the local facade/roof relationship without allowing the partitioned
        # main body to claim points or recalibrate unrelated interior parts.
        neighbours=[j for j in raw_neighbours
            if not has_touching_rings(units[j].geometry)
            or (boundary_dominated_shape and
                f.geometry.boundary.intersection(units[j].geometry.boundary).length>0 and
                (floors or 0)>0 and
                (units[j].properties.get('storeys_above') or 0)>0 and
                abs(floors-units[j].properties['storeys_above'])<=1)]
        same_parent_neighbours=[j for j in neighbours if units[j].parent_id==f.parent_id]
        local_storey_ref=_local_storey_reference(i,same_parent_neighbours,units,samples,reliable,config)
        adjacent_dominant_roofs=_adjacent_dominant_roofs(
            i,same_parent_neighbours,units,samples,reliable)
        boundary_shared_roof=_boundary_shared_roof(
            i,planes,xyz,adjacent_dominant_roofs,parent_indices.get(f.parent_id,()),
            reliable,spacings,spacing,units,samples,config)
        physical_storey_neighbours=sorted(units[j].key for j in same_parent_neighbours
            if f.geometry.boundary.intersection(units[j].geometry.boundary).length>0
            and (floors or 0)>0 and (units[j].properties.get('storeys_above') or 0)>0)
        polygons=list(f.geometry.geoms) if hasattr(f.geometry,'geoms') else [f.geometry]
        holes=unary_union([Polygon(ring) for polygon in polygons for ring in polygon.interiors])
        if floors and ground is not None:
            for j in neighbours:
                other=units[j];ofloors=other.properties.get('storeys_above');og=samples[other.key]['ground_z']
                if other.parent_id!=f.parent_id or not ofloors or ofloors<=floors or og is None or not reliable[j]:continue
                op=max(reliable[j],key=lambda plane:plane['cells'])
                if not holes.is_empty and holes.buffer(c.registration_m).covers(other.geometry):
                    enclosed_higher_roofs.extend((p['fitted_upper_z'],other.key) for p in reliable[j])
                unit=(sum(op['observed_z_range'])/2-og)/ofloors
                if config.height.min_floor_height_m<=unit<=config.height.max_floor_height_m:
                    sibling_refs.append((op['cells'],unit,ofloors,other.key,j))
        # Relative storeys constrain ownership only with one unambiguous local
        # higher sibling. Complex blocks can expose several legitimate levels;
        # choosing one of those references would recalibrate unrelated parts.
        sibling_ref=sibling_refs[0] if len(sibling_refs)==1 else None
        enclosed_alignment_ref=(sibling_ref if sibling_ref and
            f.geometry.convex_hull.buffer(c.registration_m).covers(units[sibling_ref[4]].geometry)
            else None)
        local_alignment_ref=(local_storey_ref if local_storey_ref and
            floors==local_storey_ref[2]+1 else None)
        alignment_ref=local_alignment_ref or enclosed_alignment_ref
        local_alignment_active=local_alignment_ref is not None
        conflict_ref=sibling_ref if sibling_ref and len(same_parent_neighbours)==1 else None
        available=[];rejected=[];details=[];expected=f.geometry
        for j in neighbours:
            other=units[j]
            if other.geometry.area<f.geometry.area and any(p['fitted_upper_z']>min((p['fitted_upper_z'] for p,_ in planes),default=float('inf'))+c.residual_m for p in reliable[j]):
                if other.geometry.intersection(f.geometry).area>0:expected=expected.difference(other.geometry)
        for plane,mask in planes:
            candidate=xyz[mask];claimed=np.zeros(len(candidate),dtype=bool);claiming=set()
            for j in neighbours:
                other=units[j];floors=f.properties.get('storeys_above');ofloors=other.properties.get('storeys_above')
                competing=(other.geometry.area<f.geometry.area and other.geometry.intersection(f.geometry).area>0) or (floors and ofloors and ofloors>floors)
                if not competing:continue
                from shapely import intersects_xy
                for op in reliable[j]:
                    match=np.abs(_plane_values(op,candidate[:,:2])-candidate[:,2])<=c.residual_m
                    take=match&intersects_xy(other.geometry.buffer(c.registration_m),candidate[:,0],candidate[:,1])
                    if take.any():claiming.add(other.key)
                    claimed|=take
            left=candidate[~claimed]
            if not expected.equals(f.geometry):
                # A nested/smaller part owns the observations inside its source
                # footprint.  The enclosing part may continue underneath it,
                # but only its exposed XY area can establish that lower roof.
                # Discard the shared area instead of joining a facade or upper
                # roof into the enclosing part's surface envelope.
                from shapely import intersects_xy
                exposed=intersects_xy(expected,left[:,0],left[:,1])
                left=left[exposed]
            if len(left)<c.min_plane_points:
                rejected.append({'roof_z':plane['fitted_upper_z'],'reason':'explained_by_adjacent_structure','neighbour_ids':sorted(claiming)});continue
            available.append((plane,left))
        groups=complementary_plane_groups(available,spacing,c)
        unaligned_dominant_z=(max(p['fitted_upper_z'] for p,_ in
            max(groups,key=lambda candidate:len(_unique_observations(candidate))))
            if groups else None)
        all_candidate_controls=_unique_observations(available) if available else np.empty((0,3),dtype=float)
        inward_context=_inward_context(all_candidate_controls,expected)
        continuity_cache={}
        all_patches=[supported_patch(q,expected,spacing,c)[2] for _,q in available] if not expected.is_empty else []
        union=unary_union(all_patches);choices=[]
        for group_index,group in enumerate(groups):
            storey_aligned=False
            local_alignment_match=False
            group,boundary_rejections=_exclude_enclosed_sibling_boundary_facets(
                group,enclosed_higher_roofs,config.height.inferred_roof_tolerance_m)
            rejected.extend(boundary_rejections)
            if alignment_ref and floors:
                expected_top=ground+floors*alignment_ref[1]
                horizontal=[piece for piece in group
                            if np.ptp(_plane_values(piece[0],piece[1][:,:2]))<=2*c.residual_m]
                if len(horizontal)>1:
                    support=[int(p.get('raw_plane_inliers',p['cells'])) for p,_ in horizontal]
                    maximum_support=max(support)
                    peers=[piece for piece,n in zip(horizontal,support)
                           if maximum_support-n<=np.sqrt(maximum_support+n)]
                    alignment_pool=horizontal if local_alignment_active else peers
                    aligned=[piece for piece in alignment_pool
                             if abs(piece[0]['fitted_upper_z']-expected_top)<=config.height.inferred_roof_tolerance_m]
                    if (aligned and max(p['fitted_upper_z'] for p,_ in alignment_pool)
                            -min(p['fitted_upper_z'] for p,_ in alignment_pool)>2*c.residual_m):
                        chosen=min(aligned,key=lambda piece:abs(piece[0]['fitted_upper_z']-expected_top))
                        chosen_z=chosen[0]['fitted_upper_z']
                        descending_choice=(unaligned_dominant_z is not None and
                            chosen_z<unaligned_dominant_z-2*c.residual_m)
                        if not local_alignment_active or descending_choice:
                            group=[chosen];storey_aligned=True
                elif local_alignment_active and len(groups)>1 and horizontal:
                    local_alignment_match=(
                        abs(horizontal[0][0]['fitted_upper_z']-expected_top)
                        <=config.height.inferred_roof_tolerance_m)
            controls=_unique_observations(group)
            own_patch=supported_patch(controls,expected,spacing,c)[2] if not expected.is_empty else expected
            # Other observed levels reduce expected visibility, never source XY.
            visible=expected.difference(union.difference(own_patch))
            valid,coverage,patch=supported_patch(controls,visible,spacing,c) if not visible.is_empty else (False,0.,own_patch)
            full=supported_patch(controls,f.geometry,spacing,c)[0]
            independent=_interior_controls(controls,f.geometry,spacing,c)
            deep_interior=_interior_controls(controls,f.geometry,2*spacing+c.registration_m,c)
            inward_seed,max_boundary_depth,deeper_interior_controls=_inward_seed_evidence(
                controls,inward_context,spacing,c)
            continuous_neighbours=set()
            observed_exterior_neighbours=set()
            from shapely import intersects_xy
            for j in neighbours:
                if any(abs(op['fitted_upper_z']-max(p['fitted_upper_z'] for p,_ in group))<=config.height.inferred_roof_tolerance_m for op in reliable[j]):
                    near=units[j].geometry.buffer(spacing+c.registration_m)
                    if intersects_xy(near,controls[:,0],controls[:,1]).any():continuous_neighbours.add(units[j].key)
                if j not in continuity_cache:
                    continuity_cache[j]=[]
                    for plane,mask in hypotheses[j]:
                        if plane not in reliable[j]:continue
                        outside=clouds[j][mask]
                        if len(outside)>=c.min_plane_points:
                            continuity_cache[j].append((outside,STRtree(points(outside[:,0],outside[:,1]))))
                reliable_planes=continuity_cache[j]
                if reliable_planes and _observed_exterior_continuity(
                        controls,units[j].geometry,reliable_planes,spacing,spacings[j],c,config.height):
                    observed_exterior_neighbours.add(units[j].key)
            larger_tall_sibling_matches=[]
            if floors:
                larger_tall_sibling_matches=[j for j in same_parent_neighbours
                    if units[j].key in continuous_neighbours
                    and units[j].geometry.area>f.geometry.area
                    and units[j].properties.get('storeys_above')
                    and units[j].properties['storeys_above']>floors]
            # Boundary continuity is ambiguous only when the target also has a
            # material unsupported gap. A complete observed surface may span
            # an attached-building boundary without belonging to the neighbour.
            # One squared observation radius is the local XY uncertainty cell;
            # this scales with point spacing instead of footprint area.
            unsupported_area=max(0.,visible.area-patch.area)
            partitioned_enclosing_body=(has_touching_rings(f.geometry) and inward_seed
                                        and len(continuous_neighbours)>=2
                                        and not boundary_dominated_shape)
            boundary_conflict_without_alignment=(not deep_interior and not partitioned_enclosing_body
                               and unsupported_area>(spacing+c.registration_m)**2 and
                               (len(continuous_neighbours)>=2 or any(units[j].geometry.area>=f.geometry.area for j in neighbours if units[j].key in continuous_neighbours)))
            if local_alignment_active:
                aligned_z=max(p['fitted_upper_z'] for p,_ in group)
                descending_alignment=(unaligned_dominant_z is not None and
                    aligned_z<unaligned_dominant_z-2*c.residual_m)
                storey_aligned=(not deep_interior and
                    (storey_aligned or local_alignment_match) and
                    descending_alignment)
            storey_step_owned=(storey_aligned and alignment_ref and alignment_ref[2]!=floors)
            boundary_conflict=(not deep_interior and not storey_step_owned and not partitioned_enclosing_body
                               and unsupported_area>(spacing+c.registration_m)**2 and
                               (len(continuous_neighbours)>=2 or any(units[j].geometry.area>=f.geometry.area for j in neighbours if units[j].key in continuous_neighbours)))
            largest_competing_area=max((supported_patch(_unique_observations(other),expected,spacing,c)[2].area
                                        for index,other in enumerate(groups) if index!=group_index),default=0.)
            largest_competing_controls=max((len(_unique_observations(other))
                                            for index,other in enumerate(groups) if index!=group_index),default=0)
            support_uncertainty_area=(spacing+c.registration_m)**2
            support_uncertainty_controls=np.sqrt(largest_competing_controls+len(controls))
            edge_contamination=(not inward_seed and not deep_interior
                                and bool(observed_exterior_neighbours) and deeper_interior_controls>0
                                and largest_competing_area>own_patch.area+support_uncertainty_area
                                and largest_competing_controls>len(controls)+support_uncertainty_controls)
            # A mapped adjacent part can establish structural context even when
            # its own LiDAR plane is incomplete. Requiring a reliable plane here
            # turns legitimate narrow attachments into isolated walls and can
            # remove the floor reference used by their siblings.
            has_adjacent_body=any(
                reliable[j]
                or bool(samples[units[j].key].get('roof_z'))
                or ((units[j].properties.get('storeys_above') or 0)>0
                    and samples[units[j].key].get('ground_z') is not None)
                for j in neighbours)
            isolated_wall_like=(footprint_compactness(f.geometry)<=NONCOMPACT_FOOTPRINT_MAX
                                and boundary_dominated_shape
                                and not deep_interior and not has_adjacent_body)
            span=max((float(np.ptp(_plane_values(p,q[:,:2]))) for p,q in group),default=0.)
            if valid and isolated_wall_like:
                valid=False;rejected.append({'roof_z':max(p['fitted_upper_z'] for p,_ in group),'reason':strings.BuildingSurfaceRejectionReason.ISOLATED_WALL_LIKE_SURFACE,'neighbour_ids':[]})
            elif valid and boundary_conflict:
                valid=False;rejected.append({'roof_z':max(p['fitted_upper_z'] for p,_ in group),'reason':strings.BuildingSurfaceRejectionReason.BOUNDARY_CONTINUITY,'neighbour_ids':sorted(continuous_neighbours)})
            own_floor_unit=((float(np.median(controls[:,2]))-ground)/floors
                            if floors and ground is not None else None)
            subresolution_single_storey_outlier=(valid and floors==1 and ground is not None
                and f.geometry.buffer(-uncertainty_radius).is_empty and not deep_interior
                and own_floor_unit is not None and own_floor_unit>config.height.max_floor_height_m
                and adjacent_dominant_roofs
                and max(p['fitted_upper_z'] for p,_ in group)>
                    max(item['roof_z'] for item in adjacent_dominant_roofs)
                    +config.height.inferred_roof_tolerance_m)
            if subresolution_single_storey_outlier:
                valid=False
                rejected.append({'roof_z':max(p['fitted_upper_z'] for p,_ in group),
                    'reason':strings.BuildingSurfaceRejectionReason.SUBRESOLUTION_SINGLE_STOREY_ABOVE_SIBLINGS,
                    'neighbour_ids':sorted(item['id'] for item in adjacent_dominant_roofs)})
            taller_sibling_is_larger=(conflict_ref is not None and
                                      units[conflict_ref[4]].geometry.area>f.geometry.area)
            if valid and conflict_ref and floors and full and taller_sibling_is_larger and not deep_interior:
                implied_storeys=(float(np.median(controls[:,2]))-ground)/conflict_ref[1]
                own_conflict=implied_storeys>floors*config.height.coherence_max_ratio
                sibling_match=abs(implied_storeys-conflict_ref[2])<=config.height.coherence_max_ratio
                if own_conflict and sibling_match:
                    valid=False;rejected.append({'roof_z':max(p['fitted_upper_z'] for p,_ in group),'reason':strings.BuildingSurfaceRejectionReason.SIBLING_STOREY_CONFLICT,'neighbour_ids':[conflict_ref[3]]})
            valid_without_storey_alignment=(valid and not
                (storey_step_owned and boundary_conflict_without_alignment))
            choice={'pieces':group,'xyz':controls,'roof_z':max(p['fitted_upper_z'] for p,_ in group),'valid':valid,'valid_without_storey_alignment':valid_without_storey_alignment,'full':full,'independent':independent,'deep_interior':deep_interior,'inward_seed':inward_seed,'inclined':span>2*c.residual_m,'continuous_neighbours':continuous_neighbours,'storey_aligned':storey_aligned,'own_floor_unit':own_floor_unit,'larger_tall_sibling_matches':larger_tall_sibling_matches,'edge_contamination':edge_contamination,'observed_exterior_neighbours':observed_exterior_neighbours}
            choices.append(choice);details.append({'roof_z':choice['roof_z'],'visible_area_m2':visible.area,'supported_area_m2':patch.area,'coverage':coverage,'independent_points':len(controls),'accepted':valid,'deep_interior_support':deep_interior,'continuous_neighbour_ids':sorted(continuous_neighbours),strings.BuildingSurfaceFields.INWARD_SEED_SUPPORT:inward_seed,strings.BuildingSurfaceFields.MAX_BOUNDARY_DEPTH_M:max_boundary_depth,strings.BuildingSurfaceFields.DEEPER_INTERIOR_CONTROLS:deeper_interior_controls,strings.BuildingSurfaceFields.OBSERVED_EXTERIOR_NEIGHBOURS:sorted(observed_exterior_neighbours)})
        for choice,detail in zip(choices,details):
            lower_alternative=any(other['valid'] and other is not choice
                and other['roof_z']<choice['roof_z']-config.height.inferred_roof_tolerance_m
                and other['own_floor_unit'] is not None
                and config.height.near_zero_m<other['roof_z']-ground
                and other['own_floor_unit']<=config.height.max_floor_height_m
                for other in choices)
            if (choice['valid'] and choice['full'] and choice['deep_interior']
                    and choice['larger_tall_sibling_matches']
                    and choice['own_floor_unit'] is not None
                    and choice['own_floor_unit']>config.height.max_floor_height_m
                    and lower_alternative):
                choice['valid']=False;detail['accepted']=False
                rejected.append({'roof_z':choice['roof_z'],'reason':strings.BuildingSurfaceRejectionReason.TALL_SIBLING_OWNS_FULL_SURFACE,
                                 'neighbour_ids':sorted(units[j].key for j in choice['larger_tall_sibling_matches'])})
        # Exterior continuation chooses between viable owned levels; it cannot
        # erase the only reconstructable surface. Evaluate it after every
        # independent rejection so a competing but invalid hypothesis cannot
        # make the mapped part (and its contextual siblings) disappear.
        has_valid_interior_alternative=_has_reconstructable_interior_alternative(
            choices,ground,config.height.near_zero_m)
        if has_valid_interior_alternative:
            for choice,detail in zip(choices,details):
                if not choice['valid'] or not choice['edge_contamination']:continue
                choice['valid']=False;detail['accepted']=False
                rejected.append({'roof_z':choice['roof_z'],'reason':strings.BuildingSurfaceRejectionReason.EDGE_LEVEL_CONTINUES_OUTSIDE,
                                 'neighbour_ids':sorted(choice['observed_exterior_neighbours'])})
        choices=[g for g in choices if g['valid']];selected=[];basis='spatial_support';floor_ref=None
        calibration_selected=[]
        envelope_required=False
        shared_majority_owned=False
        if choices:
            maximum=max(len(g['xyz']) for g in choices)
            # Sampling-count uncertainty prevents a tiny incidental patch from
            # competing with a densely observed body. No square-metre cutoff.
            choices=[g for g in choices if len(g['xyz'])>=max(c.min_plane_points,np.sqrt(maximum))]
            calibration_candidates=[g for g in choices if g['valid_without_storey_alignment']]
            if calibration_candidates:
                calibration_selected=[max(calibration_candidates,key=lambda g:len(g['xyz']))]
            trusted=[g for g in choices if g['full'] and g['independent']]
            dominant=max(choices,key=lambda g:len(g['xyz']))
            compactness=footprint_compactness(f.geometry)
            # Several levels and shared elevations are not sufficient to erase
            # a mapped part. Deep interior controls establish ownership even
            # when attached urban roofs continue through most neighbours. Only
            # a boundary-dominated dominant level can remain ambiguous under a
            # strict majority of adjacent footprints.
            neighbour_majority=(len(dominant['continuous_neighbours'])>=3 and
                                len(dominant['continuous_neighbours'])*2>len(neighbours))
            shared_majority_owned=(compactness>NONCOMPACT_FOOTPRINT_MAX and len(choices)>1 and
                                   neighbour_majority and dominant['deep_interior'])
            seed_resolves_boundary=(dominant['inward_seed'] and
                expected.area>4*(spacing+c.registration_m)**2)
            if (compactness>NONCOMPACT_FOOTPRINT_MAX and len(choices)>1 and
                    neighbour_majority and not dominant['deep_interior'] and
                    not seed_resolves_boundary and not any(g['storey_aligned'] and alignment_ref
                        and alignment_ref[2]!=floors for g in choices)):
                rejected.append({'roof_z':dominant['roof_z'],'reason':strings.BuildingSurfaceRejectionReason.MULTILEVEL_NEIGHBOUR_CONTINUITY,'neighbour_ids':sorted(dominant['continuous_neighbours'])})
                choices=[];trusted=[]
            peers=[g for g in choices if maximum-len(g['xyz'])<=np.sqrt(maximum+len(g['xyz']))]
            refs=[(alignment_ref[0],alignment_ref[1])] if alignment_ref else []
            if floors and ground is not None:
                for j in neighbours:
                    other=units[j];ofloors=other.properties.get('storeys_above');og=samples[other.key]['ground_z']
                    if other.geometry.area<=f.geometry.area or not ofloors or ofloors<=floors or og is None or not hypotheses[j]:continue
                    op,_=max(hypotheses[j],key=lambda item:item[0]['cells'])
                    if op['cells']<=maximum:continue
                    unit=(sum(op['observed_z_range'])/2-og)/ofloors
                    if unit>0:refs.append((op['cells'],unit))
            # Storeys rank only genuinely ambiguous, widely separated levels.
            # A lone tall one-storey roof is never scaled to a typical floor.
            if refs:floor_ref=max(refs)[1]
            separation=max(g['roof_z'] for g in peers)-min(g['roof_z'] for g in peers) if peers else 0.
            contextual=(floor_ref is not None and len(peers)>1 and
                        separation>floor_ref*config.height.coherence_max_ratio and
                        not all(g['full'] and g['independent'] for g in peers))
            if not choices:pass
            elif any(g['storey_aligned'] for g in choices):selected=[max((g for g in choices if g['storey_aligned']),key=lambda g:len(g['xyz']))];basis='sibling_storey_alignment'
            elif contextual:
                selected=[min(peers,key=lambda g:abs(np.log(((float(np.median(g['xyz'][:,2]))-ground)/floors)/floor_ref)))];basis='neighbour_storeys'
            elif trusted:
                comparable=[g for g in trusted if g in peers]
                selected=[max(comparable,key=lambda g:g['roof_z'])] if len(comparable)>1 else [max(trusted,key=lambda g:(len(g['xyz']),-g['roof_z']))]
                envelope_required=len(trusted)>1
            elif len(peers)>1 and all(not g['inclined'] for g in peers):selected=peers;basis='comparable_flat_levels'
            else:selected=[dominant]
        own=[piece for group in selected for piece in group['pieces']]
        calibration_own=[piece for group in calibration_selected for piece in group['pieces']]
        interior=bool(selected) and _interior_controls(_unique_observations(own),f.geometry,spacing,c)
        inclined=bool(selected) and any(g['inclined'] for g in selected)
        tall_sibling_conflict=bool(selected) and any(g['full'] and g['larger_tall_sibling_matches']
            and g['own_floor_unit'] is not None and g['own_floor_unit']>config.height.max_floor_height_m
            for g in selected)
        local_storey_aligned=(local_alignment_active and bool(selected)
                              and any(g['storey_aligned'] for g in selected))
        sibling_calibration_allowed=(bool(own) and not shared_majority_owned
                                     and not tall_sibling_conflict and not local_storey_aligned
                                     and boundary_shared_roof is None)
        calibration_roof_z=None
        if local_storey_aligned and calibration_own:
            calibration_roof_z,_=_spatial_cell_upper_median_z(
                _unique_observations(calibration_own),f.geometry,spacing)
        boundary_continuity_rejected=any(item.get('reason')==
            strings.BuildingSurfaceRejectionReason.BOUNDARY_CONTINUITY for item in rejected)
        expanded_local_fallback=(not own and local_storey_ref
            and 0<floors-local_storey_ref[2]<=2
            and (local_storey_fallback_shape or
                 (boundary_continuity_rejected and
                  footprint_compactness(f.geometry)<=LOCAL_STOREY_FALLBACK_COMPACTNESS_MAX)))
        if boundary_dominated_shape:
            local_storey_neighbours=physical_storey_neighbours
        elif expanded_local_fallback:
            local_storey_neighbours=[units[local_storey_ref[4]].key]
        else:
            local_storey_neighbours=[]
        shared_roof_z=(boundary_shared_roof[0] if boundary_shared_roof else None)
        shared_roof_neighbours=(boundary_shared_roof[1] if boundary_shared_roof else [])
        evidence={'selection_policy':'xyz_footprints_adjacent_surfaces','accepted':bool(own),'original_representatives':counts[i],'retained_surface_representatives':len(xyz),'spacing_m':spacing,'planes':[p for p,_ in planes],'candidates':details,'rejected_neighbour_planes':rejected,'neighbour_ids':[units[j].key for j in neighbours],'source_classes_used':False,strings.BuildingSurfaceFields.INDEPENDENT_INTERIOR:bool(interior),strings.BuildingSurfaceFields.INCLINED_CONTINUOUS:bool(inclined),strings.BuildingSurfaceFields.ENVELOPE_REQUIRED:bool(inclined or len(selected)>1 or envelope_required),strings.BuildingSurfaceFields.SIBLING_CALIBRATION_ALLOWED:sibling_calibration_allowed,strings.BuildingSurfaceFields.TALL_SIBLING_CONFLICT:tall_sibling_conflict,strings.BuildingSurfaceFields.LOCAL_STOREY_NEIGHBOURS:local_storey_neighbours,strings.BuildingSurfaceFields.LOCAL_STOREY_ALIGNED:local_storey_aligned,strings.BuildingSurfaceFields.CALIBRATION_ROOF_Z:calibration_roof_z,strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_Z:shared_roof_z,strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_NEIGHBOURS:shared_roof_neighbours,'selection_basis':basis,'context_floor_height_m':floor_ref}
        if own:
            attributed=_unique_observations(own)
            # A newly owned surface shared through most attached neighbours is
            # authoritative for this part's geometry, but must not rewrite the
            # earlier independent roof sample used to calibrate every sibling.
            # The qualified roof_surface below can still reconstruct this part.
            if local_storey_aligned or boundary_shared_roof is not None:
                s['roof_z']=[]
            else:
                s['roof_z']=attributed[:,2].tolist() if sibling_calibration_allowed else []
            top,spatial_cells=_spatial_cell_upper_median_z(attributed,f.geometry,spacing);evidence['roof_z']=top
            evidence[strings.BuildingSurfaceFields.LOD1_REDUCTION]=strings.LoD1RoofReductionMethod.SPATIAL_CELL_UPPER_MEDIAN
            evidence[strings.BuildingSurfaceFields.LOD1_SPATIAL_CELLS]=spatial_cells
            reduction_accepted=ground is not None and top>ground+config.height.near_zero_m
            reason=('attributed_geometric_surfaces' if reduction_accepted
                    else strings.LoD1RoofReductionReason.REPRESENTATIVE_NEAR_GROUND)
            s['roof_surface']={'accepted':reduction_accepted,'reason':reason,'roof_z':top,'planes':[p for p,_ in own],'retained_cells':len(attributed),'storeys_used':basis=='neighbour_storeys',strings.BuildingSurfaceFields.LOD1_REDUCTION:strings.LoD1RoofReductionMethod.SPATIAL_CELL_UPPER_MEDIAN,strings.BuildingSurfaceFields.LOD1_SPATIAL_CELLS:spatial_cells}
        else:s['roof_z']=[];evidence['roof_z']=None
        s[strings.BuildingHeightFields.BUILDING_SURFACES]=evidence
    for _ in _map_bounded(attribute,range(len(units)),c.workers):pass


def sample_building_surfaces(config,root,features,samples,working,progress):
    """Read original XYZ in bounded cells/layers; labels cannot route a building.

    Full received footprints supply evidence; no fixed inward erosion is used.
    Regular LAZ is streamed; COPC queries use full resolution and half-open cells.
    All source files and previous outputs are read-only.
    """
    c=config.building_surfaces;root=Path(root)
    units=[f for f in features if f.key in samples and not f.issues]
    if not units:return
    tree=STRtree([f.geometry for f in units]);cells=[{} for _ in units];overflowed=[set() for _ in units];total=0;peak=0
    clouds=[None]*len(units);hypotheses=[None]*len(units);spacings=[None]*len(units);counts=[0]*len(units)
    bounds=[np.array(f.geometry.bounds[:2]) for f in units]
    sizes=[np.maximum((np.array(f.geometry.bounds[2:])-lo)/c.grid_axis,c.min_cell_size_m) for f,lo in zip(units,bounds)]
    roi=unary_union([f.geometry for f in units])
    def consume(chunk,tx,query_cell=None):
        nonlocal total,peak
        if len(chunk)>config.sampling.chunk_points:raise ValueError('Building COPC query exceeds chunk_points')
        x,y=map(np.asarray,tx.transform(np.asarray(chunk.x),np.asarray(chunk.y)));z=np.asarray(chunk.z)
        good=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
        if query_cell is not None:
            a,b,d,e=query_cell.bounds;good&=(x>=a)&(x<d)&(y>=b)&(y<e)
        x,y,z=x[good],y[good],z[good];pairs=tree.query(points(x,y),predicate='intersects')
        for unit in np.unique(pairs[1]):
            i=int(unit);ids=pairs[0,pairs[1]==i];lo=bounds[i];size=sizes[i]
            xy=np.column_stack((x[ids],y[ids]));key=np.minimum(c.grid_axis-1,np.floor((xy-lo)/size).astype(int))
            layer=np.floor(z[ids]/c.layer_step_m).astype(int);distance=((xy-(lo+(key+.5)*size))**2).sum(axis=1)
            order=np.lexsort((z[ids],y[ids],x[ids],distance,layer,key[:,1],key[:,0]));grouped=np.column_stack((key[order],layer[order]));first=np.r_[True,np.any(grouped[1:]!=grouped[:-1],axis=1)]
            for k in order[first]:
                cellkey=tuple(map(int,key[k]));layers=cells[i].setdefault(cellkey,{})
                band=int(layer[k]);j=ids[k];v=(float(distance[k]),float(x[j]),float(y[j]),float(z[j]))
                if band not in layers and len(layers)>=c.max_layers_per_cell:overflowed[i].add(cellkey)
                if band not in layers and len(layers)<c.max_layers_per_cell:
                    if total>=c.max_total_layers:raise ValueError('building_surfaces max_total_layers exceeded; partition input or increase explicit budget')
                total+=retain_vertical_extremes(layers,band,v,c.max_layers_per_cell)
                peak=max(peak,total)
    def prepare(i):
        """Fit one independent completed footprint without shared budget mutation."""
        xyz=np.array([v[1:] for _,layers in sorted(cells[i].items()) for _,v in sorted(layers.items())],dtype=float).reshape(-1,3)
        primary=np.array([v[1:] for key,layers in sorted(cells[i].items()) if key not in overflowed[i] for _,v in sorted(layers.items())],dtype=float).reshape(-1,3)
        planes,spacing=local_hypotheses(units[i],xyz,samples[units[i].key],config,primary=primary)
        keep=np.zeros(len(xyz),dtype=bool)
        for _,mask in planes:keep|=mask
        return i,len(xyz),xyz[keep],[(p,m[keep]) for p,m in planes],spacing
    def complete(indices):
        """Commit bounded independent fits after the last intersecting source.

        Original counts, masks and spacing match sequential evaluation. Logical
        layer accounting and raw release are committed only on the caller thread.
        """
        nonlocal total
        for i,count,xyz,planes,spacing in _map_bounded(prepare,indices,c.workers):
            counts[i]=count;clouds[i]=xyz;hypotheses[i]=planes;spacings[i]=spacing
            total-=count-len(xyz);cells[i]=None;overflowed[i].clear()
    inventory=[];pending=np.zeros(len(units),dtype=int)
    for path in lidar_files(config.lidar,root):
        with laspy.open(path) as reader:
            source=reader.header.parse_crs()
            if source is None:raise ValueError('Building surface source requires CRS')
            tx=Transformer.from_crs(source,working,always_xy=True)
            rect=box(*tx.transform_bounds(*reader.header.mins[:2],*reader.header.maxs[:2],densify_pts=21))
            affected=tree.query(rect,predicate='intersects')
            if not len(affected):continue
            copc=any(v.user_id=='copc' and v.record_id==1 for v in reader.header.vlrs)
            pending[affected]+=1;inventory.append((path,source,tx,rect,copc,affected))
    progress('building_surfaces',{'candidates':len(units)})
    for path,source,tx,rect,copc,affected in inventory:
        if not copc:
            with laspy.open(path) as reader:
                for chunk in reader.chunk_iterator(config.sampling.chunk_points):consume(chunk,tx)
        if copc:
            a,b,d,e=roi.bounds;size=config.sampling.cell_size_m;x0=np.floor(a/size)*size;y0=np.floor(b/size)*size
            inverse=Transformer.from_crs(working,source,always_xy=True)
            with laspy.CopcReader.open(str(path)) as reader:
                for ix in range(int(np.ceil((d-x0)/size))):
                    for iy in range(int(np.ceil((e-y0)/size))):
                        cell=box(x0+ix*size,y0+iy*size,x0+(ix+1)*size,y0+(iy+1)*size)
                        if not cell.intersects(rect) or not len(tree.query(cell,predicate='intersects')):continue
                        bnd=inverse.transform_bounds(*cell.bounds,densify_pts=21)
                        consume(reader.query(bounds=Bounds(np.array(bnd[:2]),np.array(bnd[2:]))),tx,cell)
        pending[affected]-=1
        complete([int(i) for i in affected[pending[affected]==0]])
        progress('building_surface_file',{'file':path.name,'retained_layers':total,'peak_retained_layers':peak,'completed_objects':sum(q is not None for q in clouds)})
    complete([i for i in range(len(units)) if clouds[i] is None])
    cells.clear();attribute_surfaces(units,clouds,samples,config,prepared=(hypotheses,spacings,counts))
    progress('building_surfaces_complete',{'candidates':len(units),'accepted':sum(samples[f.key]['building_surfaces']['accepted'] for f in units),'retained_layers':total,'peak_retained_layers':peak})
