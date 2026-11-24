"""Independent class lifting and boundary-constrained surface triangulation.

Original implementation of documented rank lifting/quadratic fitting concepts;
no reference engine source is incorporated. Scene stitching is not applied here.
"""
from lodext import strings
from collections import Counter
import math

import numpy as np
from shapely import constrained_delaunay_triangles, contains_xy, intersects_xy
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


class SurfaceUnresolved(ValueError):
    """Insufficient observations, distinct from invalid input or mesh failure."""


def rank_elevation(values, percentile):
    """Select an observed metre Z at floor(n*p/100), capped to n−1 for p=100.

    Discard non-finite observations; raise SurfaceUnresolved if none remain.
    The caller supplies a percentile validated by LiftingPolicy. No interpolation
    or Z rounding occurs, so the result preserves an actual observation.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        raise SurfaceUnresolved("no_elevation_observations")
    k = min(len(values) - 1, math.floor(len(values) * percentile / 100))
    return float(np.partition(values, k)[k])


def smooth_road(xy, elevations, config):
    """Fit a centred/scaled quadratic; explicit skip/revert, no invented plane.

    Iteratively exclude the largest residual beyond two residual standard
    deviations. A fit needs six independent coefficients and cannot exclude
    more than the configured fraction. A flat fit changes all Z; filtering
    changes excluded Z only. Quantity/rank/fraction failure retains input Z.
    """
    raw = np.asarray(elevations, dtype=float)
    info = {strings.RoadFitFields.STATUS: "disabled", "outlier_vertices": [], "changed_vertices": 0}
    if not (config.road_filter_outliers or config.road_flatten):
        return raw, info
    if len(raw) < 6:
        return raw, {**info, strings.RoadFitFields.STATUS: "skipped_insufficient_vertices"}
    xy = np.asarray(xy, dtype=float)
    local = xy - xy.mean(axis=0)
    extent = float(np.max(np.ptp(local, axis=0)))
    if extent <= 0:
        return raw, {**info, strings.RoadFitFields.STATUS: "skipped_rank_deficient"}
    x, y = (local / extent).T
    design = np.column_stack((np.ones(len(x)), x, y, x*x, x*y, y*y))
    keep = np.ones(len(raw), dtype=bool)
    while True:
        coefficients, _, rank, _ = np.linalg.lstsq(design[keep], raw[keep], rcond=None)
        if rank < 6:
            return raw, {**info, strings.RoadFitFields.STATUS: "skipped_rank_deficient"}
        fitted = design @ coefficients
        residual = np.abs(raw - fitted)
        sigma = float(np.std((raw - fitted)[keep]))
        selected = np.flatnonzero(keep)
        worst = int(selected[np.argmax(residual[keep])])
        if residual[worst] <= max(2 * sigma, 1e-9):
            break
        proposed = int((~keep).sum()) + 1
        if proposed / len(raw) > config.max_outlier_fraction or int(keep.sum()) <= 6:
            return raw, {**info, strings.RoadFitFields.STATUS: "reverted_outlier_fraction_or_fit_support"}
        keep[worst] = False
    result = fitted if config.road_flatten else np.where(keep, raw, fitted)
    return result, {strings.RoadFitFields.STATUS: "flattened" if config.road_flatten else "filtered",
                    "outlier_vertices": list(map(int, np.flatnonzero(~keep))),
                    "changed_vertices": int(np.count_nonzero(np.abs(result - raw) > 1e-9)),
                    "fit_rms_m": float(np.sqrt(np.mean((raw[keep] - fitted[keep])**2)))}


def lift_boundary(rings, points, policy, config):
    """Lift non-repeated XY ring vertices from class-filtered metric XYZ points.

    Select observations within the inclusive XY radius and use policy's observed
    rank for each vertex. Unsupported vertices may borrow from the nearest
    supported vertex by cyclic distance within their own ring (lower index wins
    a tie). An unsupported whole ring or strict missing-vertex policy raises
    SurfaceUnresolved; support is never borrowed across holes/components.

    Return flattened XY, aligned Z, raw support counts and flattened borrowed
    indices. Inputs and point classes are not modified or inferred here.
    """
    xy = np.asarray([p for ring in rings for p in ring], dtype=float)
    counts, elevations = [], []
    radius2 = config.radius_m ** 2
    for p in xy:
        selected = points[np.sum((points[:, :2] - p)**2, axis=1) <= radius2, 2]
        counts.append(len(selected))
        elevations.append(rank_elevation(selected, policy.percentile) if len(selected) else None)
    borrowed = []
    offset = 0
    for ring in rings:
        supported = [i for i in range(len(ring)) if elevations[offset+i] is not None]
        if not supported:
            raise SurfaceUnresolved("ring_without_elevation_support")
        for i in range(len(ring)):
            if elevations[offset+i] is None:
                if config.missing_vertices == strings.InputFailurePolicy.ERROR:
                    raise SurfaceUnresolved("unsupported_boundary_vertex")
                neighbour = min(supported, key=lambda j: (min((i-j) % len(ring), (j-i) % len(ring)), j))
                elevations[offset+i] = elevations[offset+neighbour]
                borrowed.append(offset+i)
        offset += len(ring)
    return xy, np.asarray(elevations), counts, borrowed


def _upward(coords):
    """Order one nondegenerate XY triangle counterclockwise for upward normals."""
    a, b, c = coords
    area2 = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    return (a, b, c) if area2 > 0 else (a, c, b)


def constrained_mesh(polygon, boundary_z, interior, max_vertices):
    """Constrained boundary mesh with original interior points, no thinning.

    Start from a constrained polygon triangulation. Each interior insertion
    splits ALL incident triangles (two on a shared edge), preventing T-junctions.
    Exact duplicate XY observations are grouped before this function. Boundary
    Z takes precedence at identical XY. The explicit small-mesh budget bounds
    this initial implementation; it is not yet the scalable terrain engine.
    """
    z = dict(boundary_z)
    for x, y, height in interior:
        z.setdefault((float(x), float(y)), float(height))
    if len(z) > max_vertices:
        raise ValueError("max_tin_vertices exceeded; no automatic thinning")
    triangles = [tuple(tuple(p) for p in list(t.exterior.coords)[:3])
                 for t in constrained_delaunay_triangles(polygon).geoms]
    inserted = set(boundary_z)
    for point in sorted(z):
        if point in inserted:
            continue
        position = Point(point)
        touched = [i for i, t in enumerate(triangles) if Polygon(t).covers(position)]
        if not touched:
            raise ValueError("Interior point is not covered by the constrained triangulation")
        additions = []
        for i in touched:
            triangle = triangles[i]
            for j in range(3):
                candidate = (triangle[j], triangle[(j+1) % 3], point)
                if Polygon(candidate).area > 1e-12:
                    additions.append(candidate)
        rejected = set(touched)
        triangles = [t for i, t in enumerate(triangles) if i not in rejected] + additions
        inserted.add(point)
    triangles = [_upward(t) for t in triangles]
    shapes = [Polygon(t) for t in triangles]
    area = sum(t.area for t in shapes)
    covered = unary_union(shapes)
    tolerance = max(1e-8, polygon.area * 1e-9)
    if (abs(area - polygon.area) > tolerance or abs(area - covered.area) > tolerance
            or covered.symmetric_difference(polygon).area > tolerance):
        raise ValueError("Surface triangulation changes footprint coverage or overlaps")
    edges = Counter((a, b) for t in triangles for a, b in zip(t, t[1:] + t[:1]))
    for (a, b), number in edges.items():
        opposite = edges[(b, a)]
        if number != 1 or (opposite != 1 and not polygon.boundary.covers(LineString([a, b]))):
            raise ValueError("Surface triangulation has a non-manifold edge or T-junction")
    return [[[x, y, z[(x, y)]] for x, y in t] for t in triangles]


def reconstruct_surface(feature, points, config):
    """Return per-component XYZ triangle meshes and auditable lifting evidence.

    feature supplies the full metric XY footprint; points is its class-filtered
    XYZ support including the search halo. Roads lift boundary vertices and may
    apply quadratic smoothing. Terrain/Forest also insert interior observations,
    combining coincident XY by observed rank. Water shares one horizontal rank
    elevation across every component. Source holes/components remain intact.

    Missing support raises SurfaceUnresolved; vertex-budget/topology failures
    raise ValueError. Output retains support counts, borrowed indices, raw/final
    elevations and fit diagnostics. No quantisation, file writes, inter-object
    stitching or vertical-datum transformation happens at this stage.
    """
    geometry, kind = feature.geometry, feature.surface_class
    policy = config.lifting[kind]
    if not len(points):
        raise SurfaceUnresolved("no_points_in_selected_classes")
    components = list(geometry.geoms) if geometry.geom_type == strings.PolygonGeometryType.MULTI_POLYGON else [geometry]
    common_water = None
    if kind == strings.SurfaceObjectClass.WATER:
        selected = intersects_xy(geometry, points[:, 0], points[:, 1])
        for polygon in components:
            for ring in [polygon.exterior, *polygon.interiors]:
                for x, y in list(ring.coords)[:-1]:
                    selected |= np.sum((points[:, :2] - [x, y])**2, axis=1) <= config.radius_m**2
        common_water = rank_elevation(points[selected, 2], policy.percentile)
    meshes, evidence = [], []
    for original in components:
        polygon = orient(original, sign=1)
        rings = [list(polygon.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in polygon.interiors]
        if sum(map(len, rings)) > config.max_tin_vertices:
            raise ValueError("max_tin_vertices exceeded by the source boundary")
        if common_water is None:
            xy, heights, counts, borrowed = lift_boundary(rings, points, policy, config)
        else:
            xy = np.asarray([p for ring in rings for p in ring])
            heights = np.full(len(xy), common_water)
            counts, borrowed = [], []
        raw = heights.copy()
        fit = {strings.RoadFitFields.STATUS: "not_applicable"}
        if kind == strings.SurfaceObjectClass.ROAD:
            heights, fit = smooth_road(xy, heights, config)
        interior = []
        duplicates = 0
        if kind in (strings.SurfaceObjectClass.TERRAIN, strings.SurfaceObjectClass.FOREST):
            inside = points[contains_xy(polygon, points[:, 0], points[:, 1])]
            # Group coincident XY without changing support positions. Deterministic
            # observed rank selection records how multiple returns are combined.
            grouped = {}
            for x, y, z in inside:
                grouped.setdefault((float(x), float(y)), []).append(float(z))
            duplicates = len(inside) - len(grouped)
            interior = [(x, y, rank_elevation(values, policy.percentile)) for (x, y), values in grouped.items()]
        boundary = {tuple(map(float, p)): float(z) for p, z in zip(xy, heights)}
        triangles = constrained_mesh(polygon, boundary, interior, config.max_tin_vertices)
        meshes.append(triangles)
        evidence.append({"boundary_vertices": len(xy), "boundary_support_counts": counts,
                         "borrowed_boundary_indices": borrowed, "raw_boundary_z": raw.tolist(),
                         "boundary_z": heights.tolist(), "interior_xy_observations": len(interior),
                         "coincident_xy_returns_combined": duplicates, "road_fit": fit,
                         strings.MeshValidationFields.TRIANGLE_COUNT: len(triangles)})
    return meshes, {strings.SurfaceReconstructionFields.METHOD: "flat_rank" if kind == strings.SurfaceObjectClass.WATER else "boundary_rank_tin" if kind in (strings.SurfaceObjectClass.TERRAIN, strings.SurfaceObjectClass.FOREST) else "boundary_rank",
                    strings.SurfaceReconstructionFields.SAMPLE_POINTS: len(points), "water_level_z": common_water,
                    strings.SurfaceReconstructionFields.COMPONENTS: evidence, strings.MeshValidationFields.TRIANGLE_COUNT: sum(len(m) for m in meshes),
                    strings.PolygonFootprintFields.AREA_M2: float(geometry.area)}
