"""Geometry controls: exposed lower roofs, small rooms, and neighbouring towers."""
from dataclasses import replace
import numpy as np
import pytest
from shapely.geometry import box,MultiPolygon,Polygon
from shapely.ops import unary_union
from shapely import intersects_xy
from lodext.core.config import BuildConfig
from lodext.io.footprints import Feature
from lodext.io.building_surfaces import attribute_surfaces,retain_vertical_extremes,local_hypotheses,_exclude_enclosed_sibling_boundary_facets,_spatial_cell_upper_median_z,_has_reconstructable_interior_alternative


def config():
 return BuildConfig(config_version='1',contract_version='0.2',dataset_id='synthetic-surfaces',geometry_mode='parts',footprints='unused.gpkg',lidar=('unused.las',),working_epsg=4083,vertical_reference='local_relative')


def feature(name,g,floors):
 return Feature('BuildingPart',name,'family',MultiPolygon([g]),{'storeys_above':floors,'storeys_below':0},[])


def grid(g,z,step=.4):
 a,b,d,e=g.bounds;x,y=np.meshgrid(np.arange(a+.15,d,step),np.arange(b+.15,e,step));x=x.ravel();y=y.ravel();m=intersects_xy(g,x,y)
 return np.column_stack((x[m],y[m],np.full(int(m.sum()),z)))


def sample(units):
 return {f.key:{'ground_z':0.,'roof_z':[],'coverage_complete':True} for f in units}


def test_vertical_layer_overflow_preserves_low_and_high_evidence_independent_of_order():
 layers={}
 for band in range(25):retain_vertical_extremes(layers,band,(0.,float(band),0.,float(band)),6)
 assert sorted(layers)==[0,1,2,22,23,24]
 reverse={}
 for band in reversed(range(25)):retain_vertical_extremes(reverse,band,(0.,float(band),0.,float(band)),6)
 assert reverse==layers


def test_vertical_layer_override_keeps_more_intermediate_evidence():
 layers={}
 for band in range(9):retain_vertical_extremes(layers,band,(0.,float(band),0.,float(band)),8)
 assert sorted(layers)==[0,1,2,3,5,6,7,8]


def test_unsaturated_columns_establish_primary_plane_before_layered_extremes():
 f=feature('layered',box(0,0,12,12),3);primary=grid(f.geometry,10,step=.6)
 vertical=np.column_stack((np.full(40,6.),np.full(40,6.),np.linspace(0,30,40)))
 xyz=np.vstack((primary,vertical));s=sample([f])[f.key]
 planes,_=local_hypotheses(f,xyz,s,config(),primary=primary)
 assert planes and planes[0][0]['fitted_upper_z']==pytest.approx(10)


@pytest.mark.parametrize('inset',[1.,.2])
def test_large_body_keeps_its_complete_footprint_below_a_room_covering_most_of_roof(inset):
 main=feature('main',box(0,0,20,20),3);room=feature('room',box(inset,inset,20-inset,20-inset),4);units=[main,room]
 low=grid(main.geometry,10);low=low[~intersects_xy(room.geometry,low[:,0],low[:,1])];upper=grid(room.geometry,14)
 clouds=[np.vstack((low,upper)),upper];samples=sample(units);before=main.geometry.wkb
 attribute_surfaces(units,clouds,samples,config())
 assert main.geometry.wkb==before and main.geometry.area==400
 assert samples[main.key]['roof_surface']['roof_z']==pytest.approx(10)
 assert samples[room.key]['roof_surface']['roof_z']==pytest.approx(14)
 assert max(samples[main.key]['roof_z'])==10
 assert samples[main.key]['building_surfaces']['rejected_neighbour_planes']
 assert any(c['visible_area_m2']<100 and c['accepted'] for c in samples[main.key]['building_surfaces']['candidates'])


def test_nested_upper_part_cannot_raise_base_through_a_boundary_transition():
 ring=Polygon([(0,0),(30,0),(30,20),(0,20)],holes=[[(5,3),(25,3),(25,17),(5,17)]])
 base=feature('base',ring,1);upper=feature('upper',box(5,3,25,17),3);units=[base,upper]
 lower=grid(base.geometry,10,step=.35)
 # Returns across the vertical/uncertain inner boundary can form an apparently
 # coherent inclined facet. They belong to the nested structure, not the base.
 boundary=(lower[:,0]>3.5)&(lower[:,0]<5)
 transition=lower[boundary].copy();lower=lower[~boundary]
 transition[:,2]=10+(transition[:,0]-3.5)*9
 high=grid(upper.geometry,22,step=.35)
 samples=sample(units);attribute_surfaces(units,[np.vstack((lower,transition,high)),high],samples,config())
 assert samples[base.key]['roof_surface']['roof_z']==pytest.approx(10)
 assert samples[upper.key]['roof_surface']['roof_z']==pytest.approx(22)


def test_displaced_central_upper_part_is_claimed_before_inward_seed_search():
 base=feature('base-with-room',box(0,0,20,20),3)
 room=feature('central-room',box(7,7,13,13),4);units=[base,room]
 lower=grid(base.geometry,10,step=.35)
 lower=lower[~intersects_xy(room.geometry.buffer(.5),lower[:,0],lower[:,1])]
 upper=grid(room.geometry,15,step=.35);upper[:,0]+=.35
 samples=sample(units)
 attribute_surfaces(units,[np.vstack((lower,upper)),upper],samples,config())
 assert samples[base.key]['roof_surface']['roof_z']==pytest.approx(10)
 assert samples[room.key]['roof_surface']['roof_z']==pytest.approx(15)


def test_enclosed_higher_sibling_boundary_facet_is_not_part_of_base_envelope():
 def piece(cells,top):return ({'cells':cells,'raw_plane_inliers':cells,'fitted_upper_z':top},np.empty((cells,3)))
 main=piece(450,16);other=piece(260,15);boundary=piece(49,22.6)
 retained,rejected=_exclude_enclosed_sibling_boundary_facets(
     [main,other,boundary],[(23.2,'BuildingPart::upper')],1.5)
 assert retained==[main,other]
 assert rejected==[{'roof_z':22.6,'reason':'higher_sibling_boundary_surface','neighbour_ids':['BuildingPart::upper']}]


def test_lod1_spatial_upper_median_gives_each_xy_cell_one_vote():
 footprint=MultiPolygon([box(0,0,10,10)])
 x,y=np.meshgrid(np.arange(.5,10,1),np.arange(.5,10,1))
 roof=np.column_stack((x.ravel(),y.ravel(),np.full(x.size,10.)))
 lower_layers=np.column_stack((x.ravel(),y.ravel(),np.full(x.size,2.)))
 dense_equipment=np.column_stack((np.full(101,.55),np.full(101,.55),np.full(101,30.)))
 top,cells=_spatial_cell_upper_median_z(np.vstack((roof,lower_layers,dense_equipment)),footprint,1.)
 assert top==pytest.approx(10) and cells==100


def test_near_ground_spatial_representative_cannot_create_a_lod1_solid():
 f=feature('ramp-from-ground',box(0,0,10,10),1);xyz=grid(f.geometry,0,step=.4);xyz[:,2]=.18*xyz[:,0]
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 assert samples[f.key]['building_surfaces']['accepted']
 assert not samples[f.key]['roof_surface']['accepted']
 assert samples[f.key]['roof_surface']['reason']=='spatial_representative_near_ground'


def test_small_body_is_not_removed_by_fixed_erosion_or_area_threshold():
 f=feature('small',box(0,0,2,2),1);xyz=grid(f.geometry,3,step=.8);samples=sample([f])
 attribute_surfaces([f],[xyz],samples,config())
 assert samples[f.key]['building_surfaces']['accepted']
 assert samples[f.key]['roof_surface']['roof_z']==pytest.approx(3)


def test_low_terrace_never_borrows_the_towers_upper_surface():
 low=feature('terrace',box(0,0,4,4),1);tower=feature('tower',box(4,0,10,10),10)
 upper=grid(tower.geometry,30);contamination=np.array([[3.7,.2,30],[3.7,1.2,30],[3.7,2.2,30],[3.9,3.4,30]])
 samples=sample([low,tower]);attribute_surfaces([low,tower],[np.vstack((grid(low.geometry,7),contamination)),upper],samples,config())
 assert samples[low.key]['roof_surface']['roof_z']==pytest.approx(7)
 assert max(samples[low.key]['roof_z'])==7


def test_dense_edge_level_continuing_outside_is_not_owned_by_target():
 target=feature('target',box(0,0,10,10),3);neighbour=feature('neighbour',box(10,0,20,10),5)
 interior=grid(box(0,0,8.5,10),10,step=.4);edge=grid(box(8.5,0,10,10),15,step=.4)
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[np.vstack((interior,edge)),grid(neighbour.geometry,15,step=.3)],samples,config())
 assert samples[target.key]['building_surfaces']['accepted']
 assert samples[target.key]['roof_surface']['roof_z']==pytest.approx(10)
 assert any(item['reason']=='edge_level_continues_outside'
            for item in samples[target.key]['building_surfaces']['rejected_neighbour_planes'])


def test_edge_level_without_exterior_continuation_remains_a_target_candidate():
 target=feature('target-edge-terrace',box(0,0,10,10),3)
 interior=grid(box(0,0,8.5,10),10,step=.4);edge=grid(box(8.5,0,10,10),15,step=.4)
 samples=sample([target]);attribute_surfaces([target],[np.vstack((interior,edge))],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['accepted'] and len([item for item in evidence['candidates'] if item['accepted']])==2
 assert not any(item['reason']=='edge_level_continues_outside' for item in evidence['rejected_neighbour_planes'])


def test_edge_contamination_requires_a_positive_non_edge_alternative():
 edge={'valid':True,'edge_contamination':True,'xyz':np.array([[0.,0.,10.]])}
 near_ground={'valid':True,'edge_contamination':False,'xyz':np.array([[0.,0.,.8]])}
 owned_roof={'valid':True,'edge_contamination':False,'xyz':np.array([[0.,0.,7.]])}
 assert not _has_reconstructable_interior_alternative([edge,near_ground],0.,1.)
 assert _has_reconstructable_interior_alternative([edge,owned_roof],0.,1.)


def test_central_upper_room_is_an_interior_level_not_edge_contamination():
 target=feature('target-room',box(0,0,10,10),3);neighbour=feature('neighbour',box(10,0,20,10),5)
 lower=grid(target.geometry,10,step=.45);room=box(3,3,7,7)
 lower=lower[~intersects_xy(room,lower[:,0],lower[:,1])];upper=grid(room,15,step=.25)
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[np.vstack((lower,upper)),grid(neighbour.geometry,15,step=.3)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['accepted'] and any(item['accepted'] and item['roof_z']>14 for item in evidence['candidates'])
 assert not any(item['reason']=='edge_level_continues_outside' for item in evidence['rejected_neighbour_planes'])


def test_broad_main_roof_around_central_room_survives_exterior_continuity():
 target=feature('main-around-room',box(0,0,10,10),3);neighbour=feature('same-low-neighbour',box(10,0,20,10),3)
 room=box(1.5,1.5,8.5,8.5);lower=grid(target.geometry,10,step=.4)
 lower=lower[~intersects_xy(room,lower[:,0],lower[:,1])];upper=grid(room,15,step=.4)
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[np.vstack((lower,upper)),grid(neighbour.geometry,10,step=.4)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['accepted'] and any(item['accepted'] and item['roof_z']<11 for item in evidence['candidates'])
 assert not any(item['reason']=='edge_level_continues_outside' and item['roof_z']<11
                for item in evidence['rejected_neighbour_planes'])


def test_isolated_sub_resolution_strip_does_not_become_a_tall_wall_volume():
 wall_like=feature('isolated-wall-like',box(0,0,30,.4),4)
 samples=sample([wall_like]);attribute_surfaces([wall_like],[grid(wall_like.geometry,15,step=.2)],samples,config())
 evidence=samples[wall_like.key]['building_surfaces']
 assert not evidence['accepted'] and samples[wall_like.key]['roof_z']==[]
 assert any(item['reason']=='isolated_wall_like_surface' for item in evidence['rejected_neighbour_planes'])


def test_isolated_sub_resolution_perimeter_does_not_escape_through_oriented_width():
 outer=box(0,0,30,20);wall_like=feature('isolated-perimeter',outer.difference(box(.6,.6,29.4,19.4)),4)
 samples=sample([wall_like]);attribute_surfaces([wall_like],[grid(wall_like.geometry,15,step=.2)],samples,config())
 evidence=samples[wall_like.key]['building_surfaces']
 assert not evidence['accepted'] and samples[wall_like.key]['roof_z']==[]
 assert any(item['reason']=='isolated_wall_like_surface' for item in evidence['rejected_neighbour_planes'])


def test_isolated_narrow_body_with_resolved_width_support_remains_owned():
 body=feature('isolated-narrow-body',box(0,0,30,3),2)
 samples=sample([body]);attribute_surfaces([body],[grid(body.geometry,7,step=.3)],samples,config())
 assert samples[body.key]['building_surfaces']['accepted']
 assert samples[body.key]['roof_surface']['roof_z']==pytest.approx(7)


def test_sub_resolution_strip_attached_to_a_mapped_body_is_not_an_isolated_wall():
 strip=feature('attached-strip',box(0,0,30,.4),2)
 body=feature('mapped-body',box(0,.4,30,6),3);units=[strip,body]
 samples=sample(units)
 attribute_surfaces(units,[grid(strip.geometry,8,step=.2),np.empty((0,3))],samples,config())
 evidence=samples[strip.key]['building_surfaces']
 assert evidence['accepted'] and samples[strip.key]['roof_surface']['roof_z']==pytest.approx(8)
 assert not any(item['reason']=='isolated_wall_like_surface'
                for item in evidence['rejected_neighbour_planes'])
 assert evidence['local_storey_neighbour_ids']==[body.key]


def test_sub_resolution_compact_room_does_not_enable_local_storey_preference():
 room=feature('compact-room',box(0,0,1,1),2)
 body=feature('mapped-body',box(1,0,8,8),3);units=[room,body]
 samples=sample(units)
 attribute_surfaces(units,[grid(room.geometry,8,step=.2),grid(body.geometry,11)],samples,config())
 assert samples[room.key]['building_surfaces']['local_storey_neighbour_ids']==[]


def test_boundary_only_one_storey_part_rejects_a_tall_siblings_displaced_roof():
 low=feature('mapped-low-part',box(0,0,2,12),1);tower=feature('tower',box(2,0,14,12),25)
 samples=sample([low,tower]);attribute_surfaces([low,tower],[grid(low.geometry,75,step=.3),grid(tower.geometry,80)],samples,config())
 evidence=samples[low.key]['building_surfaces']
 assert not evidence['accepted'] and samples[low.key]['roof_z']==[]
 assert any(item['reason']=='sibling_storey_surface_conflict' for item in evidence['rejected_neighbour_planes'])


def test_incompatible_touching_ring_neighbour_does_not_disable_single_sibling_conflict():
 low=feature('mapped-low-part',box(0,0,2,12),1);tower=feature('tower',box(2,0,14,12),25)
 enclosing=feature('partitioned-main',Polygon([(-8,0),(0,0),(0,12),(-8,12)],
     holes=[[(-8,0),(-6,1),(-7,2),(-8,0)]]),9)
 assert enclosing.geometry.is_valid
 units=[low,tower,enclosing];samples=sample(units)
 attribute_surfaces(units,[grid(low.geometry,75,step=.3),grid(tower.geometry,80),grid(enclosing.geometry,30)],samples,config())
 evidence=samples[low.key]['building_surfaces']
 assert enclosing.key not in evidence['neighbour_ids']
 assert not evidence['accepted'] and samples[low.key]['roof_z']==[]
 assert any(item['reason']=='sibling_storey_surface_conflict'
            and item['neighbour_ids']==[tower.key]
            for item in evidence['rejected_neighbour_planes'])


def test_deep_full_surface_without_a_lower_alternative_remains_owned():
 low=feature('mapped-courtyard',box(0,0,8,8),2);tower=feature('tower',box(8,0,20,12),20)
 samples=sample([low,tower]);attribute_surfaces([low,tower],[grid(low.geometry,80,step=.3),grid(tower.geometry,80)],samples,config())
 evidence=samples[low.key]['building_surfaces']
 assert evidence['accepted'] and samples[low.key]['roof_surface']['roof_z']==pytest.approx(80)
 assert evidence['tall_sibling_conflict']
 assert not evidence['sibling_calibration_allowed'] and samples[low.key]['roof_z']==[]


def test_complex_parent_rejects_a_full_high_surface_shared_by_larger_tall_siblings():
 low=feature('mapped-courtyard',box(8,0,16,8),2)
 left=feature('left-tower',box(0,0,8,12),20);right=feature('right-tower',box(16,0,28,12),20)
 units=[low,left,right];samples=sample(units)
 target=np.vstack((grid(low.geometry,7,step=.3),grid(low.geometry,80,step=.3)))
 attribute_surfaces(units,[target,grid(left.geometry,80),grid(right.geometry,80)],samples,config())
 evidence=samples[low.key]['building_surfaces']
 assert evidence['accepted'] and samples[low.key]['roof_surface']['roof_z']==pytest.approx(7)
 rejected=next(item for item in evidence['rejected_neighbour_planes'] if item['reason']=='tall_sibling_owns_full_surface')
 assert rejected['neighbour_ids']==['BuildingPart::left-tower','BuildingPart::right-tower']


def test_deep_interior_support_preserves_a_genuinely_tall_one_storey_hall():
 hall=feature('tall-hall',box(0,0,20,20),1);tower=feature('tower',box(20,0,32,20),25)
 samples=sample([hall,tower]);attribute_surfaces([hall,tower],[grid(hall.geometry,75),grid(tower.geometry,80)],samples,config())
 assert samples[hall.key]['building_surfaces']['accepted']
 assert samples[hall.key]['roof_surface']['roof_z']==pytest.approx(75)


def test_same_parent_storey_scale_selects_main_plateau_below_connected_upper_detail():
 ring=Polygon([(0,0),(20,0),(20,20),(0,20)],holes=[[(6,6),(14,6),(14,14),(6,14)]])
 body=feature('main-ring',ring,25);upper=feature('upper-ring',box(6,6,14,14),26)
 xyz=grid(body.geometry,82,step=.35);transition=(xyz[:,0]>=9)&(xyz[:,0]<11);high=xyz[:,0]>=11
 xyz[transition,2]=82+1.5*(xyz[transition,0]-9);xyz[high,2]=85
 samples=sample([body,upper]);attribute_surfaces([body,upper],[xyz,grid(upper.geometry,85)],samples,config())
 evidence=samples[body.key]['building_surfaces']
 assert evidence['accepted'] and evidence['selection_basis']=='sibling_storey_alignment'
 assert samples[body.key]['roof_surface']['roof_z']==pytest.approx(82,abs=.2)


def test_adjacent_storey_step_selects_structural_roof_below_rooftop_equipment():
 target=feature('three-storey-target',box(0,0,3.9,3.9),3)
 neighbour=feature('two-storey-neighbour',box(3.9,0,12,3.9),2)
 structural=grid(target.geometry,12,step=.7);equipment=grid(target.geometry,16,step=.45)
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[np.vstack((structural,equipment)),grid(neighbour.geometry,8,step=.35)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['selection_basis']=='sibling_storey_alignment'
 assert evidence['local_storey_aligned'] and not evidence['sibling_calibration_allowed']
 assert samples[target.key]['roof_surface']['roof_z']==pytest.approx(12,abs=.2)


def test_deep_observed_retracted_terraces_keep_each_structural_level():
 low=feature('terrace-three',box(0,0,8,8),3)
 middle=feature('terrace-four',box(8,0,16,8),4)
 high=feature('terrace-five',box(16,0,24,8),5)
 units=[low,middle,high];samples=sample(units)
 attribute_surfaces(units,[grid(low.geometry,12),grid(middle.geometry,16),grid(high.geometry,20)],samples,config())
 assert [samples[item.key]['roof_surface']['roof_z'] for item in units]==pytest.approx([12,16,20])
 assert all(samples[item.key]['building_surfaces']['accepted'] for item in units)
 assert not any(samples[item.key]['building_surfaces']['local_storey_aligned'] for item in units)


def test_subresolution_part_uses_absolute_shared_roof_when_declared_step_is_unobserved():
 target=feature('seven-storey-facade',box(0,0,1,1),7)
 neighbour_geometry=box(-2,-2,3,3).difference(box(0,0,1,3))
 neighbour=feature('five-storey-body',neighbour_geometry,5)
 shared=grid(target.geometry,22,step=.25);upper=grid(target.geometry,25,step=.22)
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[np.vstack((shared,upper)),grid(neighbour.geometry,22,step=.35)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['boundary_shared_roof_z']==pytest.approx(22)
 assert evidence['boundary_shared_roof_neighbour_ids']==[neighbour.key]
 assert not evidence['sibling_calibration_allowed'] and samples[target.key]['roof_z']==[]


def test_repeated_facade_family_corrobates_shared_roof_without_a_larger_neighbour():
 target=feature('six-storey-facade-c',box(0,0,1.2,8),6)
 neighbour=feature('seven-storey-balcony-c',box(1.2,0,2.4,8),7)
 peer_a=feature('six-storey-facade-a',box(3,0,4.2,8),6)
 peer_b=feature('six-storey-facade-b',box(5,0,6.2,8),6)
 units=[target,neighbour,peer_a,peer_b];samples=sample(units)
 target_xyz=np.vstack((grid(target.geometry,30.8,step=.3),grid(target.geometry,32,step=.22)))
 attribute_surfaces(units,[target_xyz,grid(neighbour.geometry,30.8),
                           grid(peer_a.geometry,30.8),grid(peer_b.geometry,30.8)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['boundary_shared_roof_z']==pytest.approx(30.8)
 assert evidence['boundary_shared_roof_neighbour_ids'][0]==neighbour.key
 assert {peer_a.key,peer_b.key}.issubset(evidence['boundary_shared_roof_neighbour_ids'])


def test_lower_storey_room_is_not_raised_to_enclosing_higher_body():
 target=feature('two-storey-room',box(0,0,2,7),2)
 body_geometry=box(-3,-3,5,10).difference(box(0,0,2,7))
 body=feature('four-storey-body',body_geometry,4)
 units=[target,body];samples=sample(units)
 attribute_surfaces(units,[grid(target.geometry,24,step=.3),grid(body.geometry,24,step=.35)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['boundary_shared_roof_z'] is None


def test_repeated_lower_facade_level_is_not_used_without_a_higher_target_level():
 target=feature('one-storey-facade-c',box(0,0,1.2,8),1)
 neighbour=feature('two-storey-body',box(1.2,0,8,8),2)
 peer_a=feature('one-storey-facade-a',box(9,0,10.2,8),1)
 peer_b=feature('one-storey-facade-b',box(11,0,12.2,8),1)
 units=[target,neighbour,peer_a,peer_b];samples=sample(units)
 attribute_surfaces(units,[grid(target.geometry,20,step=.3),grid(neighbour.geometry,20),
                           grid(peer_a.geometry,20),grid(peer_b.geometry,20)],samples,config())
 assert samples[target.key]['building_surfaces']['boundary_shared_roof_z'] is None


def test_unobserved_sliver_uses_two_compatible_roofs_that_bracket_its_storeys():
 left=feature('three-storey-body',box(-8,0,0,8),3)
 target=feature('four-storey-sliver',box(0,0,.4,8),4)
 right=feature('five-storey-body',box(.4,0,8,8),5)
 units=[left,target,right];samples=sample(units)
 attribute_surfaces(units,[grid(left.geometry,22),np.empty((0,3)),grid(right.geometry,22.4)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['boundary_shared_roof_z']==pytest.approx(22.2)
 assert set(evidence['boundary_shared_roof_neighbour_ids'])=={left.key,right.key}


def test_unobserved_part_ignores_bracketing_roofs_at_marginal_contacts():
 target=feature('four-storey-body',box(0,0,8,8),4)
 left=feature('three-storey-contact',box(-3,0,0,.5),3)
 right=feature('five-storey-contact',box(8,7.5,11,8),5)
 units=[left,target,right];samples=sample(units)
 attribute_surfaces(units,[grid(left.geometry,22),np.empty((0,3)),grid(right.geometry,22.4)],samples,config())
 assert samples[target.key]['building_surfaces']['boundary_shared_roof_z'] is None


def test_observed_narrow_storey_step_is_not_flattened_to_shared_boundary_roof():
 target=feature('three-storey-terrace',box(0,0,1.2,8),3)
 neighbour=feature('two-storey-body',box(1.2,0,10,8),2)
 target_xyz=np.vstack((grid(target.geometry,8,step=.3),grid(target.geometry,12,step=.22)))
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[target_xyz,grid(neighbour.geometry,8)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['boundary_shared_roof_z'] is None


def test_subresolution_single_storey_surface_above_multistorey_roofs_is_rejected():
 target=feature('one-storey-outlier',box(0,0,1.4,8),1)
 left=feature('seven-storey-body',box(-10,0,0,8),7)
 right=feature('eight-storey-body',box(1.4,0,12,8),8)
 units=[target,left,right];samples=sample(units)
 attribute_surfaces(units,[grid(target.geometry,44,step=.22),grid(left.geometry,30),grid(right.geometry,33)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert not evidence['accepted'] and samples[target.key]['roof_z']==[]
 assert any(item['reason']=='subresolution_single_storey_above_siblings'
            for item in evidence['rejected_neighbour_planes'])


def test_unowned_multistorey_target_prefers_adjacent_multistorey_body_over_ground_floor():
 target=feature('seven-storey-target',box(0,0,2,10),7)
 ground_floor=feature('one-storey-body',box(-10,0,0,10),1)
 multistorey=feature('six-storey-body',box(2,0,12,10),6)
 units=[target,ground_floor,multistorey];samples=sample(units)
 attribute_surfaces(units,[np.empty((0,3)),grid(ground_floor.geometry,7),grid(multistorey.geometry,24)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert not evidence['accepted']
 assert evidence['local_storey_neighbour_ids']==[multistorey.key]


def test_boundary_rejected_elongated_target_retains_local_storey_fallback():
 target=feature('seven-storey-target',box(0,0,2.5,10),7)
 neighbour=feature('six-storey-body',box(2.5,0,12.5,10),6)
 target_points=grid(target.geometry,24,step=.35)
 target_points=target_points[target_points[:,0]>1.6]
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[target_points,grid(neighbour.geometry,24,step=.35)],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert not evidence['accepted']
 assert any(item['reason']=='boundary_continuous_with_adjacent_structures'
            for item in evidence['rejected_neighbour_planes'])
 assert evidence['local_storey_neighbour_ids']==[neighbour.key]


def test_unobserved_space_between_beams_is_not_filled_by_a_convex_hull():
 f=feature('open-shell',box(0,0,12,12),1)
 x=np.arange(.1,12,.4);xyz=np.vstack([np.column_stack((x,np.full(len(x),y),np.full(len(x),4.))) for y in [1.,11.]])
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 assert not samples[f.key]['building_surfaces']['accepted']
 assert samples[f.key]['roof_z']==[]


def test_dense_irregular_canopy_is_not_a_supported_roof():
 f=feature('irregular',box(0,0,20,20),1);xyz=grid(f.geometry,4)
 xyz[:,2]=np.random.default_rng(23).uniform(2,12,len(xyz))
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 assert not samples[f.key]['building_surfaces']['accepted']


def test_only_neighbour_returns_do_not_create_a_floating_low_part():
 low=feature('occluded-low-part',box(3.6,0,4,4),1);tower=feature('tower',box(4,0,10,10),10)
 own=grid(low.geometry,30,step=.15);upper=grid(tower.geometry,30)
 samples=sample([low,tower]);attribute_surfaces([low,tower],[own,upper],samples,config())
 assert not samples[low.key]['building_surfaces']['accepted']
 assert samples[low.key]['roof_z']==[]
 assert samples[tower.key]['building_surfaces']['accepted']


def test_prepared_surface_compression_preserves_neighbour_attribution():
 from lodext.io.building_surfaces import local_hypotheses
 main=feature('main',box(0,0,20,20),3);room=feature('room',box(1,1,19,19),4);units=[main,room]
 low=grid(main.geometry,10);low=low[~intersects_xy(room.geometry,low[:,0],low[:,1])];upper=grid(room.geometry,14)
 raw=[np.vstack((low,upper)),upper];a=sample(units);b=sample(units);c=config()
 attribute_surfaces(units,raw,a,c)
 clouds=[];hypotheses=[];spacings=[];counts=[]
 for f,xyz in zip(units,raw):
  planes,spacing=local_hypotheses(f,xyz,b[f.key],c);keep=np.zeros(len(xyz),dtype=bool)
  for _,mask in planes:keep|=mask
  clouds.append(xyz[keep]);hypotheses.append([(p,m[keep]) for p,m in planes]);spacings.append(spacing);counts.append(len(xyz))
 attribute_surfaces(units,clouds,b,c,prepared=(hypotheses,spacings,counts))
 for f in units:
  assert a[f.key]['roof_z']==b[f.key]['roof_z']
  assert a[f.key]['roof_surface']==b[f.key]['roof_surface']
  for field in ['planes','candidates','rejected_neighbour_planes','spacing_m','original_representatives']:
   assert a[f.key]['building_surfaces'][field]==b[f.key]['building_surfaces'][field]


def test_incomplete_source_coverage_cannot_supply_an_observed_roof_or_context():
 f=feature('partial',box(0,0,4,4),1);s=sample([f]);s[f.key]['coverage_complete']=False
 attribute_surfaces([f],[grid(f.geometry,3)],s,config())
 assert not s[f.key]['building_surfaces']['accepted'] and s[f.key]['roof_z']==[]


def test_three_far_returns_do_not_expand_uncertainty_to_fill_a_large_roof():
 f=feature('sparse-large',box(0,0,40,40),1);xyz=np.array([[.2,.2,4],[39.8,.2,4],[.2,39.8,4]])
 s=sample([f]);attribute_surfaces([f],[xyz],s,config())
 assert not s[f.key]['building_surfaces']['accepted'] and s[f.key]['roof_z']==[]


def test_distributed_support_across_large_body_survives_an_unsampled_interior_strip():
 shape=unary_union([box(0,0,100,8),box(0,0,20,60),box(80,0,100,60)])
 f=feature('large-complex',shape,4);xyz=grid(f.geometry,15,step=.8);xyz=xyz[(xyz[:,0]<42)|(xyz[:,0]>58)]
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 assert samples[f.key]['building_surfaces']['accepted']
 assert samples[f.key]['roof_surface']['roof_z']==pytest.approx(15)


def test_partial_support_confined_to_one_side_does_not_fill_a_large_body():
 shape=unary_union([box(0,0,100,8),box(0,0,20,60),box(80,0,100,60)])
 f=feature('one-sided',shape,4);samples=sample([f])
 attribute_surfaces([f],[grid(box(0,0,20,60),15,step=.8)],samples,config())
 assert not samples[f.key]['building_surfaces']['accepted'] and samples[f.key]['roof_z']==[]


def test_short_cluster_cannot_establish_an_entire_long_narrow_body():
 f=feature('narrow',box(0,0,50,.3),1);xyz=np.array([[.2,.05,3],[.6,.05,3],[.2,.25,3],[.6,.25,3]])
 s=sample([f]);attribute_surfaces([f],[xyz],s,config())
 assert not s[f.key]['building_surfaces']['accepted'] and s[f.key]['roof_z']==[]


def test_fully_supported_strip_continuous_with_two_neighbours_remains_a_candidate():
 left=feature('left',box(0,0,10,10),3);strip=feature('strip',box(10,0,12,10),3);right=feature('right',box(12,0,22,10),3)
 units=[left,strip,right];samples=sample(units)
 attribute_surfaces(units,[grid(left.geometry,10),grid(strip.geometry,10,step=.3),grid(right.geometry,10)],samples,config())
 assert samples[strip.key]['building_surfaces']['accepted'] and samples[strip.key]['roof_z']


def test_boundary_dominated_strip_with_a_material_support_gap_stays_unresolved():
 left=feature('left',box(0,0,10,50),3);strip=feature('strip',box(10,0,12,50),3);right=feature('right',box(12,0,22,50),3)
 strip_points=grid(strip.geometry,10,step=.3);strip_points=strip_points[(strip_points[:,1]<18)|(strip_points[:,1]>32)]
 units=[left,strip,right];samples=sample(units)
 attribute_surfaces(units,[grid(left.geometry,10),strip_points,grid(right.geometry,10)],samples,config())
 assert not samples[strip.key]['building_surfaces']['accepted'] and samples[strip.key]['roof_z']==[]
 rejected=samples[strip.key]['building_surfaces']['rejected_neighbour_planes']
 assert any(r['reason']=='boundary_continuous_with_adjacent_structures' for r in rejected)
 assert samples[left.key]['building_surfaces']['accepted'] and samples[right.key]['building_surfaces']['accepted']


def test_compact_multilevel_surface_with_deep_controls_remains_owned_among_neighbours():
 target=feature('target',box(10,0,20,10),5);left=feature('left',box(0,0,10,10),5);right=feature('right',box(20,0,30,10),5);top=feature('top',box(10,10,20,20),5);bottom=feature('bottom',box(10,-10,20,0),5)
 xyz=grid(target.geometry,10,step=.4);xyz[xyz[:,0]>17,2]=12
 units=[target,left,right,top,bottom];samples=sample(units);samples[target.key]['roof_z']=[7.25]*12
 attribute_surfaces(units,[xyz,grid(left.geometry,10),grid(right.geometry,10),grid(top.geometry,10),grid(bottom.geometry,10)],samples,config())
 assert samples[target.key]['building_surfaces']['accepted']
 assert samples[target.key]['roof_surface']['roof_z']==pytest.approx(10)
 assert not samples[target.key]['building_surfaces']['sibling_calibration_allowed']
 assert samples[target.key]['roof_z']==[]


def test_boundary_dominated_compact_multilevel_surface_remains_ambiguous():
 target=feature('target',box(10,0,12,2),5);left=feature('left',box(8,0,10,2),5);right=feature('right',box(12,0,14,2),5);top=feature('top',box(10,2,12,4),5);bottom=feature('bottom',box(10,-2,12,0),5)
 xyz=grid(target.geometry,10,step=.25);xyz[xyz[:,0]>11.5,2]=12
 units=[target,left,right,top,bottom];samples=sample(units)
 attribute_surfaces(units,[xyz,grid(left.geometry,10,step=.25),grid(right.geometry,10,step=.25),grid(top.geometry,10,step=.25),grid(bottom.geometry,10,step=.25)],samples,config())
 assert not samples[target.key]['building_surfaces']['accepted'] and samples[target.key]['roof_z']==[]
 assert any(r['reason']=='multiple_levels_continuous_with_adjacent_structures' for r in samples[target.key]['building_surfaces']['rejected_neighbour_planes'])


def test_inward_seed_preserves_a_narrow_mapped_part_among_continuous_neighbours():
 target=feature('target',box(10,0,12,6),3)
 neighbours=[feature('left',box(0,0,10,6),3),feature('right',box(12,0,22,6),3),
             feature('top',box(10,6,12,12),3),feature('bottom',box(10,-6,12,0),3)]
 xyz=grid(target.geometry,10,step=.25);xyz[xyz[:,0]>11.25,2]=12
 units=[target]+neighbours;samples=sample(units)
 attribute_surfaces(units,[xyz]+[grid(f.geometry,10,step=.25) for f in neighbours],samples,config())
 evidence=samples[target.key]['building_surfaces']
 assert evidence['accepted'] and evidence['roof_z']==pytest.approx(10)
 assert len(evidence['candidates'])>1
 assert any(item['inward_seed_support'] and not item['deep_interior_support'] for item in evidence['candidates'])


def test_multilevel_surface_continuous_with_only_one_neighbour_remains_owned():
 target=feature('target',box(0,0,10,10),3);neighbour=feature('neighbour',box(10,0,20,10),3)
 xyz=grid(target.geometry,10,step=.35);xyz[xyz[:,0]<2,2]=12
 units=[target,neighbour];samples=sample(units)
 attribute_surfaces(units,[xyz,grid(neighbour.geometry,10)],samples,config())
 assert samples[target.key]['building_surfaces']['accepted']
 assert samples[target.key]['roof_surface']['roof_z']==pytest.approx(10)


def test_multilevel_surface_shared_with_less_than_half_of_neighbours_keeps_own_dominant_level():
 target=feature('target',box(10,0,20,10),4)
 neighbour_shapes=[box(0,0,10,10/3),box(0,10/3,10,20/3),box(0,20/3,10,10),
                   box(20,0,30,10/3),box(20,10/3,30,20/3),box(20,20/3,30,10),
                   box(10,10,15,20),box(15,10,20,20),box(10,-10,20,0)]
 neighbours=[feature(f'n{i}',shape,4) for i,shape in enumerate(neighbour_shapes)]
 xyz=grid(target.geometry,10,step=.35);xyz[xyz[:,0]>18,2]=12
 clouds=[xyz]+[grid(f.geometry,10 if i<4 else 6) for i,f in enumerate(neighbours)]
 units=[target]+neighbours;samples=sample(units)
 attribute_surfaces(units,clouds,samples,config())
 assert samples[target.key]['building_surfaces']['accepted']
 assert samples[target.key]['roof_surface']['roof_z']==pytest.approx(10)


def test_high_perimeter_and_low_centre_are_not_one_continuous_roof():
 f=feature('rim',box(0,0,10,10),2);xyz=grid(f.geometry,6,step=.45)
 boundary=np.minimum.reduce([xyz[:,0],xyz[:,1],10-xyz[:,0],10-xyz[:,1]])<1.5
 xyz[boundary,2]=10
 c=config();c=replace(c,building_surfaces=replace(c.building_surfaces,registration_m=.25))
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,c)
 assert samples[f.key]['building_surfaces']['accepted']
 assert samples[f.key]['roof_surface']['roof_z']==pytest.approx(6)
 assert max(samples[f.key]['roof_z'])==6


def test_continuous_gable_facets_can_jointly_support_a_roof():
 f=feature('gable',box(0,0,10,10),2);xyz=grid(f.geometry,6,step=.4)
 xyz[:,2]=6+.5*(5-np.abs(xyz[:,0]-5))
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 evidence=samples[f.key]['building_surfaces'];assert evidence['accepted']
 # The integration result uses the same deterministic spatial-cell reduction;
 # the symmetric gable's representative elevation lies below its ridge.
 expected,_=_spatial_cell_upper_median_z(xyz,f.geometry,evidence['spacing_m'])
 assert samples[f.key]['roof_surface']['roof_z']==pytest.approx(expected)
 assert samples[f.key]['roof_surface']['lod1_reduction']=='spatial_cell_upper_median'


def test_adaptive_anisotropic_sampling_does_not_fragment_a_large_pitched_roof():
 f=feature('long-hall',box(0,0,80,20),1)
 x,y=np.meshgrid(np.arange(1.25,80,2.5),np.arange(.3,20,.625))
 xyz=np.column_stack((x.ravel(),y.ravel(),6+.12*x.ravel()))
 samples=sample([f]);attribute_surfaces([f],[xyz],samples,config())
 e=samples[f.key]['building_surfaces']
 assert e['accepted'] and e['spacing_m']>=2.5
 assert e['planes'][0]['cells']==len(xyz)
 assert samples[f.key]['roof_surface']['roof_z']==pytest.approx(np.median(xyz[:,2]))


@pytest.mark.parametrize('workers',[0,-1,True,1.5])
def test_invalid_worker_counts_are_rejected(workers):
 from lodext.core.building_surfaces import BuildingSurfaceConfig
 with pytest.raises(ValueError,match='workers'):BuildingSurfaceConfig(workers=workers)


def test_parallel_attribution_preserves_frozen_neighbour_decisions():
 from copy import deepcopy
 main=feature('main',box(0,0,20,20),3);room=feature('room',box(1,1,19,19),4)
 low=grid(main.geometry,10);low=low[~intersects_xy(room.geometry,low[:,0],low[:,1])];upper=grid(room.geometry,14)
 units=[main,room];clouds=[np.vstack((low,upper)),upper];serial=sample(units);parallel=deepcopy(serial)
 attribute_surfaces(units,clouds,serial,config())
 cfg=config();cfg=replace(cfg,building_surfaces=replace(cfg.building_surfaces,workers=4))
 attribute_surfaces(units,clouds,parallel,cfg)
 assert serial==parallel


def test_comparable_low_and_high_returns_use_observed_context_without_scaling():
    low=feature('projection',box(0,0,8,8),1)
    tower=feature('tower',box(8,0,28,20),20)
    # Equal, spatially complementary evidence: seven metres and a displaced
    # high facade level, deliberately different from the tower's roof plane.
    xyz=grid(low.geometry,7,step=.5);xyz[xyz[:,0]>4,2]=78
    upper=grid(tower.geometry,82,step=.5)
    samples=sample([low,tower]);attribute_surfaces([low,tower],[xyz,upper],samples,config())
    evidence=samples[low.key]['building_surfaces']
    assert evidence['selection_basis']=='neighbour_storeys'
    assert samples[low.key]['roof_surface']['roof_z']==pytest.approx(7)
    assert max(samples[low.key]['roof_z'])==7
    assert evidence['context_floor_height_m']==pytest.approx(4.1)


def test_dominant_tall_single_storey_hall_is_not_scaled_to_neighbour_floor_unit():
    hall=feature('hall',box(0,0,20,20),1)
    neighbour=feature('neighbour',box(20,0,40,20),6)
    roof=grid(hall.geometry,20,step=.5)
    lower=grid(box(0,0,2,2),3,step=.5)
    samples=sample([hall,neighbour])
    attribute_surfaces([hall,neighbour],[np.vstack((roof,lower)),grid(neighbour.geometry,20,step=.5)],samples,config())
    assert samples[hall.key]['roof_surface']['roof_z']==pytest.approx(20)
    assert max(samples[hall.key]['roof_z'])==20
    assert samples[hall.key]['building_surfaces']['selection_basis']!='neighbour_storeys'


def test_mixed_observed_roof_levels_preserve_a_supported_body_and_source_boundary():
    f=feature('stepped-body',box(0,0,12,12),2)
    xyz=grid(f.geometry,6,step=.5);xyz[xyz[:,0]>8,2]=9
    samples=sample([f]);before=f.geometry.wkb
    attribute_surfaces([f],[xyz],samples,config())
    assert samples[f.key]['building_surfaces']['accepted']
    assert len(samples[f.key]['roof_z'])>0 and f.geometry.wkb==before
    assert len(samples[f.key]['building_surfaces']['planes'])>=2
