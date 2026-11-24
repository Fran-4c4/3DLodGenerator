"""Direct raw-point ground sampling, auditable selection and observed-point TIN.

The original point classes/coordinates are never written back. A footprint
intersection is a selection warning, not proof of a classification error.
Building ground statistics count selected raw returns in a free search ring;
the reduced display TIN never feeds those estimates.
"""
from collections import Counter
from contextlib import ExitStack
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import laspy
from laspy.copc import Bounds
import numpy as np
from pyproj import CRS,Transformer
from shapely import STRtree,intersects_xy,points as xy_points,to_wkb,delaunay_triangles,get_coordinates
from shapely.geometry import box,MultiPoint,Polygon
from shapely.ops import unary_union

from lodext import strings
from .sampling import lidar_files,roof_support,_roof_point_groups
from .geometric_ground import GeometricGroundAccumulator as GroundPointAccumulator
from ..export.cityjson import Vertices,validate_cityjson


def ground_surface(store,config):
    """TIN from reduced original observations; omit long/occupied triangles.

    Selection keeps one original point per configured XY cell, independently
    of building-base estimation. Delaunay interpolation is confined by an edge
    limit and excludes all building polygons; small unsupported gaps can still
    be bridged. No sea-level, hidden ground or stitched interfaces are invented.
    """
    xyz=np.asarray([v[1] for _,v in sorted(store.cells.items())])
    summary={'candidate_cells':len(xyz),'triangles':0,'long_triangles_omitted':0,'building_triangles_omitted':0,
             'cell_size_m':config.ground.surface_cell_size_m,'max_edge_m':config.ground.surface_max_edge_m,'stitching_applied':False}
    if len(xyz)<3:return None,summary
    triangulation=delaunay_triangles(MultiPoint(xyz[:,:2]))
    # Terrain can be regridded onto the building model's grid in the combined
    # scene. Reserve twice the quantisation step so neither grid operation can
    # create an occupied triangle; this omits boundary faces, not source points.
    occupied=STRtree([g.buffer(2*config.precision_m) for g in store.obstacles.geometries])
    triangles=list(triangulation.geoms)
    origin=(float(xyz[:,0].min()),float(xyz[:,1].min()),float(xyz[:,2].min()))
    vertices=Vertices(config.precision_m,origin);lookup={tuple(p[:2]):p[2] for p in xyz};faces=[]
    for start in range(0,len(triangles),8192):
        batch=triangles[start:start+8192]
        if not batch:continue
        xy=get_coordinates(batch).reshape(-1,4,2)[:,:3]
        lengths=np.linalg.norm(xy-np.roll(xy,1,axis=1),axis=2).max(axis=1)
        valid=lengths<=config.ground.surface_max_edge_m
        summary['long_triangles_omitted']+=int((~valid).sum())
        ids=np.flatnonzero(valid)
        if len(ids):
            pairs=occupied.query(np.asarray(batch,dtype=object)[ids],predicate='intersects')
            if pairs.shape[1]:
                blocked=ids[np.unique(pairs[0])];valid[blocked]=False;summary['building_triangles_omitted']+=len(blocked)
        for coords in xy[valid]:
            a,b=coords[1]-coords[0],coords[2]-coords[0]
            if a[0]*b[1]-a[1]*b[0]<0:coords=coords[[0,2,1]]
            ring=[vertices((x,y,lookup[(x,y)])) for x,y in coords]
            decoded=np.asarray([vertices.decode(i)[:2] for i in ring]);a,b=decoded[1]-decoded[0],decoded[2]-decoded[0]
            if len(set(ring))!=3 or a[0]*b[1]-a[1]*b[0]<=0:raise ValueError('Ground quantization collapses a triangle; reduce precision_m')
            # Check occupied footprints again after quantization, which can move
            # a near-boundary triangle by half a grid step.
            if len(occupied.query(Polygon(decoded),predicate='intersects')):
                summary['building_triangles_omitted']+=1;continue
            faces.append([ring])
    summary['triangles']=len(faces)
    if not faces:return None,summary
    model={'type':'CityJSON','version':'2.0','transform':{'scale':[config.precision_m]*3,'translate':list(origin)},
        'metadata':{'identifier':config.dataset_id+'-ground','referenceSystem':f'https://www.opengis.net/def/crs/EPSG/0/{config.working_epsg}'},
        'CityObjects':{'Terrain::lidar-ground':{'type':'TINRelief','attributes':{'sourceId':'lidar-ground','method':'observed_point_tin',**summary},
            'geometry':[{'type':'CompositeSurface','lod':'1','boundaries':faces,'semantics':{'surfaces':[{'type':'GroundSurface'}],'values':[0]*len(faces)}}]}},
        'vertices':vertices.vertices,'lodext':{'vertical_reference':config.vertical_reference,'clamping_applied':False}}
    coords=np.asarray([vertices.decode(i) for i in range(len(vertices.vertices))]);model['metadata']['geographicalExtent']=[*coords.min(axis=0).tolist(),*coords.max(axis=0).tolist()]
    validate_cityjson(model);return model,summary


def sample_point_sources(config,root,features,working,progress,*,scratch=None,artifacts=None):
    """Stream each selected LAS/LAZ once, or full-resolution occupied COPC cells.

    Scratch and artifacts belong to run_build's temporary context. Direct sampler
    callers may omit them to receive numerical evidence only. NoDTM is read in
    this route. Return ordinary (samples, cloud_summary), never a live connection.
    """
    if scratch is None:
        with TemporaryDirectory(prefix='lodext-ground-') as tmp:
            return sample_point_sources(config,root,features,working,progress,scratch=Path(tmp))
    policy=config.sampling;kind=strings.BuildingObjectType.BUILDING_PART if config.geometry_mode==strings.BuildingGeometryMode.PARTS else strings.BuildingObjectType.BUILDING
    full_surface=config.ground.surface_scope=='input_tiles'
    units=[f for f in features if f.kind==kind and not f.issues]
    obstacles=[f.geometry for f in features if f.geometry is not None and not f.geometry.is_empty and f.geometry.is_valid]
    obstacle_tree=STRtree(obstacles)
    supports=[roof_support(f.geometry,policy) for f in units];support_tree=STRtree([p[0] for p in supports])
    samples={f.key:{strings.BuildingHeightFields.ROOF_Z:[],strings.BuildingHeightFields.SAMPLE_AREA_M2:g.area,strings.RoofSupportFields.EROSION:e,strings.LidarSamplingFields.COVERAGE_COMPLETE:False} for f,(g,e) in zip(units,supports)}
    recovery=None
    if config.roof_recovery.enabled and config.roof_recovery.candidate_classes is not None:
        from .roof_recovery import RoofRecoveryAccumulator
        recovery=RoofRecoveryAccumulator(units,supports,config.roof_recovery)
    summary={strings.LidarSamplingFields.FILES_SCANNED:0,strings.LidarSamplingFields.FILES_SELECTED:0,strings.LidarSamplingFields.POINTS_DECODED:0,strings.LidarSamplingFields.PEAK_BATCH_POINTS:0,
             strings.LidarSamplingFields.CLASSES:{},'vertical_check':{strings.VerticalConsistencyFields.STATUS:'single_lidar_basis'},'ground_source':'lidar_points'}
    if not units:return samples,summary
    # The 5x5 coherence neighbourhood needs two full cells plus a boundary
    # cell beyond the base-search radius. This halo makes base evidence
    # independent of whether distant display terrain is requested.
    read_radius=max(policy.ground_buffers_m)+3*config.ground.geometric_cell_size_m
    roi=unary_union([f.geometry.buffer(read_radius) for f in units])
    roi_tree=STRtree([f.geometry.buffer(read_radius) for f in units])
    selected=[];covers=[]
    for path in lidar_files(config.lidar,root):
        summary[strings.LidarSamplingFields.FILES_SCANNED]+=1
        with laspy.open(path) as reader:
            source=reader.header.parse_crs()
            if source is None:raise ValueError(f'LiDAR file has no declared CRS: {path.name}')
            source=CRS.from_user_input(source);tx=Transformer.from_crs(source,working,always_xy=True);h=reader.header
            rect=box(*tx.transform_bounds(*h.mins[:2],*h.maxs[:2],densify_pts=21))
            if full_surface or rect.intersects(roi):
                selected.append((path,source,tx,any(v.user_id=='copc' and v.record_id==1 for v in h.vlrs),rect));covers.append(rect.buffer(policy.coverage_tolerance_m,join_style='mitre'))
    coverage=unary_union(covers)
    for f,(g,_) in zip(units,supports):samples[f.key][strings.LidarSamplingFields.COVERAGE_COMPLETE]=coverage.covers(g)
    summary[strings.LidarSamplingFields.FILES_SELECTED]=len(selected);classes=Counter()
    store=GroundPointAccumulator(Path(scratch)/strings.PointGroundFiles.POINTS,working,config.ground,obstacles,units,policy)
    need_roof=1 in config.lods and config.height_source==strings.BuildingHeightSource.LIDAR

    def consume(points,tx,path,source,offset=None,cell=None):
        """Accumulate one bounded decoded batch; preserve original record linkage."""
        n=len(points);summary[strings.LidarSamplingFields.POINTS_DECODED]+=n
        summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS]=max(summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS],n)
        if n>policy.chunk_points:raise ValueError('Decoded COPC query exceeds chunk_points; reduce cell_size_m or increase explicit budget')
        if not n:return
        sx,sy,sz=np.asarray(points.x),np.asarray(points.y),np.asarray(points.z);x,y=map(np.asarray,tx.transform(sx,sy));c=np.asarray(points.classification)
        keep=np.isfinite(x)&np.isfinite(y)&np.isfinite(sz)
        if not full_surface:keep&=intersects_xy(roi,x,y)
        if cell is not None:
            a,b,d,e=cell.bounds;keep&=(x>=a)&(x<d)&(y>=b)&(y<e)
        original=np.flatnonzero(keep);x,y,z,c=x[keep],y[keep],sz[keep],c[keep]
        classes.update(map(int,c))
        if recovery is not None:recovery.add(x,y,z,c)
        if need_roof:
            for i,values in _roof_point_groups(support_tree,x,y,z,c,None):samples[units[i].key][strings.BuildingHeightFields.ROOF_Z].extend(map(float,values))
        g=np.ones(len(c),dtype=bool);idx=original[g]
        if len(idx):store.add(x[g],y[g],z[g],c[g],str(path.relative_to(root)) if path.is_relative_to(root) else path.name,source,
            [None]*len(idx) if offset is None else idx+offset,sx[idx],sy[idx],sz[idx])
        if summary[strings.LidarSamplingFields.POINTS_DECODED]//5_000_000!=(summary[strings.LidarSamplingFields.POINTS_DECODED]-n)//5_000_000:
            progress('lidar_points',{strings.LidarSamplingFields.POINTS_DECODED:summary[strings.LidarSamplingFields.POINTS_DECODED]})
    try:
        for number,(path,source,tx,copc,rect) in enumerate(selected,1):
            if not copc:
                offset=0
                with laspy.open(path) as reader:
                    for points in reader.chunk_iterator(policy.chunk_points):consume(points,tx,path,source,offset);offset+=len(points)
            else:
                query_roi=unary_union([item[4] for item in selected]) if full_surface else roi
                size=policy.cell_size_m;a,b,c,d=query_roi.bounds;x0,y0=math.floor(a/size)*size,math.floor(b/size)*size
                inverse=Transformer.from_crs(working,source,always_xy=True)
                with laspy.CopcReader.open(str(path)) as reader:
                    for iy in range(math.ceil((d-y0)/size)):
                        for ix in range(math.ceil((c-x0)/size)):
                            cell=box(x0+ix*size,y0+iy*size,x0+(ix+1)*size,y0+(iy+1)*size)
                            if not cell.intersects(rect) or (not full_surface and not len(roi_tree.query(cell,predicate='intersects'))):continue
                            bounds=inverse.transform_bounds(*cell.bounds,densify_pts=21)
                            consume(reader.query(bounds=Bounds(np.asarray(bounds[:2]),np.asarray(bounds[2:]))),tx,path,source,cell=cell)
            progress('lidar_file',{'completed':number,'total':len(selected),strings.LidarSamplingFields.POINTS_DECODED:summary[strings.LidarSamplingFields.POINTS_DECODED]})
        store.finish()
        for i,f in enumerate(units):
            samples[f.key].update(store.estimate(i))
            if (i+1)%2000==0:progress('ground',{'completed':i+1,'total':len(units)})
        from .adjacent_ground import infer_adjacent_ground
        infer_adjacent_ground(config,features,samples)
        from .adjacent_ground import reconcile_inconsistent_ground
        reconcile_inconsistent_ground(config,features,samples)
        from .adjacent_ground import reconcile_exterior_planes
        reconcile_exterior_planes(config,features,samples)
        if recovery is not None:recovery.finish(samples,config)
        if config.ground.export_surface and artifacts is not None:
            terrain,tin_summary=ground_surface(store,config);summary['terrain']=tin_summary
            tin_summary['surface_scope']=config.ground.surface_scope
            if terrain is not None:artifacts['terrain_model']=terrain
        summary['ground_statistics']={'retained_histogram_bins':store.bin_count,'peak_histogram_bins':store.peak_bins,'method':'geometric_exterior_plane','candidate_cell_size_m':config.ground.geometric_cell_size_m,'candidate_layer_step_m':config.ground.layer_step_m,'surface_residual_m':config.ground.surface_residual_m,'median_error_bound_m':None,'exported_debug_points':len(store.audit_rows),'complete_point_cache':False};summary['ground_points']=dict(store.counts);summary[strings.LidarSamplingFields.CLASSES]={str(k):v for k,v in sorted(classes.items())}
        summary['files']=[str(p.relative_to(root)) if p.is_relative_to(root) else p.name for p,_,_,_,_ in selected]
        if config.ground.export_points and artifacts is not None:artifacts['ground_points_path']=store.path
    finally:store.audit_rows.clear()
    progress('ground',{strings.ProgressEventFields.OBJECT_COUNT:len(units),'valid_ground':sum(v[strings.BuildingHeightFields.GROUND_Z] is not None for v in samples.values())})
    return samples,summary
