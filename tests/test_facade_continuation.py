from types import SimpleNamespace

import pytest
from shapely.geometry import box

from lodext.core.config import BuildConfig
from lodext.pipeline import reconcile_facade_roofs


@pytest.mark.parametrize("interior,parent,expected", [
    (False, "building", 29.0),
    (True, "building", 46.0),
    (False, "another-building", 46.0),
])
def test_extrapolated_top_and_observed_absolute_roof(interior, parent, expected):
    strip = SimpleNamespace(key="strip", parent_id="building", issues=[], geometry=box(0,0,1,10))
    body = SimpleNamespace(key="body", parent_id=parent, issues=[], geometry=box(1,0,15,10))
    row = dict(method="floor_share", ground_z=9., height_m=37., reconstructed_top_z=46.,
               flags=[], building_surfaces=dict(independent_interior_support=interior,
               planes=[dict(observed_z_range=[28.5,29.1])]))
    records = {"strip": row, "body": dict(method="direct", reconstructed_top_z=29.,
                                          ground_z=9., height_m=20.)}
    config = SimpleNamespace(height=SimpleNamespace(inferred_roof_tolerance_m=1.5, near_zero_m=.1),
                             building_surfaces=SimpleNamespace(registration_m=.5,residual_m=.2))
    reconcile_facade_roofs([strip,body], records, config)
    assert row["reconstructed_top_z"] == expected
    assert row["height_m"] == expected - 9.
