"""Streaming class-neutral exterior surfaces for building bases and terrain."""
from collections import Counter
from lodext import strings
from types import SimpleNamespace
import numpy as np
from shapely import STRtree, points
from shapely.geometry import Point
from .ground_accumulator import GroundPointAccumulator
from .roof_recovery_fit import fit_recovery_planes


class GeometricGroundAccumulator(GroundPointAccumulator):
    """Keep bounded cell/layer statistics, then test geometric lower surfaces.

    No class code participates in selection. Cells retain actual observations;
    the display TIN is a separate reduction and never supplies building bases.
    The inherited histogram budget caps all retained cell/elevation layers.
    """
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.layers={}  # XY key -> Z-layer -> (count, original representative); bounded by max_histogram_bins.
        self.ground_xyz=np.empty((0,3))  # Coherent original exterior representatives; independent of display cell size.

    def add(self,x,y,z,classes,path,source,records,sx,sy,sz):
        """Aggregate all finite exterior XYZ, retaining original labels for audit."""
        xy=points(x,y);pairs=self.obstacles.query(xy,predicate='intersects')
        blocked=np.zeros(len(x),dtype=bool)
        if pairs.shape[1]:blocked[pairs[0]]=True
        self.counts['inside_building']+=int(blocked.sum())
        self.counts['exterior_candidates']+=int((~blocked).sum())
        ids=np.flatnonzero(~blocked)
        if len(ids):
            size=self.policy.geometric_cell_size_m
            keys=np.floor(np.column_stack((x[ids],y[ids]))/size).astype(np.int64)
            zs=np.floor(z[ids]/self.policy.layer_step_m).astype(np.int64)
            dist=((np.column_stack((x[ids],y[ids]))-(keys+.5)*size)**2).sum(axis=1)
            order=np.lexsort((z[ids],y[ids],x[ids],dist,zs,keys[:,1],keys[:,0]))
            grouped=np.column_stack((keys[order],zs[order]));first=np.r_[True,np.any(grouped[1:]!=grouped[:-1],axis=1)]
            starts=np.flatnonzero(first);counts=np.diff(np.r_[starts,len(order)])
            for start,n in zip(starts,counts):
                k=order[start];i=ids[k];key=tuple(map(int,keys[k]));layer=int(zs[k])
                bucket=self.layers.setdefault(key,{})
                value=(float(dist[k]),float(x[i]),float(y[i]),float(z[i]))
                if layer not in bucket:
                    if self.bin_count>=self.policy.max_histogram_bins:
                        raise ValueError('Geometric ground exceeds max_histogram_bins; partition input or increase explicit budget')
                    self.bin_count+=1;bucket[layer]=(int(n),value)
                else:
                    count,old=bucket[layer];bucket[layer]=(count+int(n),min(old,value))
            self.peak_bins=max(self.peak_bins,self.bin_count)
        if self.policy.export_points:
            count=min(len(x),self.policy.max_export_points-len(self.audit_rows))
            for i in range(count):
                self.audit_rows.append((float(x[i]),float(y[i]),float(z[i]),int(classes[i]),
                    'inside_building' if blocked[i] else strings.GroundPointDecision.GEOMETRY_CANDIDATE,path,source.to_epsg(),
                    None if records[i] is None else int(records[i]),float(sx[i]),float(sy[i]),float(sz[i])))

    def finish(self):
        """Select supported lower layers and reject isolated nonplanar patches."""
        selected=[];keys=[]
        for key,layers in sorted(self.layers.items()):
            good=[(layer,v) for layer,v in layers.items() if v[0]>=self.policy.min_layer_returns]
            if not good:continue
            _,(_,v)=min(good)
            keys.append(key);selected.append(v[1:])
        self.layers.clear()
        xyz=np.asarray(selected,dtype=float).reshape(-1,3)
        index={key:i for i,key in enumerate(keys)};accepted=np.zeros(len(xyz),dtype=bool)
        # A fixed 5x5 lattice neighbourhood is measured in the owner's metric
        # cell size. Least squares is iteratively trimmed by vertical residual;
        # no absolute-elevation or horizontal-ground assumption is made.
        offsets=[(a,b) for a in range(-2,3) for b in range(-2,3)]
        for start in range(0,len(keys),4096):
            batch=keys[start:start+4096]
            ids=np.array([[index.get((k[0]+a,k[1]+b),-1) for a,b in offsets] for k in batch])
            valid=ids>=0;q=xyz[np.maximum(ids,0)];origin=xyz[start:start+len(batch)]
            design=np.concatenate((q[:,:,:2]-origin[:,None,:2],np.ones((*ids.shape,1))),axis=2)
            mask=valid.copy();beta=np.zeros((len(batch),3))
            for _ in range(3):
                weighted=design*mask[:,:,None]
                normal=np.einsum('nki,nkj->nij',weighted,design)
                rhs=np.einsum('nki,nk->ni',weighted,q[:,:,2])
                beta=np.einsum('nij,nj->ni',np.linalg.pinv(normal),rhs)
                residual=np.abs(np.einsum('nki,ni->nk',design,beta)-q[:,:,2])
                mask=valid&(residual<=self.policy.surface_residual_m)
            slope=np.degrees(np.arctan(np.linalg.norm(beta[:,:2],axis=1)))
            rank=np.linalg.matrix_rank(np.einsum('nki,nkj->nij',design*mask[:,:,None],design))
            accepted[start:start+len(batch)]=(mask.sum(axis=1)>=3)&(rank==3)&(slope<=self.policy.max_slope_deg)&(np.abs(beta[:,2]-origin[:,2])<=self.policy.surface_residual_m)
        self.ground_xyz=xyz[accepted]
        self.ground_tree=STRtree(points(self.ground_xyz[:,0],self.ground_xyz[:,1]))
        self.counts['coherent_exterior_cells']=int(accepted.sum())
        if self.policy.export_surface:
            size=self.policy.surface_cell_size_m
            for x,y,z in self.ground_xyz:
                key=(int(np.floor(x/size)),int(np.floor(y/size)))
                value=(float((x-(key[0]+.5)*size)**2+(y-(key[1]+.5)*size)**2),(float(x),float(y),float(z)))
                if key not in self.cells or value<self.cells[key]:self.cells[key]=value
            if len(self.cells)>self.policy.max_surface_vertices:
                raise ValueError('Ground surface exceeds max_surface_vertices; partition input or change display resolution/budget')
        super().finish()

    def estimate(self,i):
        """Project the nearest supported local exterior plane to this footprint.

        Only a bounded nearest set within the configured search rings is fitted.
        Hills remain sloped; another street level cannot win by point count alone.
        An unsupported interior base remains missing for explicit adjacency inference.
        """
        g=self.geometries[i]
        common={strings.PointGroundFields.METHOD:strings.PointGroundMethod.GEOMETRIC_EXTERIOR_PLANE,'ground_median_error_bound_m':None,
                'ground_excluded_inside_buildings':None}
        fitpolicy=SimpleNamespace(max_planes=4,min_plane_points=3,min_plane_fraction=.2,
            trials=64,max_slope_deg=self.policy.max_slope_deg,residual_m=self.policy.surface_residual_m)
        fallback=None
        validated_samples=max(self.sampling.min_ground_samples,4)
        for j,radius in enumerate(self.sampling.ground_buffers_m):
            if self.free_area(i,j)<self.sampling.min_free_area_m2:continue
            ids=self.ground_tree.query(g.buffer(radius),predicate='intersects')
            if len(ids)<self.sampling.min_ground_samples:continue
            q=self.ground_xyz[ids]
            distances=np.array([g.distance(Point(x,y)) for x,y in q[:,:2]])
            order=np.lexsort((q[:,2],q[:,1],q[:,0],distances))[:64]
            q=q[order];distances=distances[order]
            fitted=fit_recovery_planes(q,fitpolicy)['planes'];choices=[]
            for p in fitted:
                a,b,d=p['local_coefficients'];ox,oy=p['xy_origin']
                residual=np.abs(a*(q[:,0]-ox)+b*(q[:,1]-oy)+d-q[:,2]);inside=residual<=fitpolicy.residual_m
                if inside.sum()<self.sampling.min_ground_samples:continue
                # LoD1 has one horizontal base. On sloping terrain its lowest
                # coherent exterior contact prevents the solid from floating;
                # projecting the plane to the footprint centre can place the
                # base above a real lower roof/access level. ``inside`` has
                # already removed non-planar and vertically incompatible cells.
                z=float(q[inside,2].min())
                choices.append(((float(np.median(distances[inside])),-int(inside.sum()),p['rmse_m']),z,p,inside))
            if choices:
                validated=[choice for choice in choices if choice[3].sum()>=validated_samples]
                # LoD1 uses one flat base. Among independently validated local
                # planes, the lowest coherent contact represents the downhill
                # access and prevents a body on a slope from floating. Distance
                # and support resolve only equal-elevation alternatives.
                _,z,p,inside=min(validated or choices,key=lambda v:(v[1],v[0]))
                result={**common,'ground_z':z,'ground_samples':int(inside.sum()),'ground_candidates':len(q),
                    'ground_radius_m':radius,'ground_free_area_m2':self.free_area(i,j),
                    'ground_min_z':float(q[inside,2].min()),'ground_max_z':float(q[inside,2].max()),
                    strings.PointGroundFields.PLANE:p}
                # Three observations determine a plane exactly and therefore
                # cannot validate its residual. Keep that nearest result as a
                # last resort, but inspect wider configured rings for a plane
                # with at least one independent control before accepting it.
                if inside.sum()>=validated_samples:return result
                if fallback is None:fallback=result
        if fallback is not None:return fallback
        return {**common,'ground_z':None,'ground_samples':0,'ground_candidates':0,
                'ground_radius_m':None,'ground_free_area_m2':0.,'ground_min_z':None,'ground_max_z':None}
