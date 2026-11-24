from lodext import strings
from lodext.pipeline import (_spatial_rejection_conflicts_with_fallback,
    _record_spatial_fallback_conflict,_accepted_attributed_roof_z,
    _accepted_local_context_roof_z,_inward_seed_owns_surface,
    _suppress_isolated_wall_like_fallback,_apply_boundary_shared_roof)


def rejected(roof_z, reason='boundary_continuous_with_adjacent_structures'):
    return {'accepted': False, 'rejected_neighbour_planes': [{'roof_z': roof_z, 'reason': reason}]}


def test_neighbour_plane_in_same_vertical_layer_blocks_contextual_fallback():
    assert _spatial_rejection_conflicts_with_fallback(rejected(40), ground_z=5, inferred_height_m=28, compactness=.08)


def test_neighbour_plane_far_above_low_contextual_volume_does_not_block_it():
    assert not _spatial_rejection_conflicts_with_fallback(rejected(54), ground_z=19, inferred_height_m=6, compactness=.08)


def test_boundary_only_rejection_does_not_erase_a_compact_contextual_part():
    assert not _spatial_rejection_conflicts_with_fallback(rejected(12), ground_z=5, inferred_height_m=5, compactness=.7)


def test_multilevel_rejection_still_protects_a_compact_footprint():
    geometry = rejected(12, reason='multiple_levels_continuous_with_adjacent_structures')
    assert _spatial_rejection_conflicts_with_fallback(geometry, ground_z=5, inferred_height_m=5, compactness=.7)


def test_tall_sibling_storey_conflict_blocks_an_unobserved_low_fallback():
    geometry = rejected(80, reason='sibling_storey_surface_conflict')
    assert _spatial_rejection_conflicts_with_fallback(geometry, ground_z=4, inferred_height_m=3.2, compactness=.1)


def test_compact_occluded_part_can_keep_a_separate_low_fallback():
    geometry = rejected(80, reason='sibling_storey_surface_conflict')
    assert not _spatial_rejection_conflicts_with_fallback(geometry, ground_z=4, inferred_height_m=3.2, compactness=.7)


def test_missing_context_cannot_override_an_ownership_rejection():
    assert _spatial_rejection_conflicts_with_fallback(rejected(20), ground_z=5, inferred_height_m=None, compactness=.08)


def test_accepted_target_surface_is_not_a_fallback_rejection():
    geometry = rejected(20)
    geometry['accepted'] = True
    assert not _spatial_rejection_conflicts_with_fallback(geometry, ground_z=5, inferred_height_m=6, compactness=.08)


def test_spatial_conflict_marks_but_preserves_contextual_volume():
    row={
        strings.BuildingHeightFields.METHOD:strings.HeightEstimationMethod.FLOOR_SHARE,
        strings.BuildingHeightFields.HEIGHT_M:10.5,
        strings.BuildingHeightFields.REFERENCE_PART_ID:'larger-part',
        strings.BuildingHeightFields.FLOOR_HEIGHT_M:3.5,
        strings.BuildingHeightFields.FLAGS:['inferred_roof_unverified'],
    }
    _record_spatial_fallback_conflict(row,True)
    assert row[strings.BuildingHeightFields.METHOD]==strings.HeightEstimationMethod.FLOOR_SHARE
    assert row[strings.BuildingHeightFields.HEIGHT_M]==10.5
    assert row[strings.BuildingHeightFields.REFERENCE_PART_ID]=='larger-part'
    assert row[strings.BuildingHeightFields.FLOOR_HEIGHT_M]==3.5
    assert row[strings.BuildingHeightFields.FLAGS][-1]==strings.BuildingHeightReason.SPATIAL_ROOF_REJECTED


def test_isolated_wall_like_rejection_suppresses_storey_only_volume():
    row={
        strings.BuildingHeightFields.METHOD:strings.HeightEstimationMethod.FLOOR_SHARE,
        strings.BuildingHeightFields.HEIGHT_M:32.0,
        strings.BuildingHeightFields.REFERENCE_PART_ID:'remote-part',
        strings.BuildingHeightFields.FLOOR_HEIGHT_M:4.0,
        strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION:None,
        strings.BuildingHeightFields.ROOF_REFERENCE_Z:None,
        strings.BuildingHeightFields.FLAGS:['inferred_roof_unverified'],
    }
    geometry=rejected(34.5,reason='isolated_wall_like_surface')
    assert _suppress_isolated_wall_like_fallback(row,geometry)
    assert row[strings.BuildingHeightFields.METHOD]==strings.HeightEstimationMethod.UNRESOLVED
    assert row[strings.BuildingHeightFields.HEIGHT_M] is None
    assert row[strings.BuildingHeightFields.REFERENCE_PART_ID] is None
    assert row[strings.BuildingHeightFields.FLAGS][-1]==strings.BuildingHeightReason.WALL_LIKE_FALLBACK_REJECTED


def test_boundary_shared_roof_replaces_storey_or_direct_height_without_calibration():
    row={
        strings.BuildingHeightFields.METHOD:strings.HeightEstimationMethod.DIRECT,
        strings.BuildingHeightFields.HEIGHT_M:27.0,
        strings.BuildingHeightFields.GROUND_Z:5.0,
        strings.BuildingHeightFields.REFERENCE_PART_ID:None,
        strings.BuildingHeightFields.FLOOR_HEIGHT_M:4.5,
        strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION:None,
        strings.BuildingHeightFields.ROOF_REFERENCE_Z:32.0,
        strings.BuildingHeightFields.FLAGS:[],
    }
    geometry={'boundary_shared_roof_z':30.8,
              'boundary_shared_roof_neighbour_ids':['BuildingPart::body']}
    assert _apply_boundary_shared_roof(row,geometry,1.0)
    assert row[strings.BuildingHeightFields.METHOD]==strings.HeightEstimationMethod.BOUNDARY_SHARED_ROOF
    assert row[strings.BuildingHeightFields.HEIGHT_M]==25.8
    assert row[strings.BuildingHeightFields.REFERENCE_PART_ID]=='BuildingPart::body'
    assert row[strings.BuildingHeightFields.FLOOR_HEIGHT_M] is None


def test_owned_surface_with_rejected_lod1_reduction_cannot_calibrate_siblings():
    sample={'building_surfaces':{'accepted':True,'roof_z':4.9},
            'roof_surface':{'accepted':False,'roof_z':4.9,'reason':'spatial_representative_near_ground'}}
    assert _accepted_attributed_roof_z(sample) is None


def test_owned_accepted_lod1_reduction_supplies_its_representative_elevation():
    sample={'building_surfaces':{'accepted':True,'roof_z':12.5,'sibling_calibration_allowed':True},
            'roof_surface':{'accepted':True,'roof_z':12.5}}
    assert _accepted_attributed_roof_z(sample)==12.5


def test_owner_only_surface_cannot_calibrate_siblings():
    sample={'building_surfaces':{'accepted':True,'roof_z':12.5,'sibling_calibration_allowed':False},
            'roof_surface':{'accepted':True,'roof_z':12.5}}
    assert _accepted_attributed_roof_z(sample) is None


def test_owner_only_surface_with_interior_support_can_calibrate_explicit_local_neighbour():
    sample={'building_surfaces':{'accepted':True,'roof_z':12.5,
                                'sibling_calibration_allowed':False,
                                'independent_interior_support':True},
            'roof_surface':{'accepted':True,'roof_z':12.5}}
    assert _accepted_local_context_roof_z(sample)==12.5


def test_boundary_only_surface_cannot_calibrate_explicit_local_neighbour():
    sample={'building_surfaces':{'accepted':True,'roof_z':12.5,
                                'sibling_calibration_allowed':False,
                                'independent_interior_support':False},
            'roof_surface':{'accepted':True,'roof_z':12.5}}
    assert _accepted_local_context_roof_z(sample) is None


def test_storey_aligned_surface_cannot_recalibrate_explicit_local_neighbour():
    sample={'building_surfaces':{'accepted':True,'roof_z':12.5,
                                'sibling_calibration_allowed':False,
                                'independent_interior_support':True,
                                'local_storey_aligned':True},
            'roof_surface':{'accepted':True,'roof_z':12.5}}
    assert _accepted_local_context_roof_z(sample) is None


def test_matching_inward_seed_owns_an_accepted_surface_despite_context_warning():
    geometry={'accepted':True,'rejected_neighbour_planes':[],'candidates':[
        {'accepted':True,'inward_seed_support':True,'roof_z':15.1}]}
    assert _inward_seed_owns_surface(geometry,{'accepted':True,'roof_z':15.0},1.5)


def test_boundary_or_rejected_candidate_cannot_bypass_context_conflict():
    geometry={'accepted':True,'rejected_neighbour_planes':[],'candidates':[
        {'accepted':True,'inward_seed_support':False,'roof_z':15.1}]}
    assert not _inward_seed_owns_surface(geometry,{'accepted':True,'roof_z':15.0},1.5)
    geometry['candidates'][0]['inward_seed_support']=True
    geometry['rejected_neighbour_planes']=[{'reason':'boundary_continuous_with_adjacent_structures','roof_z':15.1}]
    assert not _inward_seed_owns_surface(geometry,{'accepted':True,'roof_z':15.0},1.5)
