"""Create a bounded real-data regression campaign from known building parts.

The source GeoPackage is copied, never modified. Seed part IDs select their
complete explicit parent buildings. Every building intersecting the metric
context buffer is then retained with all its parts, so ground exclusion and
neighbour attribution see realistic surroundings. The generated configuration
uses project-relative paths and ``building_context`` terrain scope; it remains
an ordinary 3DLodExt build, not a special algorithm route.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3

from shapely.ops import unary_union

from lodext import strings
from lodext.core.config import BuildConfig
from lodext.io.footprints import quote,read_footprints


def _plain_part_id(value: str) -> str:
    """Accept a source part ID or its class-qualified quality-report key."""
    prefix=strings.BuildingObjectType.BUILDING_PART+strings.SourceObjectIdentity.IDENTITY_SEPARATOR
    return value[len(prefix):] if value.startswith(prefix) else value


def create_subset(config_path: Path,output_dir: Path,part_ids: list[str],context_m: float) -> tuple[Path,Path,dict]:
    """Copy a spatially complete parent subset and return paths plus summary.

    ``context_m`` is a nonnegative distance in the configured metric working
    CRS. Zero keeps the selected complete parents only. Existing output paths
    are rejected so a campaign can never overwrite a previous result silently.
    """
    if context_m<0:raise ValueError('context_m must be nonnegative metres')
    config_path=config_path.resolve();output_dir=output_dir.resolve()
    if output_dir.exists():raise ValueError('Output subset directory already exists')
    config=BuildConfig.read(config_path);root=config_path.parent
    features,_=read_footprints(config,root);parts={f.id:f for f in features if f.kind==strings.BuildingObjectType.BUILDING_PART}
    requested={_plain_part_id(value) for value in part_ids};unknown=requested-parts.keys()
    if unknown:raise ValueError('Unknown part IDs: '+', '.join(sorted(unknown)))
    seed_parents={parts[value].parent_id for value in requested}
    parents={f.id:f for f in features if f.kind==strings.BuildingObjectType.BUILDING}
    seed_geometry=unary_union([parents[parent].geometry for parent in seed_parents]);context=seed_geometry.buffer(context_m)
    retained=set(seed_parents)
    for feature in features:
        if feature.geometry is None or feature.geometry.is_empty:continue
        parent=feature.id if feature.kind==strings.BuildingObjectType.BUILDING else feature.parent_id
        if feature.geometry.intersects(context):retained.add(parent)
    source=(root/config.footprints).resolve();output_dir.mkdir(parents=True);gpkg=output_dir/'footprints.gpkg';shutil.copy2(source,gpkg)
    with sqlite3.connect(gpkg) as connection:
        placeholders=','.join('?' for _ in retained)
        connection.execute(f'DELETE FROM {quote(config.parts_layer)} WHERE {quote(strings.SourceObjectIdentity.BUILDING_ID)} NOT IN ({placeholders})',tuple(sorted(retained)))
        connection.execute(f'DELETE FROM {quote(config.buildings_layer)} WHERE {quote(strings.SourceObjectIdentity.BUILDING_ID)} NOT IN ({placeholders})',tuple(sorted(retained)))
        connection.commit();connection.execute('VACUUM')
    payload=deepcopy(json.loads(config_path.read_text(encoding=strings.TextFileEncoding.UTF8)))
    payload['dataset_id']=config.dataset_id+'-case-subset';payload['footprints']='footprints.gpkg'
    payload['lidar']=[Path(os.path.relpath((root/path).resolve(),output_dir)).as_posix() for path in config.lidar]
    payload.setdefault('ground',{})['surface_scope']='building_context'
    regions=payload.get('roof_regions')
    if regions and regions.get('object_ids') is not None:
        included={f.key for f in features if (f.id if f.kind==strings.BuildingObjectType.BUILDING else f.parent_id) in retained}
        regions['object_ids']=[key for key in regions['object_ids'] if key in included]
        if not regions['object_ids']:regions['enabled']=False;regions['object_ids']=None
    generated=output_dir/'build.json';generated.write_text(json.dumps(payload,indent=2)+'\n',encoding=strings.TextFileEncoding.UTF8)
    checked=BuildConfig.read(generated);subset,_=read_footprints(checked,output_dir)
    summary={'requested_parts':sorted(requested),'seed_parents':sorted(seed_parents),'retained_parents':len(retained),
             'retained_buildings':sum(f.kind==strings.BuildingObjectType.BUILDING for f in subset),
             'retained_parts':sum(f.kind==strings.BuildingObjectType.BUILDING_PART for f in subset),'context_m':context_m}
    (output_dir/'subset.json').write_text(json.dumps(summary,indent=2)+'\n',encoding=strings.TextFileEncoding.UTF8)
    return gpkg,generated,summary


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path,help='Source build configuration')
    parser.add_argument('--output',type=Path,required=True,help='New subset directory')
    parser.add_argument('--part-id',action='append',required=True,help='Seed source part ID or BuildingPart:: key; repeatable')
    parser.add_argument('--context-m',type=float,default=30.0,help='Metric context buffer around complete seed parents (default: 30)')
    args=parser.parse_args();gpkg,config,summary=create_subset(args.config,args.output,args.part_id,args.context_m)
    print(json.dumps({'footprints':str(gpkg),'config':str(config),**summary}))
    return 0


if __name__=='__main__':raise SystemExit(main())
