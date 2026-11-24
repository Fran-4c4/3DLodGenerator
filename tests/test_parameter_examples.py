"""Physical controls for runnable user-facing comparisons, not mock pictures."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest
from jsonschema import Draft7Validator
from shapely import from_wkb
from shapely.geometry import Polygon
from shapely.ops import unary_union

from lodext.export.cityjson import validate_cityjson
from lodext.export.tiles import surfaces, triangulate_surface


@pytest.fixture(scope="module")
def gallery(tmp_path_factory):
    path=Path(__file__).resolve().parents[1]/"tools/generate_parameter_examples.py"
    spec=importlib.util.spec_from_file_location("parameter_examples",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    root=tmp_path_factory.mktemp("parameters")/"gallery"
    module.generate(root)
    return root


def records(root, family, variant):
    report=json.loads((root/family/"evidence"/(variant+".json")).read_text())
    return {r["source_id"]:r for r in report["objects"]}


def test_parameter_changes_exercise_height_support_and_fallback(gallery):
    # Boundary tolerance may leave uncertainty, but must never choose the high edge contamination.
    for variant in ("none","half","one"):
        assert records(gallery,"erosion",variant)["main"]["height_m"] is None or records(gallery,"erosion",variant)["main"]["height_m"]==pytest.approx(6)
    assert records(gallery,"erosion","one")["main"]["height_m"]==pytest.approx(6)
    # Actual labels differ between the two input LAS files; XYZ remains fixed.
    for variant in ("all","roof"):
        assert records(gallery,"classes",variant)["main"]["height_m"]==pytest.approx(6)
    for variant in ("count","density"):
        r=records(gallery,"density",variant)["terrace"]
        assert r["height_m"]==pytest.approx(2) and r["building_surfaces"]["accepted"]
    assert records(gallery,"auxiliary","off")["sparse"]["height_m"] is None
    r=records(gallery,"auxiliary","on")["sparse"]
    assert (r["height_m"],r["method"])==(4,"external_height")
    assert records(gallery,"floor-reference","standard")["sparse"]["height_m"] is None
    r=records(gallery,"floor-reference","lower")["sparse"]
    assert r["height_m"]==pytest.approx(2) and r["method"]=="floor_share"
    for v in ("standard","lower"):
        assert records(gallery,"floor-reference",v)["terrace"]["height_m"]==pytest.approx(2)
        assert records(gallery,"floor-reference",v)["main"]["height_m"]==pytest.approx(4)
    assert records(gallery,"ground","short")["main"]["ground_z"] is None
    r=records(gallery,"ground","expand")["main"]
    assert (r["ground_z"],r["ground_radius_m"],r["height_m"])==(25,6,6)


def test_water_levels_and_road_outlier_replacement_are_measured(gallery):
    for variant,z in (("low",24),("high",25)):
        r=records(gallery,"water",variant)["pond"]
        assert r["water_level_z"]==z
        assert set(r["components"][0]["boundary_z"])=={z}
    road={v:records(gallery,"road",v)["road"]["components"][0] for v in ("raw","filter","smooth")}
    assert max(road["raw"]["boundary_z"])>28
    assert max(road["filter"]["boundary_z"])<27
    assert road["filter"]["road_fit"]["changed_vertices"]>0
    assert road["smooth"]["road_fit"]["changed_vertices"]==12
    assert road["filter"]["boundary_z"]!=road["smooth"]["boundary_z"]


def test_actual_models_and_display_triangles_retain_footprints_and_coordinates(gallery):
    schema=json.loads((Path(__file__).parent/"schemas/cityjson-2.0.1.schema.json").read_text())
    validator=Draft7Validator(schema)
    models_checked=0
    for folder in [p for p in gallery.iterdir() if p.is_dir()]:
        display=json.loads((folder/"presentation.json").read_text())
        with sqlite3.connect(folder/"inputs/footprints.gpkg") as db:
            footprints={identifier:from_wkb(bytes(blob)[8:]) for identifier,blob in db.execute("SELECT part_id,geom FROM building_parts")}
        for case in display["cases"]:
            model=json.loads((folder/"models"/(case["id"]+".city.json")).read_text())
            errors=list(validator.iter_errors(model))
            assert not errors, [(list(e.path),e.message) for e in errors[:3]]
            validate_cityjson(model)
            xyz=np.asarray(model["vertices"],dtype=float).reshape(-1,3)*model["transform"]["scale"]+model["transform"]["translate"]
            rendered={mesh["id"]:mesh for mesh in case["meshes"]}
            for identifier,obj in model["CityObjects"].items():
                faces=[face for geom in obj.get("geometry",[]) for face in surfaces(geom)]
                if not faces:continue
                indices=[i for face in faces for i in triangulate_surface(face,xyz)]
                transported=np.asarray(rendered[identifier]["positions"]).reshape(-1,3)
                assert np.max(np.abs(transported-(xyz[indices]-display["origin"])))<1e-6
                if obj["type"]=="BuildingPart":
                    projected=[Polygon(xyz[f[0],:2]) for f in faces if Polygon(xyz[f[0],:2]).area>0]
                    actual=unary_union(projected)
                    source=footprints[identifier.split("::",1)[1]]
                    assert actual.symmetric_difference(source).area<1e-5
            assert len(case["selected_xyz"])==3*len(case["selected_classes"])
            assert len(case["rejected_xyz"])==3*len(case["rejected_classes"])
            if folder.name=="lod" and case["id"]=="zero":
                assert not case["selected_xyz"]
                assert all(g["type"]=="MultiSurface" for o in model["CityObjects"].values() for g in o.get("geometry",[]))
            models_checked+=1
    assert models_checked==20
