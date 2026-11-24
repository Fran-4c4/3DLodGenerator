"""Control cases for attribution before selecting a spatial roof envelope."""
import pytest
from lodext.core.roof_surfaces import separate_neighbour_planes,RoofSurfaceConfig
from lodext.core.heights import HeightConfig


def planes(*elevations):return [{'fitted_upper_z':z} for z in elevations]


def test_low_part_beside_tower_never_uses_tower_envelope():
    own,neighbour=separate_neighbour_planes(planes(10.7,78.7,79.4,81.6),3.3,1,[82],HeightConfig())
    assert [p['fitted_upper_z'] for p in own]==[10.7]
    assert len(neighbour)==3


@pytest.mark.parametrize('levels,ground,storeys,neighbours',[
    ([20.4,23.1],6.2,4,[24]), # Ordinary terrace and rooftop room.
    ([10.,12.5],0.,1,[10]), # A rooftop room is not a jump of many storeys.
    ([18.,24.],3.,1,[24]), # Tall industrial surfaces, not residential floors.
    ([81.6],3.3,1,[82]), # No supported lower alternative: do not invent it.
    ([10.7,81.6],3.3,None,[82]), # Unknown floors are not one floor.
    ([10.7,81.6],3.3,1,[]), # No independent neighbour observation.
])
def test_preserve_valid_roofs_and_uncertainty(levels,ground,storeys,neighbours):
    source=planes(*levels);own,rejected=separate_neighbour_planes(source,ground,storeys,neighbours,HeightConfig())
    assert own==source and not rejected


def test_no_implicit_footprint_area_gate_and_invalid_contracts():
    assert RoofSurfaceConfig().min_area_m2==0
    for fields in [{'min_area_m2':-1},{'min_cell_size_m':0},{'min_plane_points':2},{'min_plane_points':13,'min_points':12}]:
        with pytest.raises(ValueError):RoofSurfaceConfig(**fields)
