"""Read-only surface polygons and full-resolution local point observations."""
from lodext import strings
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import struct

import laspy
from laspy.copc import Bounds
import numpy as np
from pyproj import CRS, Transformer
from shapely import STRtree, intersects_xy
from shapely.geometry import box
from shapely.ops import transform, unary_union

from ..core.surfaces import DEFAULT_LIFTING
from .footprints import gpkg_geometry, metric_working_crs, quote
from .sampling import lidar_files


@dataclass(frozen=True)
class SurfaceFeature:
    """Normalised input: class-qualified TEXT identity and complete metric XY shape.

    id is source surface_id, unmodified; surface_class is a supported exact key.
    geometry is valid positive-area Polygon/MultiPolygon, with every ring retained.
    A sampler never replaces it with an envelope or buffer. key is reversible.
    """
    id: str  # Original nonempty surface_id text; unique together with surface_class.
    surface_class: str  # Exact supported class key; selects lifting policy and export type.
    geometry: object  # Complete valid positive-area metric XY polygon(s), retaining holes/components.

    @property
    def key(self):
        """Return the class-qualified source key shared by sampling and export."""
        return f"{self.surface_class}{strings.SourceObjectIdentity.IDENTITY_SEPARATOR}{self.id}"


def read_surfaces(config, root):
    """Read canonical surface polygons without modification; return (features, CRS).

    Resolve the GPKG from root; require nonempty text IDs, supported exact class
    keys, unique class/ID pairs, declared CRS and valid positive-area XY polygon
    geometry. Check blob/layer CRS agreement, then transform to projected metres
    while retaining holes/components. Every contract violation raises rather
    than repairing geometry, guessing classes or silently excluding a row.
    """
    working = metric_working_crs(config.working_epsg)
    path = (Path(root) / config.polygons).resolve()
    if not path.is_file():
        raise ValueError("Surface GeoPackage does not exist")
    result, seen = [], set()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        info = connection.execute(
            strings.GeoPackageMetadataQueries.GEOMETRY_METADATA,
            (config.layer,)).fetchone()
        if not info or info[2].upper() not in ("POLYGON", "MULTIPOLYGON") or info[3] or info[4]:
            raise ValueError("Surface layer must declare Polygon/MultiPolygon XY")
        column, srid = info[:2]
        names = {r[1] for r in connection.execute(f"PRAGMA table_info({quote(config.layer)})")}
        if not {column, "surface_id", "surface_class"} <= names:
            raise ValueError("Surface layer requires surface_id TEXT and surface_class TEXT")
        srs = connection.execute(
            strings.GeoPackageMetadataQueries.CRS_METADATA,
            (srid,)).fetchone()
        if not srs:
            raise ValueError("Surface layer lacks a declared CRS")
        source = CRS.from_epsg(srs[1]) if str(srs[0]).upper() == "EPSG" else CRS.from_wkt(srs[2])
        converter = Transformer.from_crs(source, working, always_xy=True)
        for row in connection.execute(f"SELECT * FROM {quote(config.layer)}"):
            identifier, kind = row["surface_id"], row["surface_class"]
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("surface_id must be nonempty TEXT")
            if kind not in DEFAULT_LIFTING:
                raise ValueError(f"Surface class {str(kind)[:80]!r} is not implemented; supported: {', '.join(DEFAULT_LIFTING)}")
            if (kind, identifier) in seen:
                raise ValueError("Duplicate class-qualified surface identity")
            seen.add((kind, identifier))
            blob = row[column]
            if blob is None or len(blob) < 8:
                raise ValueError(f"Missing surface geometry: {kind}::{identifier}")
            if struct.unpack("<i" if blob[3] & 1 else ">i", blob[4:8])[0] != srid:
                raise ValueError("Geometry header CRS disagrees with GeoPackage metadata")
            geometry = gpkg_geometry(blob)
            if (geometry.is_empty or geometry.geom_type not in (strings.PolygonGeometryType.POLYGON, strings.PolygonGeometryType.MULTI_POLYGON)
                    or geometry.has_z or getattr(geometry, "has_m", False)
                    or not geometry.is_valid or geometry.area <= 0):
                raise ValueError(f"Invalid XY polygon: {kind}::{identifier}")
            geometry = transform(converter.transform, geometry)
            if not geometry.is_valid or not np.all(np.isfinite(geometry.bounds)) or geometry.area <= 0:
                raise ValueError("Invalid transformed surface geometry")
            result.append(SurfaceFeature(identifier, kind, geometry))
    if not result:
        raise ValueError("No surfaces in selected GeoPackage layer")
    return result, working


def sample_surface_points(config, root, features, working, progress):
    """Read each selected regular file in batches, COPC spatially without thinning.

    Accumulated samples are bounded per object. COPC bounding queries use the
    combined ROI at full resolution; decoded query guards cannot prevent an
    initial allocation. Header coverage differs from point/class evidence.
    Return (samples_by_feature_key, summary). Samples contain finite metric XYZ
    arrays selected by each class policy inside the boundary-search envelope,
    plus header coverage of the original polygon. XY is transformed to working;
    Z is retained. Exact boundary/interior selection belongs to reconstruction.
    Missing CRS, non-metre declared Z and exceeded budgets raise. Inputs remain
    read-only; progress receives (phase, details) events for processed files.
    """
    envelopes = [box(*f.geometry.bounds).buffer(config.radius_m, join_style="mitre") for f in features]
    tree = STRtree(envelopes)
    roi = unary_union(envelopes)
    chunks = [[] for _ in features]
    counts = [0] * len(features)
    coverage_boxes = []
    summary = {strings.LidarSamplingFields.FILES_SCANNED: 0, strings.LidarSamplingFields.FILES_SELECTED: 0, strings.LidarSamplingFields.POINTS_DECODED: 0,
               strings.LidarSamplingFields.PEAK_BATCH_POINTS: 0, "classes_seen": {}}

    def consume(points, to_work):
        """Distribute finite class-filtered XYZ to intersecting feature envelopes.

        Update decoded/class counts and retained sample chunks. Enforce decoded
        batch and per-object budgets without thinning or changing original Z.
        """
        n = len(points)
        summary[strings.LidarSamplingFields.POINTS_DECODED] += n
        summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS] = max(summary[strings.LidarSamplingFields.PEAK_BATCH_POINTS], n)
        if n > config.chunk_points:
            raise ValueError("Decoded COPC query exceeds chunk_points; reduce input extent or increase explicit budget")
        if not n:
            return
        x, y = to_work.transform(np.asarray(points.x), np.asarray(points.y))
        values = np.column_stack((x, y, np.asarray(points.z), np.asarray(points.classification)))
        values = values[np.isfinite(values).all(axis=1)]
        if not len(values):
            return
        classes, frequency = np.unique(values[:, 3].astype(int), return_counts=True)
        for c, number in zip(classes, frequency):
            summary["classes_seen"][str(c)] = summary["classes_seen"].get(str(c), 0) + int(number)
        for i in tree.query(box(*values[:, :2].min(axis=0), *values[:, :2].max(axis=0))):
            i = int(i)
            mask = intersects_xy(envelopes[i], values[:, 0], values[:, 1])
            policy = config.lifting[features[i].surface_class]
            if policy.las_classes is not None:
                mask &= np.isin(values[:, 3], policy.las_classes)
            selected = values[mask, :3]
            counts[i] += len(selected)
            if counts[i] > config.max_points_per_feature:
                raise ValueError(f"max_points_per_feature exceeded for {features[i].key}; no automatic thinning")
            if len(selected):
                chunks[i].append(selected)

    for path in lidar_files(config.lidar, root):
        summary[strings.LidarSamplingFields.FILES_SCANNED] += 1
        with laspy.open(path) as reader:
            header = reader.header
            declared = header.parse_crs()
            if declared is None:
                raise ValueError(f"LiDAR source has no declared CRS: {path.name}")
            source = CRS.from_user_input(declared)
            if len(source.axis_info) > 2 and abs(source.axis_info[2].unit_conversion_factor - 1) > 1e-10:
                raise ValueError("LiDAR vertical axis is not in metres; explicit preparation required")
            to_work = Transformer.from_crs(source, working, always_xy=True)
            rect = box(*to_work.transform_bounds(*header.mins[:2], *header.maxs[:2], densify_pts=21))
            if not rect.intersects(roi):
                continue
            coverage_boxes.append(rect.buffer(config.coverage_tolerance_m, join_style="mitre"))
            summary[strings.LidarSamplingFields.FILES_SELECTED] += 1
            is_copc = any(v.user_id == "copc" and v.record_id == 1 for v in header.vlrs)
            if is_copc:
                to_source = Transformer.from_crs(working, source, always_xy=True)
                left, bottom, right, top = to_source.transform_bounds(*roi.bounds, densify_pts=21)
                with laspy.CopcReader.open(path) as copc:
                    consume(copc.query(Bounds(np.array([left, bottom, header.mins[2]]),
                                              np.array([right, top, header.maxs[2]]))), to_work)
            else:
                for points in reader.chunk_iterator(config.chunk_points):
                    consume(points, to_work)
        progress("surface_lidar", {strings.LidarSamplingFields.FILES_SELECTED: summary[strings.LidarSamplingFields.FILES_SELECTED],
                                    strings.LidarSamplingFields.POINTS_DECODED: summary[strings.LidarSamplingFields.POINTS_DECODED]})
    coverage = unary_union(coverage_boxes)
    samples = {f.key: {strings.ShowcasePresentationFields.POINTS: np.concatenate(chunks[i]) if chunks[i] else np.empty((0, 3)),
                       strings.LidarSamplingFields.COVERAGE_COMPLETE: coverage.covers(f.geometry)} for i, f in enumerate(features)}
    return samples, summary
