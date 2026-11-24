"""Run the authorized experimental relative-height trial on local fixture data.

Both class profiles are explicit: all_classes retains every source class to
compare with the historical method; building_class_6 selects ASPRS building
points. Reference heights are comparison-only and never enter the estimator.
No named vertical datum, terrain clamping or ECEF placement is asserted.
"""
from __future__ import annotations
from lodext import strings

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import json
from pathlib import Path

if __package__:
    from .check_vertical_consistency import check_fixture
    from .inspect_fixture import ReferenceSampling, inspect_fixture, inventory_tiles, load_layer, read_selected_points, roof_support
else:
    from check_vertical_consistency import check_fixture
    from inspect_fixture import ReferenceSampling, inspect_fixture, inventory_tiles, load_layer, read_selected_points, roof_support

from pyproj import CRS
from shapely import intersects_xy
import numpy as np

from lodext.core.heights import HeightConfig, PartObservation, estimate_building


# Closed profile domain owned here. None means all original classifications;
# (6,) is an explicit filter, never a silent replacement of the reference run.
# Both small/full trial runners produce separately named results for these
# profiles using the same original observations. Adding a key changes report
# domains and comparison scope, not the public BuildConfig.roof_classes default.
CLASS_PROFILES = {strings.HeightTrialClassProfile.ALL_CLASSES: None, strings.HeightTrialClassProfile.BUILDING_CLASS_6: (6,)}


def run_trial(directory, *, experimental_relative_z: bool, height_config=None):
    """Require explicit trial scope and fresh local consistency evidence.

    experimental_relative_z is required bool; False rejects execution. True
    authorizes only local numerical trials, not a datum assertion or publishing.
    CLI owns its disabled-by-default switch. height_config=None delegates to
    HeightConfig's sole defaults. Sources and previous reports remain untouched.
    """
    if experimental_relative_z is not True:
        raise ValueError("This trial needs explicit experimental-relative-Z scope")
    height_config = HeightConfig() if height_config is None else height_config
    root = Path(directory).resolve()
    evidence, _ = check_fixture(root)
    if evidence[strings.VerticalConsistencyFields.ASSESSMENT][strings.VerticalConsistencyFields.STATUS] != strings.VerticalConsistencyStatus.LOCALLY_CONSISTENT:
        raise ValueError("Fresh local ground comparison does not support this relative trial")
    sampling = ReferenceSampling()
    audit = inspect_fixture(root, sampling)
    crs = CRS.from_epsg(audit[strings.GeospatialInputFields.WORKING_EPSG])
    tiles = inventory_tiles(root, audit[strings.AuditCropFields.BBOX_XY], crs)
    x, y, z, classes = read_selected_points(root, tiles, crs)
    parts = load_layer(root / strings.SyntheticInputFiles.FOOTPRINTS, strings.GeoPackageLayers.BUILDING_PARTS)
    sampled = {p[strings.SourceObjectIdentity.PART_ID]: p for p in audit[strings.HeightTrialFields.PARTS]}
    profiles = {}
    for profile, allowed_classes in CLASS_PROFILES.items():
        buildings = defaultdict(list)
        reference_values = {}
        for props, footprint in parts:
            support, _ = roof_support(footprint, sampling)
            mask = intersects_xy(support, x, y)
            if allowed_classes is not None:
                mask &= np.isin(classes, allowed_classes)
            record = sampled[props[strings.SourceObjectIdentity.PART_ID]]
            observation = PartObservation(
                part_id=props[strings.SourceObjectIdentity.PART_ID], building_id=props[strings.SourceObjectIdentity.BUILDING_ID],
                area_m2=footprint.area, sample_area_m2=support.area,
                roof_z=tuple(map(float, z[mask])), ground_z=record[strings.GroundSamplingFields.GROUND][strings.GroundSamplingFields.Z_MEDIAN],
                check_small_part_coherence=footprint.area < sampling.erode_min_area_m2,
                storeys_above=props.get(strings.BuildingInputFields.STOREYS_ABOVE), storeys_below=props.get(strings.BuildingInputFields.STOREYS_BELOW),
            )
            buildings[observation.building_id].append(observation)
            reference_values[observation.part_id] = props.get(strings.BuildingInputFields.REFERENCE_HEIGHT_M)
        results = []
        for building_id in sorted(buildings):
            for estimate in estimate_building(buildings[building_id], height_config):
                row = asdict(estimate)
                original = reference_values[estimate.part_id]
                row[strings.BuildingInputFields.REFERENCE_HEIGHT_M] = original
                row[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] = estimate.height_m - original if estimate.height_m is not None and original is not None else None
                row[strings.BuildingHeightFields.BASE_Z] = estimate.ground_z
                row[strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z] = estimate.ground_z + estimate.height_m if estimate.height_m is not None else None
                row[strings.BuildingHeightFields.SAMPLING_EVIDENCE] = {key: sampled[estimate.part_id][key] for key in (strings.PolygonFootprintFields.AREA_M2, strings.BuildingHeightFields.SAMPLE_AREA_M2, strings.RoofSupportFields.SAMPLE_COMPONENTS, strings.RoofSupportFields.EROSION)}
                results.append(row)
        differences = [abs(p[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M]) for p in results if p[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] is not None]
        profiles[profile] = {
            "class_filter": list(allowed_classes) if allowed_classes is not None else None,
            strings.BuildingHeightFields.METHODS: dict(Counter(p[strings.BuildingHeightFields.METHOD] for p in results)), strings.HeightTrialFields.PARTS: results,
            "comparison": {"paired_parts": len(differences),
                strings.HeightTrialFields.MEAN_ABSOLUTE_DIFFERENCE_M: float(np.mean(differences)) if differences else None,
                strings.HeightTrialFields.MAX_ABSOLUTE_DIFFERENCE_M: max(differences) if differences else None,
                strings.HeightTrialFields.PARTS_OVER_0_5M: sum(value > 0.5 for value in differences)},
        }
    return {
        strings.ReportEnvelopeFields.VERSION: strings.ReportSchemaVersion.SMALL_HEIGHT_TRIAL, "algorithm": "lodext-modal-height-0.1",
        strings.ReconstructionRunFields.CREATED_AT_UTC: datetime.now(timezone.utc).isoformat(),
        strings.ValidationReportFields.SCOPE: "experimental_relative_heights", strings.GeospatialInputFields.WORKING_EPSG: audit[strings.GeospatialInputFields.WORKING_EPSG],
        strings.VerticalConsistencyFields.ABSOLUTE_VERTICAL_DATUM: None, strings.TileConversionFields.CLAMPING_APPLIED: False,
        strings.TileConversionFields.PLACEMENT: "Terrain placement is separate; base_z is the sampled DTM basis, not an ellipsoidal height assertion.",
        "local_vertical_evidence": evidence[strings.VerticalConsistencyFields.ASSESSMENT],
        strings.HeightTrialFields.SAMPLING_CONFIG: asdict(sampling), strings.HeightTrialFields.HEIGHT_CONFIG: asdict(height_config),
        "selected_lidar_files": audit[strings.FixtureInspectionFields.LIDAR_EVIDENCE][strings.LidarInventoryFields.SELECTED_FILES], strings.HeightTrialFields.PROFILES: profiles,
        strings.BuildingHeightFields.REFERENCE_ROLE: "Stored comparison values only; not independent surveyed truth.",
    }


def write_report(report, output):
    """Create a new run directory with JSON and flat comparison CSV."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "relative_heights.json").open("x", encoding=strings.TextFileEncoding.UTF8) as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    fields = [strings.HeightTrialFields.PROFILE, strings.SourceObjectIdentity.BUILDING_ID, strings.SourceObjectIdentity.PART_ID, strings.BuildingHeightFields.METHOD, strings.BuildingHeightFields.HEIGHT_M, strings.BuildingInputFields.REFERENCE_HEIGHT_M,
              strings.HeightTrialFields.DELTA_FROM_REFERENCE_M, strings.BuildingHeightFields.GROUND_Z, "roof_mode_z", strings.BuildingHeightFields.N_POINTS, strings.BuildingHeightFields.DENSITY_POINTS_M2,
              strings.BuildingHeightFields.ROOF_STRENGTH, strings.BuildingHeightFields.REFERENCE_PART_ID, strings.BuildingHeightFields.FLAGS]
    with (output / "comparison.csv").open("x", encoding=strings.TextFileEncoding.UTF8, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for profile, values in report[strings.HeightTrialFields.PROFILES].items():
            for record in values[strings.HeightTrialFields.PARTS]:
                row = {key: record[key] for key in fields if key not in (strings.HeightTrialFields.PROFILE, strings.BuildingHeightFields.FLAGS)}
                row.update(profile=profile, flags=";".join(record[strings.BuildingHeightFields.FLAGS]))
                writer.writerow(row)


def main():
    """Run the opt-in relative-Z audit and write reports in a new directory.

    Regional fallback remains explicitly supplied; omitted values delegate to
    HeightConfig. This CLI does not declare an absolute datum or clamp a model.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(strings.CommandLineArguments.DATA_OPTION, type=Path, required=True, help=strings.CommandLineArguments.FIXTURE_HELP)
    parser.add_argument(strings.CommandLineArguments.OUTPUT_OPTION, type=Path, required=True, help=strings.CommandLineArguments.NEW_RUN_HELP)
    parser.add_argument(strings.CommandLineArguments.RELATIVE_Z_OPTION, action="store_true",
                        help="Explicit local relative trial, disabled by default; no absolute datum or clamping claim")
    parser.add_argument("--regional-floor-height-m", type=float, default=HeightConfig.regional_floor_height_m,
                        help="Optional regional fallback; omitted means no regional assumption")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(strings.OutputDirectoryMessages.OUTPUT_EXISTS)
    report = run_trial(args.data, experimental_relative_z=args.experimental_relative_z,
                       height_config=HeightConfig(regional_floor_height_m=args.regional_floor_height_m))
    write_report(report, args.output)
    print(json.dumps({profile: {strings.BuildingHeightFields.METHODS: p[strings.BuildingHeightFields.METHODS], "comparison": p["comparison"]}
                      for profile, p in report[strings.HeightTrialFields.PROFILES].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
