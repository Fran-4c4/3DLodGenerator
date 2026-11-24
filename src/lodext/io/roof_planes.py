"""Experimental spatial roof diagnostics; deliberately not wired into build.

Fit observed planes to bounded spatial representatives. This is evidence for a
possible LoD1 approximation, not roof ownership, a solid or LoD2 reconstruction.
"""
from dataclasses import dataclass, asdict
import math
import numpy as np
from shapely import intersects_xy


@dataclass(frozen=True)
class RoofPlaneReviewConfig:
    """Authoritative experimental defaults, serialized with every review.

    No production BuildConfig defaults are changed. All thresholds are inclusive.
    Changing them changes acceptance, resolution or fitting cost. Coordinates
    must already share a projected metre CRS and a common source-Z basis.
    """
    grid_axis: int = 24  # Integer >=4; normalized XY grid, at most axis**2 retained points per body.
    trials: int = 384  # Positive integer; deterministic three-point RANSAC hypotheses per plane.
    max_planes: int = 6  # Positive integer; maximum extracted surfaces, not an asserted roof count.
    residual_m: float = 0.18  # Metres >0; maximum vertical point-to-plane residual for inliers.
    min_plane_fraction: float = 0.12  # (0,1]; inliers per plane / all spatial representatives.
    min_supported_fraction: float = 0.7  # (0,1]; union of plane inliers / spatial representatives.
    min_footprint_coverage: float = 0.5  # (0,1]; inlier cells / support-grid centres inside the footprint.
    min_points: int = 40  # Integer >=3; minimum distinct occupied cells, never a raw point-density gate.
    min_slope_deg: float = 3.0  # Degrees [0,90); at least one substantial plane must reach this slope.
    max_slope_deg: float = 60.0  # Degrees >min and <90; reject near-vertical hypotheses.

    def __post_init__(self):
        """Reject invalid domains rather than clamp configuration."""
        for key in ('grid_axis','trials','max_planes','min_points'):
            v=getattr(self,key)
            if type(v) is not int or v < (4 if key=='grid_axis' else 3 if key=='min_points' else 1):
                raise ValueError(f'Invalid {key}')
        for key in ('residual_m','min_plane_fraction','min_supported_fraction','min_footprint_coverage','min_slope_deg','max_slope_deg'):
            v=getattr(self,key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError(f'Invalid {key}')
        if self.residual_m<=0 or not 0<=self.min_slope_deg<self.max_slope_deg<90:raise ValueError('Invalid residual/slope range')
        if any(not 0<getattr(self,k)<=1 for k in ('min_plane_fraction','min_supported_fraction','min_footprint_coverage')):raise ValueError('Invalid fraction')


def review_roof_planes(xyz, support, config=None):
    """Return auditable plane evidence from finite, inside-support source XYZ.

    Select the observed point nearest each grid-cell centre, never an average Z.
    Fit z=ax+by+c after local recentering. Refine RANSAC consensuses by least
    squares and remove inliers before fitting another plane. Require broad XY
    support and at least one sloped plane. The proposed flat LoD1 roof is the
    highest *fitted* Z at accepted observations, not extrapolation to corners or
    a raw maximum. It can overestimate most of a sloping roof and cannot define
    missing terraces. Excluded points retain their original classifications.

    Input selection must already exclude sibling overlays/known neighbours;
    this routine alone cannot attribute a plane to a particular building part.
    Representative storage and plane fitting are bounded by grid_axis**2; the
    caller owns input streaming. This review API does not stream its input.
    """
    c=RoofPlaneReviewConfig() if config is None else config
    xyz=np.asarray(xyz,dtype=float)
    if xyz.ndim!=2 or xyz.shape[1]!=3:raise ValueError('Expected an N by 3 XYZ array')
    if support.is_empty or not support.is_valid or support.area<=0:raise ValueError('Valid metric support required')
    xyz=xyz[np.isfinite(xyz).all(axis=1)]
    xyz=xyz[intersects_xy(support,xyz[:,0],xyz[:,1])]
    lo=np.array(support.bounds[:2]);extent=np.array(support.bounds[2:])-lo
    cell=np.minimum(c.grid_axis-1,((xyz[:,:2]-lo)/extent*c.grid_axis).astype(int))
    centre=lo+(cell+.5)*extent/c.grid_axis
    distance=np.sum((xyz[:,:2]-centre)**2,axis=1)
    ids=cell[:,0]+cell[:,1]*c.grid_axis
    order=np.lexsort((xyz[:,2],xyz[:,1],xyz[:,0],distance,ids))
    chosen=order[np.r_[True,np.diff(ids[order])!=0]] if len(order) else order
    points=xyz[chosen];origin=np.r_[lo,0.0];p=points-origin
    gx,gy=np.meshgrid(np.arange(c.grid_axis)+.5,np.arange(c.grid_axis)+.5)
    centres=lo+np.column_stack((gx.ravel(),gy.ravel()))*extent/c.grid_axis
    expected=int(intersects_xy(support,centres[:,0],centres[:,1]).sum())
    result={'experimental':True,'config':asdict(c),'raw_selected_points':len(xyz),'representatives':len(p),
            'expected_footprint_cells':expected,'planes':[],'supported_fraction':0.0,'footprint_coverage':0.0,
            'accepted':False,'proposed_lod1_roof_z':None,'ownership_established':False}
    if len(p)<c.min_points:return result
    rng=np.random.default_rng(0);remaining=np.arange(len(p));accepted=[];tops=[]
    for _ in range(c.max_planes):
        if len(remaining)<max(3,math.ceil(c.min_plane_fraction*len(p))):break
        q=p[remaining];design=np.column_stack((q[:,:2],np.ones(len(q))))
        triplets=np.array([rng.choice(len(q),3,replace=False) for _ in range(c.trials)])
        matrices=design[triplets];valid=np.abs(np.linalg.det(matrices))>1e-6
        if not valid.any():break
        coeff=np.linalg.solve(matrices[valid],q[triplets[valid],2][...,None])[...,0]
        slopes=np.degrees(np.arctan(np.linalg.norm(coeff[:,:2],axis=1)))
        coeff=coeff[slopes<=c.max_slope_deg]
        if not len(coeff):break
        residual=np.abs(design@coeff.T-q[:,2,None]);counts=(residual<=c.residual_m).sum(axis=0)
        best=int(np.argmax(counts));inside=residual[:,best]<=c.residual_m
        if inside.sum()<max(3,math.ceil(c.min_plane_fraction*len(p))):break
        beta=coeff[best]
        for _ in range(3):
            beta=np.linalg.lstsq(design[inside],q[inside,2],rcond=None)[0]
            inside=np.abs(design@beta-q[:,2])<=c.residual_m
            if inside.sum()<3:break
        slope=float(np.degrees(np.arctan(np.linalg.norm(beta[:2]))))
        if inside.sum()<max(3,math.ceil(c.min_plane_fraction*len(p))) or slope>c.max_slope_deg:break
        fitted=design[inside]@beta;accepted.extend(remaining[inside]);tops.append(float(fitted.max()))
        result['planes'].append({'slope_deg':slope,'cells':int(inside.sum()),'rmse_m':float(np.sqrt(np.mean((fitted-q[inside,2])**2))),
                                 'local_coefficients':beta.tolist(),'xy_origin':lo.tolist(),  # z=a*(x-origin_x)+b*(y-origin_y)+c, source metres; used for independent spatial support checks, never global-coordinate extrapolation.
                                 'observed_z_range':[float(q[inside,2].min()),float(q[inside,2].max())],
                                 'fitted_upper_z':float(fitted.max())})
        remaining=remaining[~inside]
    result['supported_fraction']=len(accepted)/len(p)
    result['footprint_coverage']=min(1.0,len(accepted)/max(1,expected))
    result['accepted']=(result['supported_fraction']>=c.min_supported_fraction and result['footprint_coverage']>=c.min_footprint_coverage
                        and any(plane['slope_deg']>=c.min_slope_deg for plane in result['planes']))
    if result['accepted']:result['proposed_lod1_roof_z']=max(tops)
    return result
