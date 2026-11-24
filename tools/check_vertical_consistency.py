"""Compare DTM elevations with LAS class-2 ground as a local diagnostic.

This establishes numerical agreement only. It cannot name a vertical datum,
prove shared provenance or authorize an ECEF transform. Source files are read
without modification. A spatially distributed sample is formed by selecting
the first ground point in each grid cell, excluding the building clearance.
No offset is fitted or subtracted: a mismatch must remain visible.
"""
from __future__ import annotations
from lodext import strings

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path

if __package__:
    from .inspect_fixture import inventory_tiles, read_selected_points, load_layer
else:
    from inspect_fixture import inventory_tiles, read_selected_points, load_layer

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from shapely import intersects_xy
from shapely.ops import unary_union


@dataclass(frozen=True)
class ConsistencyConfig:
    """Owner of the fixture's empirical check policy, not an accuracy standard.

    sampling_grid_m: finite metres >0; one original ground point per cell,
      using the crop's lower-left XY as grid origin. Controls spatial thinning
      of this comparison only, not reconstruction or source point files.
    building_clearance_m: finite metres >=0; exclude buildings plus this margin;
      0 excludes their footprints alone. Reduces wall/interpolation artefacts.
    min_valid_pairs: positive int (not bool); below it evidence is insufficient.
    min_valid_fraction: fraction in (0,1]; valid pairs / selected ground points.
      A low-coverage raster must not pass on a handful of surviving samples.
    max_abs_median_z: finite source-Z units >=0; allowed absolute signed median.
    max_p95_abs_z: finite source-Z units >=max_abs_median_z; allowed 95th
      percentile absolute difference. No automatic unit or datum conversion.

    Thresholds assume the metre-valued Z used by this source pipeline, which
    the received DTM does not encode explicitly. They express a local test
    policy, not certified centimetre accuracy or named-datum validation.
    Changing them changes the diagnostic classification and requires regression
    checks. CLI/report use this owner; invalid settings are rejected.
    """

    sampling_grid_m: float = 5.0  # Metres; one ground control per comparison cell.
    building_clearance_m: float = 1.0  # Metres outside occupied building footprints.
    min_valid_pairs: int = 100  # Fewer paired observations means insufficient evidence.
    min_valid_fraction: float = 0.9  # Valid DTM pairs / selected LiDAR ground controls.
    max_abs_median_z: float = 0.1  # Metre signed-median magnitude limit for this check.
    max_p95_abs_z: float = 0.25  # Metre p95 absolute-residual ceiling; not certified accuracy.

    def __post_init__(self):
        """Reject invalid coverage fractions and contradictory residual limits."""
        values = (self.sampling_grid_m, self.building_clearance_m,
                  self.min_valid_fraction, self.max_abs_median_z, self.max_p95_abs_z)
        if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
            raise ValueError("Consistency settings must be finite numbers")
        if self.sampling_grid_m <= 0 or self.building_clearance_m < 0:
            raise ValueError("Grid must be positive and clearance nonnegative")
        if not 0 < self.min_valid_fraction <= 1:
            raise ValueError("Valid-pair fraction must be in (0,1]")
        if self.max_abs_median_z < 0 or self.max_p95_abs_z < self.max_abs_median_z:
            raise ValueError("Residual limits must be nonnegative and ordered")
        if isinstance(self.min_valid_pairs, bool) or not isinstance(self.min_valid_pairs, int) or self.min_valid_pairs < 1:
            raise ValueError("Minimum pair count must be a positive integer")


def assess_pairs(lidar_z, dtm_z, config=None):
    """Preserve pairing, reject shape mismatch and report raw DTM-minus-LAS Z.

    Status is insufficient_samples, offset_or_mismatch_detected, or
    locally_consistent. The last is deliberately weaker than a datum/origin
    claim. None is returned for statistics when no finite paired values exist.
    """
    config = config or ConsistencyConfig()
    lidar_z = np.asarray(lidar_z, dtype=float)
    dtm_z = np.asarray(dtm_z, dtype=float)
    if lidar_z.ndim != 1 or lidar_z.shape != dtm_z.shape:
        raise ValueError("LiDAR and DTM arrays must be paired one-dimensional arrays")
    valid = np.isfinite(lidar_z) & np.isfinite(dtm_z)
    residuals = dtm_z[valid] - lidar_z[valid]
    fraction = len(residuals) / len(lidar_z) if len(lidar_z) else 0.0
    median = float(np.median(residuals)) if len(residuals) else None
    p95 = float(np.percentile(np.abs(residuals), 95)) if len(residuals) else None
    if len(residuals) < config.min_valid_pairs or fraction < config.min_valid_fraction:
        status = "insufficient_samples"
    elif abs(median) > config.max_abs_median_z or p95 > config.max_p95_abs_z:
        status = strings.VerticalConsistencyStatus.OFFSET_OR_MISMATCH
    else:
        status = strings.VerticalConsistencyStatus.LOCALLY_CONSISTENT
    return {
        strings.VerticalConsistencyFields.STATUS: status, "sampled_ground_points": len(lidar_z), "valid_pairs": len(residuals),
        "valid_fraction": fraction, "residual_convention": "DTM minus LAS class 2 Z, no fitted correction",
        "median_residual_z": median, "p95_absolute_residual_z": p95,
        "quantiles_residual_z": {str(q): float(np.percentile(residuals, q)) for q in (1, 5, 25, 50, 75, 95, 99)} if len(residuals) else {},
        "max_absolute_residual_z": float(np.max(np.abs(residuals))) if len(residuals) else None,
        "fraction_abs_below_limit": float(np.mean(np.abs(residuals) <= config.max_p95_abs_z)) if len(residuals) else None,
        "common_origin_confirmed": False, "absolute_vertical_datum_identified": False,
        "evidence_scope": "Local ground elevations only; not rooftop geometry or a complete vertical reference certificate",
    }, valid


def paired_raster_values(dataset, x, y, working_crs):
    """Sample DTM with stable indices; NoData/outside/NaN remain missing pairs."""
    tx, ty = Transformer.from_crs(working_crs, dataset.crs, always_xy=True).transform(x, y)
    tx, ty = np.asarray(tx), np.asarray(ty)
    inside = ((tx >= dataset.bounds.left) & (tx < dataset.bounds.right)
              & (ty > dataset.bounds.bottom) & (ty <= dataset.bounds.top))
    output = np.full(len(x), np.nan, dtype=float)
    indices = np.flatnonzero(inside)
    if len(indices):
        samples = np.ma.concatenate(list(dataset.sample(zip(tx[inside], ty[inside]), indexes=1, masked=True)))
        output[indices] = np.ma.asarray(samples, dtype=float).filled(np.nan) * dataset.scales[0] + dataset.offsets[0]
    return output


def check_fixture(directory, config=None):
    """Return a local DTM/LiDAR assessment and paired metric ground observations.

    Read the audit fixture's crop request, cloud tiles, footprints/context and
    single DTM. Select class-2 points outside building clearance, keep one per
    configured grid cell and assess DTM-minus-LiDAR residuals. config=None uses
    ConsistencyConfig. Return (report, Nx5 pairs: X, Y, LiDAR Z, DTM Z, residual).
    This read-only numerical check does not confirm a vertical datum, common
    source provenance or absolute geodetic accuracy, and computes no building
    heights. Missing resources/invalid raster structure raise explicitly.
    """
    root = Path(directory).resolve()
    config = config or ConsistencyConfig()
    request = json.loads((root / strings.AuditFixtureFiles.CROP_REQUEST).read_text(encoding=strings.TextFileEncoding.UTF8))
    crs = CRS.from_epsg(request[strings.GeospatialInputFields.WORKING_EPSG])
    tiles = inventory_tiles(root, request[strings.AuditCropFields.BBOX_XY], crs)
    x, y, z, classification = read_selected_points(root, tiles, crs)
    features = load_layer(root / strings.SyntheticInputFiles.FOOTPRINTS, strings.GeoPackageLayers.BUILDINGS)
    features += load_layer(root / strings.SyntheticInputFiles.FOOTPRINTS, strings.GeoPackageLayers.CONTEXT_BUILDINGS)
    exclude = unary_union([g for _,g in features]).buffer(config.building_clearance_m)
    mask = (classification == 2) & ~intersects_xy(exclude, x, y)
    gx, gy, gz = x[mask], y[mask], z[mask]
    cells = np.column_stack((np.floor((gx - request[strings.AuditCropFields.BBOX_XY][0]) / config.sampling_grid_m),
                             np.floor((gy - request[strings.AuditCropFields.BBOX_XY][1]) / config.sampling_grid_m)))
    _, indices = np.unique(cells, axis=0, return_index=True)
    gx, gy, gz = gx[indices], gy[indices], gz[indices]
    rasters = sorted(p for p in (root / "terrain").rglob("*") if p.suffix.lower() in (".tif", ".tiff"))
    if len(rasters) != 1:
        raise ValueError("Select a single explicit DTM in the fixture's terrain directory")
    with rasterio.open(rasters[0]) as dataset:
        if dataset.crs is None or dataset.count != 1:
            raise ValueError("The DTM must declare a CRS and contain a single band")
        dz = paired_raster_values(dataset, gx, gy, crs)
    assessment, valid = assess_pairs(gz, dz, config)
    report = {
        strings.ReportEnvelopeFields.VERSION: strings.ReportSchemaVersion.VERTICAL_CONSISTENCY, strings.ReconstructionRunFields.CREATED_AT_UTC: datetime.now(timezone.utc).isoformat(),
        strings.GeospatialInputFields.WORKING_EPSG: request[strings.GeospatialInputFields.WORKING_EPSG], "policy": asdict(config),
        strings.LidarInventoryFields.LIDAR_FILES: [t[strings.LidarInventoryFields.FILE] for t in tiles if t[strings.LidarInventoryFields.SELECTED]],
        strings.GeospatialInputFields.DTM_FILE: rasters[0].relative_to(root).as_posix(),
        "ground_points_available": int(mask.sum()), strings.VerticalConsistencyFields.ASSESSMENT: assessment,
        "relative_test_readiness": "supported_by_local_comparison" if assessment[strings.VerticalConsistencyFields.STATUS] == strings.VerticalConsistencyStatus.LOCALLY_CONSISTENT else "not_supported",
        "source_z_units": "metres expected from the source pipeline; not explicitly encoded in the DTM",
        strings.BuildingHeightFields.HEIGHT_M: None, "origin_evidence": "not_confirmed",
    }
    pairs = np.column_stack((gx[valid], gy[valid], gz[valid], dz[valid], dz[valid] - gz[valid]))
    return report, pairs


def main():
    """Write a new JSON assessment and sibling paired CSV, preserving prior files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(strings.CommandLineArguments.DATA_OPTION, type=Path, required=True, help=strings.CommandLineArguments.FIXTURE_HELP)
    parser.add_argument(strings.CommandLineArguments.OUTPUT_OPTION, type=Path, required=True, help="New JSON report path; paired CSV is written beside it")
    args = parser.parse_args()
    csv_path = args.output.with_suffix(".csv")
    if args.output.exists() or csv_path.exists():
        raise ValueError("Choose new output paths; previous evidence is preserved")
    report, pairs = check_fixture(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding=strings.TextFileEncoding.UTF8) as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with csv_path.open("x", encoding=strings.TextFileEncoding.UTF8, newline="") as stream:
        np.savetxt(stream, pairs, delimiter=",", header="x_working,y_working,lidar_ground_z,dtm_z,dtm_minus_lidar_z", comments="", fmt="%.9f")
    print(json.dumps(report[strings.VerticalConsistencyFields.ASSESSMENT], ensure_ascii=False))


if __name__ == "__main__":
    main()
