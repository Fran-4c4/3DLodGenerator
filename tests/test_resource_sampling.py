"""Numerical tests for fixture selection and independent LiDAR/DTM sampling."""
from pathlib import Path

import laspy
import numpy as np
import pytest
from pyproj import CRS, Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely import contains_xy
from shapely.geometry import Polygon, box

from tools.inspect_fixture import (
    ReferenceSampling, bounds_intersect, ground_grid, inventory_tiles,
    read_selected_points, roof_summary, sample_dtm,
)


@pytest.mark.parametrize("override", [
    {"erode_m": -1}, {"erode_m": float("nan")},
    {"grid_step_m": 0}, {"ground_buffers_m": ()},
    {"ground_buffers_m": (8, 8)}, {"ground_buffers_m": (14, 8)},
    {"ground_buffers_m": (8, float("inf"))},
    {"min_ground_samples": True}, {"min_ground_samples": 2.5},
])
def test_invalid_sampling_configuration_is_rejected(override):
    with pytest.raises(ValueError):
        ReferenceSampling(**override)


def test_zero_erosion_and_explicit_sampling_override():
    config = ReferenceSampling(erode_m=0, grid_step_m=1, ground_buffers_m=(4, 8))
    assert config.erode_m == 0 and config.grid_step_m == 1
    assert config.ground_buffers_m == (4, 8)


def test_envelope_selection_is_conservative_and_excludes_distant_tiles():
    target = (10, 10, 20, 20)
    assert bounds_intersect((0, 0, 100, 100), target)
    assert bounds_intersect((20, 10, 30, 20), target)
    assert not bounds_intersect((21, 10, 30, 20), target)


def test_ground_grid_respects_holes_and_disconnected_components():
    courtyard = Polygon([(0, 0), (8, 0), (8, 8), (0, 8)],
                        holes=[[(2, 2), (6, 2), (6, 6), (2, 6)]])
    free = courtyard.union(box(12, 0, 16, 4))
    x, y = ground_grid(free, 1)
    assert len(x) > 0 and contains_xy(free, x, y).all()
    assert (x > 12).any() and (x < 8).any()
    assert not ((x >= 2) & (x <= 6) & (y >= 2) & (y <= 6)).any()


def test_raster_sampling_transforms_xy_excludes_nodata_and_applies_scale_offset():
    values = np.array([[10, -9999], [12, 14]], dtype="float32")
    lon = np.array([-3.0005, -2.9995, -3.0005, -2.9995, 10.0])
    lat = np.array([40.0005, 40.0005, 39.9995, 39.9995, 10.0])
    x, y = Transformer.from_crs(4326, 32630, always_xy=True).transform(lon, lat)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=2, height=2, count=1,
                         dtype="float32", crs="EPSG:4326", nodata=-9999,
                         transform=from_origin(-3.001, 40.001, 0.001, 0.001)) as dataset:
            dataset.write(values, 1)
            dataset.scales = (2.0,)
            dataset.offsets = (3.0,)
            actual = sample_dtm(dataset, x, y, CRS.from_epsg(32630))
    assert sorted(actual) == [23, 27, 31]


def test_roof_summary_retains_original_classes_and_separates_building_observations():
    summary = roof_summary(np.array([3.0, 4.0, 30.0]), np.array([6, 6, 5]))
    assert summary["classes"] == {"5": 1, "6": 2}
    assert summary["all_classes"]["n_points"] == 3
    assert summary["building_class_6"]["z_median"] == 3.5
    assert summary["building_class_6"]["z_max"] == 4


def test_tile_inventory_and_chunked_las_read_preserve_points(tmp_path):
    lidar = tmp_path / "lidar"
    lidar.mkdir()
    for name, offset in (("near.las", 0), ("far.las", 100_000)):
        header = laspy.LasHeader(version="1.4", point_format=8)
        header.add_crs(CRS.from_epsg(32630))
        data = laspy.LasData(header)
        data.x = np.array([500000.0, 500010.0]) + offset
        data.y = [4400000.0, 4400010.0]
        data.z = [3.0, 8.0]
        data.classification = [2, 6]
        data.write(lidar / name)
    crs = CRS.from_epsg(32630)
    inventory = inventory_tiles(tmp_path, (499999, 4399999, 500020, 4400020), crs)
    assert [Path(t["file"]).name for t in inventory if t["selected"]] == ["near.las"]
    x, y, z, classification = read_selected_points(tmp_path, inventory, crs)
    assert list(x) == [500000, 500010]
    assert list(y) == [4400000, 4400010]
    assert list(z) == [3, 8]
    assert list(classification) == [2, 6]
