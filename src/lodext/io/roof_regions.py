"""Bounded class-neutral XYZ observations for internal stepped roof regions."""
from pathlib import Path
import numpy as np
import laspy
from pyproj import Transformer
from shapely import STRtree,points
from shapely.geometry import box
from shapely.ops import unary_union
from laspy.copc import Bounds
from lodext import strings
from .sampling import roof_support,lidar_files
from ..reconstruction.roof_regions import fit_roof_regions


def reconstruct_roof_regions(config,root,features,records,samples,working,progress):
    """Read candidates in bounded batches and attach accepted geometry evidence.

    Candidate roof histograms screen for several populated elevations. Spatial
    support, not global percentiles, decides whether those are distinct bodies.
    Preserve original ground and source identities. This stage runs after height
    calibration so a high tower cannot change sibling storey-height anchors.
    LAS/LAZ streams and full-resolution COPC cell queries leave inputs unchanged.
    Global XY-budget exhaustion aborts explicitly. Excessively layered individual
    columns are unusable evidence, recorded without discarding other roof cells.
    """
    c=config.roof_regions;units=[];supports=[];siblings={}
    if c.object_ids is not None:
        unknown=set(c.object_ids)-{f.key for f in features}
        if unknown:raise ValueError('Unknown roof_regions.object_ids: '+', '.join(sorted(unknown)))
    for f in features:
        if f.parent_id:siblings.setdefault(f.parent_id,[]).append(f)
    for f in features:
        if c.object_ids is not None and f.key not in c.object_ids:continue
        row=records.get(f.key)
        if not row or f.issues or row.get('ground_z') is None or not row.get('coverage_complete'):continue
        if f.geometry.area<2*c.min_region_area_m2:continue
        # Existing per-object modal summary is not enough to reject coherent
        # small roof regions: retain every sufficiently sampled positive body.
        available=max(row.get('sampled_roof_points',0),row.get('building_surfaces',{}).get('original_representatives',0))
        if available<2*c.min_region_cells*c.min_cell_points:continue
        # Regions resolve mixed roofs precisely when no single flat-roof
        # estimate exists. Do not screen them through a previous height/mode.
        support=f.geometry
        overlap=[o.geometry for o in siblings.get(f.parent_id,[]) if o.key!=f.key and o.geometry is not None and o.geometry.is_valid and o.geometry.intersects(support)]
        if overlap:support=support.difference(unary_union(overlap))
        if support.is_empty:continue
        units.append(f);supports.append(support)
    progress('roof_regions',{'candidates':len(units)})
    if not units:return
    tree=STRtree(supports);stores=[{} for _ in units];total=0;roi=unary_union(supports)
    def consume(chunk,tx,query_cell=None):
        nonlocal total
        if len(chunk)>config.sampling.chunk_points:raise ValueError('Roof regions COPC query exceeds chunk_points; reduce sampling.cell_size_m')
        mask=np.ones(len(chunk),dtype=bool)
        x,y=map(np.asarray,tx.transform(np.asarray(chunk.x)[mask],np.asarray(chunk.y)[mask]));z=np.asarray(chunk.z)[mask]
        good=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
        if query_cell is not None:
            a,b,d,e=query_cell.bounds;good&=(x>=a)&(x<d)&(y>=b)&(y<e)
        x,y,z=x[good],y[good],z[good]
        pairs=tree.query(points(x,y),predicate='intersects')
        for unit in np.unique(pairs[1]):
            i=int(unit);idx=pairs[0,pairs[1]==i];lo=np.array(supports[i].bounds[:2])
            keys=np.floor((np.column_stack((x[idx],y[idx]))-lo)/c.cell_size_m).astype(np.int64)
            layers=np.floor(z[idx]/c.layer_step_m).astype(np.int64)
            grouped=np.column_stack((keys,layers));unique,inverse=np.unique(grouped,axis=0,return_inverse=True)
            counts=np.bincount(inverse);sums=np.bincount(inverse,weights=z[idx])
            for (ix,iy,layer),count,zz in zip(unique,counts,sums):
                key=(int(ix),int(iy));layer=int(layer)
                if key not in stores[i]:
                    if len(stores[i])>=c.max_cells_per_object or total>=c.max_total_cells:raise ValueError('roof_regions cell budget exceeded; raise explicit budget or partition inputs')
                    stores[i][key]={};total+=1
                column=stores[i][key]
                if column is None:continue
                if layer not in column and len(column)>=c.max_layers_per_cell:
                    stores[i][key]=None;continue
                n,s=column.get(layer,(0,0.));column[layer]=[n+int(count),s+float(zz)]
    for path in lidar_files(config.lidar,Path(root)):
        with laspy.open(path) as reader:
            source=reader.header.parse_crs()
            if source is None:raise ValueError('Roof regions require a declared source CRS')
            tx=Transformer.from_crs(source,working,always_xy=True)
            extent=box(*tx.transform_bounds(*reader.header.mins[:2],*reader.header.maxs[:2],densify_pts=21))
            if not extent.intersects(roi):continue
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
                        if not cell.intersects(extent) or not len(tree.query(cell,predicate='intersects')):continue
                        bounds=inverse.transform_bounds(*cell.bounds,densify_pts=21)
                        consume(reader.query(bounds=Bounds(np.array(bounds[:2]),np.array(bounds[2:]))),tx,cell)
        progress('roof_regions_file',{'file':path.name,'retained_cells':total})
    accepted=0;xy_origin=tuple(min(f.geometry.bounds[i] for f in features if f.geometry is not None and not f.issues) for i in (0,1))
    for f,support,store in zip(units,supports,stores):
        row=records[f.key];result=fit_roof_regions(f.geometry,support,store,row['ground_z'],row['reconstructed_top_z'],c,precision_m=config.precision_m,xy_origin=xy_origin)
        result.update(original_method=row['method'],original_roof_z=row['reconstructed_top_z'],original_flags=list(row['flags']))
        result['unusable_vertical_cells']=sum(layers is None for layers in store.values())
        if result['unusable_vertical_cells']:row['flags'].append('roof_regions_unusable_vertical_cells')
        result['retained_source_returns']=sum(v[0] for layers in store.values() if layers is not None for v in layers.values())
        row[strings.BuildingHeightFields.ROOF_REGIONS]=result
        if not result['accepted']:continue
        # Prove quantized extrusion viability before accepting this partition.
        from ..export.cityjson import Vertices
        from ..reconstruction.models import extrusion
        from shapely.geometry import shape
        vertex=Vertices(config.precision_m,(*f.geometry.bounds[:2],row['ground_z']))
        try:
            for region in result['regions']:extrusion(shape(region['footprint']),row['ground_z'],region['roof_z']-row['ground_z'],1,vertex)
        except ValueError:
            result['accepted']=False;result['reason']='non_extrudable_partition';result.pop('regions');continue
        accepted+=1
        if row['status']!=strings.ReconstructionObjectStatus.RESOLVED:
            stale={'no_roof_points','below_statistical_point_floor','no_floor_reference','ambiguous_floor_reference','no_attributable_roof_band','inferred_roof_unsupported'}
            row['flags']=[v for v in row['flags'] if v not in stale]
            row['flags'].append('recovered_from_mixed_roof_levels')
        row['status']=strings.ReconstructionObjectStatus.RESOLVED
        row['method']=strings.BuildingReconstructionMethod.ROOF_REGIONS
        row['reconstructed_top_z']=max(r['roof_z'] for r in result['regions'])
        row['height_m']=row['reconstructed_top_z']-row['ground_z'];row['roof_reference_z']=row['reconstructed_top_z']
        row['floor_height_m']=None;row['reference_part_id']=None;row['inferred_roof_support_fraction']=None
        row['reference_role']=strings.AuxiliaryHeightRole.COMPARISON
        reference=row.get('reference_height_m')
        row['delta_from_reference_m']=row['height_m']-reference if reference is not None else None
        row['flags'].append('inferred_internal_roof_regions')
    progress('roof_regions_complete',{'candidates':len(units),'accepted':accepted,'retained_cells':total})
