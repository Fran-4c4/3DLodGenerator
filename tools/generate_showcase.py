"""Generate original GIS documentation inputs and ACTUAL reconstructed models.

This is a documentation fixture, not a scene-stitching implementation or a
survey. Dimensions/elevations below own this synthetic neighbourhood only.
Roof observations use nominal 5 points/m² (1/sqrt(5) m spacing); ground uses
a separate 2 m grid plus explicit boundary controls for narrow parcels.
A controlled high tail illustrates height estimation.
--output is REQUIRED and must not exist; previous runs and input data are never
replaced. The generator creates its own inputs, then invokes both public engines.
The presentation combines their outputs without moving vertices or stitching.

presentation.json is a display transport, consumed only by the example viewer:
meshes carry source object IDs/classes and flattened XYZ triangle coordinates
in metres after subtracting render_origin; no height scaling is allowed. points
uses parallel XYZ/class arrays of the actual generated cloud, clipped to extent.
map contains original XY polygon rings including closure, holes and components.
extent is the local XY domain; render_origin is the shared source XYZ origin.
Density/spacing/control fields describe this fixture, never engine defaults.
showcase.json stores actual pipeline summaries and the controlled high-tail ID.
truth.json records independent generator heights/areas, not estimated results.
"""
from lodext import strings
import argparse
import json
import math
from pathlib import Path
import sqlite3
import struct


def generate(output):
    """Create original teaching inputs, run both engines and derive display data.

    output must be a new directory. Build synthetic polygons, nominal-density
    roof points, independent ground controls and a flat DTM, recording generated
    height truth separately. Invoke the public building/surface pipelines and
    require both stages complete before preparing triangulated presentation data.
    Display coordinates subtract a common origin without exaggeration or scene
    stitching. These are fixture dimensions/settings, not engine defaults or an
    accuracy benchmark. Only this newly created fixture is opened for writing;
    failed generation may leave its new directory for diagnosis.
    """
    import laspy
    import numpy as np
    from pyproj import CRS
    import rasterio
    from rasterio.transform import from_origin
    from shapely import contains_xy, intersects_xy, to_wkb
    from shapely.geometry import MultiPolygon, Polygon, box
    from shapely.ops import unary_union
    from lodext.demo import create_demo
    from lodext.pipeline import dump, run_build
    from lodext.surface_pipeline import run_surfaces
    from lodext.export.tiles import surfaces as faces, triangulate_surface

    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Showcase output must be a new directory")
    inputs = output/strings.ReconstructionRunFields.INPUTS
    create_demo(inputs)
    # Discard bootstrap-specific controls/configurations; they describe the
    # small tutorial rather than this newly generated neighbourhood.
    for name in (strings.SyntheticInputFiles.TRUTH, strings.SyntheticInputFiles.KNOWN_CONFIG, strings.SyntheticInputFiles.LOD0_CONFIG):
        (inputs/name).unlink()
    x0, y0, epsg, base = 500000., 3100000., 25828, 25.
    def shift(geom):
        from shapely.affinity import translate
        return translate(geom,xoff=x0,yoff=y0)
    domain = box(0,0,180,120)
    shore = [(82,0),(85,20),(81,40),(88,65),(84,90),(90,120)]
    far = [(x+11,y) for x,y in shore]
    water = Polygon(shore+list(reversed(far)))
    parks = [Polygon([(74,0),*shore,(74,120)]), Polygon([*far,(105,120),(105,0)])]
    roads = []
    for a,b in [(5,74),(106,176)]:
        rectangles = [box(a,y,b,y+6) for y in (28,70,108)]
        rectangles += [box(x,0,x+6,120) for x in ((22,55) if a==5 else (122,158))]
        roads.append(unary_union(rectangles))
    parts=[]
    number=0
    for left,right in [(5,20),(30,53),(63,72),(108,120),(130,156),(166,176)]:
        columns = [(left,right)] if right-left<18 else [(left,(left+right)/2-1),((left+right)/2+1,right)]
        for row in (3,39,81):
            for dy in (0,15):
                for a,b in columns:
                    number+=1
                    identifier=f'block-{number:02d}'
                    height=(6.,9.,12.)[number%3]
                    outer=box(a,row+dy,b,row+dy+10)
                    if number%7==0 and b-a>=10:
                        main=outer.difference(box(a+3,row+dy+3,b-3,row+dy+7))
                        parts.append((identifier+'-main',identifier,main,height,int(height/3)))
                    elif number%8==0 and b-a>=10:
                        parts.append((identifier+'-main',identifier,box(a,row+dy,b-3,row+dy+10),height,int(height/3)))
                        parts.append((identifier+'-terrace',identifier,box(b-3,row+dy,b,row+dy+6),1.8,1))
                    else:
                        parts.append((identifier+'-main',identifier,outer,height,int(height/3)))
    parents={b:unary_union([g for _,parent,g,_,_ in parts if parent==b]) for b in sorted({p[1] for p in parts})}
    occupied=unary_union(list(parents.values()))
    reserved=unary_union([occupied,water,*roads,*parks])
    surface_features=[('road-west',strings.SurfaceObjectClass.ROAD,roads[0]),('road-east',strings.SurfaceObjectClass.ROAD,roads[1]),('canal',strings.SurfaceObjectClass.WATER,water)]
    surface_features += [(f'bank-{i}',strings.SurfaceObjectClass.FOREST,g) for i,g in enumerate(parks)]
    for x in range(0,180,10):
        for y in range(0,120,10):
            patch=box(x,y,x+10,y+10).difference(reserved)
            if patch.is_empty or patch.area<.01:
                continue
            polys=[patch] if patch.geom_type==strings.PolygonGeometryType.POLYGON else list(patch.geoms)
            polys=[g for g in polys if g.geom_type==strings.PolygonGeometryType.POLYGON and g.area>.01]
            if polys:
                surface_features.append((f'ground-{x}-{y}',strings.SurfaceObjectClass.TERRAIN,unary_union(polys)))
    # Only this newly created fixture is edited. No supplied GeoPackage is opened
    # in write mode and no production/database connection is involved.
    with sqlite3.connect(inputs/strings.SyntheticInputFiles.FOOTPRINTS) as db:
        db.execute('DELETE FROM building_parts');db.execute('DELETE FROM buildings')
        def encoded(geom):
            geom=shift(geom)
            geom=geom if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else MultiPolygon([geom])
            return b'GP\x00\x01'+struct.pack('<i',epsg)+to_wkb(geom)
        for identifier,geom in parents.items():
            db.execute('INSERT INTO buildings (building_id,geom) VALUES (?,?)',(identifier,encoded(geom)))
        for identifier,parent,geom,height,storeys in parts:
            db.execute('INSERT INTO building_parts (part_id,building_id,geom,storeys_above,storeys_below,reference_height_m,reference_height_method,reference_height_source) VALUES (?,?,?,?,?,?,?,?)',
                       (identifier,parent,encoded(geom),storeys,0,height,'synthetic_truth','Original 3DLodExt neighbourhood control'))
        db.execute('CREATE TABLE surfaces (fid INTEGER PRIMARY KEY,surface_id TEXT,surface_class TEXT,geom MULTIPOLYGON)')
        db.execute('INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)',(strings.GeoPackageLayers.SURFACES,strings.GeoPackageGeometryFields.GEOM,'MULTIPOLYGON',epsg,0,0))
        db.execute('INSERT INTO gpkg_contents (table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) VALUES (?,?,?,?,?,?,?,?)',
                   (strings.GeoPackageLayers.SURFACES,'features',strings.GeoPackageLayers.SURFACES,x0,y0,x0+180,y0+120,epsg))
        db.execute("UPDATE gpkg_contents SET min_x=?,min_y=?,max_x=?,max_y=? WHERE table_name IN ('buildings','building_parts')",(x0,y0,x0+180,y0+120))
        for identifier,kind,geom in surface_features:
            db.execute('INSERT INTO surfaces (surface_id,surface_class,geom) VALUES (?,?,?)',(identifier,kind,encoded(geom)))
    with rasterio.open(inputs/strings.SyntheticInputFiles.DTM,'w',driver='GTiff',width=480,height=360,count=1,dtype='float32',
                       crs=f'EPSG:{epsg}',transform=from_origin(x0-30,y0+150,.5,.5),nodata=-9999,compress='deflate') as raster:
        raster.write(np.full((360,480),base,dtype='float32'),1)
    gx,gy=np.meshgrid(np.arange(-29,210,2.),np.arange(-29,150,2.))
    gx,gy=gx.ravel(),gy.ravel()
    keep=~intersects_xy(occupied,gx,gy)
    gx,gy=gx[keep],gy[keep]
    cls=np.full(len(gx),2,dtype=np.uint8)
    cls[intersects_xy(unary_union(roads),gx,gy)]=11
    cls[intersects_xy(water,gx,gy)]=9
    xyz=[np.column_stack((gx+x0,gy+y0,np.full(len(gx),base)))];classes=[cls]
    controls=[]
    for _,kind,geom in surface_features:
        if kind not in (strings.SurfaceObjectClass.TERRAIN,strings.SurfaceObjectClass.FOREST):
            continue
        for g in (list(geom.geoms) if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else [geom]):
            for ring in [g.exterior,*g.interiors]:
                controls.extend((x+x0,y+y0,base) for x,y in list(ring.coords)[:-1])
    xyz.append(np.asarray(controls));classes.append(np.full(len(controls),2,dtype=np.uint8))
    spacing=1/math.sqrt(5)
    noise_id=parts[0][0]
    for identifier,_,geom,height,_ in parts:
        a,b,c,d=geom.bounds
        xx,yy=np.meshgrid(np.arange(a+spacing/2,c,spacing),np.arange(b+spacing/2,d,spacing))
        xx,yy=xx.ravel(),yy.ravel();inside=contains_xy(geom,xx,yy);xx,yy=xx[inside],yy[inside]
        zz=np.full(len(xx),base+height)
        if identifier==noise_id:
            zz[::7]+=8 # deliberate high tail; rank vs modal illustration only
        xyz.append(np.column_stack((xx+x0,yy+y0,zz)));classes.append(np.full(len(xx),6,dtype=np.uint8))
    cloud=laspy.LasData(laspy.LasHeader(point_format=6,version='1.4'))
    cloud.header.scales=[.001]*3;cloud.header.offsets=[x0,y0,0];cloud.header.add_crs(CRS.from_epsg(epsg))
    values=np.concatenate(xyz);cl=np.concatenate(classes)
    cloud.x,cloud.y,cloud.z=values.T;cloud.classification=cl;cloud.write(inputs/strings.SyntheticInputFiles.CLOUD)
    building_config={strings.ConfigurationEnvelopeFields.VERSION:strings.InputContractVersion.CONFIG_VERSION,strings.BuildConfigurationFields.CONTRACT_VERSION:strings.InputContractVersion.BUILDING_CONTRACT_VERSION,strings.DatasetIdentityFields.DATASET_ID:'canal-neighbourhood-buildings',
        strings.BuildConfigurationFields.GEOMETRY_MODE:strings.BuildingGeometryMode.PARTS,strings.GeospatialInputFields.FOOTPRINTS:strings.SyntheticInputFiles.FOOTPRINTS,strings.GeospatialInputFields.DTM:strings.SyntheticInputFiles.DTM,strings.GeospatialInputFields.LIDAR:[strings.SyntheticInputFiles.CLOUD],
        strings.GeospatialInputFields.WORKING_EPSG:epsg,strings.GeospatialInputFields.VERTICAL_REFERENCE:strings.VerticalReferenceDeclaration.LOCAL_RELATIVE,strings.BuildConfigurationFields.LODS:[0,1]}
    dump(inputs/strings.SyntheticInputFiles.BUILD_CONFIG,building_config)
    dump(inputs/strings.SyntheticInputFiles.TRUTH,{strings.SyntheticControlFields.DESCRIPTION:'Original synthetic neighbourhood controls; not survey data',
          strings.SyntheticControlFields.BASE_Z_M:base,strings.HeightTrialFields.PARTS:{identifier:{strings.BuildingHeightFields.HEIGHT_M:height,strings.PolygonFootprintFields.AREA_M2:geom.area}
              for identifier,_,geom,height,_ in parts}})
    dump(inputs/strings.SyntheticInputFiles.SURFACE_CONFIG,{strings.ConfigurationEnvelopeFields.VERSION:strings.InputContractVersion.CONFIG_VERSION,strings.SurfaceConfigurationFields.SURFACE_CONTRACT:strings.InputContractVersion.SURFACE_CONTRACT_VERSION,strings.DatasetIdentityFields.DATASET_ID:'canal-neighbourhood-surfaces',
        strings.GeospatialInputFields.POLYGONS:strings.SyntheticInputFiles.FOOTPRINTS,strings.GeospatialInputFields.LIDAR:[strings.SyntheticInputFiles.CLOUD],strings.GeospatialInputFields.WORKING_EPSG:epsg,strings.GeospatialInputFields.VERTICAL_REFERENCE:strings.VerticalReferenceDeclaration.LOCAL_RELATIVE,
        strings.SurfaceConfigurationFields.RADIUS_M:2.1,strings.ModelQuantizationFields.PRECISION_M:.0001})
    print('Building original neighbourhood...',flush=True)
    building_summary=run_build(inputs/strings.SyntheticInputFiles.BUILD_CONFIG,output/'buildings')
    print('Lifting original road, water and land polygons...',flush=True)
    surface_summary=run_surfaces(inputs/strings.SyntheticInputFiles.SURFACE_CONFIG,output/'surfaces')
    if building_summary[strings.ReconstructionRunFields.STATUS]!=strings.ReconstructionRunStatus.COMPLETE or surface_summary[strings.ReconstructionRunFields.STATUS]!=strings.ReconstructionRunStatus.COMPLETE:
        raise ValueError('Documentation showcase has unresolved objects; inspect reports before rendering')
    models=[]
    for filename in [output/'buildings/model.lod1.city.json',output/'surfaces/model.surfaces.city.json']:
        model=json.loads(filename.read_text(encoding=strings.TextFileEncoding.UTF8))
        world=np.asarray(model[strings.CityJSONFields.VERTICES])*model[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.SCALE]+model[strings.CityJSONFields.TRANSFORM][strings.CityJSONFields.TRANSLATE]
        for identifier,obj in model[strings.CityJSONFields.CITY_OBJECTS].items():
            indices=[]
            for g in obj.get(strings.CityJSONFields.GEOMETRY,[]):
                for face in faces(g):indices.extend(triangulate_surface(face,world))
            if indices:
                coords=world[indices]-[x0,y0,base]
                models.append({'id':identifier,strings.SourceObjectIdentity.KIND:obj[strings.CityJSONFields.ATTRIBUTES].get(strings.CityJSONReconstructionAttributes.SOURCE_CLASS,obj[strings.CityJSONFields.TYPE]),
                               'positions':np.round(coords,6).ravel().tolist()})
    visible=(values[:,0]>=x0)&(values[:,0]<=x0+180)&(values[:,1]>=y0)&(values[:,1]<=y0+120)
    map_features=[{strings.SourceObjectIdentity.KIND:strings.BuildingObjectType.BUILDING,strings.GeospatialInputFields.POLYGONS:[[list(g.exterior.coords),*[list(r.coords) for r in g.interiors]]
                    for g in (list(geom.geoms) if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else [geom])]} for geom in parents.values()]
    map_features += [{strings.SourceObjectIdentity.KIND:kind,strings.GeospatialInputFields.POLYGONS:[[list(g.exterior.coords),*[list(r.coords) for r in g.interiors]]
                      for g in (list(geom.geoms) if geom.geom_type==strings.PolygonGeometryType.MULTI_POLYGON else [geom])]} for _,kind,geom in surface_features]
    dump(output/'presentation.json',{strings.ValidationReportFields.SCOPE:'Visual composition of two actual runs; no cross-object stitching',
          'extent':[0,0,180,120],'render_origin':[x0,y0,base],strings.ShowcasePresentationFields.MESHES:models,
          strings.ShowcasePresentationFields.POINTS:{'xyz':np.round(values[visible]-[x0,y0,base],4).ravel().tolist(),strings.ShowcasePresentationFields.POINT_CLASS_VALUES:cl[visible].tolist()},
          'map':map_features,'roof_nominal_density_points_m2':5,'ground_spacing_m':2,
          'roof_spacing_m':spacing,'ground_boundary_controls':len(controls),
          'comparison_scope':'Synthetic illustration, not a 3dfier benchmark'})
    dump(output/'showcase.json',{strings.ShowcaseReportFields.BUILDING_RUN:building_summary,strings.ShowcaseReportFields.SURFACE_RUN:surface_summary,
          'rendering':'Composition only; source coordinates and generated heights retained',
          'roof_nominal_points_m2':5,'ground_spacing_m':2,'high_tail_part':noise_id})
    print(json.dumps({strings.ShowcaseReportFields.BUILDING_OBJECT_COUNT:building_summary.get(strings.ReconstructionRunFields.SOURCE_OBJECTS),'surface_objects':surface_summary[strings.ReconstructionRunFields.SOURCE_OBJECTS],
                      'rendered_meshes':len(models),'roof_spacing_m':spacing}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument(strings.CommandLineArguments.OUTPUT_OPTION,type=Path,required=True,help='New documentation-fixture run directory')
    generate(parser.parse_args().output)
