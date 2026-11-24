"""Inspect local vector/LiDAR/DTM resources without reconstructing buildings.

This fixture tool selects tiles by transformed header bounds, queries COPC at
full source resolution and samples the original DTM in its actual CRS. It never
modifies source data. Reports contain relative paths. No height subtraction or
ECEF conversion is performed: horizontal CRS metadata does not establish the
vertical relationship between sources.
"""
from __future__ import annotations
from lodext import strings

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

if __package__:
    from .native_environment import isolate_wheel_proj_data
else:
    from native_environment import isolate_wheel_proj_data

# Wheel databases must be selected before either native library is imported.
# Import-time diagnostic tuple of removed PROJ variable NAMES, never values.
# inspect_fixture records it for reproducibility; an empty tuple means no override
# was removed. This reports process isolation, not source CRS/datum validity.
REMOVED_PROJ_OVERRIDES = isolate_wheel_proj_data()

import laspy
from laspy.copc import Bounds
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from shapely import contains_xy, intersects_xy
from shapely.geometry import box, shape
from shapely.ops import unary_union


@dataclass(frozen=True)
class ReferenceSampling:
    """Single owner of reference-fixture sampling parameters, not app defaults.

    Fields:
      erode_m: finite metres >=0, 0 disables erosion. Applied only at/above
        erode_min_area_m2; empty erosion retains the original support and is
        recorded. Affects roof samples, never exported footprints.
      erode_min_area_m2: finite m² >0. Threshold for attempting erosion.
      ground_buffers_m: nonempty, strictly increasing positive finite metre
        radii. Select the first whose free ground yields enough valid samples.
        Their largest radius must fit the fixture's declared halo.
      grid_step_m: finite metres >0. Grid starts at each free-zone bbox minimum.
      min_free_area_m2: finite m² >0. Minimum free area before raster sampling.
      min_ground_samples: integer >=1, excluding bool. Valid, finite, unmasked
        DTM samples needed to accept a radius; NoData never becomes zero.

    Values reproduce the reference fixture policy. They do not constitute
    global calibration. CLI and reports consume this owner via defaults/asdict.
    Invalid settings are rejected, not clamped. Changing sampling changes
    counts, densities and ground medians and requires numerical regression.
    """

    erode_m: float = 1.0  # Metres inward for roof support, never exported geometry.
    erode_min_area_m2: float = 40.0  # Inclusive footprint-area gate for erosion.
    ground_buffers_m: tuple[float, ...] = (8.0, 14.0, 25.0)  # Increasing metre search radii.
    grid_step_m: float = 2.0  # Metre spacing between candidate DTM samples.
    min_free_area_m2: float = 5.0  # Minimum unoccupied ground before sampling.
    min_ground_samples: int = 3  # Valid values required to accept a search ring.

    def __post_init__(self):
        """Reject invalid reference-sampling ranges without clamping/calibration."""
        scalars = (self.erode_m, self.erode_min_area_m2, self.grid_step_m, self.min_free_area_m2)
        if any(isinstance(v, bool) or not math.isfinite(v) for v in scalars):
            raise ValueError("Sampling scalars must be finite numbers")
        if self.erode_m < 0 or min(scalars[1:]) <= 0:
            raise ValueError("Erosion must be nonnegative; area and grid settings must be positive")
        radii = self.ground_buffers_m
        if not radii or any(isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in radii):
            raise ValueError("Ground radii must be positive finite values")
        if any(a >= b for a, b in zip(radii, radii[1:])):
            raise ValueError("Ground radii must be strictly increasing")
        if isinstance(self.min_ground_samples, bool) or not isinstance(self.min_ground_samples, int) or self.min_ground_samples < 1:
            raise ValueError("Minimum ground sample count must be a positive integer")


def load_layer(gpkg, layer):
    """Read an audit layer through ogr2ogr as (properties, Shapely geometry) pairs.

    GDAL CLI is required by this optional fixture inspector, not the public
    reconstruction engine. Capture GeoJSON in memory, enforce a process timeout
    and raise with bounded diagnostics on failure; do not write to the GPKG.
    """
    executable = shutil.which("ogr2ogr")
    if not executable:
        raise RuntimeError("GDAL ogr2ogr is required to read this fixture")
    process = subprocess.run(
        [executable, "-f", "GeoJSON", "/vsistdout/", str(gpkg), layer],
        capture_output=True, text=True, encoding=strings.TextFileEncoding.UTF8, timeout=30,
    )
    if process.returncode:
        raise RuntimeError(f"Cannot read layer {layer}: {process.stderr[:500]}")
    return [(f["properties"], shape(f[strings.GeoJSONFields.GEOMETRY])) for f in json.loads(process.stdout)[strings.GeoJSONFields.FEATURES]]


def bounds_intersect(left, right):
    """Closed XY envelope overlap; boundary contact conservatively selects a tile."""
    return not (left[2] < right[0] or left[0] > right[2] or left[3] < right[1] or left[1] > right[3])


def inventory_tiles(root, bounds_xy, working_crs, *, lidar_directory=None):
    """Header-only inventory; missing CRS is an explicit error, not a guess.

    lidar_directory=None selects root/lidar, preserving the fixture interface.
    An explicit directory can reuse another local data folder. Report file
    paths remain relative to root, including '..' for shared project assets.
    """
    tiles = []
    directory = Path(root) / "lidar" if lidar_directory is None else Path(lidar_directory)
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() not in (".las", ".laz"):
            continue
        with laspy.open(path) as reader:
            header = reader.header
            crs = header.parse_crs()
            if crs is None:
                raise ValueError(f"Missing LiDAR CRS: {path.name}")
            transformed = Transformer.from_crs(working_crs, crs, always_xy=True).transform_bounds(
                *bounds_xy, densify_pts=21,
            )
            tile_bounds = [float(header.mins[0]), float(header.mins[1]),
                           float(header.maxs[0]), float(header.maxs[1])]
            copc = any(v.user_id == "copc" and v.record_id == 1 for v in header.vlrs)
            tiles.append({
                strings.LidarInventoryFields.FILE: Path(os.path.relpath(path, root)).as_posix(), "size_bytes": path.stat().st_size,
                "point_count": int(header.point_count), "las_version": str(header.version),
                "point_format": header.point_format.id, strings.LidarInventoryFields.CRS_WKT: crs.to_wkt(),
                "epsg": crs.to_epsg(), strings.LidarInventoryFields.IS_COPC: copc, strings.LidarInventoryFields.BOUNDS_XY: tile_bounds,
                strings.LidarInventoryFields.SELECTED: bounds_intersect(tile_bounds, transformed),
                "query_bounds_xy": list(transformed),
                "z_range": [float(header.mins[2]), float(header.maxs[2])],
                "scales_xyz": list(map(float, header.scales)),
            })
    if not tiles:
        raise ValueError("No LAS/LAZ resources found")
    return tiles


def read_selected_points(root, tiles, working_crs):
    """Full-resolution COPC queries; ordinary LAS/LAZ use bounded-memory chunks.

    Bounds are an I/O prefilter. Per-part tests still crop against the exact
    polygon. Every class is retained. Read errors propagate instead of being
    disguised as an empty footprint. This prototype does not deduplicate
    overlapping flight tiles; their overlap remains visible in the inventory.
    """
    xs, ys, zs, classes = [], [], [], []
    for info in tiles:
        if not info[strings.LidarInventoryFields.SELECTED]:
            continue
        path = root / info[strings.LidarInventoryFields.FILE]
        xmin, ymin, xmax, ymax = info["query_bounds_xy"]
        crs = CRS.from_wkt(info[strings.LidarInventoryFields.CRS_WKT])
        if info[strings.LidarInventoryFields.IS_COPC]:
            with laspy.CopcReader.open(str(path)) as reader:
                # No resolution/level arguments: preserve full source resolution.
                points = reader.query(bounds=Bounds(np.array([xmin, ymin]), np.array([xmax, ymax])))
            chunks = (points,)
            append_points(chunks, crs, working_crs, xs, ys, zs, classes, (xmin,ymin,xmax,ymax))
        else:
            with laspy.open(path) as reader:
                append_points(reader.chunk_iterator(500_000), crs, working_crs,
                              xs, ys, zs, classes, (xmin,ymin,xmax,ymax))
    if not xs:
        raise ValueError("No points found in the requested extent")
    return tuple(np.concatenate(values) for values in (xs, ys, zs, classes))


def append_points(chunks, source_crs, target_crs, xs, ys, zs, classes, bounds_xy):
    """Append bounded source-cloud chunks to caller-owned coordinate/class lists.

    Crop by the inclusive source-CRS XY rectangle before transforming horizontal
    coordinates to target_crs. Preserve Z/classification; no height or datum
    conversion occurs. This helper accumulates arrays and does not write files.
    """
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    xmin, ymin, xmax, ymax = bounds_xy
    for points in chunks:
        x, y = np.asarray(points.x), np.asarray(points.y)
        mask = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
        if not np.any(mask):
            continue
        tx, ty = transformer.transform(x[mask], y[mask])
        xs.append(np.asarray(tx)); ys.append(np.asarray(ty))
        zs.append(np.asarray(points.z)[mask])
        classes.append(np.asarray(points.classification)[mask])


def roof_summary(z, classification):
    """Describe independent roof observations; no terrain subtraction or fitting."""
    result = {strings.BuildingHeightFields.N_POINTS: len(z), strings.LidarSamplingFields.CLASSES: {str(k): v for k,v in sorted(Counter(map(int,classification)).items())}}
    for name, values in ((strings.HeightTrialClassProfile.ALL_CLASSES, z), (strings.HeightTrialClassProfile.BUILDING_CLASS_6, z[classification == 6])):
        result[name] = {strings.BuildingHeightFields.N_POINTS: len(values), strings.GroundSamplingFields.Z_MEDIAN: float(np.median(values)) if len(values) else None,
                        "z_min": float(np.min(values)) if len(values) else None,
                        "z_max": float(np.max(values)) if len(values) else None}
    return result


def ground_grid(geometry, step):
    """Return XY grid candidates strictly inside a metric free-ground polygon.

    step is positive metre spacing; the grid starts at the polygon BBOX minimum.
    Holes and exterior boundaries are excluded by exact containment. This audit
    helper materialises the grid in memory and does not sample the raster itself.
    """
    xmin, ymin, xmax, ymax = geometry.bounds
    x = np.arange(xmin, xmax + step * 1e-9, step)
    y = np.arange(ymin, ymax + step * 1e-9, step)
    xx, yy = np.meshgrid(x,y)
    xx, yy = xx.ravel(), yy.ravel()
    mask = contains_xy(geometry, xx, yy)
    return xx[mask], yy[mask]


def sample_dtm(dataset, x, y, working_crs):
    """Transform XY to raster CRS and preserve vertical values/NoData separately."""
    if not len(x):
        return np.array([], dtype=float)
    tx, ty = Transformer.from_crs(working_crs, dataset.crs, always_xy=True).transform(x,y)
    inside = ((tx >= dataset.bounds.left) & (tx < dataset.bounds.right)
              & (ty > dataset.bounds.bottom) & (ty <= dataset.bounds.top))
    tx, ty = np.asarray(tx)[inside], np.asarray(ty)[inside]
    samples = list(dataset.sample(zip(tx, ty), indexes=1, masked=True))
    if not samples:
        return np.array([], dtype=float)
    values = np.ma.concatenate(samples).compressed()
    values = values[np.isfinite(values)]
    return values * dataset.scales[0] + dataset.offsets[0]


def roof_support(footprint, config):
    """Sampling-policy owner for erosion; preserve the original output footprint."""
    if footprint.area >= config.erode_min_area_m2 and config.erode_m > 0:
        eroded = footprint.buffer(-config.erode_m)
        if not eroded.is_empty and eroded.area > 0:
            return eroded, strings.RoofSupportErosionStatus.APPLIED
        return footprint, strings.RoofSupportErosionStatus.EMPTY_RETAINED
    return footprint, "not_attempted_small_area"


def inspect_fixture(directory, config=None):
    """Return source-coverage, roof and DTM evidence for the local audit fixture.

    Read crop_request.json, canonical/context footprint layers, selected clouds
    and one terrain raster. Require compatible metric XY, available context halo
    and complete header/raster coverage. Sample roofs and unoccupied DTM rings
    under ReferenceSampling without changing supplied files. Elevations remain
    separate: unknown vertical relationship explicitly prevents computing height.
    This diagnostic report is not a reconstruction or accuracy certification.
    """
    root = Path(directory).resolve()
    config = config or ReferenceSampling()
    request = json.loads((root / strings.AuditFixtureFiles.CROP_REQUEST).read_text(encoding=strings.TextFileEncoding.UTF8))
    if config.ground_buffers_m[-1] > request["halo_m"]:
        raise ValueError("Ground buffer exceeds the fixture's available context halo")
    working_crs = CRS.from_epsg(request[strings.GeospatialInputFields.WORKING_EPSG])
    if not working_crs.is_projected or any(a.unit_name != "metre" for a in working_crs.axis_info[:2]):
        raise ValueError("Fixture sampling requires a suitable projected metre CRS")
    gpkg = root / strings.SyntheticInputFiles.FOOTPRINTS
    buildings = load_layer(gpkg,strings.GeoPackageLayers.BUILDINGS)
    parts = load_layer(gpkg,strings.GeoPackageLayers.BUILDING_PARTS)
    context = load_layer(gpkg,strings.GeoPackageLayers.CONTEXT_BUILDINGS)
    obstacles = unary_union([geom for _,geom in buildings + context])
    inventory = inventory_tiles(root,request[strings.AuditCropFields.BBOX_XY],working_crs)
    selected = [tile for tile in inventory if tile[strings.LidarInventoryFields.SELECTED]]
    if not selected:
        raise ValueError("No LiDAR tile covers the requested extent")
    # Coverage check is geometric, not an assumption based on file naming.
    coverage = unary_union([
        box(*Transformer.from_crs(CRS.from_wkt(t[strings.LidarInventoryFields.CRS_WKT]),working_crs,always_xy=True)
            .transform_bounds(*t[strings.LidarInventoryFields.BOUNDS_XY],densify_pts=21)) for t in selected
    ])
    complete = coverage.covers(box(*request[strings.AuditCropFields.BBOX_XY]))
    if not complete:
        raise ValueError("LiDAR header extents do not cover the complete requested rectangle")
    x,y,z,classification = read_selected_points(root,inventory,working_crs)
    rasters = sorted(p for p in (root / "terrain").rglob("*") if p.suffix.lower() in (".tif",".tiff"))
    if len(rasters) != 1:
        raise ValueError("Fixture inspection requires exactly one explicit DTM raster")
    records = []
    with rasterio.open(rasters[0]) as dtm:
        if dtm.crs is None or dtm.count != 1:
            raise ValueError("DTM must have one band and a declared CRS")
        raster_bounds = Transformer.from_crs(working_crs,dtm.crs,always_xy=True).transform_bounds(
            *request[strings.AuditCropFields.BBOX_XY],densify_pts=21)
        dtm_covers = box(*dtm.bounds).covers(box(*raster_bounds))
        if not dtm_covers:
            raise ValueError("DTM does not cover the fixture extent")
        raster_info = {strings.LidarInventoryFields.FILE:rasters[0].relative_to(root).as_posix(),strings.LidarInventoryFields.CRS_WKT:dtm.crs.to_wkt(),
            "shape":[dtm.height,dtm.width],"resolution_xy":list(dtm.res),"nodata":dtm.nodata,
            strings.ModelElevationUnits.Z_UNIT:dtm.units[0],"covers_requested_extent":dtm_covers}
        for properties, footprint in parts:
            support, erosion = roof_support(footprint, config)
            # Include boundary points; the crop includes every polygon component.
            mask = intersects_xy(support,x,y)
            roof = roof_summary(z[mask],classification[mask])
            ground = {strings.GroundSamplingFields.STATUS:"no_valid_free_ground",strings.GroundSamplingFields.Z_MEDIAN:None,strings.GroundSamplingFields.VALID_SAMPLES:0}
            for radius in config.ground_buffers_m:
                free = footprint.buffer(radius).difference(obstacles)
                if free.is_empty or free.area < config.min_free_area_m2:
                    continue
                gx,gy = ground_grid(free,config.grid_step_m)
                values = sample_dtm(dtm,gx,gy,working_crs)
                if len(values) >= config.min_ground_samples:
                    ground = {strings.GroundSamplingFields.STATUS:strings.GroundSamplingStatus.SAMPLED,strings.GroundSamplingFields.Z_MEDIAN:float(np.median(values)),
                        strings.GroundSamplingFields.VALID_SAMPLES:len(values),strings.GroundSamplingFields.GRID_CANDIDATES:len(gx),strings.GroundSamplingFields.SEARCH_RADIUS_M:radius,
                        strings.GroundSamplingFields.FREE_AREA_M2:free.area}
                    break
            records.append({strings.SourceObjectIdentity.PART_ID:properties[strings.SourceObjectIdentity.PART_ID],strings.SourceObjectIdentity.BUILDING_ID:properties[strings.SourceObjectIdentity.BUILDING_ID],
                strings.PolygonFootprintFields.AREA_M2:footprint.area,strings.BuildingHeightFields.SAMPLE_AREA_M2:support.area,strings.RoofSupportFields.EROSION:erosion,
                strings.RoofSupportFields.SAMPLE_COMPONENTS:len(support.geoms) if hasattr(support,"geoms") else 1,
                "density_per_sample_m2":roof[strings.BuildingHeightFields.N_POINTS]/support.area,
                "roof":roof,strings.GroundSamplingFields.GROUND:ground,
                strings.BuildingHeightFields.HEIGHT_M:None,"height_status":"not_computed_vertical_relationship_not_declared"})
    return {strings.ReportEnvelopeFields.VERSION:strings.ReportSchemaVersion.FIXTURE_INSPECTION,strings.ReconstructionRunFields.CREATED_AT_UTC:datetime.now(timezone.utc).isoformat(),
        strings.GeospatialInputFields.WORKING_EPSG:request[strings.GeospatialInputFields.WORKING_EPSG],strings.AuditCropFields.BBOX_XY:request[strings.AuditCropFields.BBOX_XY],
        strings.FixtureInspectionFields.SAMPLING_POLICY:asdict(config),strings.FixtureInspectionFields.LIDAR_EVIDENCE:{strings.LidarSamplingFields.FILES_SCANNED:len(inventory),strings.LidarInventoryFields.SELECTED_FILES:[t[strings.LidarInventoryFields.FILE] for t in selected],
        "header_coverage_complete":complete,"points_in_extent":len(z),
        "classes_in_extent":{str(k):v for k,v in sorted(Counter(map(int,classification)).items())},"inventory":inventory},
        strings.FixtureInspectionFields.DTM_EVIDENCE:raster_info,strings.HeightTrialFields.PARTS:records,
        "vertical_relationship":"not_declared_by_source_headers",
        "process_proj_overrides_removed":list(REMOVED_PROJ_OVERRIDES),
        strings.ReconstructionRunFields.VERSIONS:{p:importlib.metadata.version(p) for p in ("laspy","lazrs","numpy","rasterio","pyproj","shapely")}}


def main():
    """Inspect one fixture and write a new JSON evidence file without overwriting."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(strings.CommandLineArguments.DATA_OPTION,type=Path,required=True,help=strings.CommandLineArguments.FIXTURE_HELP)
    parser.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True,help="New report file; existing files are rejected")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output report already exists")
    report = inspect_fixture(args.data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding=strings.TextFileEncoding.UTF8) as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({strings.LidarSamplingFields.FILES_SCANNED:report[strings.FixtureInspectionFields.LIDAR_EVIDENCE][strings.LidarSamplingFields.FILES_SCANNED],
        strings.LidarInventoryFields.SELECTED_FILES:report[strings.FixtureInspectionFields.LIDAR_EVIDENCE][strings.LidarInventoryFields.SELECTED_FILES],"points_in_extent":report[strings.FixtureInspectionFields.LIDAR_EVIDENCE]["points_in_extent"],
        strings.HeightTrialFields.PARTS:len(report[strings.HeightTrialFields.PARTS]),"parts_with_points":sum(p["roof"][strings.BuildingHeightFields.N_POINTS]>0 for p in report[strings.HeightTrialFields.PARTS]),
        "parts_with_ground":sum(p[strings.GroundSamplingFields.GROUND][strings.GroundSamplingFields.STATUS]==strings.GroundSamplingStatus.SAMPLED for p in report[strings.HeightTrialFields.PARTS]),
        "vertical_relationship":report["vertical_relationship"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
