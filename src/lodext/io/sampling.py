"""Local DTM and full-resolution LAS/LAZ/COPC evidence for the public pipeline."""
from lodext import strings
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
import math
from pathlib import Path

import laspy
from laspy.copc import Bounds
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from shapely import STRtree, contains_xy, intersects_xy, points as xy_points
from shapely.geometry import box
from shapely.ops import unary_union


@lru_cache(maxsize=32)
def _raster_transformer(working_wkt, raster_wkt):
    """Cache at most 32 XY operations by their full CRS definitions.

    Only construction cost changes; no point coordinates or elevations are
    cached. Z is never transformed. Native data setup precedes raster reception.
    """
    return Transformer.from_crs(working_wkt,raster_wkt,always_xy=True)


def raster_values(dataset, x, y, working):
    """Sample the same nearest cells as Rasterio.sample using bounded block reads.

    Preserve input order, XY reprojection, pixel-edge ownership, masks, scale
    and offset. Return NaN for NoData/outside/non-finite samples, never zero.
    Read one stored raster block at a time rather than one GDAL window per point;
    the raster's own block layout bounds memory independently of dataset extent.
    """
    x,y = np.asarray(x),np.asarray(y)
    out = np.full(len(x),np.nan,dtype=float)
    if not len(x):
        return out
    tx,ty = _raster_transformer(working.to_wkt(),dataset.crs.to_wkt()).transform(x,y)
    tx,ty = np.asarray(tx),np.asarray(ty)
    bounds=dataset.bounds
    inside = np.isfinite(tx) & np.isfinite(ty) & (tx >= bounds.left) & (tx < bounds.right) & (ty > bounds.bottom) & (ty <= bounds.top)
    positions = np.flatnonzero(inside)
    if not len(positions):return out
    rows,cols=rasterio.transform.rowcol(dataset.transform,tx[positions],ty[positions])
    rows,cols=np.asarray(rows,dtype=np.int64),np.asarray(cols,dtype=np.int64)
    valid=(rows>=0)&(rows<dataset.height)&(cols>=0)&(cols<dataset.width)
    positions,rows,cols=positions[valid],rows[valid],cols[valid]
    if not len(positions):return out
    block_h,block_w=dataset.block_shapes[0]
    keys,groups=np.unique(np.column_stack((rows//block_h,cols//block_w)),axis=0,return_inverse=True)
    for group,(by,bx) in enumerate(keys):
        mask=groups==group;row0,col0=int(by*block_h),int(bx*block_w)
        window=rasterio.windows.Window(col0,row0,min(block_w,dataset.width-col0),min(block_h,dataset.height-row0))
        block=dataset.read(1,window=window,masked=True)
        sample=block[rows[mask]-row0,cols[mask]-col0]
        good=~np.ma.getmaskarray(sample)&np.isfinite(sample.data)
        out[positions[mask][good]]=sample.data[good].astype(float)*dataset.scales[0]+dataset.offsets[0]
    return out


def roof_support(geom, config):
    """Return the roof sampling polygon and its erosion-status reason.

    geom is the complete working-metre footprint; config is SamplingConfig.
    Erode only at/above the area gate and retain all surviving components. An
    empty erosion keeps the original with an explicit status. This derivative
    controls crop/density only; it never replaces the exported source footprint.
    """
    if geom.area >= config.erode_min_area_m2 and config.erode_m:
        eroded = geom.buffer(-config.erode_m)
        if not eroded.is_empty and eroded.area > 0:
            return eroded,strings.RoofSupportErosionStatus.APPLIED
        return geom,strings.RoofSupportErosionStatus.EMPTY_RETAINED
    return geom,"not_attempted"


def ground_for(geom, obstacles, tree, raster, working, config):
    """Find a representative DTM ground elevation outside occupied footprints.

    Try increasing configured metre radii, subtract the body and indexed nearby
    obstacles, then sample valid DTM cells on a metric grid. The first free ring
    meeting area/sample requirements supplies a median, counts, radius and area.
    Return ground_z=None when none qualifies; never use zero or roof points as
    missing-ground replacement. Raster NoData/outside values are ignored.
    The broad-ring median is representative ground, not a local terrain plane.
    """
    for radius in config.ground_buffers_m:
        ring = geom.buffer(radius).difference(geom)
        indices = tree.query(ring,predicate="intersects")
        free = ring.difference(unary_union([obstacles[int(i)] for i in indices]))
        if free.is_empty or free.area < config.min_free_area_m2:
            continue
        left,bottom,right,top = free.bounds
        # Row-wise grids bound temporary memory even for very long buildings.
        x = np.arange(left,right,config.grid_step_m)
        values = []
        candidates = 0
        pending_x,pending_y=[],[]
        # Read batching only: at most 4096 pending metre-XY samples. This is
        # not a support threshold and cannot change the selected ground grid.
        batch_limit=4096
        def consume_pending():
            """Read and clear one bounded XY batch without changing sample order."""
            z=raster_values(raster,np.asarray(pending_x),np.asarray(pending_y),working)
            values.extend(map(float,z[np.isfinite(z)]))
            pending_x.clear();pending_y.clear()
        for y in np.arange(bottom,top,config.grid_step_m):
            xx = x[contains_xy(free,x,np.full(len(x),y))]
            candidates += len(xx)
            for start in range(0,len(xx),batch_limit):
                chunk=xx[start:start+batch_limit]
                if len(pending_x)+len(chunk)>batch_limit:consume_pending()
                pending_x.extend(chunk);pending_y.extend([y]*len(chunk))
        if pending_x:consume_pending()
        if len(values) >= config.min_ground_samples:
            return {strings.BuildingHeightFields.GROUND_Z:float(np.median(values)),"ground_samples":len(values),
                    "ground_candidates":candidates,"ground_radius_m":radius,"ground_free_area_m2":free.area}
    return {strings.BuildingHeightFields.GROUND_Z:None,"ground_samples":0,"ground_candidates":0,"ground_radius_m":None,"ground_free_area_m2":0.0}


def lidar_files(paths, root):
    """Resolve and deduplicate declared local LAS/LAZ resources in sorted order.

    Relative paths use root; directories are searched recursively (COPC LAZ is
    included). Empty declarations return []; missing/unsupported files and
    declared directories without clouds raise ValueError. No download or glob
    expansion occurs, and only headers/samplers later inspect point contents.
    """
    result = set()
    for value in paths:
        p = (Path(root)/value).resolve()
        if p.is_dir():
            found = [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in (".las",".laz")]
            if not found:
                raise ValueError(f"No LAS/LAZ files in declared directory: {p.name}")
            result.update(found)
        elif p.is_file() and p.suffix.lower() in (".las",".laz"):
            result.add(p)
        else:
            raise ValueError(f"Missing or unsupported LiDAR resource: {p.name}")
    return sorted(result)


def _roof_point_groups(tree,x,y,z,classes,allowed_classes):
    """Yield (support index, elevations) for exact point/polygon intersections.

    Inputs are aligned finite arrays from one decoded batch in working metres.
    The tree owns the unchanged sampling polygons. Only None is accepted for allowed_classes; labels are metadata.
    configured class lists filter before spatial lookup. Boundaries, holes and
    overlaps keep intersects_xy semantics: one point may support several bodies.
    Per-support elevations retain original batch order. Bulk point queries avoid
    testing every point against every polygon touched by a large LAS batch BBOX;
    no observations are thinned or assigned to an arbitrary nearest footprint.
    """
    if allowed_classes is not None:raise ValueError('Building classes are metadata; allowed_classes must be null')
    eligible=np.arange(len(z))
    if not len(eligible):return
    pairs=tree.query(xy_points(x[eligible],y[eligible]),predicate="intersects")
    if not pairs.shape[1]:return
    order=np.lexsort((pairs[0],pairs[1]))
    polygons=pairs[1,order];indices=eligible[pairs[0,order]]
    breaks=np.r_[0,np.flatnonzero(np.diff(polygons))+1,len(polygons)]
    for first,last in zip(breaks[:-1],breaks[1:]):
        yield int(polygons[first]),z[indices[first:last]]


def sample_sources(config, root, features, working, progress, *, scratch=None, artifacts=None):
    """Evidence for valid reconstruction units, preserving all obstacles.

    Non-COPC files are streamed once per selected file in chunk_points batches.
    COPC uses spatial queries in occupied working-CRS cells at full resolution.
    Header coverage and point/class support are separate diagnostics. The memory
    budget guards a decoded query; accumulated per-object roof points are kept.
    No thinning, source writes, vertical datum conversion or class inference.
    Return (samples_by_feature_key, cloud_summary): per-unit roof Z values,
    support area/erosion, header coverage and DTM ground evidence; plus decoded
    counts, selected files and DTM/class-2 consistency diagnostics. LoD0/known
    mode skips cloud reading. Sufficient independent ground pairs with excessive
    median or p95 residual abort; insufficient pairs remain explicitly unverified.
    progress receives (phase, details) events without affecting sample selection.
    """
    if config.dtm is None:
        from .point_ground import sample_point_sources
        return sample_point_sources(config,root,features,working,progress,scratch=scratch,artifacts=artifacts)
    policy = config.sampling
    kind = strings.BuildingObjectType.BUILDING_PART if config.geometry_mode == strings.BuildingGeometryMode.PARTS else strings.BuildingObjectType.BUILDING
    units = [f for f in features if f.kind == kind and not f.issues]
    obstacles = [f.geometry for f in features if f.geometry is not None and not f.geometry.is_empty
                 and f.geometry.is_valid and (f.kind == kind or config.geometry_mode == strings.BuildingGeometryMode.PARTS)]
    obstacle_tree = STRtree(obstacles)
    supports = [roof_support(f.geometry,policy) for f in units]
    support_geoms = [p[0] for p in supports]
    recovery=None
    if config.roof_recovery.enabled and config.roof_recovery.candidate_classes is not None:
        from .roof_recovery import RoofRecoveryAccumulator
        recovery=RoofRecoveryAccumulator(units,supports,config.roof_recovery)
    support_tree = STRtree(support_geoms)
    samples = {f.key:{strings.BuildingHeightFields.ROOF_Z:[],strings.BuildingHeightFields.SAMPLE_AREA_M2:support.area,strings.RoofSupportFields.EROSION:erosion,strings.LidarSamplingFields.COVERAGE_COMPLETE:False}
               for f,(support,erosion) in zip(units,supports)}
    dtm_path = (Path(root)/config.dtm).resolve()
    if not dtm_path.is_file():
        raise ValueError("Required DTM file does not exist")
    with rasterio.open(dtm_path) as raster:
        if raster.crs is None or raster.count != 1:
            raise ValueError("DTM requires a declared CRS and exactly one elevation band")
        if not raster.crs or raster.nodata is None:
            raise ValueError("DTM must declare NoData explicitly")
        for f in units:
            samples[f.key].update(ground_for(f.geometry,obstacles,obstacle_tree,raster,working,policy))
        from .adjacent_ground import infer_adjacent_ground
        infer_adjacent_ground(config,features,samples)
        progress("ground",{strings.ProgressEventFields.OBJECT_COUNT:len(units),"valid_ground":sum(samples[f.key][strings.BuildingHeightFields.GROUND_Z] is not None for f in units)})
        summary = {strings.LidarSamplingFields.FILES_SCANNED:0,strings.LidarSamplingFields.FILES_SELECTED:0,strings.LidarSamplingFields.POINTS_DECODED:0,strings.LidarSamplingFields.PEAK_BATCH_POINTS:0,strings.LidarSamplingFields.CLASSES:{},"vertical_check":{strings.VerticalConsistencyFields.STATUS:"not_requested"}}
        if 1 not in config.lods or config.height_source == strings.BuildingHeightSource.KNOWN or not config.lidar or not units:
            return samples,summary
        roi = unary_union([g.buffer(max(policy.ground_buffers_m)) for g in support_geoms])
        clearance = unary_union(obstacles).buffer(1.0)
        from .geometric_ground import GeometricGroundAccumulator
        from ..core.ground import PointGroundConfig
        controls=GeometricGroundAccumulator(Path('.'),working,PointGroundConfig(export_surface=False),obstacles,[],policy)
        classes_seen = Counter()
        selected = []
        cover_boxes = []
        for path in lidar_files(config.lidar,root):
            summary[strings.LidarSamplingFields.FILES_SCANNED] += 1
            with laspy.open(path) as reader:
                h = reader.header
                source = h.parse_crs()
                if source is None:
                    raise ValueError(f"LiDAR file has no declared CRS: {path.name}")
                source = CRS.from_user_input(source)
                to_work = Transformer.from_crs(source,working,always_xy=True)
                rect = box(*to_work.transform_bounds(float(h.mins[0]),float(h.mins[1]),float(h.maxs[0]),float(h.maxs[1]),densify_pts=21))
                if rect.intersects(roi):
                    selected.append((path,source,to_work,any(v.user_id=="copc" and v.record_id==1 for v in h.vlrs),rect))
                    cover_boxes.append(rect.buffer(policy.coverage_tolerance_m,join_style="mitre"))
        summary[strings.LidarSamplingFields.FILES_SELECTED] = len(selected)
        coverage = unary_union(cover_boxes)
        for f,(support,_) in zip(units,supports):
            samples[f.key][strings.LidarSamplingFields.COVERAGE_COMPLETE] = coverage.covers(support)

        def consume(points,to_work,cell=None):
            """Accumulate one decoded batch into roof evidence and ground controls.

            Transform XY only, reject non-finite coordinates, and apply half-open
            cell membership for COPC to avoid query-edge duplication. Retain
            selected roof Z and geometric exterior controls
            outside building clearance. Mutates this run's samples/statistics;
            oversized decoded batches raise before further accumulation.
            """
            n = len(points)
            summary[strings.LidarSamplingFields.POINTS_DECODED] += n
            summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS] = max(summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS],n)
            if n > policy.chunk_points:
                raise ValueError("Decoded COPC query exceeds chunk_points; reduce cell_size_m or increase explicit budget")
            if not n:
                return
            x,y = to_work.transform(np.asarray(points.x),np.asarray(points.y))
            x,y,z,c = np.asarray(x),np.asarray(y),np.asarray(points.z),np.asarray(points.classification)
            keep = np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
            if cell is not None:
                left,bottom,right,top = cell.bounds
                keep &= (x>=left)&(x<right)&(y>=bottom)&(y<top)
            keep &= intersects_xy(roi,x,y)
            x,y,z,c = x[keep],y[keep],z[keep],c[keep]
            if not len(z):
                return
            classes_seen.update(map(int,c))
            if recovery is not None:recovery.add(x,y,z,c)
            for j,selected_z in _roof_point_groups(support_tree,x,y,z,c,None):
                samples[units[j].key][strings.BuildingHeightFields.ROOF_Z].extend(map(float,selected_z))
            g = ~intersects_xy(clearance,x,y)
            gx,gy,gz = x[g],y[g],z[g]
            controls.add(gx,gy,gz,c[g],'vertical-control',working,[None]*len(gx),gx,gy,gz)

        copc = [(p,s,t,rect) for p,s,t,c,rect in selected if c]
        regular = [(p,t) for p,s,t,c,rect in selected if not c]
        for number,(path,to_work) in enumerate(regular,1):
            with laspy.open(path) as reader:
                for points in reader.chunk_iterator(policy.chunk_points):
                    consume(points,to_work)
            progress("lidar_file",{"completed":number,"total":len(regular),strings.LidarSamplingFields.POINTS_DECODED:summary[strings.LidarSamplingFields.POINTS_DECODED]})
        if copc:
            roi_tree = STRtree([g.buffer(max(policy.ground_buffers_m)) for g in support_geoms])
            left,bottom,right,top = roi.bounds
            size = policy.cell_size_m
            x0,y0 = math.floor(left/size)*size,math.floor(bottom/size)*size
            cells = []
            for iy in range(math.ceil((top-y0)/size)):
                for ix in range(math.ceil((right-x0)/size)):
                    cell = box(x0+ix*size,y0+iy*size,x0+(ix+1)*size,y0+(iy+1)*size)
                    if len(roi_tree.query(cell,predicate="intersects")):
                        cells.append(cell)
            with ExitStack() as stack:
                readers = [stack.enter_context(laspy.CopcReader.open(str(p))) for p,_,_,_ in copc]
                transforms = [Transformer.from_crs(working,s,always_xy=True) for _,s,_,_ in copc]
                for number,cell in enumerate(cells,1):
                    for i,(_,_,to_work,rect) in enumerate(copc):
                        if not cell.intersects(rect):
                            continue
                        bounds = transforms[i].transform_bounds(*cell.bounds,densify_pts=21)
                        points = readers[i].query(bounds=Bounds(np.asarray(bounds[:2]),np.asarray(bounds[2:])))
                        consume(points,to_work,cell)
                    if number%max(1,len(cells)//10)==0 or number==len(cells):
                        progress("lidar_cells",{"completed":number,"total":len(cells),strings.LidarSamplingFields.POINTS_DECODED:summary[strings.LidarSamplingFields.POINTS_DECODED]})
        summary[strings.LidarSamplingFields.CLASSES] = {str(k):v for k,v in sorted(classes_seen.items())}
        summary["files"] = [str(p.relative_to(root)) if p.is_relative_to(root) else p.name for p,_,_,_,_ in selected]
        controls.finish()
        pairs = controls.ground_xyz
        if len(pairs):
            dtm = raster_values(raster,pairs[:,0],pairs[:,1],working)
            residual = dtm-pairs[:,2]
            residual = residual[np.isfinite(residual)]
        else:
            residual = np.asarray([])
        checked = len(residual)>=policy.min_vertical_pairs
        median = float(np.median(residual)) if len(residual) else None
        summary["vertical_check"] = {strings.VerticalConsistencyFields.STATUS:strings.VerticalConsistencyStatus.LOCALLY_CONSISTENT if checked else "insufficient_pairs",
            "pairs":len(residual),"median_dtm_minus_lidar_m":median,
            "p95_absolute_m":float(np.percentile(np.abs(residual),95)) if len(residual) else None}
        if checked and (abs(median)>policy.vertical_check_limit_m or summary["vertical_check"]["p95_absolute_m"]>policy.vertical_check_p95_m):
            raise ValueError("DTM/LiDAR ground elevations are locally inconsistent; inspect sources before reconstruction")
        if recovery is not None:recovery.finish(samples,config)
        return samples,summary
