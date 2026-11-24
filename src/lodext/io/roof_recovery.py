"""Bounded, streaming alternative-class roof evidence for received footprints."""
from collections import Counter
import math
import numpy as np
from shapely import STRtree,points
from shapely.geometry import box
from shapely.ops import unary_union
from lodext import strings


class RoofRecoveryAccumulator:
    """Keep original XYZ/class representatives, never a full point-cloud copy.

    Each unit has bounded original representatives per metric cell/Z layer. Explicit overlapping
    sibling geometry is excluded without inferring vertical stacking. The run
    owns this transient accumulator; only aggregate evidence enters outputs.
    """
    def __init__(self,units,supports,config,budget=None):
        """Build bounded stores; an optional shared [occupied-cell count] pools roles.

        The mutable one-element counter is internal run state, not configuration.
        Sharing requires the same policy; allocations check its hard cap first.
        """
        self.config=config;self.units=units;self.cells=[{} for _ in units];self.counts=[Counter() for _ in units]
        self.moments=[{} for _ in units]  # Per retained cell/layer (count, sum Z, sum Z squared); raw vertical spread, not a point cache.
        self.overflow=set();self.total=0
        self.budget=[0] if budget is None else budget  # Shared occupied-cell count across recovery roles; cleared on owned-store release.
        siblings={}
        for f in units:siblings.setdefault(f.parent_id or f.id,[]).append(f)
        self.supports=[]
        for f,(g,_) in zip(units,supports):
            others=[o.geometry for o in siblings[f.parent_id or f.id] if o.key!=f.key and o.geometry.intersects(g)]
            self.supports.append(g.difference(unary_union(others)) if others else g)
        self.tree=STRtree(self.supports)

    def add(self,x,y,z,classes):
        """Consume finite working-metre arrays; retain source class and coordinates."""
        c=self.config;eligible=np.arange(len(z))
        if not len(eligible):return
        pairs=self.tree.query(points(x[eligible],y[eligible]),predicate='intersects')
        for unit in np.unique(pairs[1]):
            i=int(unit)
            if i in self.overflow:continue
            idx=eligible[pairs[0,pairs[1]==i]];self.counts[i].update(map(int,classes[idx]))
            lo=np.array(self.supports[i].bounds[:2]);xy=np.column_stack((x[idx],y[idx]));cell=np.floor((xy-lo)/c.cell_size_m).astype(int)
            centres=lo+(cell+.5)*c.cell_size_m;dist=np.sum((xy-centres)**2,axis=1)
            # One batch representative per cell, deterministic across ordering
            # and read-chunk boundaries; never an interpolated coordinate/Z.
            bins=np.floor(z[idx]/c.layer_step_m).astype(int)
            order=np.lexsort((z[idx],y[idx],x[idx],dist,bins,cell[:,1],cell[:,0]))
            grouped=np.column_stack((cell[order],bins[order]));first=np.r_[True,np.any(grouped[1:]!=grouped[:-1],axis=1)]
            starts=np.flatnonzero(first);sizes=np.diff(np.r_[starts,len(order)])
            sums=np.add.reduceat(z[idx[order]],starts);squares=np.add.reduceat(z[idx[order]]**2,starts)
            for position,n,total,sq in zip(starts,sizes,sums,squares):
                k=order[position];key=tuple(map(int,cell[k]));layer=int(bins[k]);j=idx[k]
                value=(float(dist[k]),float(x[j]),float(y[j]),float(z[j]),int(classes[j]))
                if key not in self.cells[i]:
                    if len(self.cells[i])>=c.max_cells_per_object:
                        self.total-=len(self.cells[i]);self.budget[0]-=len(self.cells[i]);self.cells[i].clear();self.moments[i].clear();self.overflow.add(i);break
                    if self.budget[0]>=c.max_total_cells:raise ValueError('roof_recovery max_total_cells exceeded; increase explicit budget or partition input')
                    self.total+=1;self.budget[0]+=1;self.cells[i][key]={};self.moments[i][key]={}
                layers=self.cells[i][key]
                if layers is None:continue
                if layer not in layers and len(layers)>=c.max_layers_per_cell:
                    self.cells[i][key]=None;self.moments[i][key].clear();continue
                if layer not in layers or value<layers[layer]:layers[layer]=value
                old=self.moments[i][key].get(layer,(0,0.,0.))
                self.moments[i][key][layer]=(old[0]+int(n),old[1]+float(total),old[2]+float(sq))

    def estimate(self,i,ground,storeys,height_policy,primary_count,coverage):
        """Return decision/evidence; no manufactured ground or storey-derived roof.

        Output accepted/reason describe selection, not source-class mutation.
        source_class_counts counts original returns; retained_cells is bounded.
        roof_z (metres or null) is a supported observed-plane envelope. Coverage
        measures support-intersection area of explained metric cells; support
        fraction counts XY/Z layers, not raw point density or accuracy. Storeys
        provide only a permissive HeightConfig range with explicit metre slack.
        """
        c=self.config;cells=self.cells[i];support=self.supports[i]
        result={'accepted':False,'reason':'not_checked','source_class_counts':dict(self.counts[i]),'retained_cells':len(cells),
                'roof_z':None,'supported_fraction':None,'area_coverage':None,'source_classes_preserved':True}
        def reject(reason):result['reason']=reason;return result
        if primary_count:return reject('primary_roof_points_present')
        if not coverage:return reject('incomplete_lidar_coverage')
        if ground is None:return reject('missing_ground')
        if not storeys:return reject('missing_positive_storeys')
        if i in self.overflow:return reject('representative_budget_exceeded')
        if len(cells)<c.min_cells or support.is_empty:return reject('insufficient_spatial_support')
        representatives=[(key,layer,layers[layer]) for key,layers in sorted(cells.items()) if layers is not None for layer in sorted(layers)]
        if len(representatives)<c.min_cells:return reject('insufficient_spatial_support')
        xyz=np.array([v[1:4] for _,_,v in representatives])
        stable=np.array([math.sqrt(max(0.,sq/n-(total/n)**2))<=c.local_std_m
                         for n,total,sq in (self.moments[i][key][layer] for key,layer,_ in representatives)])
        result['retained_layers']=len(representatives);result['stable_layers']=int(stable.sum())
        if stable.sum()<c.min_cells:return reject('excessive_local_vertical_scatter')
        # Preserve every stable layer for fitting: the XY-only review helper's
        # decimation would discard the lower roof under terrace furniture.
        from .roof_recovery_fit import fit_recovery_planes
        fit=fit_recovery_planes(xyz[stable],c)
        result['planes']=fit['planes']
        if not fit['planes']:return reject('no_coherent_surface')
        explained=np.zeros(len(xyz),dtype=bool)
        for plane in fit['planes']:
            a,b,d=plane['local_coefficients'];ox,oy=plane['xy_origin']
            explained|=np.abs(a*(xyz[:,0]-ox)+b*(xyz[:,1]-oy)+d-xyz[:,2])<=c.residual_m
        explained&=stable
        fraction=float(explained.mean());area=0.0;lo=np.array(support.bounds[:2])
        for key in {key for (key,_,_),good in zip(representatives,explained) if good}:
            corner=lo+np.array(key)*c.cell_size_m
            area+=box(*corner,*(corner+c.cell_size_m)).intersection(support).area
        result['supported_fraction']=fraction;result['area_coverage']=area/support.area
        if fraction<c.min_supported_fraction or area/support.area<c.min_coverage:return reject('insufficient_coherent_coverage')
        top=max(p['fitted_upper_z'] for p in fit['planes']);height=top-ground
        result['storey_height_range_m']=[max(height_policy.near_zero_m,storeys*height_policy.min_floor_height_m-c.storey_tolerance_m),storeys*height_policy.max_floor_height_m+c.storey_tolerance_m]
        low,high=result['storey_height_range_m']
        if height<=0 or not low<=height<=high:return reject('storey_height_conflict')
        result.update(accepted=True,reason='coherent_footprint_surface',roof_z=top)
        return result

    def finish(self,samples,build_config):
        """Attach decisions to samples after ground/coverage are known; clear storage."""
        for i,f in enumerate(self.units):
            sample=samples[f.key]
            from ..core.heights import modal_roof
            primary=sample['roof_z'];mode,strength,mixed=modal_roof(tuple(primary),build_config.height)
            # A handful of primary-class returns or a weak/mixed histogram is
            # not a reliable roof and must not veto coherent alternative classes.
            # Original primary points remain in samples and ordinary estimates.
            trusted=len(primary)>=build_config.height.min_points_absolute and strength>=build_config.height.min_mode_strength and not mixed
            sample[strings.BuildingHeightFields.ROOF_RECOVERY]=self.estimate(i,sample['ground_z'],f.properties['storeys_above'],build_config.height,len(primary) if trusted else 0,sample['coverage_complete'])
        self.budget[0]-=self.total;self.cells.clear();self.moments.clear();self.total=0
