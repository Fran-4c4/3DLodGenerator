"""Observable numerical rules, including branches the source tests missed."""
from dataclasses import replace

import pytest

from lodext.core.heights import HeightConfig, PartObservation, estimate_building, modal_roof, roof_band_candidates


def observation(name, z, *, area=100.0, sample_area=None, ground=0.0,
                 storeys=None, small=False, below=None, building="b", attributed=None, context=(), local=(), local_context=None,
                 calibration=None):
    return PartObservation(name, building, area, area if sample_area is None else sample_area,
                           tuple(z), ground, small, storeys, below, attributed_roof_z=attributed,
                           context_roof_z=tuple(context),local_storey_neighbour_ids=tuple(local),
                           local_context_roof_z=local_context,calibration_roof_z=calibration)


def by_id(parts, config=None):
    return {p.part_id: p for p in estimate_building(parts, config)}


def test_reliable_lidar_wins_over_cadastral_storeys():
    result = by_id([observation("p", [4.3] * 120 + [9] * 15, storeys=2)])["p"]
    assert result.method == "direct" and result.height_m == 4.5
    assert result.height_m < 6


def test_two_references_cannot_extrapolate_a_roof_above_all_ambiguous_returns():
    parts=[observation('large',[25.5]*40,area=52,ground=5.5,storeys=3),
           observation('upper',[28.5]*40,area=25,ground=5.3,storeys=7),
           observation('mixed',[25.5]*90+[25.749]+[28]*75+[27]*27+[90],area=28,ground=5.3,storeys=6)]
    r=by_id(parts)['mixed']
    assert r.reference_part_id=='upper' and r.height_m==pytest.approx(25.749-5.3)
    assert r.ground_z+r.height_m==25.749
    assert r.method=='roof_band' and r.roof_reference_z==25.749
    assert r.inferred_roof_support_fraction>=.1
    assert 'roof_supported_floor_reference' in r.flags
    disabled=by_id(parts,HeightConfig(min_inferred_roof_support=0))['mixed']
    assert disabled.height_m==40 and disabled.inferred_roof_support_fraction is None


def test_unsupported_building_inference_is_unresolved_instead_of_clipped():
    r=by_id([observation('anchor',[24]*30,area=100,ground=4,storeys=3),
             observation('mixed',[10]*30+[13]*30,area=20,ground=4,storeys=6)])['mixed']
    assert r.height_m is None and r.method=='unresolved'
    assert r.inferred_roof_support_fraction==0 and 'unsupported_inferred_roof' in r.flags


def test_sparse_conflicting_references_need_local_evidence_to_choose():
    parts=[observation('low',[10]*30,area=100,ground=4,storeys=2),
           observation('high',[25]*30,area=200,ground=4,storeys=3),
           observation('missing',[],ground=4,storeys=6)]
    r=by_id(parts)['missing']
    assert r.height_m is None and 'ambiguous_floor_reference' in r.flags


def test_smaller_recovered_surface_cannot_poison_larger_sibling_fallback():
    parts=[observation('large',[10.5]*30,area=82,ground=4,storeys=2),
           observation('small',[12]*30,area=79,ground=4,storeys=1,small=True,attributed=12)]
    result=by_id(parts)
    assert result['large'].method=='direct'
    assert result['small'].method=='floor_share'
    assert result['small'].height_m==pytest.approx(3.25)
    assert result['small'].reference_part_id=='large'
    assert 'small_part_incoherent' in result['small'].flags


def test_accepted_spatial_surfaces_anchor_a_missing_sibling_despite_mixed_modal_points():
    parts=[observation('surface-a',[],area=200,ground=4,storeys=25,attributed=84),
           observation('surface-b',[],area=180,ground=4,storeys=25,attributed=85),
           observation('one-storey-outlier',[79]*30,area=250,ground=4,storeys=1),
           observation('missing',[],area=30,ground=4,storeys=25,context=(84.5,))]
    result=by_id(parts)['missing']
    assert result.method=='floor_share' and result.height_m==pytest.approx(80)
    assert result.reference_part_id=='surface-a' and result.floor_height_m==pytest.approx(3.2)


def test_attributed_surface_requires_positive_clearance_and_ground():
    with pytest.raises(ValueError,match='positive clearance'):
        observation('bad',[],ground=5,storeys=2,attributed=5)
    with pytest.raises(ValueError,match='positive clearance'):
        observation('missing-ground',[],ground=None,storeys=2,attributed=8)
    with pytest.raises(ValueError,match='immutable tuple'):
        PartObservation('bad-context','b',10,10,(),0,False,context_roof_z=[4])


def test_pre_alignment_roof_calibrates_only_other_siblings():
    result=by_id([
        observation('aligned',[],area=100,ground=4,storeys=3,calibration=16),
        observation('missing',[],area=20,ground=4,storeys=4),
    ])
    assert result['aligned'].method=='unresolved'
    assert result['missing'].method=='floor_share'
    assert result['missing'].height_m==pytest.approx(16)
    assert result['missing'].reference_part_id=='aligned'


def test_pre_alignment_roof_requires_positive_clearance_and_ground():
    with pytest.raises(ValueError,match='positive clearance'):
        observation('bad',[],ground=5,storeys=2,calibration=5)
    with pytest.raises(ValueError,match='positive clearance'):
        observation('missing-ground',[],ground=None,storeys=2,calibration=8)


def test_spatial_anchor_requires_matching_target_context():
    parts=[observation('spatial-a',[],area=200,ground=4,storeys=25,attributed=84),
           observation('spatial-b',[],area=180,ground=4,storeys=25,attributed=85),
           observation('missing',[],area=30,ground=4,storeys=25,context=(33,))]
    result=by_id(parts)['missing']
    assert result.method=='unresolved' and 'unsupported_inferred_roof' in result.flags


def test_coherent_direct_anchor_precedes_conflicting_spatial_surfaces():
    parts=[observation('direct',[10]*30,area=200,ground=4,storeys=2),
           observation('spatial-a',[],area=180,ground=4,storeys=2,attributed=20),
           observation('spatial-b',[],area=160,ground=4,storeys=2,attributed=22),
           observation('missing',[],area=20,ground=4,storeys=1)]
    result=by_id(parts)['missing']
    assert result.method=='floor_share' and result.height_m==3
    assert result.reference_part_id=='direct'


def test_spatial_fallback_does_not_recalibrate_resolved_direct_parts():
    parts=[observation('direct-low',[10]*30,area=220,ground=4,storeys=2),
           observation('direct-high',[25]*30,area=200,ground=4,storeys=3),
           observation('surface-a',[],area=180,ground=4,storeys=5,attributed=19),
           observation('surface-b',[],area=160,ground=4,storeys=5,attributed=19.5),
           observation('missing',[],area=30,ground=4,storeys=5,context=(19.2,))]
    results=by_id(parts)
    assert results['direct-low'].method=='direct' and results['direct-low'].height_m==6
    assert results['direct-high'].method=='direct' and results['direct-high'].height_m==21
    assert results['missing'].method=='floor_share'
    assert results['missing'].reference_part_id=='surface-a'


def test_matching_larger_roof_is_not_mistaken_for_independent_small_body_evidence():
    r=by_id([observation('terrace',[14]*60,area=110,ground=4.4,storeys=2),
             observation('main',[17]*60,area=16,ground=4.4,storeys=3),
             observation('small',[14]*60,area=7,ground=4.4,storeys=1,small=True)])['small']
    assert r.method=='floor_share' and r.height_m==pytest.approx(4.8)
    assert 'shared_roof_storey_conflict' in r.flags
    assert 'inferred_roof_unverified' in r.flags


@pytest.mark.parametrize('changes',[{'inferred_roof_tolerance_m':0},{'inferred_roof_tolerance_m':float('nan')},
                                    {'min_inferred_roof_support':-.1},{'min_inferred_roof_support':1.1}])
def test_invalid_inference_support_fields(changes):
    with pytest.raises(ValueError):HeightConfig(**changes)


def test_roof_reference_candidates_reject_isolated_high_returns():
    assert roof_band_candidates(tuple([25.5]*90+[28]*75+[90]),HeightConfig())==[25.5,28.0]


def test_isolated_tall_storey_anchor_cannot_inflate_ten_storey_fallback():
    parts=[observation('large-hall',[10.5]*100,ground=2.835,area=300,storeys=1),
           observation('tower-a',[40]*100,ground=10,area=120,storeys=9),
           observation('tower-b',[43]*100,ground=10,area=100,storeys=10),
           observation('tower-c',[37.5]*100,ground=10,area=80,storeys=8),
           observation('ambiguous',[40]*30+[43]*30,ground=10,area=15,storeys=10)]
    r=by_id(parts)
    assert r['large-hall'].height_m==pytest.approx(7.665)
    assert r['large-hall'].method=='direct' and 'floor_reference_outlier' in r['large-hall'].flags
    assert r['ambiguous'].height_m==33 and r['ambiguous'].roof_reference_z==43
    assert r['ambiguous'].reference_part_id=='tower-a'
    assert 'floor_reference_consensus' in r['ambiguous'].flags
    assert by_id(list(reversed(parts)))['ambiguous']==r['ambiguous']
    # Explicitly delaying consensus reproduces the old area-only choice.
    old=by_id(parts,HeightConfig(anchor_consensus_min_parts=5,min_inferred_roof_support=0))
    assert old['ambiguous'].height_m==pytest.approx(76.65)


def test_two_equal_floor_clusters_do_not_invent_a_reference():
    parts=[observation('a',[3]*20,storeys=1),observation('b',[3.5]*20,storeys=1),
           observation('c',[7]*20,storeys=1),observation('d',[7.5]*20,storeys=1),
           observation('missing',[],storeys=5)]
    r=by_id(parts)
    assert r['missing'].height_m is None and 'ambiguous_floor_reference' in r['missing'].flags
    assert all(r[k].method=='direct' for k in ('a','b','c','d'))


def test_overlapping_consensus_tie_uses_diminishing_spatial_support():
    parts=[observation('broad-low',[10]*30,ground=6.9,area=81,storeys=1),
           observation('low-a',[10]*30,ground=6.8,area=10,storeys=1),
           observation('low-b',[10]*30,ground=6.8,area=36,storeys=1),
           observation('middle',[10]*30,ground=5.85,area=28,storeys=1),
           observation('small-high',[10]*30,ground=5.01,area=5,storeys=1),
           observation('missing',[],area=26,storeys=6)]
    result=by_id(parts)['missing']
    assert result.method=='floor_share'
    assert result.reference_part_id=='low-b'
    assert result.floor_height_m==pytest.approx(3.2)
    assert result.height_m==pytest.approx(19.2)
    assert by_id(list(reversed(parts)))['missing']==result
    assert by_id(parts)['small-high'].method=='direct'


def test_consensus_uses_a_measured_central_reference_not_the_largest_high_anchor():
    parts=[observation('large',[7]*30,area=300,storeys=2),
           observation('central',[6.5]*30,area=100,storeys=2),
           observation('low',[6]*30,area=90,storeys=2),
           observation('missing',[],storeys=10)]
    result=by_id(parts)['missing']
    assert result.reference_part_id=='central' and result.height_m==32.5


@pytest.mark.parametrize('changes',[{'anchor_consensus_min_parts':2},{'anchor_consensus_min_parts':True},
                                    {'anchor_consensus_max_ratio':.9},{'anchor_consensus_max_ratio':float('nan')}])
def test_invalid_anchor_consensus_contract(changes):
    with pytest.raises(ValueError):HeightConfig(**changes)


def test_histogram_override_is_explicit_and_does_not_change_the_default_owner():
    p = observation("p", [4.3] * 30)
    assert by_id([p])["p"].height_m == 4.5
    assert by_id([p], HeightConfig(roof_bin_m=0.1))["p"].height_m == pytest.approx(4.3)
    assert HeightConfig().roof_bin_m == 0.5


def test_dense_support_with_fewer_than_twelve_points_really_uses_density():
    p = observation("frame", [7] * 4, area=100, sample_area=1, ground=3)
    result = by_id([p])["frame"]
    assert result.n_points == 4 and result.density_points_m2 == 4
    assert result.method == "direct" and result.height_m == 4
    assert "quantity_supported_by_density" in result.flags
    assert by_id([p], HeightConfig(min_density_points_m2=None))["frame"].method == "unresolved"


def test_density_cannot_bypass_the_minimum_statistical_sample():
    p = observation("p", [7] * 2, area=1, sample_area=0.1)
    result = by_id([p])["p"]
    assert result.method == "unresolved" and result.height_m is None
    assert "below_statistical_point_floor" in result.flags


def test_mixed_roofs_fall_back_to_the_largest_reliable_building_part():
    parts = [observation("main", [7] * 60, area=150, storeys=2),
             observation("frame", [3] * 30 + [9] * 30, area=90, storeys=1)]
    frame = by_id(parts)["frame"]
    assert frame.method == "roof_band" and frame.height_m == 3.0
    assert frame.roof_reference_z == 3.0
    assert frame.reference_part_id == "main" and frame.bimodal


def test_modal_ties_and_anchor_ties_are_independent_of_input_order():
    config = HeightConfig()
    assert modal_roof((3, 3, 9, 9), config) == modal_roof((9, 9, 3, 3), config)
    parts = [observation("z", [8] * 20, storeys=2),
             observation("a", [7] * 20, storeys=2),
             observation("missing", [], area=10, storeys=1)]
    assert by_id(parts)["missing"].reference_part_id == "a"
    assert by_id(list(reversed(parts)))["missing"].height_m == 3.5


def test_small_neighbour_contamination_is_inferred_but_large_hall_stays_measured():
    parts = [observation("main", [7] * 60, area=200, storeys=2),
             observation("small", [9] * 40, area=10, storeys=1, small=True),
             observation("hall", [13] * 40, area=150, storeys=1)]
    result = by_id(parts)
    assert result["small"].height_m == 3.5 and result["small"].method == "floor_share"
    assert "small_part_incoherent" in result["small"].flags
    assert result["hall"].height_m == 13 and result["hall"].method == "direct"


def test_medium_courtyard_uses_relative_parent_context_not_fixed_area_cutoff():
    parts=[observation('tower',[61.5]*200,area=575,ground=18,storeys=15),
           observation('courtyard',[62.5]*120,area=74,ground=16,storeys=2,small=True)]
    result=by_id(parts)['courtyard']
    assert result.method=='floor_share' and result.height_m==pytest.approx(5.8)
    assert 'shared_roof_storey_conflict' in result.flags
    assert 'small_part_incoherent' in result.flags


def test_large_tall_single_storey_hall_survives_relative_context_check():
    parts=[observation('reference',[7]*100,area=200,ground=0,storeys=2),
           observation('hall',[20]*100,area=150,ground=0,storeys=1,small=True)]
    result=by_id(parts)['hall']
    assert result.method=='direct' and result.height_m==20
    assert 'small_part_incoherent' not in result.flags


def test_low_terrace_and_small_rooftop_hut_keep_direct_evidence():
    parts = [observation("main", [7] * 60, area=200, storeys=2),
             observation("terrace", [2] * 20, area=8, storeys=2, small=True),
             observation("hut", [5.5] * 22, area=3.8, storeys=2, small=True)]
    result = by_id(parts)
    assert result["terrace"].height_m == 2 and result["terrace"].method == "direct"
    assert result["hut"].height_m == 5.5 and result["hut"].method == "direct"


def test_near_zero_requires_an_auditable_fallback():
    parts = [observation("main", [7] * 30, storeys=2),
             observation("low", [0.5] * 30, storeys=1)]
    low = by_id(parts)["low"]
    assert low.method == "floor_share" and low.height_m == 3.5
    assert "near_zero_direct_height" in low.flags


def test_missing_ground_and_nonpositive_observed_height_do_not_invent_a_base():
    config = HeightConfig(regional_floor_height_m=4)
    for p in [observation("missing", [7] * 30, ground=None, storeys=2),
              observation("above", [7] * 30, ground=8, storeys=2)]:
        result = by_id([p], config)[p.part_id]
        assert result.height_m is None and result.method == "unresolved"


@pytest.mark.parametrize("storeys", [None, 0])
def test_unknown_and_known_zero_storeys_do_not_become_one_floor(storeys):
    p = observation("p", [], storeys=storeys)
    result = by_id([p], HeightConfig(regional_floor_height_m=4))["p"]
    assert result.height_m is None and "no_positive_storeys_for_fallback" in result.flags


def test_regional_floor_height_has_to_be_supplied_explicitly():
    p = observation("p", [], storeys=2, ground=3)
    assert by_id([p])["p"].method == "unresolved"
    result = by_id([p], HeightConfig(regional_floor_height_m=4))["p"]
    assert result.height_m == 8 and result.method == "regional"
    assert result.ground_z == 3 and result.roof_mode_z is None


def test_basements_are_recorded_without_adding_visible_height():
    p = observation("p", [4] * 30, storeys=1, below=2)
    result = by_id([p])["p"]
    assert result.height_m == 4 and "basement_not_extruded" in result.flags


def test_batch_boundaries_preserve_explicit_building_identity():
    a = observation("a", [4] * 20)
    with pytest.raises(ValueError):
        estimate_building([a, replace(a, part_id="b", building_id="other")])
    with pytest.raises(ValueError):
        estimate_building([a, a])


def test_boundary_dominated_part_prefers_its_adjacent_spatial_storey_reference():
    parts=[
        observation('remote', [22.5]*20, area=8.5, ground=15, storeys=1),
        observation('adjacent', [], area=156, ground=15, storeys=7, local_context=38.1),
        observation('strip', [], area=3.8, ground=15, storeys=6, local=('adjacent',)),
    ]
    result=by_id(parts)['strip']
    assert result.method=='floor_share' and result.height_m==pytest.approx(19.8)
    assert result.reference_part_id=='adjacent'
    assert 'adjacent_floor_reference' in result.flags


def test_boundary_returns_conflicting_with_adjacent_storeys_do_not_create_a_wall():
    parts=[
        observation('adjacent', [31]*60, area=66, ground=7, storeys=8),
        observation('strip', [33.5]*12, area=3.8, ground=7, storeys=6, local=('adjacent',)),
    ]
    result=by_id(parts)['strip']
    assert result.method=='floor_share' and result.height_m==pytest.approx(18)
    assert result.reference_part_id=='adjacent'
    assert 'adjacent_roof_storey_conflict' in result.flags


def test_matching_boundary_returns_remain_a_direct_measurement():
    parts=[
        observation('adjacent', [31]*60, area=66, ground=7, storeys=8),
        observation('strip', [25]*12, area=3.8, ground=7, storeys=6, local=('adjacent',)),
    ]
    result=by_id(parts)['strip']
    assert result.method=='direct' and result.height_m==pytest.approx(18)


def test_multistorey_local_target_does_not_extrapolate_ground_floor_height():
    parts=[
        observation('ground-floor', [10]*40, area=200, ground=4, storeys=1),
        observation('six-storey', [28]*40, area=120, ground=4, storeys=6),
        observation('target', [], area=20, ground=4, storeys=7,
                    local=('ground-floor','six-storey')),
    ]
    result=by_id(parts)['target']
    assert result.method=='floor_share' and result.height_m==pytest.approx(28)
    assert result.reference_part_id=='six-storey'


@pytest.mark.parametrize("change", [
    {"roof_bin_m": 0}, {"min_points_absolute": 2}, {"min_points_statistical": 2},
    {"min_points_absolute": True}, {"min_mode_strength": 0},
    {"secondary_peak_ratio": 1.1}, {"coherence_max_ratio": 0.5},
    {"min_floor_height_m": 9, "max_floor_height_m": 8},
    {"regional_floor_height_m": 0}, {"min_density_points_m2": 0},
    {"near_zero_m": -1}, {"bimodal_gap_m": float("nan")},
])
def test_invalid_algorithm_settings_are_rejected(change):
    with pytest.raises(ValueError):
        HeightConfig(**change)


@pytest.mark.parametrize("change", [
    {"storeys_above": 1.5}, {"storeys_above": True}, {"storeys_below": -1},
    {"sample_area_m2": 101}, {"ground_z": float("nan")},
    {"roof_z": (float("inf"),)}, {"building_id": ""},
    {"local_storey_neighbour_ids": ["other"]},
    {"local_storey_neighbour_ids": ("p",)},
    {"local_storey_neighbour_ids": ("other", "other")},
    {"local_context_roof_z": float("nan")},
])
def test_invalid_observation_fields_are_rejected(change):
    with pytest.raises(ValueError):
        replace(observation("p", [4] * 20), **change)

