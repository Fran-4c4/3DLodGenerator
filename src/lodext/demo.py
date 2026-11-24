"""Create small licensed synthetic inputs for the public first-run tutorial."""
from lodext import strings
import json
import math
from pathlib import Path
import sqlite3
import struct


def create_demo(output):
    """Write original building controls and runnable local-file configurations.

    output must be new. Generate canonical GPKG identities, a flat metre-valued
    DTM, classified LAS observations and separate known-height/LoD0 settings.
    Include courtyards, a low terrace, concavity, disconnected components and
    sparse support. truth.json records generator dimensions independently of
    estimation. Coordinates/heights are synthetic, not surveyed/datum control;
    no reconstruction is run or pre-existing input/output modified here.
    """
    from .io.native import configure_native_environment
    configure_native_environment()
    import laspy
    import numpy as np
    from pyproj import CRS
    import rasterio
    from rasterio.transform import from_origin
    from shapely import contains_xy,to_wkb
    from shapely.geometry import Polygon,MultiPolygon,box
    from shapely.ops import unary_union
    from .pipeline import dump
    output = Path(output)
    if output.exists():
        raise ValueError("Demo directory already exists; choose a new location")
    output.mkdir(parents=True,exist_ok=False)
    x0,y0 = 500000.0,3100000.0
    def shifted(coords):
        """Translate local fixture XY into its declared metric source coordinates."""
        return [(x+x0,y+y0) for x,y in coords]
    court = Polygon(shifted([(0,0),(20,0),(20,20),(0,20)]),[shifted([(6,6),(6,14),(14,14),(14,6)])])
    terrace = box(x0+20,y0,x0+26,y0+20)
    concave = Polygon(shifted([(40,0),(55,0),(55,5),(45,5),(45,20),(40,20)]))
    multipart = MultiPolygon([box(x0+70,y0,x0+76,y0+6),box(x0+80,y0,x0+86,y0+6)])
    sparse = box(x0+100,y0,x0+103,y0+2)
    # Real geometry/height truth belongs to this generator, independently of
    # the later estimator, with deterministic class-6 roof samples at ~5 pts/m².
    parts = [("court","b-court",court,6.0,2),("terrace","b-court",terrace,1.8,1),
             ("concave","b-concave",concave,8.0,2),("multipart","b-multi",multipart,5.0,1),
             ("sparse","b-sparse",sparse,4.0,1)]
    parents = {identifier:unary_union([geom for _,parent,geom,_,_ in parts if parent==identifier])
               for identifier in sorted({p[1] for p in parts})}
    srid = 25828
    with sqlite3.connect(output/strings.SyntheticInputFiles.FOOTPRINTS) as connection:
        connection.executescript("""
        PRAGMA application_id=1196444487;
        PRAGMA user_version=10300;
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL,srs_id INTEGER NOT NULL PRIMARY KEY,organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,definition TEXT NOT NULL,description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY,data_type TEXT NOT NULL,identifier TEXT UNIQUE,description TEXT DEFAULT '',last_change DATETIME NOT NULL DEFAULT '2026-11-13T00:00:00.000Z',min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL,column_name TEXT NOT NULL,geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,z TINYINT NOT NULL,m TINYINT NOT NULL,PRIMARY KEY(table_name,column_name));
        CREATE TABLE buildings (fid INTEGER PRIMARY KEY,building_id TEXT NOT NULL UNIQUE,geom MULTIPOLYGON);
        CREATE TABLE building_parts (fid INTEGER PRIMARY KEY,part_id TEXT NOT NULL UNIQUE,building_id TEXT NOT NULL,geom MULTIPOLYGON,storeys_above INTEGER,storeys_below INTEGER,reference_height_m REAL,reference_height_method TEXT,reference_height_source TEXT);
        """)
        connection.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",[
            ("Undefined Cartesian",-1,"NONE",-1,"undefined",None),
            ("Undefined geographic",0,"NONE",0,"undefined",None),
            ("WGS 84",4326,"EPSG",4326,CRS.from_epsg(4326).to_wkt(),None),
            ("ETRS89 / UTM zone 28N",srid,"EPSG",srid,CRS.from_epsg(srid).to_wkt(),None)])
        for layer in (strings.GeoPackageLayers.BUILDINGS,strings.GeoPackageLayers.BUILDING_PARTS):
            connection.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) VALUES (?,?,?,?,?,?,?,?)",(layer,"features",layer,x0,y0,x0+103,y0+20,srid))
            connection.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",(layer,strings.GeoPackageGeometryFields.GEOM,"MULTIPOLYGON",srid,0,0))
        def encoded(geom):
            """Wrap synthetic polygon WKB in a standard XY GeoPackage header."""
            multi = geom if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else MultiPolygon([geom])
            return b"GP\x00\x01"+struct.pack("<i",srid)+to_wkb(multi)
        for identifier,geom in parents.items():
            connection.execute("INSERT INTO buildings (building_id,geom) VALUES (?,?)",(identifier,encoded(geom)))
        for identifier,parent,geom,height,storeys in parts:
            connection.execute("INSERT INTO building_parts (part_id,building_id,geom,storeys_above,storeys_below,reference_height_m,reference_height_method,reference_height_source) VALUES (?,?,?,?,?,?,?,?)",(identifier,parent,encoded(geom),storeys,0,height,"synthetic_truth","3DLodExt synthetic tutorial"))
    left,bottom,right,top = x0-40,y0-40,x0+145,y0+65
    resolution = 0.5
    with rasterio.open(output/strings.SyntheticInputFiles.DTM,"w",driver="GTiff",width=round((right-left)/resolution),height=round((top-bottom)/resolution),count=1,dtype="float32",crs=f"EPSG:{srid}",transform=from_origin(left,top,resolution,resolution),nodata=-9999,compress="deflate") as raster:
        raster.write(np.full((raster.height,raster.width),25.0,dtype="float32"),1)
    obstacles = unary_union([p[2] for p in parts])
    gx,gy = np.meshgrid(np.arange(left+1,right,2),np.arange(bottom+1,top,2))
    gx,gy = gx.ravel(),gy.ravel()
    keep = ~contains_xy(obstacles,gx,gy)
    xs,ys,zs,classes = list(gx[keep]),list(gy[keep]),[25.0]*int(keep.sum()),[2]*int(keep.sum())
    spacing = 1/math.sqrt(5)
    for identifier,_,geom,height,_ in parts:
        if identifier=="sparse":
            xx,yy = np.asarray([x0+101,x0+102]),np.asarray([y0+1,y0+1])
        else:
            a,b,c,d = geom.bounds
            xx,yy = np.meshgrid(np.arange(a+spacing/2,c,spacing),np.arange(b+spacing/2,d,spacing))
            xx,yy = xx.ravel(),yy.ravel()
            inside = contains_xy(geom,xx,yy)
            xx,yy = xx[inside],yy[inside]
        xs.extend(xx);ys.extend(yy);zs.extend([25+height]*len(xx));classes.extend([6]*len(xx))
    header = laspy.LasHeader(point_format=6,version="1.4")
    header.scales = [0.001]*3
    header.offsets = [x0,y0,0]
    header.add_crs(CRS.from_epsg(srid))
    cloud = laspy.LasData(header)
    cloud.x,cloud.y,cloud.z,cloud.classification = np.asarray(xs),np.asarray(ys),np.asarray(zs),np.asarray(classes,dtype=np.uint8)
    cloud.write(output/strings.SyntheticInputFiles.CLOUD)
    config = {strings.ConfigurationEnvelopeFields.VERSION:strings.InputContractVersion.CONFIG_VERSION,strings.BuildConfigurationFields.CONTRACT_VERSION:strings.InputContractVersion.BUILDING_CONTRACT_VERSION,strings.DatasetIdentityFields.DATASET_ID:"synthetic-first-run", strings.BuildConfigurationFields.GEOMETRY_MODE:strings.BuildingGeometryMode.PARTS, strings.GeospatialInputFields.FOOTPRINTS:strings.SyntheticInputFiles.FOOTPRINTS,strings.GeospatialInputFields.DTM:strings.SyntheticInputFiles.DTM,strings.GeospatialInputFields.LIDAR:[strings.SyntheticInputFiles.CLOUD],strings.GeospatialInputFields.WORKING_EPSG:srid,strings.GeospatialInputFields.VERTICAL_REFERENCE:strings.VerticalReferenceDeclaration.LOCAL_RELATIVE,strings.BuildConfigurationFields.LODS:[0,1],strings.BuildConfigurationFields.EXTERNAL_HEIGHT_FALLBACK:True}
    dump(output/strings.SyntheticInputFiles.BUILD_CONFIG,config)
    # Direct-point variant: same source footprints/cloud, no required raster.
    direct={k:v for k,v in config.items() if k!=strings.GeospatialInputFields.DTM}
    direct['roof_classes']=None  # This original synthetic cloud explicitly labels roofs as class 6.
    dump(output/'build.lidar.json',direct)
    dump(output/strings.SyntheticInputFiles.KNOWN_CONFIG,{**config,strings.GeospatialInputFields.LIDAR:[],strings.BuildConfigurationFields.HEIGHT_SOURCE:strings.BuildingHeightSource.KNOWN,strings.BuildConfigurationFields.EXTERNAL_HEIGHT_FALLBACK:False})
    dump(output/strings.SyntheticInputFiles.LOD0_CONFIG,{**config,strings.GeospatialInputFields.LIDAR:[],strings.BuildConfigurationFields.LODS:[0],strings.BuildConfigurationFields.EXTERNAL_HEIGHT_FALLBACK:False})
    dump(output/strings.SyntheticInputFiles.TRUTH,{strings.SyntheticControlFields.DESCRIPTION:"Synthetic fixture, not surveyed data or an absolute vertical datum", strings.SyntheticControlFields.BASE_Z_M:25,strings.HeightTrialFields.PARTS:{identifier:{strings.BuildingHeightFields.HEIGHT_M:height,strings.PolygonFootprintFields.AREA_M2:geom.area,strings.SyntheticControlFields.COMPONENT_COUNT:len(geom.geoms) if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else 1} for identifier,_,geom,height,_ in parts}})
