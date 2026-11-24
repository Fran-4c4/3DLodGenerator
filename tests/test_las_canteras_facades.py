"""Opt-in repeatable review of the Las Canteras facade/ground campaign."""
import csv
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def run():
    explicit = os.environ.get("LODEXT_FACADE_RUN")
    folder = Path(explicit) if explicit else (
        Path(__file__).resolve().parents[1] / "data/las_canteras/trial-01/case-facades-45/output-02")
    if not explicit and not folder.is_dir():
        pytest.skip("Las Canteras facade subset is optional")
    return folder


@pytest.fixture(scope="module")
def parts(run):
    with (run / "objects.csv").open(encoding="utf-8") as stream:
        return {row["source_id"]: row for row in csv.DictReader(stream)}


# Absolute roof Z ranges in the survey datum. These are regression envelopes
# based on adjacent bodies and fitted returns, not surveyed reference heights.
@pytest.mark.parametrize("source,lower,upper", [
    ("7926102DS5172N_part3", 30, 34), ("7424903DS5172S_part7", 25, 29),
    ("7425207DS5172N_part5", 22, 25), ("6718701DS5161N_part5", 23, 25),
    ("6614413DS5161S_part2", 27, 29), ("6614413DS5161S_part4", 27, 29),
    ("6614711DS5161S_part10", 31, 33), ("6815602DS5161N_part12", 41, 43),
    ("6313128DS5161S_part37", 43, 47), ("7918108DS5171N_part3", 17, 20),
    ("6819701DS5161N_part1", 24, 26), ("6819701DS5161N_part9", 24, 26),
    ("6918601DS5161N_part2", 27, 30), ("6918601DS5161N_part4", 26, 30),
    ("8438113DS5183N_part1", 21, 24),
])
def test_local_roof_envelope(parts, source, lower, upper):
    row = parts["ES.SDGC.BU." + source]
    assert row["status"] == "resolved"
    top = float(row["reconstructed_top_z"])
    assert lower <= top <= upper
    assert top == pytest.approx(float(row["height_m"]) + float(row["ground_z"]))


@pytest.mark.parametrize("target,body", [
    ("6718701DS5161N_part5", "6718701DS5161N_part2"),
    ("6614711DS5161S_part10", "6614711DS5161S_part7"),
    ("6815602DS5161N_part12", "6815602DS5161N_part1"),
    ("6819701DS5161N_part9", "6819701DS5161N_part1"),
])
def test_facade_base(parts, target, body):
    assert abs(float(parts["ES.SDGC.BU." + target]["ground_z"]) -
               float(parts["ES.SDGC.BU." + body]["ground_z"])) < 0.5


def test_lod0_footprint_on_measured_ground(run):
    model = json.loads((run / "model.lod0.city.json").read_bytes())
    obj = model["CityObjects"]["BuildingPart::ES.SDGC.BU.7426327DS5172N_part8"]
    transform = model["transform"]
    assert "height_m" not in obj["attributes"]
    for geom in obj["geometry"]:
        assert geom["lod"] == "0" and geom["type"] == "MultiSurface"
        for face in geom["boundaries"]:
            for ring in face:
                for index in ring:
                    z = model["vertices"][index][2] * transform["scale"][2] + transform["translate"][2]
                    assert 4 <= z <= 5


def test_previous_reviewed_roofs_and_coastal_steps():
    """Check all historical seed parts and every terrace in the four coastal controls."""
    trial = Path(__file__).resolve().parents[1] / "data/las_canteras/trial-01"
    history = trial / "case-history-45"
    candidate = Path(os.getenv("LODEXT_HISTORY_RUN", str(history / "output-01")))
    if not candidate.is_dir() and not os.getenv("LODEXT_HISTORY_RUN"):
        pytest.skip("Optional historical subset is unavailable")
    def load(folder):
        with (folder / "objects.csv").open(encoding="utf-8") as stream:
            return {r["source_id"]: r for r in csv.DictReader(stream)}
    baseline = load(trial / "build-44-candidate-04")
    current = load(candidate)
    seeds = set(json.loads((history / "subset.json").read_bytes())["requested_parts"])
    coastal = {"ES.SDGC.BU." + prefix + "DS5172S" for prefix in
               ["7224611", "7223402", "7223401", "7223410"]}
    seeds.update(key for key, row in baseline.items() if row["parent_id"] in coastal)
    for key in sorted(seeds):
        assert current[key]["status"] == baseline[key]["status"], key
        if baseline[key]["reconstructed_top_z"]:
            assert float(current[key]["reconstructed_top_z"]) == pytest.approx(
                float(baseline[key]["reconstructed_top_z"]), abs=.01), key
