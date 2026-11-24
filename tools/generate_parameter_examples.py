"""Generate original, runnable parameter comparisons using the public pipelines.

--output is required and must be new. Each family shares byte-identical inputs
between variants; only the named settings change. Fixture values below describe
controls, never replace engine defaults. Native run reports remain in _runs/;
publish inputs/, configs/, models/, evidence/, summary.json and presentation.json.
No supplied dataset, existing output or engine setting is changed.

Presentation contract (display only, consumed by examples/parameters/preview.html):
title is a human label; extent is [minX,minY,maxX,maxY] in local metres;
min_z/max_z define the common local-Z camera envelope. cases carry id/title,
meshes (source ID/type plus
flat local XYZ triangle coordinates), selected_xyz and rejected_xyz (actual LAS
locations relative to origin), selected_classes/rejected_classes (parallel LAS
class codes for those positions), support (closed XY roof-selection rings), metrics
(short display text), and status. footprints are original closed local XY rings.
origin is source XYZ subtracted uniformly, with no height exaggeration. Empty
meshes mean no geometry at that level, not a zero-height substitute.

summary.json records actual statuses, geometry/evidence metrics and SHA-256 input
hashes. evidence/*.json contains the engine's object records and summary, without
local machine file locations. truth.json holds independent synthetic dimensions.
All numbers, labels, units and fields belong to these teaching fixtures only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import struct
import zipfile


def dump(path, value):
    """Write UTF-8 fixture/transport JSON; parent must already be owned."""
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def parts_for(name):
    """Return local polygons and independent heights/storeys for one family.

    A tuple is (part ID, XY polygon in metres, height above ground in metres,
    optional storeys, optional supplied height). Parentage is explicit and shared.
    """
    from shapely.geometry import box
    if name == "density":
        return [("terrace", box(0, 0, 2, 1), 2., None, None)]
    if name == "auxiliary":
        return [("main", box(0, 0, 6, 6), 6., 2, 6.),
                ("sparse", box(7, 0, 9, 1), 4., None, 4.)]
    if name == "floor-reference":
        return [("main", box(0, 0, 6, 6), 4., 2, None),
                ("sparse", box(7, 0, 9, 1), 2., 1, None),
                ("terrace", box(7, 3, 9, 5), 2., 1, None)]
    if name == "lod":
        return [("main", box(0, 0, 8, 8), 6., 2, None),
                ("terrace", box(8, 0, 11, 5), 2., 1, None)]
    return [("main", box(0, 0, 10, 10), 6., None, None)]


def write_inputs(directory, name):
    """Create canonical GPKG, LAS, DTM and truth in a new directory.

    EPSG:25828 and the local Z base 25 m are synthetic example coordinates.
    Roof grids are nominal 5 points/m²; background ground uses a separate 2 m
    grid. Border contamination replaces returns at existing XY, never duplicates
    a point. Sparse bodies deliberately have two observations; density has eight.
    """
    from lodext.demo import create_demo
    from shapely.geometry import MultiPolygon, Point, Polygon, box
    from shapely.affinity import translate
    from shapely.ops import unary_union
    from shapely import contains_xy, intersects_xy, to_wkb
    import numpy as np
    import laspy
    from pyproj import CRS
    import rasterio
    from rasterio.transform import from_origin
    from datetime import date

    create_demo(directory)
    for file in ("build.json", "build.known.json", "build.lod0.json", "truth.json"):
        (directory/file).unlink()
    parts=parts_for(name)
    features=[]
    if name == "water":
        features=[("pond", "Water", box(0,0,8,8))]
    elif name == "road":
        bottom=[(0,0),(2,.2),(4,-.1),(6,.3),(8,.1),(10,.4)]
        top=[(10,5.7),(8,6),(6,5.6),(4,6.2),(2,5.8),(0,6)]
        features=[("road", "Road", Polygon(bottom+top))]
    if features: parts=[]
    occupied=unary_union([p[1] for p in parts])
    with sqlite3.connect(directory/"footprints.gpkg") as db:
        db.execute("DELETE FROM building_parts")
        db.execute("DELETE FROM buildings")
        def blob(geom):
            moved=translate(geom,xoff=500000,yoff=3100000)
            multi=moved if moved.geom_type=="MultiPolygon" else MultiPolygon([moved])
            return b"GP\x00\x01"+struct.pack("<i",25828)+to_wkb(multi)
        if parts:
            db.execute("INSERT INTO buildings (building_id,geom) VALUES (?,?)",("example",blob(occupied)))
        for identifier, geom, height, storeys, reference in parts:
            db.execute("INSERT INTO building_parts (part_id,building_id,geom,storeys_above,reference_height_m,reference_height_method,reference_height_source) VALUES (?,?,?,?,?,?,?)",
                       (identifier,"example",blob(geom),storeys,reference,
                        "synthetic_control" if reference else None,
                        "Original parameter example" if reference else None))
        db.execute("UPDATE gpkg_contents SET min_x=499970,min_y=3099970,max_x=500040,max_y=3100040")
        if features:
            db.execute("CREATE TABLE surfaces (fid INTEGER PRIMARY KEY,surface_id TEXT,surface_class TEXT,geom MULTIPOLYGON)")
            db.execute("INSERT INTO gpkg_geometry_columns VALUES ('surfaces','geom','MULTIPOLYGON',25828,0,0)")
            db.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) VALUES ('surfaces','features','surfaces',499970,3099970,500040,3100040,25828)")
            for identifier,kind,geom in features:
                db.execute("INSERT INTO surfaces (surface_id,surface_class,geom) VALUES (?,?,?)",(identifier,kind,blob(geom)))
    dtm=np.full((140,140),25,dtype="float32")
    if name == "ground":
        # NoData extends four metres outside the building; the long search can
        # reach valid terrain, while a radius of two metres cannot.
        for row in range(140):
            for col in range(140):
                x,y=-30+(col+.5)*.5,40-(row+.5)*.5
                if occupied.distance(Point(x,y)) < 4:dtm[row,col]=-9999
    with rasterio.open(directory/"dtm.tif","w",driver="GTiff",width=140,height=140,count=1,dtype="float32",
                       crs="EPSG:25828",transform=from_origin(499970,3100040,.5,.5),nodata=-9999,compress="deflate") as dst:
        dst.write(dtm,1)
    points=[]
    classes=[]
    if parts:
        gx,gy=np.meshgrid(np.arange(-29,40,2.),np.arange(-29,40,2.))
        gx,gy=gx.ravel(),gy.ravel()
        free=~intersects_xy(occupied,gx,gy)
        for x,y in zip(gx[free],gy[free]):
            nearby=name in ("erosion","classes") and occupied.distance(Point(x,y))<1.5
            points.append((x,y,35. if nearby else 25.));classes.append(5 if nearby else 2)
        spacing=1/math.sqrt(5)
        for identifier,geom,height,_,_ in parts:
            if name=="density":
                xx,yy=np.meshgrid([.25,.75,1.25,1.75],[.25,.75]);xx,yy=xx.ravel(),yy.ravel()
            elif identifier=="sparse":
                xx,yy=np.array([7.5,8.5]),np.array([.5,.5])
            else:
                a,b,c,d=geom.bounds
                xx,yy=np.meshgrid(np.arange(a+spacing/2,c,spacing),np.arange(b+spacing/2,d,spacing))
                xx,yy=xx.ravel(),yy.ravel();keep=contains_xy(geom,xx,yy);xx,yy=xx[keep],yy[keep]
            for x,y in zip(xx,yy):
                z,cls=25+height,6
                if name in ("erosion","classes") and geom.boundary.distance(Point(x,y))<1.5:
                    z,cls=35.,5
                points.append((x,y,z));classes.append(cls)
    elif name=="water":
        for x in np.arange(0,8.1,.5):
            for y in np.arange(0,8.1,.5):
                points.append((x,y,25. if x>6 else 24.));classes.append(9)
    else:
        geom=features[0][2]
        wobble=[0,.10,-.07,.02,.13,-.11,.04,-.08,.09,-.10,.05,-.04]
        for i,(x,y) in enumerate(list(geom.exterior.coords)[:-1]):
            points.append((x,y,25+.1*x+.03*y+wobble[i]+(3 if i==3 else 0)));classes.append(11)
    # Nonselected class-7 extent controls satisfy header context, without
    # providing invented support to the lifting calculation.
    points.extend([(-3.125,-3.125,25),(14.125,14.125,25)]);classes.extend([7,7])
    values=np.asarray(points,dtype=float)
    assert len({(round(x,6),round(y,6)) for x,y,_ in values})==len(values)
    header=laspy.LasHeader(point_format=6,version="1.4")
    header.scales=[.001]*3;header.offsets=[500000,3100000,0]
    header.creation_date=date(2026,1,1);header.add_crs(CRS.from_epsg(25828))
    cloud=laspy.LasData(header)
    cloud.x,cloud.y,cloud.z=values[:,0]+500000,values[:,1]+3100000,values[:,2]
    cloud.classification=np.asarray(classes,dtype="uint8");cloud.write(directory/"cloud.las")
    truth={"base_z_m":25,"parts":{i:{"height_m":h,"area_m2":g.area} for i,g,h,_,_ in parts},
           "description":"Original synthetic controls, not surveyed data",
           "roof_nominal_points_m2":5,"ground_grid_spacing_m":2,
           "surface_control":"Water: 24 m with a high tail at 25 m; road: 25 + .1x + .03y, boundary noise up to 0.13 m and one +3 m spike" if features else None}
    dump(directory/"truth.json",truth)
    return parts,features,cloud


def variants_for(name):
    """Name the explicit parameter overrides; omitted options use engine owners."""
    return {
        "erosion":[("none","0 m uncertainty",{"building_surfaces":{"registration_m":0}}),
                   ("half","0.25 m uncertainty",{"building_surfaces":{"registration_m":.25}}),
                   ("one","0.5 m uncertainty",{"building_surfaces":{"registration_m":.5}})],
        "classes":[("all","Original LAS labels",{"roof_classes":None}),
                   ("roof","Same XYZ, alternative labels",{"roof_classes":None,"lidar":["../inputs/alternative-labels.las"]})],
        "density":[("count","Count only",{"height":{"min_density_points_m2":None}}),
                   ("density","Count or density",{"height":{"min_density_points_m2":3}})],
        "auxiliary":[("off","Fallback disabled",{"external_height_fallback":False}),
                     ("on","Known-height fallback",{"external_height_fallback":True})],
        "floor-reference":[("standard","Reference minimum 2.5 m",{"height":{"min_floor_height_m":2.5}}),
                           ("lower","Reference minimum 1.5 m",{"height":{"min_floor_height_m":1.5}})],
        "ground":[("short","Ground search: 2 m",{"sampling":{"ground_buffers_m":[2]}}),
                  ("expand","Ground search: 2, 6 m",{"sampling":{"ground_buffers_m":[2,6]}})],
        "lod":[("zero","LoD0",{"lods":[0]}),("one","LoD1",{"lods":[1]})],
        "water":[("low","Percentile 10",{"lifting":{"Water":{"percentile":10}}}),
                 ("high","Percentile 90",{"lifting":{"Water":{"percentile":90}}})],
        "road":[("raw","Raw elevations",{"road_filter_outliers":False,"road_flatten":False}),
                ("filter","Outliers filtered",{"road_filter_outliers":True,"road_flatten":False}),
                ("smooth","Smoothed road",{"road_filter_outliers":True,"road_flatten":True})],
    }[name]


def generate_family(root, name, title):
    """Run all variants, retaining partial outcomes and portable user artefacts."""
    import numpy as np
    import laspy
    from shapely import contains_xy
    from lodext.pipeline import run_build
    from lodext.surface_pipeline import run_surfaces
    from lodext.export.tiles import surfaces, triangulate_surface
    from lodext.io.sampling import roof_support
    from lodext.core.config import SamplingConfig

    root.mkdir()
    inputs=root/"inputs"
    parts,features,cloud=write_inputs(inputs,name)
    if name=="classes":
        alternative=laspy.read(inputs/"cloud.las")
        alternative.classification=np.random.default_rng(17).integers(0,32,len(alternative.points),dtype=np.uint8)
        alternative.write(inputs/"alternative-labels.las")
    for folder in ("configs","models","evidence","_runs"):(root/folder).mkdir()
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    base={"config_version":"1","dataset_id":"parameter-"+name,"working_epsg":25828,"vertical_reference":"local_relative",
          "lidar":["../inputs/cloud.las"]}
    if features:
        base.update(surface_contract="0.1",polygons="../inputs/footprints.gpkg",radius_m=.04)
    else:
        base.update(contract_version="0.2",geometry_mode="parts",footprints="../inputs/footprints.gpkg",
                    dtm="../inputs/dtm.tif",lods=[1],sampling={"erode_m":0})
    cases=[];results=[]
    xyz=np.column_stack((np.asarray(cloud.x)-500000,np.asarray(cloud.y)-3100000,np.asarray(cloud.z)-25))
    all_classes=np.asarray(cloud.classification)
    shapes=[g for _,g,_,_,_ in parts] if parts else [g for _,_,g in features]
    bounds=np.asarray([g.bounds for g in shapes]);extent=[float(bounds[:,0].min()-2),float(bounds[:,1].min()-2),float(bounds[:,2].max()+2),float(bounds[:,3].max()+2)]
    visible=(xyz[:,0]>=extent[0])&(xyz[:,0]<=extent[2])&(xyz[:,1]>=extent[1])&(xyz[:,1]<=extent[3])
    for identifier,label,overrides in variants_for(name):
        case_classes=np.asarray(laspy.read(inputs/"alternative-labels.las").classification) if name=="classes" and identifier=="roof" else all_classes
        config={**base,**overrides}
        if "sampling" in overrides:config["sampling"]={**base.get("sampling",{}),**overrides["sampling"]}
        path=root/"configs"/(identifier+".json");dump(path,config)
        summary=(run_surfaces if features else run_build)(path,root/"_runs"/identifier)
        quality=json.loads((root/"_runs"/identifier/"quality.json").read_text(encoding="utf-8"))
        records=[r for r in quality["objects"] if r.get("kind")!="Building"]
        level=0 if config.get("lods")==[0] else 1
        model_name="model.surfaces.city.json" if features else f"model.lod{level}.city.json"
        source=root/"_runs"/identifier/model_name
        target=root/"models"/(identifier+".city.json");shutil.copy2(source,target)
        shutil.copy2(root/"_runs"/identifier/"objects.csv",root/"evidence"/(identifier+".csv"))
        dump(root/"evidence"/(identifier+".json"),{"summary":summary,"objects":records})
        model=json.loads(source.read_text(encoding="utf-8"))
        vertices=np.asarray(model["vertices"],dtype=float).reshape(-1,3)
        world=vertices*model["transform"]["scale"]+model["transform"]["translate"]
        meshes=[]
        for key,obj in model["CityObjects"].items():
            indices=[i for geom in obj.get("geometry",[]) for face in surfaces(geom) for i in triangulate_surface(face,world)]
            if indices:
                meshes.append({"id":key,"type":obj["type"],"positions":np.round(world[indices]-[500000,3100000,25],6).ravel().tolist()})
        selected=np.zeros(len(xyz),dtype=bool);support=[]
        if parts:
            sampling=SamplingConfig(**config.get("sampling",{}))
            for _,g,_,_,_ in parts:
                area=g  # Current building attribution uses complete footprints, without fixed inward erosion.
                selected|=contains_xy(area,xyz[:,0],xyz[:,1])
                for poly in (list(area.geoms) if area.geom_type=="MultiPolygon" else [area]):
                    support.append(list(poly.exterior.coords))

            if level==0:
                selected[:]=False
                support=[]
        else:
            selected=all_classes==(9 if name=="water" else 11)
        row={"id":identifier,"title":label,"settings":overrides,"status":summary["status"],"objects":records}
        results.append(row)
        if parts:
            metrics="\n".join(f'{r["source_id"]}: '+(f'{r["height_m"]:g} m' if r.get("height_m") is not None else 'unresolved')+f' · {r.get("method")} · {r.get("n_points",0)} points' for r in records)
        else:
            r=records[0];boundary=[z for c in r["components"] for z in c["boundary_z"]]
            fit=r["components"][0]["road_fit"]
            metrics=(f'Level Z: {r["water_level_z"]:g} m · {r["sample_points"]} points' if name=="water" else
                     f'Z: {min(boundary):.2f}–{max(boundary):.2f} m\n{fit["status"]} · {fit.get("changed_vertices",0)} vertices changed')
        cases.append({"id":identifier,"title":label,"status":summary["status"],"meshes":meshes,
                      "selected_xyz":np.round(xyz[visible&selected],4).ravel().tolist(),
                      "selected_classes":case_classes[visible&selected].tolist(),
                      "rejected_xyz":np.round(xyz[visible&~selected],4).ravel().tolist(),
                      "rejected_classes":case_classes[visible&~selected].tolist(),"support":support,
                      "metrics":metrics})
        print(f'{name}/{identifier}: {summary["status"]}',flush=True)
    assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    dump(root/"summary.json",{"family":name,"title":title,"input_sha256":hashes,"cases":results})
    footprints=[list(g.exterior.coords) for g in shapes]
    local_z=xyz[visible,2]
    dump(root/"presentation.json",{"title":title,"origin":[500000,3100000,25],"extent":extent,
                                    "min_z":float(min(-.1,local_z.min())),"max_z":float(max(.1,local_z.max())),
                                    "footprints":footprints,"cases":cases})
    with zipfile.ZipFile(root/"example.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for folder in ("inputs","configs","models","evidence"):
            for p in (root/folder).iterdir():archive.write(p,str(p.relative_to(root)))
        for name2 in ("summary.json","presentation.json"):archive.write(root/name2,name2)
        archive.write(Path(__file__).resolve().parents[1]/"LICENSE","LICENSE")
    return results


def generate(output):
    """Build all controls under a new root; preserve existing runs on failure."""
    output=Path(output).resolve()
    if output.exists():raise ValueError("Choose a new output directory")
    output.mkdir(parents=True)
    families=[("erosion","Boundary uncertainty and edge contamination"),("classes","Building results are independent of LAS labels"),
              ("density","Small bodies: count and density"),("auxiliary","Supplied-height fallback"),
              ("floor-reference","Storey-height reference"),("ground","Finding valid DTM ground"),
              ("lod","LoD0 and LoD1"),("water","Water elevation percentile"),("road","Road filtering and smoothing")]
    for name,title in families:generate_family(output/name,name,title)
    dump(output/"catalog.json",{"families":[{"id":name,"title":title} for name,title in families]})


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True,help="New parameter-example root directory")
    generate(parser.parse_args().output)
