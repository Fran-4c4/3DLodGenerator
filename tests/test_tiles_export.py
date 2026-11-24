"""Numerical GLB/3D Tiles verification, independent of rendering."""
from copy import deepcopy
import json
import struct

import numpy as np
import pytest
from pyproj import Geod,Transformer

from lodext.demo import create_demo
from lodext.pipeline import run_build
from lodext.export.tiles import TileConfig,write_tiles


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    root = tmp_path_factory.mktemp("tiles-flow")
    create_demo(root/"inputs")
    run_build(root/"inputs/build.json",root/"models")
    result = write_tiles(root/"models/model.lod1.city.json",root/"tiles",TileConfig(-25))
    return root,result


def read_glb(file):
    data = file.read_bytes()
    magic,version,length = struct.unpack_from('<4sII',data)
    assert magic==b'glTF' and version==2 and length==len(data)
    json_length,kind = struct.unpack_from('<I4s',data,12)
    assert kind==b'JSON' and json_length%4==0
    gltf = json.loads(data[20:20+json_length])
    binary_length,kind = struct.unpack_from('<I4s',data,20+json_length)
    assert kind==b'BIN\0' and binary_length%4==0
    binary = data[28+json_length:]
    assert len(binary)==binary_length
    return gltf,binary


def positions(gltf,binary):
    for mesh in gltf['meshes']:
        for primitive in mesh['primitives']:
            accessor = gltf['accessors'][primitive['attributes']['POSITION']]
            view = gltf['bufferViews'][accessor['bufferView']]
            yield np.frombuffer(binary,dtype='<f4',count=accessor['count']*3,offset=view.get('byteOffset',0)).reshape(-1,3)


def test_glb_has_all_mesh_ids_and_explicit_vertical_placement(converted):
    root,result = converted
    gltf,binary = read_glb(root/'tiles/model.glb')
    assert len(gltf['meshes'])==5 and result['triangles']==100
    assert {n['extras']['sourceId'] for n in gltf['nodes']}=={'court','terrace','concave','multipart','sparse'}
    assert result['placement']['z_offset_m']==-25
    assert result['max_ecef_roundtrip_error_m']<.0001
    assert len(binary)>=gltf['buffers'][0]['byteLength']


def test_tile_box_contains_actual_float32_vertices(converted):
    root,_ = converted
    gltf,binary = read_glb(root/'tiles/model.glb')
    tile = json.loads((root/'tiles/tileset.json').read_text())
    b = tile['root']['boundingVolume']['box']
    center,half = np.array(b[:3]),np.array([b[3],b[7],b[11]])
    for points in positions(gltf,binary):
        enu = points.astype(float)[:,[0,2,1]]*np.array([1,-1,1])
        assert np.all(np.abs(enu-center)<=half+1e-10)
    assert tile['asset']['version']=='1.1'
    assert tile['geometricError']>0 and tile['root']['geometricError']==0
    assert tile['root']['content']['uri']=='model.glb'


def test_gltf_y_up_tile_z_up_ecef_matches_source_geodesy(converted):
    root,_ = converted
    source = json.loads((root/'models/model.lod1.city.json').read_text())
    world = np.array(source['vertices'])*source['transform']['scale']+source['transform']['translate']
    lon,lat = Transformer.from_crs(25828,4326,always_xy=True).transform(world[:,0],world[:,1])
    truth = np.column_stack(Transformer.from_crs(4979,4978,always_xy=True).transform(lon,lat,world[:,2]-25))
    tile = json.loads((root/'tiles/tileset.json').read_text())
    matrix = np.array(tile['root']['transform']).reshape(4,4).T
    gltf,binary = read_glb(root/'tiles/model.glb')
    recovered = []
    for p in positions(gltf,binary):
        enu = p.astype(float)[:,[0,2,1]]*np.array([1,-1,1])
        recovered.append(enu@matrix[:3,:3].T+matrix[:3,3])
    recovered = np.vstack(recovered)
    # Every source vertex is used by an exported face, and returns to its ECEF
    # coordinate within tolerance independently of the writer's own error field.
    assert all(np.linalg.norm(recovered-v,axis=1).min()<.0001 for v in truth)


def test_courtyard_is_not_filled_in_glb_roof(converted):
    root,_ = converted
    gltf,binary = read_glb(root/'tiles/model.glb')
    node = next(n for n in gltf['nodes'] if n['extras']['sourceId']=='court')
    mesh = gltf['meshes'][node['mesh']]
    values = list(positions({'meshes':[mesh],'accessors':gltf['accessors'],'bufferViews':gltf['bufferViews']},binary))[0]
    tri = values.reshape(-1,3,3)
    normal = np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    normal /= np.linalg.norm(normal,axis=1)[:,None]
    roof = normal[:,1]>.999
    areas = np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)/2
    # Projected UTM area is 336; Earth-surface area differs by the projection's
    # scale factor. Use independent geodesic area rather than loosening a test
    # to hide the difference, while still detecting any filled courtyard.
    from lodext.core.config import BuildConfig
    from lodext.io.footprints import read_footprints
    features,_ = read_footprints(BuildConfig.read(root/'inputs/build.json'),root/'inputs')
    polygon = next(f.geometry for f in features if f.id=='court').geoms[0]
    geod = Geod(ellps='WGS84')
    transform = Transformer.from_crs(25828,4326,always_xy=True)
    def ring_area(ring):
        x,y = np.array(ring.coords).T
        lon,lat = transform.transform(x,y)
        return abs(geod.polygon_area_perimeter(lon,lat)[0])
    expected = ring_area(polygon.exterior)-sum(ring_area(r) for r in polygon.interiors)
    assert areas[roof].sum()==pytest.approx(expected,abs=.01)


def test_single_tile_limit_and_existing_output_rejected(converted):
    root,_ = converted
    with pytest.raises(ValueError,match='already exists'):
        write_tiles(root/'models/model.lod1.city.json',root/'tiles',TileConfig(-25))
    with pytest.raises(ValueError,match='extent budget'):
        write_tiles(root/'models/model.lod1.city.json',root/'too-large',TileConfig(-25,max_span_m=1))
    assert not (root/'too-large').exists()


@pytest.mark.parametrize('offset',[float('nan'),True,float('inf')])
def test_vertical_offset_is_a_required_finite_explicit_value(offset):
    with pytest.raises(ValueError):
        TileConfig(offset)
