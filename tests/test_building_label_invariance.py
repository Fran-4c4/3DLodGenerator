"""Mandatory end-to-end classification independence in both ground modes."""
import json
import numpy as np
import laspy
import pytest
from lodext.demo import create_demo
from lodext.pipeline import run_build
from lodext.core.config import BuildConfig


@pytest.mark.parametrize('dtm',[False,True])
@pytest.mark.parametrize('labels',['all-noise','all-unclassified','random'])
def test_labels_cannot_change_a_building_decision_or_geometry(tmp_path,dtm,labels):
 root=tmp_path/'input';create_demo(root);cfg=json.loads((root/'build.json').read_text())
 if not dtm:cfg.pop('dtm')
 cfg['roof_classes']=None;path=root/'build.json';path.write_text(json.dumps(cfg))
 before=run_build(path,tmp_path/'before');assert before['resolved_units']==5
 a=json.loads((tmp_path/'before/model.lod1.city.json').read_text())
 cloud=laspy.read(root/'cloud.las');xyz=np.column_stack((cloud.X,cloud.Y,cloud.Z)).copy()
 code=7 if labels=='all-noise' else 1
 cloud.classification=np.random.default_rng(51).integers(0,32,len(cloud.points),dtype=np.uint8) if labels=='random' else np.full(len(cloud.points),code,dtype=np.uint8)
 cloud.write(root/'cloud.las');np.testing.assert_array_equal(xyz,np.column_stack((cloud.X,cloud.Y,cloud.Z)))
 after=run_build(path,tmp_path/'after');assert after['resolved_units']==5
 b=json.loads((tmp_path/'after/model.lod1.city.json').read_text())
 assert a['transform']==b['transform'] and a['vertices']==b['vertices']
 assert a['CityObjects'].keys()==b['CityObjects'].keys()
 for key,obj in a['CityObjects'].items():
  actual=b['CityObjects'][key];assert obj['geometry']==actual['geometry']
  for field in ['height_m','ground_z','reconstructed_top_z','method','reconstructionStatus']:
   assert obj['attributes'].get(field)==actual['attributes'].get(field)


@pytest.mark.parametrize('field',['roof_classes','ground','roof_recovery'])
def test_building_class_filters_require_explicit_migration(tmp_path,field):
 root=tmp_path/'input';create_demo(root);cfg=json.loads((root/'build.json').read_text());cfg.pop('dtm')
 cfg[field]=[6] if field=='roof_classes' else {'classes':[2]} if field=='ground' else {'candidate_classes':[3,4,5]}
 with pytest.raises(ValueError,match='null'):BuildConfig(**cfg)
