"""Measurable acceptance for first-class surface lifting, not full scene parity."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys

import laspy
import numpy as np
import pytest
from jsonschema import Draft7Validator
from shapely import to_wkb
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from lodext.core.surfaces import DEFAULT_LIFTING, SurfaceConfig
from lodext.export.cityjson import validate_cityjson
from lodext.export.tiles import TileConfig, write_tiles
from lodext.io.surfaces import SurfaceFeature, read_surfaces
from lodext.reconstruction.surfaces import (SurfaceUnresolved, constrained_mesh,
                                          rank_elevation, reconstruct_surface, smooth_road)
from lodext.surface_demo import create_surface_demo
from lodext.surface_pipeline import run_surfaces
from lodext.surface_pipeline import build_surface_cityjson


@pytest.fixture(scope="module")
def surface_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("surface pipeline")
    inputs, output = root/"input with spaces", root/"output"
    create_surface_demo(inputs)
    before = {name: hashlib.sha256((inputs/name).read_bytes()).hexdigest()
              for name in ("footprints.gpkg", "surfaces.las")}
    summary = run_surfaces(inputs/"surfaces.json", output)
    return inputs, output, summary, before


def config(**changes):
    return SurfaceConfig(**({"config_version": "1", "surface_contract": "0.1",
        "dataset_id": "test", "polygons": "input.gpkg", "lidar": ["input.las"],
        "working_epsg": 25828, "vertical_reference": "local_relative"} | changes))


def world(model):
    return np.asarray(model["vertices"])*model["transform"]["scale"]+model["transform"]["translate"]


def object_shapes(model, obj):
    vertices = world(model)
    return [Polygon(vertices[surface[0], :2]) for g in obj["geometry"] for surface in g["boundaries"]]


def test_public_surface_workflow_preserves_shapes_relief_water_and_classes(surface_run):
    inputs, output, summary, before = surface_run
    assert summary["status"] == "complete"
    assert summary["resolved_objects"] == 4
    assert summary["stitching_applied"] is False
    assert summary["minimum_product_complete"] is False
    for name, digest in before.items():
        assert hashlib.sha256((inputs/name).read_bytes()).hexdigest() == digest
    model = json.loads((output/"model.surfaces.city.json").read_text())
    truth = json.loads((inputs/"surface-truth.json").read_text())
    vertices = world(model)
    observed_types = set()
    for obj in model["CityObjects"].values():
        observed_types.add(obj["type"])
        kind = obj["attributes"]["sourceClass"]
        shapes = object_shapes(model, obj)
        assert sum(p.area for p in shapes) == pytest.approx(truth[kind]["area_m2"], abs=.001)
        assert unary_union(shapes).area == pytest.approx(sum(p.area for p in shapes), abs=.001)
        indices = {i for g in obj["geometry"] for face in g["boundaries"] for i in face[0]}
        used = vertices[sorted(indices)]
        if kind == "Water":
            assert np.ptp(used[:, 2]) == 0
            assert used[0, 2] == 24
        elif kind == "Terrain":
            assert any(np.allclose(p, truth[kind]["peak_xyz"]) for p in used)
        elif kind == "Road":
            # A percentile in a finite-radius neighbourhood can be biased on
            # a slope, especially at corners. Check all recovered vertices
            # against the independent plane within radius × grade, not exact
            # extrema that the reference method does not promise to preserve.
            grade = (truth[kind]["maximum_z"]-truth[kind]["minimum_z"])/np.ptp(used[:,0])
            expected = truth[kind]["minimum_z"]+grade*(used[:,0]-used[:,0].min())
            settings = json.loads((output/"run.json").read_text())["config"]
            assert np.max(np.abs(used[:,2]-expected)) <= grade*settings["radius_m"]+.001
        else:
            assert used[:, 2].min() == pytest.approx(truth[kind]["minimum_z"], abs=.001)
            assert used[:, 2].max() == pytest.approx(truth[kind]["maximum_z"], abs=.001)
    assert observed_types == {"Road", "TINRelief", "PlantCover", "WaterBody"}
    assert validate_cityjson(model)["closed_shells"] == 0


def test_official_schema_accepts_surface_types_and_geometry(surface_run):
    model = json.loads((surface_run[1]/"model.surfaces.city.json").read_text())
    schema = json.loads((Path(__file__).parent/"schemas/cityjson-2.0.1.schema.json").read_text())
    errors = list(Draft7Validator(schema).iter_errors(model))
    assert not errors, [(list(e.path), e.message) for e in errors[:5]]


def test_surface_model_converts_to_independently_validated_glb(surface_run, tmp_path):
    result = write_tiles(surface_run[1]/"model.surfaces.city.json", tmp_path/"tiles", TileConfig(0))
    assert result["objects_with_mesh"] == 4
    assert (tmp_path/"tiles/model.glb").read_bytes()[:4] == b"glTF"


def test_report_preserves_fit_point_support_and_class_filter(surface_run):
    records = json.loads((surface_run[1]/"quality.json").read_text())["objects"]
    by_kind = {r["source_class"]: r for r in records}
    assert by_kind["Road"]["components"][0]["road_fit"]["status"] == "flattened"
    assert by_kind["Terrain"]["components"][0]["interior_xy_observations"] > 0
    assert by_kind["Forest"]["sample_points"] == 121  # canopy returns are excluded
    assert all(not any(c["borrowed_boundary_indices"] for c in r["components"]) for r in records)


def test_constrained_tin_retains_courtyard_and_inserts_shared_edge_points():
    polygon = Polygon([(0,0),(8,0),(8,8),(0,8)], [[(3,3),(3,5),(5,5),(5,3)]])
    boundary = {tuple(p): 10.0 for r in [polygon.exterior, *polygon.interiors] for p in list(r.coords)[:-1]}
    # Include a point on an initial constrained-diagonal edge, requiring both
    # incident triangles to be split, and genuine relief elsewhere.
    initial = constrained_mesh(polygon, boundary, [], 100)
    edges = [(a, b) for t in initial for a, b in zip(t, t[1:]+t[:1])
             if not polygon.boundary.covers(LineString([a[:2], b[:2]]))]
    a, b = edges[0]
    middle = ((a[0]+b[0])/2, (a[1]+b[1])/2, 12)
    mesh = constrained_mesh(polygon, boundary, [middle, (1,1,14)], 100)
    shapes = [Polygon(t) for t in mesh]
    assert sum(s.area for s in shapes) == pytest.approx(60)
    assert unary_union(shapes).symmetric_difference(polygon).area < 1e-9
    assert not any(s.contains(Point(4,4)) for s in shapes)
    assert any(p == [1,1,14.0] for t in mesh for p in t)


def test_disconnected_components_keep_identity_and_separate_elevation_support():
    geom = MultiPolygon([box(0,0,2,2), box(10,0,12,2)])
    points = np.array([(x,y,z) for g,z in zip(geom.geoms,[10,20])
                       for x,y in list(g.exterior.coords)[:-1]], dtype=float)
    meshes, report = reconstruct_surface(SurfaceFeature("two", "Road", geom), points,
                                        config(radius_m=.01, road_filter_outliers=False, road_flatten=False))
    assert len(meshes) == 2 and len(report["components"]) == 2
    assert {p[2] for t in meshes[0] for p in t} == {10}
    assert {p[2] for t in meshes[1] for p in t} == {20}


def test_rank_uses_observed_zero_based_reference_order_not_interpolated_quantile():
    assert rank_elevation([1,2,3,4], 50) == 3
    assert rank_elevation([1,2,3,4], 100) == 4
    assert rank_elevation([1,2,3,4], 0) == 1


def test_partial_boundary_support_is_borrowed_explicitly_or_rejected():
    feature = SurfaceFeature("ring", "Road", box(0,0,2,2))
    one = np.array([[0,0,15.0]])
    meshes, report = reconstruct_surface(feature, one, config(radius_m=.1))
    assert len(report["components"][0]["borrowed_boundary_indices"]) == 3
    assert {p[2] for t in meshes[0] for p in t} == {15}
    with pytest.raises(SurfaceUnresolved, match="unsupported_boundary_vertex"):
        reconstruct_surface(feature, one, config(radius_m=.1, missing_vertices="error"))


def test_unsupported_hole_ring_never_borrows_from_a_different_ring():
    geom = Polygon([(0,0),(10,0),(10,10),(0,10)], [[(4,4),(4,6),(6,6),(6,4)]])
    with pytest.raises(SurfaceUnresolved, match="ring_without_elevation_support"):
        reconstruct_surface(SurfaceFeature("hole", "Road", geom), np.array([[0,0,5]]), config(radius_m=.1))


def test_quadratic_fit_preserves_a_known_sloping_surface_and_reports_rank_failures():
    xy = np.array([(x,y) for x in range(4) for y in range(4)], dtype=float)
    z = 20 + .3*xy[:,0] + .1*xy[:,1] + .02*xy[:,0]**2
    fitted, report = smooth_road(xy + [500000,3100000], z, config())
    assert fitted == pytest.approx(z, abs=1e-9)
    assert report["status"] == "flattened"
    _, report = smooth_road(np.array([(x,0) for x in range(8)]), np.arange(8), config())
    assert report["status"] == "skipped_rank_deficient"


def test_quadratic_outlier_is_replaced_without_forcing_all_raw_vertices():
    xy = np.array([(x,y) for x in range(5) for y in range(5)], dtype=float)
    z = 20 + .3*xy[:,0] + .1*xy[:,1]
    dirty = z.copy(); dirty[12] += 20
    fitted, report = smooth_road(xy, dirty, config(road_flatten=False))
    assert fitted == pytest.approx(z, abs=1e-8)
    assert 12 in report["outlier_vertices"]


@pytest.mark.parametrize("changes", [
    {"lifting":{"Unknown":{}}}, {"lifting":{"Road":{"percentile":101}}},
    {"lifting":{"Road":{"las_classes":[]}}}, {"radius_m":0}, {"chunk_points":True},
    {"road_flatten":"false"}, {"max_outlier_fraction":1}, {"missing_vertices":"zero"},
])
def test_invalid_surface_policies_fail_explicitly(changes):
    with pytest.raises(ValueError):
        config(**changes)


def test_lifting_override_does_not_mutate_authoritative_defaults():
    changed = config(lifting={"Road":{"las_classes":[11], "percentile":25}})
    assert changed.lifting["Road"].las_classes == (11,)
    assert config().lifting["Road"] == DEFAULT_LIFTING["Road"]
    assert replace(changed, radius_m=2).lifting["Road"] == changed.lifting["Road"]
    with pytest.raises(TypeError):
        changed.lifting["Road"] = DEFAULT_LIFTING["Road"]


def changed_configuration(inputs, destination, **changes):
    data = json.loads((inputs/"surfaces.json").read_text())
    # Use absolute references only in temporary tests, since this copy can live
    # outside the fixture directory. Runtime remains config-relative.
    data["polygons"] = str(inputs/data["polygons"])
    data["lidar"] = [str(inputs/p) for p in data["lidar"]]
    data.update(changes)
    destination.write_text(json.dumps(data))
    return destination


def test_absent_class_support_is_partial_and_strict_policy_aborts(surface_run, tmp_path):
    path = changed_configuration(surface_run[0], tmp_path/"bad.json",
                                lifting={"Road":{"las_classes":[200]}})
    summary = run_surfaces(path, tmp_path/"partial")
    assert summary["status"] == "partial" and summary["unresolved_objects"] == 1
    objects = json.loads((tmp_path/"partial/model.surfaces.city.json").read_text())["CityObjects"]
    assert objects["Road::slope"]["geometry"] == []
    path = changed_configuration(surface_run[0], tmp_path/"strict.json",
                                lifting={"Road":{"las_classes":[200]}}, unresolved_objects="error")
    with pytest.raises(ValueError, match="Unresolved Road"):
        run_surfaces(path, tmp_path/"strict")
    assert not (tmp_path/"strict").exists()


def test_resource_guards_and_existing_output_never_silently_drop_points(surface_run, tmp_path):
    with pytest.raises(ValueError, match="already exists"):
        run_surfaces(surface_run[0]/"surfaces.json", surface_run[1])
    path = changed_configuration(surface_run[0], tmp_path/"small.json", max_points_per_feature=3)
    with pytest.raises(ValueError, match="no automatic thinning"):
        run_surfaces(path, tmp_path/"small")
    assert not (tmp_path/"small").exists()


def test_canonical_reader_rejects_unsupported_classes_and_web_mercator(surface_run, tmp_path):
    import shutil
    gpkg = tmp_path/"copy.gpkg"; shutil.copy2(surface_run[0]/"footprints.gpkg", gpkg)
    with sqlite3.connect(gpkg) as db:
        db.execute("UPDATE surfaces SET surface_class='Bridge' WHERE surface_class='Road'")
    with pytest.raises(ValueError, match="not implemented"):
        read_surfaces(config(polygons=str(gpkg)), tmp_path)
    with pytest.raises(ValueError, match="Web Mercator"):
        read_surfaces(config(polygons=str(gpkg), working_epsg=3857), tmp_path)


def test_surface_cli_from_another_directory_has_real_outputs_and_partial_exit(surface_run, tmp_path):
    path = changed_configuration(surface_run[0], tmp_path/"cli.json", lifting={"Road":{"las_classes":[200]}})
    command = [sys.executable,"-m","lodext","build-surfaces",str(path),"--output",str(tmp_path/"cli")]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 3, run.stderr
    assert (tmp_path/"cli/model.surfaces.city.json").is_file()


def test_quantization_must_not_join_distinct_components():
    geom = MultiPolygon([box(0,0,1,1), box(1.0004,0,2.0004,1)])
    feature = SurfaceFeature("close", "Road", geom)
    points = np.array([(x,y,10) for g in geom.geoms for x,y in list(g.exterior.coords)[:-1]])
    settings = config(radius_m=.00001)
    meshes, evidence = reconstruct_surface(feature, points, settings)
    with pytest.raises(ValueError, match="merges disconnected"):
        build_surface_cityjson([feature], {feature.key:meshes}, {feature.key:{**evidence,"status":"resolved"}}, settings)


def test_reader_transforms_geographic_polygons_without_changing_source(surface_run, tmp_path):
    import shutil
    from pyproj import Transformer
    from shapely.ops import transform
    from lodext.io.footprints import gpkg_geometry
    gpkg = tmp_path/"geographic.gpkg"; shutil.copy2(surface_run[0]/"footprints.gpkg", gpkg)
    converter = Transformer.from_crs(25828,4326,always_xy=True)
    with sqlite3.connect(gpkg) as db:
        for fid, blob in db.execute("SELECT fid,geom FROM surfaces").fetchall():
            geographic = transform(converter.transform,gpkg_geometry(blob))
            encoded = b"GP\x00\x01"+struct.pack("<i",4326)+to_wkb(geographic)
            db.execute("UPDATE surfaces SET geom=? WHERE fid=?",(encoded,fid))
        db.execute("UPDATE gpkg_geometry_columns SET srs_id=4326 WHERE table_name='surfaces'")
        db.execute("UPDATE gpkg_contents SET srs_id=4326 WHERE table_name='surfaces'")
    before = hashlib.sha256(gpkg.read_bytes()).hexdigest()
    read, _ = read_surfaces(config(polygons=str(gpkg)),tmp_path)
    original, _ = read_surfaces(SurfaceConfig.read(surface_run[0]/"surfaces.json"),surface_run[0])
    assert [f.key for f in read] == [f.key for f in original]
    for a,b in zip(read,original):
        assert a.geometry.hausdorff_distance(b.geometry)<.00001
        assert a.geometry.area == pytest.approx(b.geometry.area,rel=1e-7)
    assert hashlib.sha256(gpkg.read_bytes()).hexdigest()==before
