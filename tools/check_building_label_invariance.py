"""Check mandatory classification invariance on public synthetic building inputs.

Run from the repository root with geo dependencies installed. No private files,
network or previous outputs are needed. Temporary LAS/CityJSON files are removed
on exit. Return 0 only when classifications do not change building elevations;
return 1 for observed label dependence, other exceptions indicate audit failure.
Print bounded counts, never point data. Provider class metadata may vary.
"""
from pathlib import Path
import json,hashlib
from tempfile import TemporaryDirectory
import numpy as np,laspy
from lodext.demo import create_demo
from lodext.pipeline import run_build
result=[]
with TemporaryDirectory(prefix='lodext-label-audit-') as temp:
 root=Path(temp)/'inputs';create_demo(root)
 cfg=json.loads((root/'build.json').read_text());cfg.pop('dtm',None)
 cfg.update(roof_classes=None,roof_recovery={'enabled':True,'candidate_classes':None},roof_surfaces={'enabled':True})
 path=root/'build.json';path.write_text(json.dumps(cfg));original=laspy.read(root/'cloud.las');labels=np.asarray(original.classification).copy()
 xyz_hash=hashlib.sha256(np.column_stack((original.X,original.Y,original.Z)).tobytes()).hexdigest()
 baseline=None
 baseline_geometry=None
 for variant in ['original','roof_labels_only','exterior_ground_labels_only','random_all_labels']:
  cloud=laspy.read(root/'cloud.las');changed=labels.copy()
  if variant=='roof_labels_only':changed[labels==6]=1
  if variant=='exterior_ground_labels_only':changed[labels==2]=1
  if variant=='random_all_labels':changed=np.random.default_rng(31).integers(0,32,len(labels),dtype=np.uint8)
  cloud.classification=changed;cloud.write(root/'cloud.las')
  assert hashlib.sha256(np.column_stack((cloud.X,cloud.Y,cloud.Z)).tobytes()).hexdigest()==xyz_hash
  out=Path(temp)/variant;summary=run_build(path,out)
  if variant=='original' and summary['resolved_units']!=5:raise AssertionError('Label invariance cannot pass by losing the five known synthetic buildings')
  rows={v['key']:v for v in json.loads((out/'quality.json').read_text())['objects']}
  model=json.loads((out/'model.lod1.city.json').read_text())
  geometry={'transform':model.get('transform'),'vertices':model['vertices'],'objects':{k:{'type':v['type'],'geometry':v.get('geometry',[]),'parents':v.get('parents',[]),'children':v.get('children',[])} for k,v in model['CityObjects'].items()}}
  geometry_hash=hashlib.sha256(json.dumps(geometry,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  if baseline is None:baseline=rows;baseline_geometry=geometry_hash
  diffs=[{'key':k,'base_height':baseline[k].get('height_m'),'height':v.get('height_m'),'base_ground':baseline[k].get('ground_z'),'ground':v.get('ground_z'),'base_method':baseline[k].get('method'),'method':v.get('method')} for k,v in rows.items() if v.get('height_m')!=baseline[k].get('height_m') or v.get('ground_z')!=baseline[k].get('ground_z') or v.get('status')!=baseline[k].get('status') or v.get('method')!=baseline[k].get('method')]
  result.append({'variant':variant,'xyz_unchanged':True,'summary':summary,'changed_buildings':diffs,'geometry_invariant':geometry_hash==baseline_geometry})
print(json.dumps([{'variant':v['variant'],'xyz_unchanged':v['xyz_unchanged'],'changed_buildings':len(v['changed_buildings']),'geometry_invariant':v['geometry_invariant'],'resolved':v['summary']['resolved_units'],'unresolved':v['summary']['unresolved_units']} for v in result]))
raise SystemExit(1 if any(v['changed_buildings'] or not v['geometry_invariant'] for v in result) else 0)
