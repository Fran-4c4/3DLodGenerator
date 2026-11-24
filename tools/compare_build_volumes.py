"""Compare reconstructed LoD1 volumes between two complete build reports.

The source footprint is authoritative for XY, so a flat LoD1 part volume is
its unchanged metric footprint area multiplied by the reported reconstructed
height. The comparison never reads provider LiDAR classes and does not modify
either build or the GeoPackage.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

from lodext.io.footprints import gpkg_geometry


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Build reports must contain finite numerical values")
    return result


def _parts(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = {
            row["source_id"]: row
            for row in csv.DictReader(stream)
            if row["kind"] == "BuildingPart"
        }
    if not rows:
        raise ValueError(f"No BuildingPart rows in {path}")
    return rows


def _areas(path: Path) -> dict[str, float]:
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        geometry_column = connection.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name='building_parts'"
        ).fetchone()
        if geometry_column is None:
            raise ValueError("GeoPackage has no building_parts geometry layer")
        column = geometry_column[0]
        rows = connection.execute(
            f'SELECT part_id, "{column}" FROM building_parts'
        )
        result = {part_id: float(gpkg_geometry(blob).area) for part_id, blob in rows}
    if not result:
        raise ValueError("GeoPackage building_parts layer is empty")
    return result


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def compare(old_csv: Path, new_csv: Path, gpkg: Path, output: Path, epsilon: float) -> dict:
    """Write complete part/parent volume diffs and return their compact summary."""
    old, new, areas = _parts(old_csv), _parts(new_csv), _areas(gpkg)
    if old.keys() != new.keys():
        raise ValueError("Build reports do not contain the same BuildingPart identities")
    missing_area = sorted(old.keys() - areas.keys())
    if missing_area:
        raise ValueError(f"Missing source footprint areas for {len(missing_area)} parts")

    part_rows: list[dict] = []
    parents: dict[str, dict] = defaultdict(
        lambda: {
            "old_volume_m3": 0.0,
            "new_volume_m3": 0.0,
            "parts": 0,
            "old_resolved_parts": 0,
            "new_resolved_parts": 0,
            "lost_parts": 0,
            "gained_parts": 0,
            "changed_parts": 0,
        }
    )
    position_only = 0
    parts_lost_total = 0
    parts_gained_total = 0
    for part_id in sorted(old):
        before, after = old[part_id], new[part_id]
        parent_id = before["parent_id"]
        if parent_id != after["parent_id"]:
            raise ValueError(f"Parent changed for {part_id}")
        area = areas[part_id]
        old_height, new_height = _float(before["height_m"]), _float(after["height_m"])
        old_volume = area * old_height if before["status"] == "resolved" and old_height is not None else 0.0
        new_volume = area * new_height if after["status"] == "resolved" and new_height is not None else 0.0
        delta = new_volume - old_volume
        old_top, new_top = _float(before["reconstructed_top_z"]), _float(after["reconstructed_top_z"])
        old_ground, new_ground = _float(before["ground_z"]), _float(after["ground_z"])
        changed = abs(delta) > epsilon
        moved = (
            old_top is not None
            and new_top is not None
            and old_ground is not None
            and new_ground is not None
            and (abs(old_top - new_top) > 0.001 or abs(old_ground - new_ground) > 0.001)
        )
        if moved and not changed:
            position_only += 1
        if changed:
            part_rows.append(
                {
                    "parent_id": parent_id,
                    "part_id": part_id,
                    "area_m2": area,
                    "old_status": before["status"],
                    "new_status": after["status"],
                    "old_method": before["method"],
                    "new_method": after["method"],
                    "old_ground_z": old_ground,
                    "new_ground_z": new_ground,
                    "old_top_z": old_top,
                    "new_top_z": new_top,
                    "old_height_m": old_height,
                    "new_height_m": new_height,
                    "old_volume_m3": old_volume,
                    "new_volume_m3": new_volume,
                    "delta_volume_m3": delta,
                }
            )
        aggregate = parents[parent_id]
        aggregate["parts"] += 1
        aggregate["old_volume_m3"] += old_volume
        aggregate["new_volume_m3"] += new_volume
        aggregate["old_resolved_parts"] += int(before["status"] == "resolved")
        aggregate["new_resolved_parts"] += int(after["status"] == "resolved")
        if before["status"] == "resolved" and after["status"] != "resolved":
            aggregate["lost_parts"] += 1
            parts_lost_total += 1
        if before["status"] != "resolved" and after["status"] == "resolved":
            aggregate["gained_parts"] += 1
            parts_gained_total += 1
        if changed:
            aggregate["changed_parts"] += 1

    parent_rows = []
    for parent_id, values in parents.items():
        delta = values["new_volume_m3"] - values["old_volume_m3"]
        if abs(delta) <= epsilon:
            continue
        old_volume = values["old_volume_m3"]
        parent_rows.append(
            {
                "parent_id": parent_id,
                **values,
                "delta_volume_m3": delta,
                "delta_percent": (100.0 * delta / old_volume) if old_volume else None,
            }
        )
    parent_rows.sort(key=lambda row: (-abs(row["delta_volume_m3"]), row["parent_id"]))
    part_rows.sort(key=lambda row: (-abs(row["delta_volume_m3"]), row["part_id"]))

    output.mkdir(parents=True, exist_ok=False)
    _write_csv(output / "parts.csv", part_rows, list(part_rows[0]) if part_rows else ["part_id"])
    _write_csv(output / "buildings.csv", parent_rows, list(parent_rows[0]) if parent_rows else ["parent_id"])
    lost_parts = [row for row in part_rows if row["old_status"] == "resolved" and row["new_status"] != "resolved"]
    gained_parts = [row for row in part_rows if row["old_status"] != "resolved" and row["new_status"] == "resolved"]
    fully_lost = [row for row in parent_rows if row["old_resolved_parts"] and not row["new_resolved_parts"]]
    _write_csv(output / "parts-lost.csv", lost_parts, list(part_rows[0]) if part_rows else ["part_id"])
    _write_csv(output / "parts-gained.csv", gained_parts, list(part_rows[0]) if part_rows else ["part_id"])
    _write_csv(output / "buildings-fully-lost.csv", fully_lost, list(parent_rows[0]) if parent_rows else ["parent_id"])
    summary = {
        "old_parts": len(old),
        "new_parts": len(new),
        "parts_with_volume_change": len(part_rows),
        "buildings_with_volume_change": len(parent_rows),
        "parts_lost": parts_lost_total,
        "parts_gained": parts_gained_total,
        "buildings_fully_lost": len(fully_lost),
        "position_only_changes": position_only,
        "old_total_volume_m3": sum(row["old_volume_m3"] for row in parents.values()),
        "new_total_volume_m3": sum(row["new_volume_m3"] for row in parents.values()),
        "epsilon_m3": epsilon,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_csv", type=Path)
    parser.add_argument("new_csv", type=Path)
    parser.add_argument("footprints_gpkg", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epsilon-m3", type=float, default=0.01)
    args = parser.parse_args()
    if not math.isfinite(args.epsilon_m3) or args.epsilon_m3 < 0:
        parser.error("--epsilon-m3 must be finite and nonnegative")
    print(json.dumps(compare(args.old_csv, args.new_csv, args.footprints_gpkg, args.output, args.epsilon_m3)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
