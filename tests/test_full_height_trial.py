"""Full-scope policies: identity accounting, parent quarantine and cell ownership."""
from dataclasses import replace
import json

import numpy as np
import pytest
from shapely import STRtree
from shapely.geometry import box

from lodext.core.heights import HeightConfig, PartObservation
from lodext.io.dataset import DatasetSpec
from tools.run_full_height_trial import FullSampling, assemble_profile, building_records, metric_crs, occupied_cells


def dataset_spec():
    return DatasetSpec("1", "local-audit", 25828, 25, "footprints.gpkg", "source_inventory.json",
                       "../shared/lidar", "../shared/dtm.tif")


@pytest.mark.parametrize("change", [
    {"working_epsg": True}, {"halo_m": 0}, {"halo_m": float("nan")},
    {"dataset_version": "2"}, {"dataset_id": ""},
    {"dtm_file": "https://example.test/dtm.tif"}, {"footprints": "/external/file.gpkg"},
    {"lidar_directory": "%DATA%/lidar"},
])
def test_invalid_dataset_declarations_are_rejected(change):
    with pytest.raises(ValueError):
        replace(dataset_spec(), **change)


def test_shared_relative_assets_are_explicit_and_unknown_fields_fail(tmp_path):
    spec = dataset_spec()
    assert spec.lidar_directory == "../shared/lidar"
    from dataclasses import asdict
    payload = asdict(spec)
    payload["unknown_override"] = True
    (tmp_path / "dataset.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        DatasetSpec.read(tmp_path)


@pytest.mark.parametrize("change", [
    {"cell_size_m": 0}, {"cell_size_m": float("inf")},
    {"coverage_tolerance_m": -1}, {"max_points_per_query": True},
])
def test_invalid_streaming_limits_are_rejected(change):
    with pytest.raises(ValueError):
        FullSampling(**change)


def test_sampling_requires_metric_projected_coordinates():
    assert metric_crs(25828).is_projected
    with pytest.raises(ValueError):
        metric_crs(4326)


def test_half_open_cell_ownership_counts_boundary_points_once():
    roi = box(0, 0, 300, 300)
    cells = list(occupied_cells(STRtree([roi]), roi.bounds, 128))
    coordinates = np.array([0, 127.999, 128, 255.999, 256, 300])
    counts = np.zeros(len(coordinates), dtype=int)
    for cell in cells:
        left, bottom, right, top = cell.bounds
        counts += ((coordinates >= left) & (coordinates < right)
                   & (coordinates >= bottom) & (coordinates < top))
    assert counts.tolist() == [1] * len(coordinates)


def obs(name, roof, *, area=100, storeys=2):
    return PartObservation(name, "b", area, area, tuple(roof), 0, False, storeys)


def test_disjoint_parent_cannot_contaminate_another_parts_reference():
    parts = [obs("valid", [7] * 50, area=200), obs("needs_reference", [], area=20, storeys=1),
             obs("wrong_parent", [8] * 50, area=1000)]
    relations = {"valid": True, "needs_reference": True, "wrong_parent": False}
    rows = assemble_profile(parts, relations, {}, {}, HeightConfig())
    by_id = {r["part_id"]: r for r in rows}
    assert by_id["needs_reference"]["height_m"] == 3.5
    assert by_id["needs_reference"]["reference_part_id"] == "valid"
    assert by_id["wrong_parent"]["height_m"] == 8
    assert not by_id["wrong_parent"]["eligible_for_building_aggregation"]
    parent = building_records([{"kind": "Building", "object_id": "b", "geometry_available": True}], rows)[0]
    assert parent["max_part_height_m"] == 7 and parent["invalid_relation_parts"] == 1


def test_bad_parent_keeps_a_row_but_never_borrows_storeys_or_region():
    p = obs("bad", [], storeys=3)
    rows = assemble_profile([p], {"bad": False}, {}, {}, HeightConfig(regional_floor_height_m=4))
    assert rows[0]["method"] == "unresolved" and rows[0]["height_m"] is None
    assert "invalid_parent_no_inference" in rows[0]["flags"]


def test_coverage_error_is_not_mislabelled_as_a_parent_error():
    parts = [obs("valid", [7] * 50, area=200), obs("no_coverage", [8] * 50, area=1000),
             obs("fallback", [], area=20, storeys=1)]
    relation = {p.part_id: True for p in parts}
    rows = assemble_profile(parts, relation, {}, {"no_coverage": "incomplete_lidar_header_coverage"}, HeightConfig())
    by_id = {r["part_id"]: r for r in rows}
    assert by_id["no_coverage"]["source_relation_status"] == "spatially_valid"
    assert by_id["no_coverage"]["height_m"] is None
    assert "invalid_parent_isolated" not in by_id["no_coverage"]["flags"]
    assert by_id["fallback"]["height_m"] == 3.5


def test_missing_geometry_parent_is_still_accounted_for():
    row = building_records([{"kind": "Building", "object_id": "missing", "geometry_available": False}], [])[0]
    assert row["status"] == "missing_geometry" and row["part_count"] == 0
