"""Bounded streaming ground statistics; source clouds remain the point archive."""
from collections import Counter
from dataclasses import dataclass,field
from contextlib import closing
from pathlib import Path
import sqlite3,struct
import numpy as np
from shapely import STRtree,points,intersects_xy,to_wkb
from shapely.geometry import Point
from shapely.ops import unary_union
from lodext import strings


@dataclass(slots=True)
class GroundRingEvidence:
    """Sufficient ground statistics for one free search ring; no point arrays."""
    histogram: Counter = field(default_factory=Counter)  # Integer Z-bin -> count; step owned by PointGroundConfig.
    samples: int = 0  # Count of original accepted returns, not bins or retained mesh vertices.
    candidates: int = 0  # All configured-class returns in the ring neighbourhood, including excluded ones.
    excluded: int = 0  # Original configured-class returns intersecting received building footprints.
    minimum: float | None = None  # Exact minimum accepted source Z, metres; null if no accepted points.
    maximum: float | None = None  # Exact maximum accepted source Z, metres; null if no accepted points.

    def add(self,z,accepted,step):
        """Aggregate original class-filtered observations, with bounded Z resolution."""
        self.candidates+=len(z);self.excluded+=int((~accepted).sum());z=z[accepted]
        if not len(z):return
        bins=np.rint(z/step)
        if np.any(np.abs(bins)>np.iinfo(np.int64).max/2):raise ValueError('Ground Z exceeds histogram numerical domain')
        keys,counts=np.unique(bins.astype(np.int64),return_counts=True)
        self.histogram.update({int(k):int(n) for k,n in zip(keys,counts)})
        self.samples+=len(z);low,high=float(z.min()),float(z.max())
        self.minimum=low if self.minimum is None else min(self.minimum,low)
        self.maximum=high if self.maximum is None else max(self.maximum,high)

    def median(self,step):
        """Median of counted bins, including the ordinary even-count midpoint."""
        ranks=((self.samples-1)//2,self.samples//2);values=[];cumulative=0
        for key,n in sorted(self.histogram.items()):
            for rank in ranks:
                if cumulative<=rank<cumulative+n:values.append(key*step)
            cumulative+=n
            if len(values)==2:break
        return sum(values)/2


class GroundPointAccumulator:
    """No complete raw-point cache, on disk or in memory.

    Accumulate Z histograms and original min/max/counts per object/radius. Once a
    smaller ring has sufficient support and free area, discard larger rings.
    Point coordinates survive only as explicitly bounded TIN representatives or
    an opt-in size-capped source-order debug sample. Histogram and vertex budgets
    fail rather than silently coarsen data. Native point files are the archive.
    """

    def __init__(self,path,working,policy,obstacles,units,sampling):
        self.path=Path(path)  # Optional capped sample file in owned build scratch; absent by default.
        self.working=working  # Declared projected-metre CRS; never changes source Z.
        self.policy=policy  # Sole PointGroundConfig owner of resolution/budgets.
        self.sampling=sampling  # Building ground-search radii, area and minimum support thresholds.
        self.geometries=[u.geometry for u in units]  # Source footprints in unit order; not repaired.
        self.obstacle_geometries=obstacles  # All valid occupied footprints, including excluded input units.
        self.obstacles=STRtree(obstacles)  # Exact occupied-area tests, independent of roof class choice.
        self.buffers=[[g.buffer(r) for r in sampling.ground_buffers_m] for g in self.geometries]  # Search shapes only, not output footprints.
        self.tree=STRtree([b[-1] for b in self.buffers])  # Broadest neighbourhood -> source unit index.
        self.states=[[GroundRingEvidence() for _ in sampling.ground_buffers_m] for _ in units]  # Streaming statistics only.
        self.limits=[len(sampling.ground_buffers_m)-1 for _ in units]  # Largest ring still needed; decreases with support.
        self.areas={}  # (unit index, ring index) -> exact free area m2, calculated lazily.
        self.cells={}  # TIN XY cell -> (distance squared, actual XYZ); bounded by max_surface_vertices.
        self.audit_rows=[]  # Opt-in capped source-order debug records, never the complete cloud by default.
        self.counts=Counter()  # Whole-run accepted/inside-building candidate counts.
        self.bin_count=0  # Active distinct bins across all retained object/ring histograms.
        self.peak_bins=0  # Peak active count for run-level resource diagnostics.

    def free_area(self,i,j):
        """Occupied-area-free support; cached only after a ring gets observations."""
        key=(i,j)
        if key not in self.areas:
            shape=self.buffers[i][j];ids=self.obstacles.query(shape,predicate='intersects')
            self.areas[key]=shape.difference(unary_union([self.obstacle_geometries[int(k)] for k in ids])).area
        return self.areas[key]

    def add(self,x,y,z,classes,path,source,records,sx,sy,sz):
        """Consume one decoded ground-class batch and discard its point arrays.

        Working XY and native XYZ remain aligned. Source record indices are
        optional for COPC. No class or source file is edited. Point rejection is
        geometric selection evidence, not an automatic classification repair.
        """
        xy=points(x,y);pairs=self.obstacles.query(xy,predicate='intersects');excluded=np.zeros(len(x),dtype=bool)
        if pairs.shape[1]:excluded[pairs[0]]=True
        self.counts[strings.GroundPointDecision.INSIDE_BUILDING]+=int(excluded.sum())
        self.counts[strings.GroundPointDecision.ACCEPTED]+=int((~excluded).sum())
        pairs=self.tree.query(xy,predicate='intersects')
        if pairs.shape[1]:
            order=np.lexsort((pairs[0],pairs[1]));objects=pairs[1,order];indices=pairs[0,order]
            splits=np.r_[0,np.flatnonzero(np.diff(objects))+1,len(objects)]
            for first,last in zip(splits[:-1],splits[1:]):
                i=int(objects[first]);ids=indices[first:last]
                for j in range(self.limits[i]+1):
                    inside=intersects_xy(self.buffers[i][j],x[ids],y[ids]);chosen=ids[inside];state=self.states[i][j]
                    before=len(state.histogram);state.add(z[chosen],~excluded[chosen],self.policy.quantile_step_m);self.bin_count+=len(state.histogram)-before
                    if state.samples>=self.sampling.min_ground_samples and self.free_area(i,j)>=self.sampling.min_free_area_m2:
                        for k in range(j+1,self.limits[i]+1):
                            self.bin_count-=len(self.states[i][k].histogram);self.states[i][k]=GroundRingEvidence()
                        self.limits[i]=j;break
                self.peak_bins=max(self.peak_bins,self.bin_count)
                if self.bin_count>self.policy.max_histogram_bins:
                    raise ValueError('Ground statistics exceed max_histogram_bins; partition the input or explicitly change the histogram budget/resolution')
        if self.policy.export_surface:
            size=self.policy.surface_cell_size_m;good=np.flatnonzero(~excluded)
            if len(good):
                keys=np.floor(np.column_stack((x[good],y[good]))/size).astype(np.int64)
                distances=(x[good]-(keys[:,0]+.5)*size)**2+(y[good]-(keys[:,1]+.5)*size)**2
                order=np.lexsort((distances,keys[:,1],keys[:,0]));ordered=keys[order];first=np.r_[True,np.any(ordered[1:]!=ordered[:-1],axis=1)]
                for j in order[first]:
                    key=tuple(map(int,keys[j]));i=good[j];candidate=(float(distances[j]),(float(x[i]),float(y[i]),float(z[i])))
                    if key not in self.cells or candidate<self.cells[key]:self.cells[key]=candidate
                if len(self.cells)>self.policy.max_surface_vertices:
                    raise ValueError('Ground surface exceeds max_surface_vertices; partition the input or explicitly change surface_cell_size_m/budget')
        if self.policy.export_points:
            # Diagnostic extraction is opt-in, source-ordered and explicitly
            # capped. It is not advertised as complete or statistically uniform.
            count=min(len(x),self.policy.max_export_points-len(self.audit_rows));epsg=source.to_epsg()
            for i in range(count):
                self.audit_rows.append((float(x[i]),float(y[i]),float(z[i]),int(classes[i]),
                    strings.GroundPointDecision.INSIDE_BUILDING if excluded[i] else strings.GroundPointDecision.ACCEPTED,path,epsg,
                    None if records[i] is None else int(records[i]),float(sx[i]),float(sy[i]),float(sz[i])))

    def estimate(self,i):
        """Return the first supported free ring's compact evidence; never use TIN."""
        common={strings.PointGroundFields.METHOD:strings.PointGroundMethod.HISTOGRAM_MEDIAN,
                strings.PointGroundFields.MEDIAN_ERROR_BOUND:self.policy.quantile_step_m/2}
        for j,state in enumerate(self.states[i][:self.limits[i]+1]):
            if state.samples<self.sampling.min_ground_samples or self.free_area(i,j)<self.sampling.min_free_area_m2:continue
            return {**common,strings.BuildingHeightFields.GROUND_Z:state.median(self.policy.quantile_step_m),'ground_samples':state.samples,
                    'ground_candidates':state.candidates,'ground_radius_m':self.sampling.ground_buffers_m[j],'ground_free_area_m2':self.free_area(i,j),
                    strings.PointGroundFields.EXCLUDED_INSIDE:state.excluded,strings.PointGroundFields.Z_MIN:state.minimum,strings.PointGroundFields.Z_MAX:state.maximum}
        return {**common,strings.BuildingHeightFields.GROUND_Z:None,'ground_samples':0,'ground_candidates':0,'ground_radius_m':None,'ground_free_area_m2':0.,
                strings.PointGroundFields.EXCLUDED_INSIDE:None,strings.PointGroundFields.Z_MIN:None,strings.PointGroundFields.Z_MAX:None}

    def finish(self):
        """Optionally write only the capped debug sample; no full point cache."""
        if not self.policy.export_points:return
        epsg=self.working.to_epsg()
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''PRAGMA application_id=1196444487;PRAGMA user_version=10300;
CREATE TABLE gpkg_spatial_ref_sys(srs_name TEXT NOT NULL,srs_id INTEGER PRIMARY KEY,organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,definition TEXT NOT NULL,description TEXT);
CREATE TABLE gpkg_contents(table_name TEXT PRIMARY KEY,data_type TEXT NOT NULL,identifier TEXT,description TEXT,last_change DATETIME NOT NULL DEFAULT '2026-11-15T00:00:00.000Z',min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,srs_id INTEGER);
CREATE TABLE gpkg_geometry_columns(table_name TEXT NOT NULL,column_name TEXT NOT NULL,geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,z TINYINT NOT NULL,m TINYINT NOT NULL,PRIMARY KEY(table_name,column_name));
CREATE TABLE ground_points(fid INTEGER PRIMARY KEY,geom BLOB NOT NULL,x REAL NOT NULL,y REAL NOT NULL,z REAL NOT NULL,original_class INTEGER NOT NULL,decision TEXT NOT NULL,source_file TEXT NOT NULL,source_epsg INTEGER,source_record INTEGER,source_x REAL NOT NULL,source_y REAL NOT NULL,source_z REAL NOT NULL);''')
            db.executemany('INSERT INTO gpkg_spatial_ref_sys VALUES(?,?,?,?,?,?)',[
                ('Undefined Cartesian',-1,'NONE',-1,'undefined',None),('Undefined geographic',0,'NONE',0,'undefined',None),
                (self.working.name,epsg,'EPSG',epsg,self.working.to_wkt(),None)])
            db.execute('INSERT INTO gpkg_contents(table_name,data_type,identifier,description,srs_id) VALUES(?,?,?,?,?)',
                ('ground_points','features','ground_points','Size-capped source-order debug sample, not a complete or uniform point inventory.',epsg))
            db.execute('INSERT INTO gpkg_geometry_columns VALUES(?,?,?,?,?,?)',('ground_points','geom','POINT',epsg,1,0))
            header=b'GP\x00\x01'+struct.pack('<i',epsg)
            db.executemany('INSERT INTO ground_points VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ((i+1,header+to_wkb(Point(*r[:3])),*r) for i,r in enumerate(self.audit_rows)))
            db.execute('UPDATE gpkg_contents SET min_x=(SELECT min(x) FROM ground_points),min_y=(SELECT min(y) FROM ground_points),max_x=(SELECT max(x) FROM ground_points),max_y=(SELECT max(y) FROM ground_points)')
            db.commit()
