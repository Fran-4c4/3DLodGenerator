"""A local consistency diagnostic must detect offsets without inventing datums."""
import numpy as np
import pytest

from tools.check_vertical_consistency import ConsistencyConfig, assess_pairs, paired_raster_values


def test_consistent_ground_elevations_support_only_local_comparison():
    lidar = np.linspace(1, 20, 200)
    result, valid = assess_pairs(lidar, lidar + 0.025)
    assert result["status"] == "locally_consistent"
    assert result["median_residual_z"] == pytest.approx(0.025)
    assert valid.all()
    assert not result["common_origin_confirmed"]
    assert not result["absolute_vertical_datum_identified"]


def test_systematic_offset_is_detected_without_fitting_it_away():
    lidar = np.linspace(1, 20, 200)
    result, _ = assess_pairs(lidar, lidar + 3)
    assert result["status"] == "offset_or_mismatch_detected"
    assert result["median_residual_z"] == pytest.approx(3)


def test_zero_median_with_large_scatter_is_still_a_mismatch():
    lidar = np.ones(200)
    result, _ = assess_pairs(lidar, lidar + np.tile([-1, 1], 100))
    assert result["median_residual_z"] == 0
    assert result["status"] == "offset_or_mismatch_detected"


def test_small_or_low_coverage_comparison_is_insufficient():
    assert assess_pairs([1, 2], [1, 2])[0]["status"] == "insufficient_samples"
    raster = np.ones(200)
    raster[:100] = np.nan
    result, valid = assess_pairs(np.ones(200), raster)
    assert result["valid_pairs"] == 100 and valid.sum() == 100
    assert result["valid_fraction"] == 0.5
    assert result["status"] == "insufficient_samples"


def test_missing_values_preserve_original_pairing_and_empty_statistics():
    config = ConsistencyConfig(min_valid_pairs=1, min_valid_fraction=0.3)
    result, valid = assess_pairs([1, np.nan, 20], [1.05, 10, np.nan], config)
    assert valid.tolist() == [True, False, False]
    assert result["median_residual_z"] == pytest.approx(0.05)
    result, _ = assess_pairs([], [])
    assert result["median_residual_z"] is None and result["quantiles_residual_z"] == {}


@pytest.mark.parametrize("override", [
    {"sampling_grid_m": 0}, {"building_clearance_m": -1},
    {"min_valid_pairs": True}, {"min_valid_pairs": 1.5},
    {"min_valid_fraction": 0}, {"min_valid_fraction": 1.1},
    {"max_abs_median_z": float("nan")}, {"max_abs_median_z": 0.5, "max_p95_abs_z": 0.1},
])
def test_invalid_diagnostic_policy_is_rejected(override):
    with pytest.raises(ValueError):
        ConsistencyConfig(**override)


def test_shape_mismatch_cannot_silently_unpair_measurements():
    with pytest.raises(ValueError):
        assess_pairs([1, 2], [1])


def test_integer_raster_nodata_and_outside_points_keep_their_original_indices():
    from pyproj import CRS
    from rasterio.io import MemoryFile
    from affine import Affine

    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=3, height=1, count=1, dtype="int16",
                         nodata=-9999, crs="EPSG:32630",
                         transform=Affine(1, 0, 500000, 0, -1, 4400000)) as dataset:
            dataset.write(np.array([[10, -9999, 30]], dtype="int16"), 1)
            values = paired_raster_values(
                dataset, np.array([500000.5, 500001.5, 500002.5, 500020]),
                np.array([4399999.5] * 4), CRS.from_epsg(32630),
            )
    assert values[0] == 10 and values[2] == 30
    assert np.isnan(values[1]) and np.isnan(values[3])
