"""Original small surface controls, alongside the existing building regression."""
from lodext import strings
from pathlib import Path
import sqlite3
import struct


def create_surface_demo(output):
    """Create a NEW local dataset, not a survey or a completed connected scene."""
    import laspy
    import numpy as np
    from pyproj import CRS
    from shapely import intersects_xy, to_wkb
    from shapely.geometry import Polygon, box
    from .demo import create_demo
    from .pipeline import dump

    output = Path(output)
    create_demo(output)
    x0, y0, epsg = 500000.0, 3100000.0, 25828
    road = Polygon([(x0+x, y0+y) for x, y in
                    [(0,-12),(13,-12),(26,-12),(26,-9),(26,-6),(13,-6),(0,-6),(0,-9)]])
    surfaces = [("slope", strings.SurfaceObjectClass.ROAD, road), ("hill", strings.SurfaceObjectClass.TERRAIN, box(x0,y0+30,x0+10,y0+40)),
                ("forest-area", strings.SurfaceObjectClass.FOREST, box(x0+20,y0+30,x0+30,y0+40)),
                ("pond", strings.SurfaceObjectClass.WATER, box(x0+50,y0+30,x0+60,y0+40))]
    with sqlite3.connect(output/strings.SyntheticInputFiles.FOOTPRINTS) as connection:
        connection.execute("CREATE TABLE surfaces (fid INTEGER PRIMARY KEY,surface_id TEXT NOT NULL,surface_class TEXT NOT NULL,geom POLYGON,UNIQUE(surface_class,surface_id))")
        connection.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) VALUES (?,?,?,?,?,?,?,?)",
                           (strings.GeoPackageLayers.SURFACES, "features", strings.GeoPackageLayers.SURFACES, x0, y0-12, x0+60, y0+40, epsg))
        connection.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)", (strings.GeoPackageLayers.SURFACES, strings.GeoPackageGeometryFields.GEOM, "POLYGON", epsg, 0, 0))
        for identifier, kind, geometry in surfaces:
            blob = b"GP\x00\x01" + struct.pack("<i", epsg) + to_wkb(geometry)
            connection.execute("INSERT INTO surfaces (surface_id,surface_class,geom) VALUES (?,?,?)", (identifier, kind, blob))
    points, classes = [], []
    for _, kind, geometry in surfaces:
        left, bottom, right, top = geometry.bounds
        step = .5 if kind == strings.SurfaceObjectClass.ROAD else 1.0
        xx, yy = np.meshgrid(np.arange(left, right+step/2, step), np.arange(bottom, top+step/2, step))
        xx, yy = xx.ravel(), yy.ravel()
        inside = intersects_xy(geometry, xx, yy)
        for x, y in zip(xx[inside], yy[inside]):
            if kind == strings.SurfaceObjectClass.ROAD:
                z = 25 + .1*(x-x0)
            elif kind == strings.SurfaceObjectClass.TERRAIN:
                z = 25 + max(0, 4 - .8*(abs(x-x0-5)+abs(y-y0-35)))
            elif kind == strings.SurfaceObjectClass.FOREST:
                z = 26 + .05*(x-x0-20)
            else:
                z = 24.0
            points.append((x, y, z))
            classes.append(9 if kind == strings.SurfaceObjectClass.WATER else 2)
            if kind == strings.SurfaceObjectClass.FOREST:
                points.append((x, y, z+10))
                classes.append(5)
    # Nonselected-class extent controls make header coverage explicit without
    # contributing any ground or water elevations.
    points += [(x0-2, y0-14, 0), (x0+62, y0+42, 0)]
    classes += [7, 7]
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales, header.offsets = [.001]*3, [x0, y0, 0]
    header.add_crs(CRS.from_epsg(epsg))
    cloud = laspy.LasData(header)
    values = np.asarray(points)
    cloud.x, cloud.y, cloud.z = values.T
    cloud.classification = np.asarray(classes, dtype=np.uint8)
    cloud.write(output/"surfaces.las")
    dump(output/strings.SyntheticInputFiles.SURFACE_CONFIG, {strings.ConfigurationEnvelopeFields.VERSION: strings.InputContractVersion.CONFIG_VERSION, strings.SurfaceConfigurationFields.SURFACE_CONTRACT: strings.InputContractVersion.SURFACE_CONTRACT_VERSION,
          strings.DatasetIdentityFields.DATASET_ID: "synthetic-surfaces", strings.GeospatialInputFields.POLYGONS: strings.SyntheticInputFiles.FOOTPRINTS,
          strings.GeospatialInputFields.LIDAR: ["surfaces.las"], strings.GeospatialInputFields.WORKING_EPSG: epsg, strings.GeospatialInputFields.VERTICAL_REFERENCE: strings.VerticalReferenceDeclaration.LOCAL_RELATIVE})
    dump(output/"surface-truth.json", {strings.SyntheticControlFields.DESCRIPTION: "Original synthetic controls, not surveyed data",
          strings.SurfaceObjectClass.ROAD: {strings.PolygonFootprintFields.AREA_M2: road.area, "minimum_z": 25, "maximum_z": 27.6},
          strings.SurfaceObjectClass.TERRAIN: {strings.PolygonFootprintFields.AREA_M2: 100, "peak_xyz": [x0+5, y0+35, 29]},
          strings.SurfaceObjectClass.FOREST: {strings.PolygonFootprintFields.AREA_M2: 100, "minimum_z": 26, "maximum_z": 26.5},
          strings.SurfaceObjectClass.WATER: {strings.PolygonFootprintFields.AREA_M2: 100, "level_z": 24}})
