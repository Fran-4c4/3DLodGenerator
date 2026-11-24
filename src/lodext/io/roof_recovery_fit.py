"""Spatial consensuses over bounded XY/elevation-layer representatives."""
import math
import numpy as np


def fit_recovery_planes(xyz,config):
    """Fit substantial low-slope planes without collapsing distinct Z layers.

    Working-metre XYZ are bounded by the caller's cell/layer budgets. Return
    per-plane local coefficients, original XY origin, inlier count, residual
    RMSE and upper fitted elevation at accepted observations. No corner
    extrapolation, storey conversion, point classification or source writes.
    These consensuses are evidence; geometry outside the footprint is absent.
    """
    c=config;origin=xyz[:,:2].min(axis=0);p=xyz.copy();p[:,:2]-=origin
    remaining=np.arange(len(p));rng=np.random.default_rng(0);planes=[]
    # The spatial surface policy owns an additional absolute plane-support floor.
    # Other callers retain the mathematical three-point minimum of their policy.
    minimum=max(getattr(c,'min_plane_points',3),math.ceil(c.min_plane_fraction*len(p)))
    for _ in range(c.max_planes):
        if len(remaining)<minimum:break
        q=p[remaining];design=np.column_stack((q[:,:2],np.ones(len(q))))
        triples=np.array([rng.choice(len(q),3,replace=False) for _ in range(c.trials)])
        matrices=design[triples];valid=np.abs(np.linalg.det(matrices))>1e-6
        if not valid.any():break
        beta=np.linalg.solve(matrices[valid],q[triples[valid],2][...,None])[...,0]
        slope=np.degrees(np.arctan(np.linalg.norm(beta[:,:2],axis=1)));beta=beta[slope<=c.max_slope_deg]
        if not len(beta):break
        residual=np.abs(design@beta.T-q[:,2,None]);best=int(np.argmax((residual<=c.residual_m).sum(axis=0)))
        inside=residual[:,best]<=c.residual_m
        if inside.sum()<minimum:break
        coeff=beta[best]
        for _ in range(3):
            coeff=np.linalg.lstsq(design[inside],q[inside,2],rcond=None)[0]
            inside=np.abs(design@coeff-q[:,2])<=c.residual_m
            if inside.sum()<minimum:break
        slope=float(np.degrees(np.arctan(np.linalg.norm(coeff[:2]))))
        if inside.sum()<minimum or slope>c.max_slope_deg:break
        fitted=design[inside]@coeff
        planes.append({'local_coefficients':coeff.tolist(),'xy_origin':origin.tolist(),'slope_deg':slope,
                       'cells':int(inside.sum()),'rmse_m':float(np.sqrt(np.mean((fitted-q[inside,2])**2))),
                       'fitted_upper_z':float(fitted.max()),'observed_z_range':[float(q[inside,2].min()),float(q[inside,2].max())]})
        remaining=remaining[~inside]
    return {'planes':planes}
