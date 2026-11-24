"""Bounded-cell relative-height audit of every entity in a local snapshot.

COPC resources are queried by occupied spatial cells instead of loading a whole
regional rectangle. All source IDs are accounted for. Invalid parent relations
remain unchanged, are isolated from building fallback anchors, and may receive
only an independently supported direct estimate. No database is used at runtime.
"""
from __future__ import annotations
from lodext import strings

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path

if __package__:
    from .inspect_fixture import ReferenceSampling, ground_grid, inventory_tiles, load_layer, roof_support, sample_dtm
    from .check_vertical_consistency import ConsistencyConfig, assess_pairs, paired_raster_values
    from .run_relative_heights import CLASS_PROFILES
else:
    from inspect_fixture import ReferenceSampling, ground_grid, inventory_tiles, load_layer, roof_support, sample_dtm
    from check_vertical_consistency import ConsistencyConfig, assess_pairs, paired_raster_values
    from run_relative_heights import CLASS_PROFILES

import laspy
from laspy.copc import Bounds
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from shapely import STRtree, intersects_xy, prepare
from shapely.geometry import box
from shapely.ops import unary_union

from lodext.core.heights import HeightConfig, PartObservation, estimate_building
from lodext.io.dataset import DatasetSpec


@dataclass(frozen=True)
class FullSampling:
    """Owner of full-scope processing settings, distinct from roof calibration.

    cell_size_m: positive finite projected metres. Every occupied cell is read;
      half-open XY ownership avoids counting points twice at adjacent cells.
      Smaller values reduce query working sets but increase COPC query overhead.
    max_points_per_query: positive integer, excluding bool; reject a query over
      this safety budget after decoding instead of silently thinning points.
      It is a diagnostic guard, not a hard bound on decoder allocation.
    coverage_tolerance_m: finite metres >=0; expand header envelopes only for
      coverage assessment, not sampling or geometry. The 0.002 m fixture setting
      covers millimetre quantization gaps between adjacent PNOA tile headers.
      0 disables the tolerance. It must never be used to bridge missing tiles.

    Defaults are authoritative here. Runtime summaries record actual peak query
    size. Changing cell size must preserve full-resolution point membership.
    Non-COPC full-scope inputs are explicitly rejected in this prototype.
    """

    cell_size_m: float = 128.0  # Metres; half-open cells own point membership.
    max_points_per_query: int = 2_000_000  # Decoded-query guard, not preallocation limit.
    coverage_tolerance_m: float = 0.002  # Header-box metres; cannot repair missing tiles.

    def __post_init__(self):
        """Reject invalid cell/tolerance units and nonpositive decoded-query budgets."""
        for value in (self.cell_size_m, self.coverage_tolerance_m):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Cell and coverage settings must be finite numbers")
        if self.cell_size_m <= 0 or self.coverage_tolerance_m < 0:
            raise ValueError("Cell size must be positive and coverage tolerance nonnegative")
        if isinstance(self.max_points_per_query, bool) or not isinstance(self.max_points_per_query, int) or self.max_points_per_query < 1:
            raise ValueError("Point-query budget must be a positive integer")


def metric_crs(epsg):
    """Return the audit's declared projected-metre CRS; reject geographic units.

    The dataset author chooses a locally suitable projection. This helper does
    not choose a zone or establish/transform the vertical reference.
    """
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected or any(axis.unit_name != "metre" for axis in crs.axis_info[:2]):
        raise ValueError("The dataset must declare an appropriate projected metre CRS")
    return crs


def occupied_cells(roi_tree, bounds, size):
    """Enumerate all intersecting cells from a deterministic projected grid."""
    x0, y0 = math.floor(bounds[0] / size) * size, math.floor(bounds[1] / size) * size
    for iy in range(math.ceil((bounds[3] - y0) / size)):
        for ix in range(math.ceil((bounds[2] - x0) / size)):
            cell = box(x0 + ix * size, y0 + iy * size, x0 + (ix + 1) * size, y0 + (iy + 1) * size)
            if len(roi_tree.query(cell, predicate="intersects")):
                yield cell


def stream_samples(root, paths, crs, parts, obstacles, halo, full, consistency, progress):
    """Read all occupied full-resolution COPC cells for the complete audit scope.

    parts supplies metric sampling supports; halo adds context without replacing
    them. Select tiles by coverage and use half-open cell ownership to prevent
    query-edge duplication. Accumulate roof Z by CLASS_PROFILES and independent
    class-2 controls outside occupied clearance. Reject regular non-COPC sources
    and decoded queries exceeding FullSampling's budget; never silently thin.

    Return roof arrays by profile/part order, ground controls (X,Y,Z,tile index),
    statistics, header-coverage union, selected tile inventory and projected tile
    boxes. progress optionally receives event dicts. Z and source files remain
    unchanged; header coverage does not prove usable observations for every part.
    """
    supports = [geometry for _, geometry, _ in parts]
    roi_shapes = [geometry.buffer(halo) for geometry in supports]
    roi_tree = STRtree(roi_shapes)
    roi = unary_union(roi_shapes)
    prepare(roi)
    inventory = inventory_tiles(root, roi.bounds, crs, lidar_directory=paths[strings.GeospatialInputFields.LIDAR_DIRECTORY])
    selected = [t for t in inventory if t[strings.LidarInventoryFields.SELECTED]]
    if any(not t[strings.LidarInventoryFields.IS_COPC] for t in selected):
        raise ValueError("Full-scope streaming currently requires COPC resources")
    tile_boxes = []
    for info in selected:
        projected = Transformer.from_crs(CRS.from_wkt(info[strings.LidarInventoryFields.CRS_WKT]), crs, always_xy=True).transform_bounds(
            *info[strings.LidarInventoryFields.BOUNDS_XY], densify_pts=21)
        tile_boxes.append(box(*projected))
    if not tile_boxes:
        raise ValueError("No cloud resources intersect the source geometry extent")
    coverage = unary_union([g.buffer(full.coverage_tolerance_m, join_style="mitre") for g in tile_boxes])
    support_tree, tile_tree = STRtree(supports), STRtree(tile_boxes)
    cells = list(occupied_cells(roi_tree, roi.bounds, full.cell_size_m))
    roof = {profile: [[] for _ in parts] for profile in CLASS_PROFILES}
    ground_pairs = {}
    clearance = obstacles.buffer(consistency.building_clearance_m)
    prepare(clearance)
    total_queried = total_owned = total_context = peak_query = 0
    class_counts = Counter()
    query_counts, returned_counts = Counter(), Counter()
    if progress:
        progress({strings.ProgressEventFields.PHASE: "cloud_plan", strings.LidarSamplingFields.FILES_SCANNED: len(inventory), "selected_tiles": len(selected), "occupied_cells": len(cells)})
    with ExitStack() as stack:
        readers = [stack.enter_context(laspy.CopcReader.open(str(root / t[strings.LidarInventoryFields.FILE]))) for t in selected]
        to_source = [Transformer.from_crs(crs, CRS.from_wkt(t[strings.LidarInventoryFields.CRS_WKT]), always_xy=True) for t in selected]
        to_working = [Transformer.from_crs(CRS.from_wkt(t[strings.LidarInventoryFields.CRS_WKT]), crs, always_xy=True) for t in selected]
        for number, cell in enumerate(cells, 1):
            left, bottom, right, top = cell.bounds
            candidates = support_tree.query(cell, predicate="intersects")
            for tile_index in tile_tree.query(cell, predicate="intersects"):
                i = int(tile_index)
                target = to_source[i].transform_bounds(left, bottom, right, top, densify_pts=21)
                points = readers[i].query(bounds=Bounds(np.array(target[:2]), np.array(target[2:])))
                count = len(points)
                query_counts[selected[i][strings.LidarInventoryFields.FILE]] += 1
                returned_counts[selected[i][strings.LidarInventoryFields.FILE]] += count
                total_queried += count
                peak_query = max(peak_query, count)
                if count > full.max_points_per_query:
                    raise ValueError("COPC query exceeded the explicit point budget; reduce cell_size_m")
                if not count:
                    continue
                x, y = to_working[i].transform(np.asarray(points.x), np.asarray(points.y))
                z, classes = np.asarray(points.z), np.asarray(points.classification)
                owner = (x >= left) & (x < right) & (y >= bottom) & (y < top)
                x, y, z, classes = np.asarray(x)[owner], np.asarray(y)[owner], z[owner], classes[owner]
                total_owned += len(z)
                context = intersects_xy(roi, x, y)
                x, y, z, classes = x[context], y[context], z[context], classes[context]
                total_context += len(z)
                class_counts.update(map(int, classes))
                for index in candidates:
                    j = int(index)
                    inside = intersects_xy(supports[j], x, y)
                    if not np.any(inside):
                        continue
                    for profile, allowed in CLASS_PROFILES.items():
                        mask = inside if allowed is None else inside & np.isin(classes, allowed)
                        if np.any(mask):
                            roof[profile][j].append(z[mask].copy())
                ground = (classes == 2) & ~intersects_xy(clearance, x, y)
                gx, gy, gz = x[ground], y[ground], z[ground]
                keys = np.column_stack((np.floor(gx / consistency.sampling_grid_m),
                                        np.floor(gy / consistency.sampling_grid_m)))
                _, chosen = np.unique(keys, axis=0, return_index=True)
                for k in chosen:
                    key = (int(keys[k, 0]), int(keys[k, 1]))
                    ground_pairs.setdefault(key, (float(gx[k]), float(gy[k]), float(gz[k]), i))
            if progress and (number == len(cells) or number % max(1, len(cells) // 10) == 0):
                progress({strings.ProgressEventFields.PHASE: "cloud_sampling", "completed_cells": number, "total_cells": len(cells)})
    arrays = {profile: [np.concatenate(chunks) if chunks else np.array([], dtype=float) for chunks in groups]
              for profile, groups in roof.items()}
    summary = {strings.LidarSamplingFields.FILES_SCANNED: len(inventory), strings.LidarInventoryFields.SELECTED_FILES: [t[strings.LidarInventoryFields.FILE] for t in selected],
               "queried_files": sorted(query_counts),
               "files_returning_points": sorted(name for name, count in returned_counts.items() if count),
               "occupied_cells": len(cells), "points_queried": total_queried,
               "points_owned_by_cells": total_owned, "points_in_context": total_context,
               "peak_query_points": peak_query, "classes_in_context": {str(k): v for k, v in sorted(class_counts.items())}}
    return arrays, list(ground_pairs.values()), summary, coverage, selected, tile_boxes


def relative_ground(footprint, obstacle_tree, obstacle_geometries, dtm, crs, sampling):
    """Return the first sufficiently supported unoccupied DTM-ring median.

    Search configured metre radii, subtract the footprint and indexed obstacles,
    and discard invalid raster samples. Evidence includes sample counts/radius;
    no valid ring returns z_median=None, never zero or an interior roof height.
    This trial helper neither interpolates a terrain plane nor modifies data.
    """
    for radius in sampling.ground_buffers_m:
        ring = footprint.buffer(radius).difference(footprint)
        nearby = obstacle_tree.query(ring, predicate="intersects")
        free = ring.difference(unary_union([obstacle_geometries[int(i)] for i in nearby])) if len(nearby) else ring
        if free.is_empty or free.area < sampling.min_free_area_m2:
            continue
        x, y = ground_grid(free, sampling.grid_step_m)
        values = sample_dtm(dtm, x, y, crs)
        if len(values) >= sampling.min_ground_samples:
            return {strings.GroundSamplingFields.STATUS: strings.GroundSamplingStatus.SAMPLED, strings.GroundSamplingFields.Z_MEDIAN: float(np.median(values)),
                    strings.GroundSamplingFields.VALID_SAMPLES: len(values), strings.GroundSamplingFields.GRID_CANDIDATES: len(x),
                    strings.GroundSamplingFields.SEARCH_RADIUS_M: radius, strings.GroundSamplingFields.FREE_AREA_M2: free.area}
    return {strings.GroundSamplingFields.STATUS: "no_valid_ground", strings.GroundSamplingFields.Z_MEDIAN: None, strings.GroundSamplingFields.VALID_SAMPLES: 0}


def assemble_profile(observations, valid_relations, reference_values, eligibility, config):
    """Keep invalid-parent rows, but prevent them sharing or creating anchors.

    A quarantined row may retain a direct height on its own evidence. Inferred
    outcomes for such rows are discarded explicitly, with a reason code, rather
    than attaching a different parent or borrowing another building's floors.
    """
    groups = defaultdict(list)
    isolated = []
    for obs in observations:
        if valid_relations[obs.part_id] and obs.part_id not in eligibility:
            groups[obs.building_id].append(obs)
        else:
            isolated.append(obs)
    estimates = []
    for building_id in sorted(groups):
        estimates.extend(estimate_building(groups[building_id], config))
    for obs in isolated:
        estimates.extend(estimate_building([obs], config))
    rows = []
    for estimate in sorted(estimates, key=lambda e: e.part_id):
        row = asdict(estimate)
        issue = eligibility.get(estimate.part_id)
        parent_ok = valid_relations[estimate.part_id]
        row["source_relation_status"] = "spatially_valid" if parent_ok else "quarantined_outside_declared_parent"
        row["eligible_for_building_aggregation"] = parent_ok and not issue
        row[strings.BuildingHeightFields.FLAGS] = list(row[strings.BuildingHeightFields.FLAGS])
        if not parent_ok:
            row[strings.BuildingHeightFields.FLAGS].append("invalid_parent_isolated")
        if issue or (not parent_ok and row[strings.BuildingHeightFields.METHOD] != strings.HeightEstimationMethod.DIRECT):
            row[strings.BuildingHeightFields.HEIGHT_M], row[strings.BuildingHeightFields.METHOD], row[strings.BuildingHeightFields.FLOOR_HEIGHT_M], row[strings.BuildingHeightFields.REFERENCE_PART_ID] = None, strings.HeightEstimationMethod.UNRESOLVED, None, None
            row[strings.BuildingHeightFields.FLAGS].append(issue or "invalid_parent_no_inference")
        original = reference_values.get(estimate.part_id)
        row[strings.BuildingInputFields.REFERENCE_HEIGHT_M] = original
        row[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] = row[strings.BuildingHeightFields.HEIGHT_M] - original if row[strings.BuildingHeightFields.HEIGHT_M] is not None and original is not None else None
        row[strings.BuildingHeightFields.BASE_Z] = row[strings.BuildingHeightFields.GROUND_Z]
        row[strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z] = row[strings.BuildingHeightFields.BASE_Z] + row[strings.BuildingHeightFields.HEIGHT_M] if row[strings.BuildingHeightFields.HEIGHT_M] is not None else None
        rows.append(row)
    return rows


def building_records(inventory, part_rows):
    """Account for every parent, including those without geometry.

    max_part_height_m is a relative per-body maximum, not a surveyed building
    height. vertical_extent_m uses max reconstructed top minus min base; these
    differ on slopes. Invalid relationships never contribute to either metric.
    """
    grouped = defaultdict(list)
    for row in part_rows:
        grouped[row[strings.SourceObjectIdentity.BUILDING_ID]].append(row)
    result = []
    for obj in inventory:
        if obj[strings.SourceObjectIdentity.KIND] != strings.BuildingObjectType.BUILDING:
            continue
        children = grouped[obj[strings.SourceObjectIdentity.OBJECT_ID]]
        accepted = [p for p in children if p["eligible_for_building_aggregation"] and p[strings.BuildingHeightFields.HEIGHT_M] is not None]
        status = strings.HeightTrialBuildingStatus.MISSING_GEOMETRY if not obj[strings.SourceInventoryFields.GEOMETRY_AVAILABLE] else "has_usable_part_heights" if accepted else "no_usable_part_heights"
        low = min(p[strings.BuildingHeightFields.BASE_Z] for p in accepted) if accepted else None
        top = max(p[strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z] for p in accepted) if accepted else None
        result.append({strings.SourceObjectIdentity.BUILDING_ID: obj[strings.SourceObjectIdentity.OBJECT_ID], strings.HeightTrialBuildingFields.STATUS: status,
            "part_count": len(children), "usable_part_count": len(accepted),
            "invalid_relation_parts": sum(p["source_relation_status"] != "spatially_valid" for p in children),
            "max_part_height_m": max(p[strings.BuildingHeightFields.HEIGHT_M] for p in accepted) if accepted else None,
            "min_part_base_z": low, "max_part_top_z": top,
            "vertical_extent_m": top - low if accepted else None})
    return result


def comparison_summary(rows):
    """Summarise available absolute height differences in metres, excluding None.

    Return count, mean, median, p95, maximum and a strict over-0.5 m count; empty
    comparisons have None statistics. Historical references are comparison
    values, not automatically independent ground truth or accuracy validation.
    """
    values = [abs(r[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M]) for r in rows if r[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] is not None]
    return {"compared_parts": len(values), strings.HeightTrialFields.MEAN_ABSOLUTE_DIFFERENCE_M: float(np.mean(values)) if values else None,
            "median_absolute_difference_m": float(np.median(values)) if values else None,
            "p95_absolute_difference_m": float(np.percentile(values, 95)) if values else None,
            strings.HeightTrialFields.MAX_ABSOLUTE_DIFFERENCE_M: max(values) if values else None,
            strings.HeightTrialFields.PARTS_OVER_0_5M: sum(v > 0.5 for v in values)}


def run_full_trial(directory, *, experimental_relative_z, sampling=None, full=None, height_config=None, progress=None):
    """Process all snapshot geometry and preserve complete entity accounting.

    Explicit experimental scope is required; no absolute datum or clamp is
    asserted. Source relation, data coverage and per-tile empirical Z evidence
    remain separate. A known tile-level Z mismatch prevents estimates from that
    tile; insufficient comparison evidence stays flagged as unconfirmed.
    Reports distinguish part results, parent summaries and source-only entities.
    """
    if experimental_relative_z is not True:
        raise ValueError("Explicit experimental relative-Z scope is required")
    root = Path(directory).resolve()
    spec = DatasetSpec.read(root)
    paths = spec.paths(root)
    crs = metric_crs(spec.working_epsg)
    sampling = ReferenceSampling() if sampling is None else sampling
    full = FullSampling() if full is None else full
    height_config = HeightConfig() if height_config is None else height_config
    consistency = ConsistencyConfig()
    if sampling.ground_buffers_m[-1] > spec.halo_m:
        raise ValueError("Dataset context halo is smaller than the required ground radius")
    inventory = json.loads(paths[strings.GeospatialInputFields.SOURCE_INVENTORY].read_text(encoding=strings.TextFileEncoding.UTF8))
    source_objects = inventory[strings.SourceInventoryFields.OBJECTS]
    if hashlib.sha256(paths[strings.GeospatialInputFields.FOOTPRINTS].read_bytes()).hexdigest() != inventory[strings.SourceInventoryFields.GEOPACKAGE_SHA256]:
        raise ValueError("Geometry snapshot no longer matches its source inventory hash")
    if len({(obj[strings.SourceObjectIdentity.KIND], obj[strings.SourceObjectIdentity.OBJECT_ID]) for obj in source_objects}) != len(source_objects):
        raise ValueError("Source inventory contains duplicate semantic identities")
    parents = load_layer(paths[strings.GeospatialInputFields.FOOTPRINTS], strings.GeoPackageLayers.BUILDINGS)
    parts = load_layer(paths[strings.GeospatialInputFields.FOOTPRINTS], strings.GeoPackageLayers.BUILDING_PARTS)
    parent_map = {p[strings.SourceObjectIdentity.BUILDING_ID]: geom for p, geom in parents}
    if len({p[strings.SourceObjectIdentity.PART_ID] for p, _ in parts}) != len(parts) or len(parent_map) != len(parents):
        raise ValueError("Duplicate normalized input identifiers")
    source_part_ids = {p[strings.SourceObjectIdentity.OBJECT_ID] for p in source_objects if p[strings.SourceObjectIdentity.KIND] == strings.BuildingObjectType.BUILDING_PART and p[strings.SourceInventoryFields.GEOMETRY_AVAILABLE]}
    if source_part_ids != {p[strings.SourceObjectIdentity.PART_ID] for p, _ in parts}:
        raise ValueError("Source inventory and part geometry are not fully accounted for")
    if any(not geom.is_valid or geom.is_empty or geom.area <= 0 for _, geom in parents + parts):
        raise ValueError("Invalid geometry must be explicitly prepared before full sampling")
    supports = [(props, *roof_support(geom, sampling)) for props, geom in parts]
    whole_supports = [(props, *roof_support(geom, sampling)) for props, geom in parents]
    obstacle_geometries = [geom for _, geom in parents + parts]
    obstacles = unary_union(obstacle_geometries)
    roofs, pairs, cloud_summary, coverage, tiles, tile_boxes = stream_samples(
        root, paths, crs, supports + whole_supports, obstacles, spec.halo_m, full, consistency, progress)
    obstacle_tree = STRtree(obstacle_geometries)
    ground_records = {}
    whole_ground = {}
    with rasterio.open(paths[strings.GeospatialInputFields.DTM_FILE]) as dtm:
        if dtm.crs is None or dtm.count != 1:
            raise ValueError("DTM must declare its horizontal CRS and contain one band")
        for number, (props, footprint) in enumerate(parts, 1):
            ground_records[props[strings.SourceObjectIdentity.PART_ID]] = relative_ground(footprint, obstacle_tree, obstacle_geometries, dtm, crs, sampling)
            if progress and (number == len(parts) or number % max(1, len(parts) // 10) == 0):
                progress({strings.ProgressEventFields.PHASE: "ground_sampling", "completed_parts": number, "total_parts": len(parts)})
        for number, (props, footprint) in enumerate(parents, 1):
            whole_ground[props[strings.SourceObjectIdentity.BUILDING_ID]] = relative_ground(footprint, obstacle_tree, obstacle_geometries, dtm, crs, sampling)
            if progress and (number == len(parents) or number % max(1, len(parents) // 10) == 0):
                progress({strings.ProgressEventFields.PHASE: "whole_building_ground", "completed_buildings": number, "total_buildings": len(parents)})
        paired = np.asarray(pairs, dtype=float).reshape((-1, 4))
        z_dtm = paired_raster_values(dtm, paired[:, 0], paired[:, 1], crs)
    combined, _ = assess_pairs(paired[:, 2], z_dtm, consistency)
    tile_evidence = []
    for i, info in enumerate(tiles):
        subset = paired[:, 3] == i
        assessment, _ = assess_pairs(paired[subset, 2], z_dtm[subset], consistency)
        tile_evidence.append({strings.LidarInventoryFields.FILE: info[strings.LidarInventoryFields.FILE], "queried": info[strings.LidarInventoryFields.FILE] in cloud_summary["queried_files"], **assessment})
    tile_tree = STRtree(tile_boxes)

    def support_issue(support):
        if not coverage.covers(support):
            return "incomplete_lidar_header_coverage"
        if any(tile_evidence[int(i)][strings.VerticalConsistencyFields.STATUS] == strings.VerticalConsistencyStatus.OFFSET_OR_MISMATCH
               for i in tile_tree.query(support, predicate="intersects")):
            return "local_vertical_mismatch"
        return None

    relations, eligibility, references = {}, {}, {}
    for j, (props, support, _) in enumerate(supports):
        footprint = parts[j][1]
        parent = parent_map.get(props[strings.SourceObjectIdentity.BUILDING_ID])
        relations[props[strings.SourceObjectIdentity.PART_ID]] = parent is not None and footprint.intersection(parent).area > 0
        references[props[strings.SourceObjectIdentity.PART_ID]] = props.get(strings.BuildingInputFields.REFERENCE_HEIGHT_M)
        issue = support_issue(support)
        if issue:
            eligibility[props[strings.SourceObjectIdentity.PART_ID]] = issue
    profiles = {}
    for profile in CLASS_PROFILES:
        observations = []
        for j, (props, support, _) in enumerate(supports):
            observations.append(PartObservation(
                props[strings.SourceObjectIdentity.PART_ID], props[strings.SourceObjectIdentity.BUILDING_ID], parts[j][1].area, support.area,
                tuple(map(float, roofs[profile][j])), ground_records[props[strings.SourceObjectIdentity.PART_ID]][strings.GroundSamplingFields.Z_MEDIAN],
                parts[j][1].area < sampling.erode_min_area_m2,
                props.get(strings.BuildingInputFields.STOREYS_ABOVE), props.get(strings.BuildingInputFields.STOREYS_BELOW),
            ))
        # Ineligible rows must not become anchors, but coverage and relationship
        # errors remain distinct and retain their actual source classifications.
        rows = assemble_profile(observations, relations, references, eligibility, height_config)
        for j, row in enumerate(rows):
            row["ground_sampling"] = ground_records[row[strings.SourceObjectIdentity.PART_ID]]
            if not relations[row[strings.SourceObjectIdentity.PART_ID]]:
                row["source_relation_status"] = "quarantined_outside_declared_parent"
        building_rows = building_records(source_objects, rows)
        whole_by_id = {}
        for j, (props, support, erosion) in enumerate(whole_supports):
            # One numerical unit represents the whole footprint for this
            # independent test; no synthetic child is added to the source data.
            unit = PartObservation(
                props[strings.SourceObjectIdentity.BUILDING_ID], props[strings.SourceObjectIdentity.BUILDING_ID], parents[j][1].area, support.area,
                tuple(map(float, roofs[profile][len(parts) + j])),
                whole_ground[props[strings.SourceObjectIdentity.BUILDING_ID]][strings.GroundSamplingFields.Z_MEDIAN],
                parents[j][1].area < sampling.erode_min_area_m2,
                props.get(strings.BuildingInputFields.STOREYS_ABOVE), props.get(strings.BuildingInputFields.STOREYS_BELOW),
            )
            estimate = asdict(estimate_building([unit], height_config)[0])
            estimate.pop(strings.SourceObjectIdentity.PART_ID)
            issue = support_issue(support)
            if issue:
                estimate.update(height_m=None, method=strings.HeightEstimationMethod.UNRESOLVED, reference_part_id=None, floor_height_m=None)
                estimate[strings.BuildingHeightFields.FLAGS] = [*estimate[strings.BuildingHeightFields.FLAGS], issue]
            estimate.update(unit_scope="whole_footprint", erosion=erosion,
                            ground_sampling=whole_ground[props[strings.SourceObjectIdentity.BUILDING_ID]])
            whole_by_id[props[strings.SourceObjectIdentity.BUILDING_ID]] = estimate
        for row in building_rows:
            row["whole_footprint"] = whole_by_id.get(row[strings.SourceObjectIdentity.BUILDING_ID])
        valid_rows = [r for r in rows if r["source_relation_status"] == "spatially_valid"]
        profiles[profile] = {strings.BuildingHeightFields.METHODS: dict(Counter(r[strings.BuildingHeightFields.METHOD] for r in rows)),
            "comparison_all_resolved": comparison_summary(rows),
            "comparison_valid_relations": comparison_summary(valid_rows),
            strings.HeightTrialFields.PARTS: rows, strings.HeightTrialFields.BUILDINGS: building_rows,
            "whole_building_methods": dict(Counter(row["whole_footprint"][strings.BuildingHeightFields.METHOD] if row["whole_footprint"] is not None else strings.SourceReceptionReason.MISSING_GEOMETRY for row in building_rows)),
            "building_statuses": dict(Counter(r[strings.HeightTrialBuildingFields.STATUS] for r in building_rows))}
    return {strings.ReportEnvelopeFields.VERSION: strings.ReportSchemaVersion.FULL_HEIGHT_TRIAL, strings.ReconstructionRunFields.CREATED_AT_UTC: datetime.now(timezone.utc).isoformat(),
        strings.DatasetIdentityFields.DATASET_ID: spec.dataset_id, strings.ValidationReportFields.SCOPE: "all_source_entities_experimental_relative",
        "source_counts": inventory["source_counts"], "geometry_counts": inventory["geometry_counts"],
        "source_issues": dict(Counter(reason for obj in source_objects for reason in obj[strings.ReconstructionObjectFields.ISSUES])),
        "source_only_entities": [obj for obj in source_objects if not obj[strings.SourceInventoryFields.GEOMETRY_AVAILABLE]],
        "processing_config": asdict(full), strings.HeightTrialFields.SAMPLING_CONFIG: asdict(sampling), strings.HeightTrialFields.HEIGHT_CONFIG: asdict(height_config),
        strings.ReconstructionRunFields.CLOUD: cloud_summary, "vertical_evidence": {"combined": combined, "tiles": tile_evidence},
        strings.VerticalConsistencyFields.ABSOLUTE_VERTICAL_DATUM: None, strings.TileConversionFields.CLAMPING_APPLIED: False, strings.HeightTrialFields.PROFILES: profiles,
        strings.BuildingHeightFields.REFERENCE_ROLE: "Historical comparisons only; not independent surveyed ground truth."}


def write_full_report(report, output):
    """Write full-trial JSON and part/building CSVs into a newly created directory.

    Preserve profile names, source identity, unresolved evidence and whole-body
    comparison fields. Existing directories raise; source inputs are untouched.
    Filesystem failures may leave a partial new directory for diagnosis.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "full_relative_heights.json").open("x", encoding=strings.TextFileEncoding.UTF8) as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    part_fields = [strings.HeightTrialFields.PROFILE, strings.SourceObjectIdentity.BUILDING_ID, strings.SourceObjectIdentity.PART_ID, "source_relation_status", strings.BuildingHeightFields.METHOD, strings.BuildingHeightFields.HEIGHT_M,
                   strings.BuildingInputFields.REFERENCE_HEIGHT_M, strings.HeightTrialFields.DELTA_FROM_REFERENCE_M, strings.BuildingHeightFields.BASE_Z, strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z, strings.BuildingHeightFields.N_POINTS,
                   strings.BuildingHeightFields.DENSITY_POINTS_M2, strings.BuildingHeightFields.ROOF_STRENGTH, strings.BuildingHeightFields.REFERENCE_PART_ID, "eligible_for_building_aggregation", strings.BuildingHeightFields.FLAGS]
    with (output / "parts_comparison.csv").open("x", encoding=strings.TextFileEncoding.UTF8, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=part_fields)
        writer.writeheader()
        for profile, data in report[strings.HeightTrialFields.PROFILES].items():
            for row in data[strings.HeightTrialFields.PARTS]:
                item = {key: row[key] for key in part_fields if key not in (strings.HeightTrialFields.PROFILE, strings.BuildingHeightFields.FLAGS)}
                item.update(profile=profile, flags=";".join(row[strings.BuildingHeightFields.FLAGS]))
                writer.writerow(item)
    first = next(iter(report[strings.HeightTrialFields.PROFILES].values()))[strings.HeightTrialFields.BUILDINGS][0]
    building_fields = [key for key in first if key != "whole_footprint"]
    building_fields += ["whole_footprint_method", "whole_footprint_height_m", "whole_footprint_flags"]
    with (output / "buildings_summary.csv").open("x", encoding=strings.TextFileEncoding.UTF8, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[strings.HeightTrialFields.PROFILE, *building_fields])
        writer.writeheader()
        for profile, data in report[strings.HeightTrialFields.PROFILES].items():
            for row in data[strings.HeightTrialFields.BUILDINGS]:
                whole = row["whole_footprint"]
                writer.writerow({strings.HeightTrialFields.PROFILE: profile,
                    **{key: row[key] for key in row if key != "whole_footprint"},
                    "whole_footprint_method": whole[strings.BuildingHeightFields.METHOD] if whole else strings.SourceReceptionReason.MISSING_GEOMETRY,
                    "whole_footprint_height_m": whole[strings.BuildingHeightFields.HEIGHT_M] if whole else None,
                    "whole_footprint_flags": ";".join(whole[strings.BuildingHeightFields.FLAGS]) if whole else "missing_footprint"})


def main():
    """Run the complete explicit relative-Z audit, stream progress and save reports.

    Reject existing outputs and require the opt-in experimental scope through
    run_full_trial. Console output is a summary; detailed evidence stays on disk.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(strings.CommandLineArguments.DATA_OPTION, type=Path, required=True, help="Local complete dataset directory with dataset.json")
    parser.add_argument(strings.CommandLineArguments.OUTPUT_OPTION, type=Path, required=True, help=strings.CommandLineArguments.NEW_RUN_HELP)
    parser.add_argument(strings.CommandLineArguments.RELATIVE_Z_OPTION, action="store_true", help="Explicit experimental local Z scope, disabled by default")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(strings.OutputDirectoryMessages.OUTPUT_EXISTS)
    report = run_full_trial(args.data, experimental_relative_z=args.experimental_relative_z,
                            progress=lambda value: print(json.dumps(value), flush=True))
    write_full_report(report, args.output)
    print(json.dumps({"source_counts": report["source_counts"], "source_issues": report["source_issues"],
        "cloud_summary": {key: report[strings.ReconstructionRunFields.CLOUD][key] for key in (strings.LidarSamplingFields.FILES_SCANNED, "occupied_cells", "points_in_context", "peak_query_points")},
        "files_returning_points": len(report[strings.ReconstructionRunFields.CLOUD]["files_returning_points"]),
        strings.HeightTrialFields.PROFILES: {name: {key: data[key] for key in (strings.BuildingHeightFields.METHODS, "comparison_all_resolved", "building_statuses", "whole_building_methods")}
        for name, data in report[strings.HeightTrialFields.PROFILES].items()}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
