"""Targeted, bounded source-point pass for spatially coherent roof surfaces."""
from pathlib import Path
import numpy as np
import laspy
from pyproj import Transformer
from shapely import STRtree,points
from shapely.geometry import box
from shapely.ops import unary_union
from laspy.copc import Bounds
from .sampling import roof_support,lidar_files
from .roof_recovery_fit import fit_recovery_planes
from ..core.heights import modal_roof
from lodext import strings


def sample_roof_surfaces(config,root,features,samples,working,progress):
    """Attach roof_surface evidence from weak ordinary observations, read-only.

    Skip strong unambiguous modal roofs and bodies without independent ground/full coverage.
    Read regular sources in bounded batches and COPC only in candidate cells,
    at full resolution. Keep one actual observation nearest each normalized XY
    cell centre, sorted deterministically before fitting. Exclude explicit sibling
    overlap from independent support, never alter exported polygons. Ground and
    storeys never translate/scale the observed roof; no floor anchors are emitted.
    """
    c=config.roof_surfaces;root=Path(root);units=[];supports=[]
    siblings={}
    for f in features:
        if f.parent_id:siblings.setdefault(f.parent_id,[]).append(f)
    for f in features:
        s=samples.get(f.key)
        if not s or f.issues or f.geometry.area<c.min_area_m2 or not s['coverage_complete'] or s['ground_z'] is None or len(s['roof_z'])<config.height.min_points_absolute:continue
        _,strength,bimodal=modal_roof(tuple(s['roof_z']),config.height)
        # A strong individual peak is not an unambiguous roof when another
        # substantial level exists (e.g. a flat terrace beside a rooftop room).
        if strength>=config.height.min_mode_strength and not bimodal:continue
        support,_=roof_support(f.geometry,config.sampling)
        overlap=[o.geometry for o in siblings.get(f.parent_id,[]) if o.key!=f.key and o.geometry is not None and o.geometry.is_valid and o.geometry.intersects(support)]
        if overlap:support=support.difference(unary_union(overlap))
        if support.is_empty:continue
        units.append(f);supports.append(support)
    progress('roof_surfaces',{'candidates':len(units)})
    if not units:return
    tree=STRtree(supports);cells=[{} for _ in units];total=0
    roi=unary_union(supports)
    def consume(chunk,tx,query_cell=None):
        nonlocal total
        if len(chunk)>config.sampling.chunk_points:raise ValueError('Spatial roof COPC query exceeds chunk_points; reduce sampling.cell_size_m')
        mask=np.ones(len(chunk),dtype=bool)  # Every provider class participates; labels are provenance only.
        x,y=map(np.asarray,tx.transform(np.asarray(chunk.x)[mask],np.asarray(chunk.y)[mask]));z=np.asarray(chunk.z)[mask]
        good=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
        if query_cell is not None:
            a,b,d,e=query_cell.bounds;good&=(x>=a)&(x<d)&(y>=b)&(y<e)
        x,y,z=x[good],y[good],z[good]
        pairs=tree.query(points(x,y),predicate='intersects')
        for unit in np.unique(pairs[1]):
            i=int(unit);idx=pairs[0,pairs[1]==i];g=supports[i];lo=np.array(g.bounds[:2]);size=np.maximum((np.array(g.bounds[2:])-lo)/c.grid_axis,c.min_cell_size_m)
            xy=np.column_stack((x[idx],y[idx]));key=np.minimum(c.grid_axis-1,np.floor((xy-lo)/size).astype(int));centre=lo+(key+.5)*size;dist=((xy-centre)**2).sum(axis=1)
            order=np.lexsort((z[idx],y[idx],x[idx],dist,key[:,1],key[:,0]));sorted_key=key[order];first=np.r_[True,np.any(sorted_key[1:]!=sorted_key[:-1],axis=1)]
            for position in order[first]:
                k=tuple(map(int,key[position]));j=idx[position];value=(float(dist[position]),float(x[j]),float(y[j]),float(z[j]))
                if k not in cells[i]:
                    if total>=c.max_total_cells:raise ValueError('roof_surfaces max_total_cells exceeded; partition inputs or raise explicit budget')
                    total+=1;cells[i][k]=value
                elif value<cells[i][k]:cells[i][k]=value
    for path in lidar_files(config.lidar,root):
        with laspy.open(path) as reader:
            source=reader.header.parse_crs()
            if source is None:raise ValueError('Spatial roof source requires CRS')
            tx=Transformer.from_crs(source,working,always_xy=True)
            rect=box(*tx.transform_bounds(*reader.header.mins[:2],*reader.header.maxs[:2],densify_pts=21))
            if not rect.intersects(roi):continue
            copc=any(v.user_id=='copc' and v.record_id==1 for v in reader.header.vlrs)
            if not copc:
                for chunk in reader.chunk_iterator(config.sampling.chunk_points):consume(chunk,tx)
        if copc:
            a,b,d,e=roi.bounds;size=config.sampling.cell_size_m;x0=np.floor(a/size)*size;y0=np.floor(b/size)*size
            inverse=Transformer.from_crs(working,source,always_xy=True)
            with laspy.CopcReader.open(str(path)) as reader:
                for ix in range(int(np.ceil((d-x0)/size))):
                    for iy in range(int(np.ceil((e-y0)/size))):
                        cell=box(x0+ix*size,y0+iy*size,x0+(ix+1)*size,y0+(iy+1)*size)
                        if not cell.intersects(rect) or not len(tree.query(cell,predicate='intersects')):continue
                        bounds=inverse.transform_bounds(*cell.bounds,densify_pts=21)
                        consume(reader.query(bounds=Bounds(np.array(bounds[:2]),np.array(bounds[2:]))),tx,cell)
        progress('roof_surface_file',{'file':path.name,'retained_cells':total})
    for i,(f,g) in enumerate(zip(units,supports)):
        entries=sorted(cells[i].items());s=samples[f.key]
        result={'accepted':False,'reason':'insufficient_spatial_support','retained_cells':len(entries),'roof_z':None,'storeys_used':False}
        s[strings.BuildingHeightFields.ROOF_SURFACE]=result
        if len(entries)<c.min_points:continue
        xyz=np.array([v[1:] for _,v in entries]);fit=fit_recovery_planes(xyz,c)
        # A coherent plane may belong to a much taller sibling. Footprint
        # overlap alone does not establish ownership when registration differs.
        # Storeys constrain this comparison only when independently observed
        # taller siblings explain the high elevation; industrial roofs without
        # such competing evidence are not forced into residential proportions.
        floors=f.properties.get('storeys_above');competing=[]
        if floors and floors>0:
            for other in siblings.get(f.parent_id,[]):
                other_floors=other.properties.get('storeys_above');sample=samples.get(other.key)
                if other.key==f.key or not other_floors or other_floors<=floors or not sample or not sample.get('coverage_complete'):continue
                mode,strength,mixed=modal_roof(tuple(sample['roof_z']),config.height)
                if mode is not None and strength>=config.height.min_mode_strength and not mixed:competing.append(mode)
        from ..core.roof_surfaces import separate_neighbour_planes
        allowed,rejected=separate_neighbour_planes(fit['planes'],s['ground_z'],floors,competing,config.height)
        result['planes']=allowed
        # Optional list of original fitted-plane evidence (metres/degrees),
        # excluded from the envelope/support after contextual attribution.
        # Absence means no planes were rejected, not absence of neighbour data.
        if rejected:result['rejected_neighbour_planes']=rejected
        fit['planes']=allowed
        if not fit['planes']:result['reason']='no_coherent_surface';continue
        explained=np.zeros(len(xyz),dtype=bool)
        for plane in fit['planes']:
            a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin'];explained|=np.abs(a*(xyz[:,0]-ox)+b*(xyz[:,1]-oy)+d-xyz[:,2])<=c.residual_m
        lo=np.array(g.bounds[:2]);size=np.maximum((np.array(g.bounds[2:])-lo)/c.grid_axis,c.min_cell_size_m);area=0
        for (key,_),inside in zip(entries,explained):
            if inside:
                corner=lo+np.array(key)*size;area+=box(*corner,*(corner+size)).intersection(g).area
        fraction=float(explained.mean());coverage=area/g.area
        result.update(supported_fraction=fraction,area_coverage=coverage)
        if fraction<c.min_supported_fraction or coverage<c.min_coverage:
            result['reason']='insufficient_spatial_support';continue
        if c.min_slope_deg>0 and not any(p['slope_deg']>=c.min_slope_deg for p in fit['planes']):
            result['reason']='insufficient_inclined_surface_support';continue
        top=max(p['fitted_upper_z'] for p in fit['planes'])
        if top-s['ground_z']<config.height.near_zero_m or top<=s['ground_z']:result['reason']='ground_not_below_surface';continue
        result.update(accepted=True,reason='coherent_roof_surfaces',roof_z=top)
    progress('roof_surfaces_complete',{'candidates':len(units),'accepted':sum(samples[f.key][strings.BuildingHeightFields.ROOF_SURFACE]['accepted'] for f in units),'retained_cells':total})
