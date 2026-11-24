"""Plot authoritative cadastral parts and reconstructed elevations for one building."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from lodext.io.footprints import gpkg_geometry


def _parts(path: Path, building_id: str):
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT part_id, storeys_above, storeys_below, geom "
            "FROM building_parts WHERE building_id=? ORDER BY part_id",
            (building_id,),
        ).fetchall()
    if not rows:
        raise ValueError(f"Building not found: {building_id}")
    return [
        {
            "id": row["part_id"],
            "storeys_above": row["storeys_above"],
            "storeys_below": row["storeys_below"],
            "geometry": gpkg_geometry(row["geom"]),
        }
        for row in rows
    ]


def _report(path: Path, wanted: set[str]):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return {
            row["source_id"]: row
            for row in csv.DictReader(stream)
            if row["source_id"] in wanted
        }


def _polygons(geometry):
    return list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]


def _suffix(part_id: str) -> str:
    return "P" + part_id.rsplit("_part", 1)[-1]


def plot(gpkg: Path, building_id: str, reports: list[tuple[str, Path]], output: Path) -> None:
    parts = _parts(gpkg, building_id)
    ids = {part["id"] for part in parts}
    observations = [(label, _report(path, ids)) for label, path in reports]
    colors = plt.get_cmap("tab10")

    figure, (plan, heights) = plt.subplots(1, 2, figsize=(15, 8), gridspec_kw={"width_ratios": [1.15, 1]})
    color_by_id = {part["id"]: colors(index) for index, part in enumerate(parts)}
    for part in sorted(parts, key=lambda item: item["geometry"].area, reverse=True):
        color = color_by_id[part["id"]]
        geometry = part["geometry"]
        for polygon in _polygons(geometry):
            x, y = polygon.exterior.xy
            plan.fill(x, y, color=color, alpha=0.58, edgecolor="black", linewidth=1.4)
            for ring in polygon.interiors:
                x, y = ring.xy
                plan.fill(x, y, color="white", edgecolor="black", linewidth=1.2)
    legend = []
    for part in parts:
        color = color_by_id[part["id"]]
        geometry = part["geometry"]
        point = geometry.representative_point()
        plan.text(point.x, point.y, _suffix(part["id"]), ha="center", va="center", weight="bold")
        legend.append(
            Patch(
                facecolor=color,
                edgecolor="black",
                alpha=0.58,
                label=f"{_suffix(part['id'])}: {part['storeys_above']} above / {part['storeys_below']} below, {geometry.area:.1f} m²",
            )
        )
    plan.set_aspect("equal")
    plan.set_title("Cadastral footprint parts — authoritative XY")
    plan.set_xlabel("EPSG:4083 easting (m)")
    plan.set_ylabel("EPSG:4083 northing (m)")
    plan.grid(alpha=0.18)
    plan.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.33), frameon=False)

    labels = [_suffix(part["id"]) for part in parts]
    width = 0.23
    x_positions = list(range(len(parts)))
    for report_index, (label, report) in enumerate(observations):
        offset = (report_index - (len(observations) - 1) / 2) * width
        for index, part in enumerate(parts):
            row = report.get(part["id"])
            if row is None or row["status"] != "resolved" or not row["height_m"]:
                heights.scatter(index + offset, 0, marker="x", s=70, color="black", zorder=4)
                continue
            ground = float(row["ground_z"])
            height = float(row["height_m"])
            heights.bar(index + offset, height, width=width, bottom=ground, label=label if index == 0 else None, alpha=0.75)
            heights.text(index + offset, ground + height + 1.0, f"{ground + height:.1f}", ha="center", va="bottom", rotation=90, fontsize=8)
    heights.set_xticks(x_positions, labels)
    heights.set_ylabel("Absolute elevation (m)")
    heights.set_title("Extrusion: same XY footprint, one base and top per part")
    heights.grid(axis="y", alpha=0.18)
    heights.legend(frameon=False)
    heights.text(0.01, 0.01, "× = footprint retained but no LoD1 volume", transform=heights.transAxes, fontsize=9)

    figure.suptitle(building_id, fontsize=14, weight="bold")
    figure.subplots_adjust(bottom=0.27, top=0.90, wspace=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpkg", type=Path)
    parser.add_argument("building_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", action="append", required=True, metavar="LABEL=OBJECTS.CSV")
    args = parser.parse_args()
    reports = []
    for item in args.report:
        if "=" not in item:
            parser.error("--report must use LABEL=OBJECTS.CSV")
        label, path = item.split("=", 1)
        reports.append((label, Path(path)))
    plot(args.gpkg, args.building_id, reports, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
