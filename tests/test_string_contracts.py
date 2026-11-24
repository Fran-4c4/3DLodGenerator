"""Compatibility at configuration, diagnostic and source-identity boundaries.

Expected wire strings deliberately do not import the implementation vocabulary:
an accidental catalogue rename must fail here rather than change both sides.
"""
from dataclasses import fields
import json

import pytest
from shapely.geometry import box

from lodext.core.config import SamplingConfig
from lodext.core.heights import finite_number
from lodext.core.surfaces import SurfaceConfig
from lodext.io.dataset import DatasetSpec
from lodext.io.footprints import Feature
from lodext.io.surfaces import SurfaceFeature


def surface_config(**changes):
    """Build a valid literal external surface request for boundary checks."""
    return SurfaceConfig(**({
        "config_version": "1", "surface_contract": "0.1", "dataset_id": "contracts",
        "polygons": "input.gpkg", "lidar": ["input.las"], "working_epsg": 25828,
        "vertical_reference": "local_relative",
    } | changes))


def test_class_constants_never_become_surface_input_or_serialized_fields(tmp_path):
    config = surface_config(lifting={"Road": {"percentile": 25, "las_classes": [11]}})
    effective = config.effective()
    assert effective["missing_vertices"] == "nearest_ring"
    assert effective["lifting"]["Road"] == {"percentile": 25, "las_classes": (11,)}
    assert set(effective) == {f.name for f in fields(SurfaceConfig)}
    assert not {"FIELD_LIFTING", "MISSING_VERTEX_NEAREST_RING"} & effective.keys()
    path = tmp_path / "surface.json"
    path.write_text(json.dumps({**effective, "FIELD_LIFTING": "unexpected"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown SurfaceConfig fields"):
        SurfaceConfig.read(path)


def test_dataset_resource_group_remains_class_only_and_resolves_all_resources(tmp_path):
    for name in ("input.gpkg", "inventory.json", "dtm.tif"):
        (tmp_path / name).touch()
    (tmp_path / "clouds").mkdir()
    request = {
        "dataset_version": "1", "dataset_id": "contracts", "working_epsg": 25828,
        "halo_m": 25, "footprints": "input.gpkg", "source_inventory": "inventory.json",
        "lidar_directory": "clouds", "dtm_file": "dtm.tif",
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    config = DatasetSpec.read(tmp_path)
    assert {f.name for f in fields(DatasetSpec)} == set(request)
    assert set(config.paths(tmp_path)) == {"footprints", "source_inventory", "lidar_directory", "dtm_file"}
    path.write_text(json.dumps({**request, "RESOURCE_FIELDS": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly the required keys"):
        DatasetSpec.read(tmp_path)


@pytest.mark.parametrize("factory, message", [
    (lambda: finite_number(True, "height_m"), "height_m must be a finite number"),
    (lambda: SamplingConfig(chunk_points=0), "chunk_points must be an integer >= 1"),
    (lambda: surface_config(dataset_id=""), "dataset_id must be nonempty text"),
    (lambda: surface_config(max_tin_vertices=2), "max_tin_vertices must be an integer >= 3"),
    (lambda: surface_config(config_version="other"), "Expected config_version '1' and surface_contract '0.1'"),
])
def test_shared_error_templates_preserve_exception_type_and_field_context(factory, message):
    with pytest.raises(ValueError) as error:
        factory()
    assert str(error.value) == message


def test_identity_delimiter_preserves_embedded_source_text():
    feature = Feature("BuildingPart", "survey::42", "parent", box(0, 0, 1, 1), {}, [])
    surface = SurfaceFeature("survey::42", "Road", box(0, 0, 1, 1))
    assert feature.key == "BuildingPart::survey::42"
    assert surface.key == "Road::survey::42"
    assert feature.parent_id == "parent"


def test_status_contract_owners_do_not_couple_distinct_record_shapes(tmp_path, monkeypatch):
    """Distinct probe keys expose cross-contract bindings hidden by equal wire text.

    Ordinary wire compatibility is tested by the public pipeline/schema tests.
    These temporary spellings test producer/consumer ownership, not a supported
    user facility for renaming public fields at runtime.
    """
    from lodext import strings
    from lodext.demo import create_demo
    from lodext.pipeline import run_build
    from lodext.surface_demo import create_surface_demo
    from lodext.surface_pipeline import run_surfaces

    monkeypatch.setattr(strings.ReconstructionObjectFields, "STATUS", "_object_state_probe")
    monkeypatch.setattr(strings.ReconstructionRunFields, "STATUS", "_run_state_probe")
    monkeypatch.setattr(strings.VerticalConsistencyFields, "STATUS", "_vertical_state_probe")
    monkeypatch.setattr(strings.RoadFitFields, "STATUS", "_fit_state_probe")
    create_demo(tmp_path / "building-inputs")
    summary = run_build(tmp_path / "building-inputs/build.json", tmp_path / "buildings")
    assert summary["_run_state_probe"] == "complete"
    assert "_object_state_probe" not in summary
    quality = json.loads((tmp_path / "buildings/quality.json").read_text(encoding="utf-8"))
    assert all("_object_state_probe" in row and "_run_state_probe" not in row
               for row in quality["objects"])
    assert quality["cloud"]["vertical_check"]["_vertical_state_probe"] == "locally_consistent"
    assert "_object_state_probe" not in quality["cloud"]["vertical_check"]

    create_surface_demo(tmp_path / "surface-inputs")
    summary = run_surfaces(tmp_path / "surface-inputs/surfaces.json", tmp_path / "surfaces")
    assert summary["_run_state_probe"] == "complete"
    quality = json.loads((tmp_path / "surfaces/quality.json").read_text(encoding="utf-8"))
    road = next(row for row in quality["objects"] if row["source_class"] == "Road")
    assert road["_object_state_probe"] == "resolved"
    fit = road["components"][0]["road_fit"]
    assert fit["_fit_state_probe"] == "flattened"
    assert "_object_state_probe" not in fit
