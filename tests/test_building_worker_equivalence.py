"""Independent parallel object fits preserve all observable native outputs."""
import json
from lodext.demo import create_demo
from lodext.pipeline import run_build


def test_native_worker_counts_preserve_model_and_quality(tmp_path):
 root=tmp_path/'inputs';create_demo(root)
 cfg=json.loads((root/'build.lidar.json').read_text())
 results=[]
 for workers in [1,4]:
  cfg['building_surfaces']={'workers':workers};path=root/f'workers-{workers}.json';path.write_text(json.dumps(cfg))
  out=tmp_path/f'out-{workers}';run_build(path,out)
  results.append({name:json.loads((out/name).read_text()) for name in ['model.lod0.city.json','model.lod1.city.json','quality.json','scene.lod1.city.json']})
 assert results[0]==results[1]
