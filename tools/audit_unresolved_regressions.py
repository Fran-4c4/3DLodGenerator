"""List current unresolved parts that a reference build reconstructed.

The quality report is scanned incrementally because complete city reports can
contain hundreds of megabytes. LiDAR presence means the completed native run
retained original XYZ representatives inside the authoritative footprint;
``ground_candidates`` records coherent exterior XYZ examined around it. Source
classification labels are neither read nor reported.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _objects(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline='',encoding='utf-8') as stream:
        return {row['source_id']:row for row in csv.DictReader(stream) if row['kind']=='BuildingPart'}


def _quality_evidence(path: Path,targets: set[str]) -> dict[str,dict]:
    """Read bounded evidence for target objects from the indented report stream."""
    result={};current=None;inside_surfaces=False
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.startswith('      "key": "BuildingPart::'):
                current=line.split('"')[3].removeprefix('BuildingPart::')
                inside_surfaces=False
                if current in targets:result[current]={'candidate_roof_z':[]}
                continue
            if current not in targets:continue
            item=result[current]
            stripped=line.strip()
            if stripped.startswith('"ground_candidates":'):
                item['exterior_ground_candidates']=int(stripped.split(':',1)[1].rstrip(','))
            elif stripped=='"building_surfaces": {':inside_surfaces=True
            elif inside_surfaces and stripped.startswith('"original_representatives":'):
                item['inside_lidar_representatives']=int(stripped.split(':',1)[1].rstrip(','))
            elif inside_surfaces and line.startswith('            "roof_z":'):
                value=stripped.split(':',1)[1].rstrip(',')
                if value!='null':item['candidate_roof_z'].append(float(value))
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference_csv',type=Path)
    parser.add_argument('current_csv',type=Path)
    parser.add_argument('current_quality',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError(f'Output already exists: {args.output}')
    reference,current=_objects(args.reference_csv),_objects(args.current_csv)
    targets={part_id for part_id,row in current.items()
             if row['status']=='unresolved' and reference.get(part_id,{}).get('status')=='resolved'}
    evidence=_quality_evidence(args.current_quality,targets);rows=[]
    for part_id in sorted(targets):
        old=reference[part_id];now=current[part_id];item=evidence.get(part_id,{})
        roofs=item.get('candidate_roof_z',[]);inside=item.get('inside_lidar_representatives',0)
        rows.append({'part_id':part_id,'parent_id':now['parent_id'],'reference_method':old['method'],
                     'reference_ground_z':old['ground_z'],'reference_top_z':old['reconstructed_top_z'],
                     'current_ground_z':now['ground_z'],'inside_lidar_representatives':inside,
                     'exterior_ground_candidates':item.get('exterior_ground_candidates',0),
                     'candidate_roof_min_z':min(roofs) if roofs else '',
                     'candidate_roof_max_z':max(roofs) if roofs else '',
                     'has_inside_lidar':inside>0,'flags':now['flags']})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0]) if rows else ['part_id']
    with args.output.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'reference_resolved_current_unresolved':len(rows),
                      'with_inside_lidar':sum(row.get('has_inside_lidar',False) for row in rows),
                      'output':str(args.output)}))
    return 0


if __name__=='__main__':raise SystemExit(main())
