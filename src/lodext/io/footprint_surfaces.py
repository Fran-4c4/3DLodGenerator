"""Class-neutral recovery of unresolved footprints with independent exterior checks."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import laspy
from laspy.copc import Bounds
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import box
from shapely.ops import unary_union
from .roof_recovery import RoofRecoveryAccumulator
from .sampling import lidar_files, roof_support


def check_exterior(result, accumulator, index, policy):
    """Reject planes continuing into unoccupied exterior, irrespective of labels.

    Cells/layers contain original XYZ representatives, not raster interpolation.
    A missing or over-budget exterior is uncertainty, never proof of a roof.
    The returned evidence mutates only the owned result, not source observations.
    This is a local continuity guard, not a semantic terrain classifier.
    """
    if not result['accepted']:
        return result
    entries=[v for layers in accumulator.cells[index].values() if layers is not None for v in layers.values()]
    result['exterior_layers']=len(entries)
    reason=None
    if index in accumulator.overflow:
        reason='exterior_representative_budget_exceeded'
    elif len(accumulator.cells[index])<policy.min_cells or len(entries)<policy.min_cells:
        reason='insufficient_exterior_context'
    else:
        xyz=np.array([v[1:4] for v in entries]);explained=np.zeros(len(xyz),dtype=bool)
        for plane in result['planes']:
            a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin']
            explained|=np.abs(a*(xyz[:,0]-ox)+b*(xyz[:,1]-oy)+d-xyz[:,2])<=policy.residual_m
        fraction=float(explained.mean())
        result['exterior_continuity_fraction']=fraction
        if fraction>=policy.max_exterior_continuity:
            reason='surface_continues_into_exterior'
    if reason:
        result.update(accepted=False,reason=reason,roof_z=None)
    return result


def recover_footprint_surfaces(config,root,features,samples,estimates,working,progress):
    """Read original points only for unresolved, covered, independently based parts.

    All LAS classes participate equally. Existing resolved estimates and accepted
    spatial roofs are untouched. The ordinary and recovery estimates never feed
    new storey anchors. Streaming memory is bounded by the owning recovery
    policy; ordinary LAZ files are scanned by chunk, COPC by candidate cells.
    Positive storeys provide a permissive plausibility interval, not a roof Z.
    """
    c=config.roof_recovery;root=Path(root);units=[];supports=[]
    occupied=[f.geometry for f in features if f.geometry is not None and not f.geometry.is_empty and f.geometry.is_valid]
    occupied_tree=STRtree(occupied)
    for f in features:
        s=samples.get(f.key);estimate=estimates.get(f.key)
        if not s or not estimate or estimate['height_m'] is not None or f.issues:
            continue
        if s.get('roof_surface',{}).get('accepted') or s['ground_z'] is None or not s['coverage_complete'] or not f.properties.get('storeys_above'):
            continue
        support,erosion=roof_support(f.geometry,config.sampling)
        units.append(f);supports.append((support,erosion))
    progress('footprint_surfaces',{'candidates':len(units)})
    if not units:
        return
    inside=RoofRecoveryAccumulator(units,supports,c)
    exterior_units=[]
    for f in units:
        ring=f.geometry.buffer(c.context_m)
        indices=occupied_tree.query(ring,predicate='intersects')
        ring=ring.difference(unary_union([occupied[int(i)] for i in indices]))
        exterior_units.append(replace(f,geometry=ring,parent_id=None))
    outside=RoofRecoveryAccumulator(exterior_units,[(f.geometry,'not_attempted') for f in exterior_units],c,budget=inside.budget)
    roi=unary_union([f.geometry.buffer(c.context_m) for f in units])
    query_tree=STRtree([f.geometry.buffer(c.context_m) for f in units])

    def consume(chunk,tx,cell=None):
        """Discard decoded batches after adding bounded original representatives."""
        if len(chunk)>config.sampling.chunk_points:
            raise ValueError('Footprint COPC query exceeds chunk_points; reduce sampling.cell_size_m')
        x,y=map(np.asarray,tx.transform(np.asarray(chunk.x),np.asarray(chunk.y)))
        z=np.asarray(chunk.z);classes=np.asarray(chunk.classification)
        keep=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
        if cell is not None:
            a,b,d,e=cell.bounds;keep&=(x>=a)&(x<d)&(y>=b)&(y<e)
        inside.add(x[keep],y[keep],z[keep],classes[keep])
        outside.add(x[keep],y[keep],z[keep],classes[keep])


    for path in lidar_files(config.lidar,root):
        with laspy.open(path) as reader:
            source=reader.header.parse_crs()
            if source is None:
                raise ValueError('Footprint surface source requires CRS')
            tx=Transformer.from_crs(source,working,always_xy=True)
            rect=box(*tx.transform_bounds(*reader.header.mins[:2],*reader.header.maxs[:2],densify_pts=21))
            if not rect.intersects(roi):
                continue
            copc=any(v.user_id=='copc' and v.record_id==1 for v in reader.header.vlrs)
            if not copc:
                for chunk in reader.chunk_iterator(config.sampling.chunk_points):
                    consume(chunk,tx)
        if copc:
            a,b,d,e=roi.bounds;size=config.sampling.cell_size_m;x0=np.floor(a/size)*size;y0=np.floor(b/size)*size
            inverse=Transformer.from_crs(working,source,always_xy=True)
            with laspy.CopcReader.open(str(path)) as reader:
                for ix in range(int(np.ceil((d-x0)/size))):
                    for iy in range(int(np.ceil((e-y0)/size))):
                        cell=box(x0+ix*size,y0+iy*size,x0+(ix+1)*size,y0+(iy+1)*size)
                        if not cell.intersects(rect) or not len(query_tree.query(cell,predicate='intersects')):
                            continue
                        bounds=inverse.transform_bounds(*cell.bounds,densify_pts=21)
                        consume(reader.query(bounds=Bounds(np.array(bounds[:2]),np.array(bounds[2:]))),tx,cell)
        progress('footprint_surface_file',{'file':path.name,'retained_cells':inside.total+outside.total})
    for i,f in enumerate(units):
        s=samples[f.key]
        result=inside.estimate(i,s['ground_z'],f.properties['storeys_above'],config.height,0,s['coverage_complete'])
        result['selection_policy']='class_neutral_with_exterior_context'
        result=check_exterior(result,outside,i,c)
        s['roof_recovery']=result
    progress('footprint_surfaces_complete',{'candidates':len(units),'accepted':sum(samples[f.key]['roof_recovery']['accepted'] for f in units),'retained_cells':inside.total+outside.total})
