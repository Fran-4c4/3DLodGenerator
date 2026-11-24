"""Independent end-to-end evidence for public configuration, sources and models."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pytest
from jsonschema import Draft7Validator

from lodext.core.config import BuildConfig
from lodext.demo import create_demo
from lodext.export.cityjson import validate_cityjson
from lodext.io.footprints import read_footprints
from lodext.pipeline import run_build


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("public-flow")
    inputs = root/"inputs with spaces"
    create_demo(inputs)
    output = root/"result"
    summary = run_build(inputs/"build.json",output)
    return root,inputs,output,summary


def config_copy(inputs,path,**changes):
    config = json.loads((inputs/"build.json").read_text(encoding="utf-8"))
    config.update(changes)
    path.write_text(json.dumps(config),encoding="utf-8")
    return path


def solid_volumes(model):
    """Independent oriented surface integral, shifted to avoid huge-coordinate cancellation."""
    scale = np.array(model["transform"]["scale"])
    vertices = np.array(model["vertices"])*scale
    result = {}
    for identifier,obj in model["CityObjects"].items():
        total = 0.0
        for geometry in obj["geometry"]:
            solids = [geometry["boundaries"]] if geometry["type"]=="Solid" else geometry["boundaries"]
            for solid in solids:
                for shell in solid:
                    for surface in shell:
                        for ring in surface:
                            a = vertices[ring[0]]
                            for i in range(1,len(ring)-1):
                                b,c = vertices[ring[i]],vertices[ring[i+1]]
                                total += np.dot(a,np.cross(b,c))/6
        if obj["geometry"]:
            result[obj["attributes"]["sourceId"]] = total
    return result


def test_public_workflow_builds_all_synthetic_objects(demo):
    _,_,output,summary = demo
    assert summary["status"]=="complete"
    assert summary["source_objects"]==9
    assert summary["resolved_units"]==5
    assert summary["methods"]=={"direct":4,"external_height":1}
    assert summary["models"]["1"]["closed_shells"]==6
    assert set(p.name for p in output.iterdir())=={"model.lod0.city.json","model.lod1.city.json","quality.json","objects.csv","run.json"}


@pytest.mark.parametrize("lod",[0,1])
def test_cityjson_validates_against_official_bundled_schema(demo,lod):
    model = json.loads((demo[2]/f"model.lod{lod}.city.json").read_text(encoding="utf-8"))
    schema = json.loads((Path(__file__).parent/"schemas/cityjson-2.0.1.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft7Validator(schema).iter_errors(model))
    assert not errors, [(list(e.path),e.message) for e in errors[:5]]


def test_oriented_shell_volumes_preserve_patios_concavity_and_components(demo):
    _,inputs,output,_ = demo
    truth = json.loads((inputs/"truth.json").read_text())
    model = json.loads((output/"model.lod1.city.json").read_text())
    volumes = solid_volumes(model)
    records = {r["source_id"]:r for r in json.loads((output/"quality.json").read_text())["objects"]}
    for identifier,expected in truth["parts"].items():
        assert volumes[identifier]==pytest.approx(expected["area_m2"]*records[identifier]["height_m"],abs=.001)
    assert len(model["CityObjects"]["BuildingPart::court"]["geometry"][0]["boundaries"][0][1])==2
    assert len(model["CityObjects"]["BuildingPart::multipart"]["geometry"])==2
    assert all(g["type"]=="Solid" for g in model["CityObjects"]["BuildingPart::multipart"]["geometry"])
    assert all(not model["CityObjects"][key]["geometry"] for key in model["CityObjects"] if key.startswith("Building::"))


def test_nonzero_dtm_base_and_reversible_source_identity(demo):
    model = json.loads((demo[2]/"model.lod1.city.json").read_text())
    z = [p[2]*model["transform"]["scale"][2]+model["transform"]["translate"][2] for p in model["vertices"]]
    assert min(z)==25
    assert max(z)==33
    parent = model["CityObjects"]["Building::b-court"]
    assert set(parent["children"])=={"BuildingPart::court","BuildingPart::terrace"}
    assert model["lodext"]["clamping_applied"] is False


def test_reference_input_never_presented_as_independent_comparison(demo):
    report = json.loads((demo[2]/"quality.json").read_text())
    sparse = next(r for r in report["objects"] if r["source_id"]=="sparse")
    assert sparse["method"]=="external_height"
    assert sparse["reference_role"]=="input"
    assert sparse["delta_from_reference_m"] is None


def test_lod0_does_not_require_lidar_or_roof_height(demo):
    root,inputs,_,_ = demo
    summary = run_build(inputs/"build.lod0.json",root/"lod0")
    assert summary["status"]=="complete"
    assert summary["methods"]=={"dtm_surface":5}
    assert summary["models"]["0"]["geometry_objects"]==5


def test_known_height_mode_is_explicit_and_uses_dtm(demo):
    root,inputs,_,_ = demo
    summary = run_build(inputs/"build.known.json",root/"known")
    assert summary["methods"]=={"known_height":5}
    report = json.loads((root/"known/quality.json").read_text())
    terrace = next(r for r in report["objects"] if r["source_id"]=="terrace")
    assert terrace["height_m"]==1.8
    assert terrace["reconstructed_top_z"]==26.8


def test_missing_roof_stays_unresolved_when_external_fallback_disabled(demo):
    root,inputs,_,_ = demo
    file = config_copy(inputs,inputs/"no-fallback.json",external_height_fallback=False)
    summary = run_build(file,root/"no-fallback")
    assert summary["status"]=="partial" and summary["unresolved_units"]==1
    model = json.loads((root/"no-fallback/model.lod1.city.json").read_text())
    obj=model["CityObjects"]["BuildingPart::sparse"]
    assert obj["geometry"][0]["type"]=="MultiSurface"
    assert obj["geometry"][0]["lod"]=="0"
    assert obj["attributes"]["representation"]=="unresolved_footprint"
    assert obj["attributes"]["reconstructionStatus"]=="unresolved"
    legacy=config_copy(inputs,inputs/"legacy-no-markers.json",external_height_fallback=False,show_unresolved_footprints=False)
    run_build(legacy,root/"legacy-no-markers")
    legacy_model=json.loads((root/"legacy-no-markers/model.lod1.city.json").read_text())
    assert legacy_model["CityObjects"]["BuildingPart::sparse"]["geometry"]==[]


def test_invalid_configuration_is_rejected_without_normalization(demo):
    data = json.loads((demo[1]/"build.json").read_text())
    for changes in [{"lods":[2]},{"roof_classes":[]},{"working_epsg":True},{"height_source":"automatic"},{"external_height_fallback":"false"},{"precision_m":0},{"contract_version":"0.1"}]:
        with pytest.raises(ValueError):
            BuildConfig(**{**data,**changes})


def test_unknown_fields_and_competing_defaults_are_not_accepted(demo):
    root,inputs,_,_ = demo
    path = config_copy(inputs,inputs/"typo.json",height={"min_poins_absolute":8})
    with pytest.raises(ValueError,match="Unknown"):
        run_build(path,root/"typo")
    assert not (root/"typo").exists()


def test_output_and_source_files_are_not_overwritten(demo):
    _,inputs,output,_ = demo
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir() if p.suffix in (".las",".tif",".gpkg")}
    with pytest.raises(ValueError,match="already exists"):
        run_build(inputs/"build.json",output)
    assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir() if p.name in hashes}


def test_orphaned_part_rejected_and_explicit_exclusion_preserves_report(tmp_path):
    create_demo(tmp_path/"data")
    inputs = tmp_path/"data"
    with sqlite3.connect(inputs/"footprints.gpkg") as c:
        c.execute("UPDATE building_parts SET building_id='not-a-parent' WHERE part_id='sparse'")
    config = BuildConfig.read(inputs/"build.json")
    with pytest.raises(ValueError,match="missing_parent"):
        read_footprints(config,inputs)
    config_path = config_copy(inputs,inputs/"exclude.json",invalid_objects="exclude")
    summary = run_build(config_path,tmp_path/"result")
    report = json.loads((tmp_path/"result/quality.json").read_text())
    assert any(r["source_id"]=="sparse" and "missing_parent" in r["issues"] for r in report["objects"])
    assert summary["status"]=="partial"


@pytest.mark.parametrize("offset_m",[26,250])
def test_part_without_positive_parent_overlap_is_rejected_or_reported(tmp_path,offset_m):
    """Boundary touch and a displaced part must not acquire another body's height."""
    from shapely import to_wkb
    from shapely.affinity import translate
    from lodext.io.footprints import gpkg_geometry

    inputs=tmp_path/"data"
    create_demo(inputs)
    with sqlite3.connect(inputs/"footprints.gpkg") as connection:
        original=bytes(connection.execute("SELECT geom FROM building_parts WHERE part_id='court'").fetchone()[0])
        moved=translate(gpkg_geometry(original),xoff=offset_m)
        connection.execute("UPDATE building_parts SET geom=? WHERE part_id='court'",(original[:8]+to_wkb(moved),))
    with pytest.raises(ValueError,match="outside_declared_parent"):
        read_footprints(BuildConfig.read(inputs/"build.json"),inputs)
    output=tmp_path/"result"
    path=config_copy(inputs,inputs/"exclude.json",invalid_objects="exclude")
    result=run_build(path,output)
    report=json.loads((output/"quality.json").read_text())
    row=next(r for r in report["objects"] if r["source_id"]=="court" and r["kind"]=="BuildingPart")
    assert row["parent_id"]=="b-court"
    assert row["status"]=="excluded" and row["height_m"] is None
    assert "outside_declared_parent" in row["issues"]
    assert result["excluded_objects"]==1 and result["status"]=="partial"
    for level in (0,1):
        model=json.loads((output/f"model.lod{level}.city.json").read_text())
        assert not model["CityObjects"]["BuildingPart::court"]["geometry"]


def test_partial_parent_overflow_is_measured_without_clipping_or_reparenting(demo):
    from shapely.geometry import box
    from shapely import to_wkb
    from lodext.io.footprints import gpkg_geometry
    root,inputs,_,_=demo
    # Independent package copy, keeping the shared fixture read-only.
    import shutil
    local=root/"overflow-data"
    shutil.copytree(inputs,local)
    with sqlite3.connect(local/"footprints.gpkg") as connection:
        blob=bytes(connection.execute("SELECT geom FROM building_parts WHERE part_id='court'").fetchone()[0])
        x,y,*_=gpkg_geometry(blob).bounds
        # Put half the child beyond the parent's entire eastern boundary.
        parent_blob=bytes(connection.execute("SELECT geom FROM buildings WHERE building_id='b-court'").fetchone()[0])
        edge=gpkg_geometry(parent_blob).bounds[2]
        shape=box(edge-1,y+1,edge+1,y+3)
        connection.execute("UPDATE building_parts SET geom=? WHERE part_id='court'",(blob[:8]+to_wkb(shape),))
    features,_=read_footprints(BuildConfig.read(local/"build.json"),local)
    f=next(f for f in features if f.key=="BuildingPart::court")
    assert not f.issues and f.parent_id=="b-court" and f.geometry.equals(shape)
    assert f.parent_relation=={"outside_area_m2":2.0,"overlap_fraction":0.5}
    run_build(local/"build.json",root/"overflow-result")
    report=json.loads((root/"overflow-result/quality.json").read_text())
    row=next(r for r in report["objects"] if r["key"]==f.key)
    assert row["parent_relation"]==f.parent_relation
    assert next(r for r in report["objects"] if r["kind"]=="Building")["parent_relation"] is None


@pytest.mark.parametrize("touch",["exterior","courtyards"])
def test_valid_2d_touching_rings_are_partitioned_into_closed_solids(tmp_path,touch):
    """Point-touching rings retain exact XY through manifold solid partitions."""
    from shapely import to_wkb
    from shapely.geometry import Polygon
    from shapely.affinity import translate
    from lodext.io.footprints import gpkg_geometry

    inputs=tmp_path/"data"
    create_demo(inputs)
    holes = [[(0,0),(2,1),(1,2),(0,0)]] if touch=="exterior" else [
        [(1,1),(3,1),(3,3),(1,3),(1,1)],
        [(3,3),(5,3),(5,5),(3,5),(3,3)]]
    shape=Polygon([(0,0),(8,0),(8,8),(0,8)],holes)
    assert shape.is_valid
    with sqlite3.connect(inputs/"footprints.gpkg") as connection:
        original=bytes(connection.execute("SELECT geom FROM building_parts WHERE part_id='court'").fetchone()[0])
        x,y,*_=gpkg_geometry(original).bounds
        connection.execute("UPDATE building_parts SET geom=? WHERE part_id='court'",(original[:8]+to_wkb(translate(shape,xoff=x,yoff=y)),))
    features,_=read_footprints(BuildConfig.read(inputs/"build.json"),inputs)
    assert not next(f for f in features if f.id=="court").issues
    summary=run_build(inputs/"build.json",tmp_path/"result")
    assert summary["excluded_objects"]==0
    report=json.loads((tmp_path/"result/quality.json").read_text())
    row=next(r for r in report["objects"] if r["key"]=="BuildingPart::court")
    assert row["issues"]==[] and row["height_m"] is not None
    lod0=json.loads((tmp_path/"result/model.lod0.city.json").read_text())
    lod1=json.loads((tmp_path/"result/model.lod1.city.json").read_text())
    assert len(lod0["CityObjects"]["BuildingPart::court"]["geometry"])==1
    solids=lod1["CityObjects"]["BuildingPart::court"]["geometry"]
    assert len(solids)>1 and all(item["type"]=="Solid" for item in solids)
    validate_cityjson(lod1)


@pytest.mark.parametrize('epsg,message',[(4326,'projected metre'),(3857,'Web Mercator')])
def test_unsuitable_working_crs_cannot_be_used_for_metric_extrusion(demo,epsg,message):
    data = json.loads((demo[1]/"build.json").read_text())
    with pytest.raises(ValueError,match=message):
        read_footprints(BuildConfig(**{**data,"working_epsg":epsg}),demo[1])


def test_cityjson_validator_catches_broken_shell(demo):
    model = json.loads((demo[2]/"model.lod1.city.json").read_text())
    shell = model["CityObjects"]["BuildingPart::court"]["geometry"][0]["boundaries"][0]
    shell.pop()
    with pytest.raises(ValueError,match="closed oriented"):
        validate_cityjson(model)


def test_installed_cli_runs_from_an_unrelated_directory(demo,tmp_path):
    result = subprocess.run([sys.executable,"-m","lodext","validate-cityjson",str(demo[2]/"model.lod1.city.json")],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)["closed_shells"]==6


def test_cli_returns_partial_exit_code_and_keeps_models(demo):
    root,inputs,_,_ = demo
    config = config_copy(inputs,inputs/"cli-partial.json",external_height_fallback=False)
    result = subprocess.run([sys.executable,"-m","lodext","build",str(config),"--output",str(root/"cli-partial")],capture_output=True,text=True)
    assert result.returncode==3,result.stderr
    assert (root/"cli-partial/model.lod1.city.json").is_file()


@pytest.mark.parametrize("spread",[False,True])
def test_incompatible_vertical_sources_are_rejected_even_with_zero_median(tmp_path,spread):
    import laspy
    inputs = tmp_path/"sources"
    create_demo(inputs)
    cloud = laspy.read(inputs/"cloud.las")
    z = np.asarray(cloud.z).copy()
    ground = np.asarray(cloud.classification)==2
    z[ground] += np.where(np.floor(np.asarray(cloud.x)[ground]/5)%2==0,.7,-.7) if spread else 5
    cloud.z = z
    cloud.write(inputs/"cloud.las")
    with pytest.raises(ValueError,match="locally inconsistent"):
        run_build(inputs/"build.json",tmp_path/"bad-z")
    assert not (tmp_path/"bad-z").exists()


def test_nodata_never_becomes_zero_ground_or_external_extrusion(tmp_path):
    import rasterio
    inputs = tmp_path/"sources"
    create_demo(inputs)
    with rasterio.open(inputs/"dtm.tif","r+") as raster:
        raster.write(np.full((raster.height,raster.width),raster.nodata,dtype="float32"),1)
    config = config_copy(inputs,inputs/"no-ground.json",unresolved_objects="error")
    with pytest.raises(ValueError,match="unresolved"):
        run_build(config,tmp_path/"no-ground")
    assert not (tmp_path/"no-ground").exists()


def test_validate_command_checks_required_resource_files(demo):
    _,inputs,_,_ = demo
    config = config_copy(inputs,inputs/"missing-dtm.json",dtm="missing.tif")
    result = subprocess.run([sys.executable,"-m","lodext","validate",str(config)],capture_output=True,text=True)
    assert result.returncode==2


def test_density_inputs_cannot_make_reference_values_override_direct_measurement(tmp_path):
    inputs = tmp_path/"sources"
    create_demo(inputs)
    first = tmp_path/"baseline"
    run_build(inputs/"build.json",first)
    original = json.loads((first/"quality.json").read_text())
    with sqlite3.connect(inputs/"footprints.gpkg") as c:
        c.execute("UPDATE building_parts SET reference_height_m=reference_height_m+100")
    run_build(inputs/"build.json",tmp_path/"changed")
    changed = json.loads((tmp_path/"changed/quality.json").read_text())
    initial = {r["key"]:r for r in original["objects"]}
    for row in changed["objects"]:
        if row.get("method")=="direct":
            assert row["height_m"]==initial[row["key"]]["height_m"]
            assert row["reference_role"]=="comparison_only"


def test_regular_laz_matches_las_without_ogr_or_pdal(demo):
    import laspy
    root,inputs,output,_ = demo
    laspy.read(inputs/'cloud.las').write(inputs/'cloud.laz')
    config = config_copy(inputs,inputs/'laz.json',lidar=['cloud.laz'])
    run_build(config,root/'laz-result')
    first = json.loads((output/'quality.json').read_text())
    second = json.loads((root/'laz-result/quality.json').read_text())
    a={r['key']:(r.get('height_m'),r.get('sampled_roof_points')) for r in first['objects']}
    b={r['key']:(r.get('height_m'),r.get('sampled_roof_points')) for r in second['objects']}
    assert a==b


def test_quantization_cannot_silently_collapse_a_courtyard(demo):
    root,inputs,_,_=demo
    config=config_copy(inputs,inputs/'coarse.json',precision_m=100)
    with pytest.raises(ValueError,match='Quantization'):
        run_build(config,root/'coarse')
    assert not (root/'coarse').exists()


def test_cli_reports_unknown_crs_as_documented_input_error(demo):
    _,inputs,_,_=demo
    config=config_copy(inputs,inputs/'unknown-crs.json',working_epsg=999999)
    result=subprocess.run([sys.executable,'-m','lodext','validate',str(config)],capture_output=True,text=True)
    assert result.returncode==2
    assert 'lodext:' in result.stderr and 'Traceback' not in result.stderr


def test_quantization_preserves_separation_between_components():
    from shapely.geometry import MultiPolygon,box
    from lodext.export.cityjson import Vertices
    from lodext.reconstruction.models import extrusion
    geometry=MultiPolygon([box(0,0,2,2),box(2.0004,0,4.0004,2)])
    assert geometry.is_valid
    with pytest.raises(ValueError,match='components'):
        extrusion(geometry,25,5,1,Vertices(.001,(0,0,25)))
