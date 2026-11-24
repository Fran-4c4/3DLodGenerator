"""First public vertical slice for independent non-building surface generation."""
from lodext import strings
from collections import Counter
import csv
import hashlib
from importlib.metadata import version
from pathlib import Path
import platform

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .core.surfaces import SurfaceConfig
from .export.cityjson import Vertices, validate_cityjson
from .io.surfaces import read_surfaces, sample_surface_points
from .pipeline import dump
from .reconstruction.surfaces import SurfaceUnresolved, reconstruct_surface


# Authoritative export mapping: surface-contract class -> (CityJSON object type,
# geometry type, semantic surface type). build_surface_cityjson consumes these
# exact schema names for each LoD1 surface; Terrain uses CompositeSurface for
# TINRelief, while the other classes use MultiSurface. This map does not select
# elevations or enable unsupported classes. Changes affect output semantics and
# must remain compatible with the CityJSON schema and downstream tile converter.
CITYJSON_SURFACE_TYPES = {
    strings.SurfaceObjectClass.ROAD: (strings.CityJSONObjectType.ROAD, strings.CityJSONGeometryType.MULTI_SURFACE, strings.CityJSONSurfaceSemantic.TRAFFIC),
    strings.SurfaceObjectClass.TERRAIN: (strings.CityJSONObjectType.TIN_RELIEF, strings.CityJSONGeometryType.COMPOSITE_SURFACE, strings.CityJSONSurfaceSemantic.GROUND),
    strings.SurfaceObjectClass.FOREST: (strings.CityJSONObjectType.PLANT_COVER, strings.CityJSONGeometryType.MULTI_SURFACE, strings.CityJSONSurfaceSemantic.GROUND),
    strings.SurfaceObjectClass.WATER: (strings.CityJSONObjectType.WATER_BODY, strings.CityJSONGeometryType.MULTI_SURFACE, strings.CityJSONSurfaceSemantic.WATER),
}


def build_surface_cityjson(features, meshes, records, config):
    """Encode lifted component meshes as class-specific CityJSON 2.0 surfaces.

    meshes/records are keyed by SurfaceFeature.key; meshes contains metre XYZ
    triangles per component, while every received feature requires a report.
    Unresolved objects retain identity/attributes with no geometry. Quantise on
    one shared grid and reject collapsed/inverted triangles, changed holes,
    overlapping triangles or newly touching disconnected components.

    Return a model dict with source identity, class, status and explicit
    stitching_applied=False. Do not write files, relift heights or stitch objects.
    """
    origin = (min(f.geometry.bounds[0] for f in features),
              min(f.geometry.bounds[1] for f in features), 0.0)
    vertex = Vertices(config.precision_m, origin)
    objects = {}
    for feature in features:
        record = records[feature.key]
        kind, geometry_type, semantic = CITYJSON_SURFACE_TYPES[feature.surface_class]
        geometries = []
        quantized_components = []
        original_components = list(feature.geometry.geoms) if feature.geometry.geom_type == strings.PolygonGeometryType.MULTI_POLYGON else [feature.geometry]
        for component in meshes.get(feature.key, []):
            faces = []
            projected = []
            for triangle in component:
                ring = [vertex(p) for p in triangle]
                xy = np.asarray([vertex.decode(i)[:2] for i in ring])
                a, b = xy[1] - xy[0], xy[2] - xy[0]
                cross = a[0]*b[1] - a[1]*b[0]
                if len(set(ring)) != 3 or cross <= 0:
                    raise ValueError("Quantization collapses or inverts a surface triangle; reduce precision_m")
                faces.append([ring])
                projected.append(Polygon(xy))
            footprint = unary_union(projected)
            original = original_components[len(quantized_components)]
            if (footprint.geom_type != strings.PolygonGeometryType.POLYGON or not footprint.is_valid
                    or len(footprint.interiors) != len(original.interiors)
                    or abs(sum(p.area for p in projected)-footprint.area) > max(1e-9, footprint.area*1e-9)):
                raise ValueError("Quantization changes surface topology; reduce precision_m")
            for i, earlier in enumerate(quantized_components):
                if original.distance(original_components[i]) > 0 and footprint.distance(earlier) == 0:
                    raise ValueError("Quantization merges disconnected surface components; reduce precision_m")
            quantized_components.append(footprint)
            geometries.append({strings.CityJSONFields.TYPE: geometry_type, strings.CityJSONFields.LOD: strings.CityModelLoD.LOD1, strings.CityJSONFields.BOUNDARIES: faces,
                               strings.CityJSONFields.SEMANTICS: {strings.CityJSONFields.SURFACES: [{strings.CityJSONFields.TYPE: semantic}], strings.CityJSONFields.VALUES: [0]*len(faces)}})
        objects[feature.key] = {strings.CityJSONFields.TYPE: kind, strings.CityJSONFields.ATTRIBUTES: {
            strings.CityJSONReconstructionAttributes.SOURCE_ID: feature.id, strings.CityJSONReconstructionAttributes.SOURCE_CLASS: feature.surface_class,
            strings.CityJSONReconstructionAttributes.KEY_RECONSTRUCTION_STATUS: record[strings.ReconstructionObjectFields.STATUS], strings.SurfaceReconstructionFields.METHOD: record.get(strings.SurfaceReconstructionFields.METHOD),
            "reason": record.get("reason"), "stitchingApplied": False}, strings.CityJSONFields.GEOMETRY: geometries}
    coordinates = [vertex.decode(i) for i in range(len(vertex.vertices))]
    extent = [min((v[i] for v in coordinates), default=0) for i in range(3)] + [max((v[i] for v in coordinates), default=0) for i in range(3)]
    return {strings.CityJSONFields.TYPE: strings.CityJSONFormat.FORMAT, strings.CityJSONFields.VERSION: strings.CityJSONFormat.VERSION, strings.CityJSONFields.TRANSFORM: {
                strings.CityJSONFields.SCALE: [config.precision_m]*3, strings.CityJSONFields.TRANSLATE: list(origin)},
            strings.CityJSONFields.METADATA: {strings.CityJSONFields.IDENTIFIER: config.dataset_id + "-surfaces", strings.CityJSONFields.TITLE: config.dataset_id + " surfaces",
                         strings.CityJSONFields.REFERENCE_SYSTEM: f"{strings.CityJSONFormat.CRS_EPSG_URI_PREFIX}{config.working_epsg}",
                         strings.CityJSONFields.GEOGRAPHICAL_EXTENT: extent},
            strings.CityJSONFields.CITY_OBJECTS: objects, strings.CityJSONFields.VERTICES: vertex.vertices,
            "lodext": {strings.GeospatialInputFields.VERTICAL_REFERENCE: config.vertical_reference, strings.ModelElevationUnits.Z_UNIT: strings.ModelElevationUnits.UNIT_METRES,
                       strings.SurfaceConfigurationFields.SURFACE_CONTRACT: config.surface_contract, "stitching_applied": False,
                       strings.ValidationReportFields.SCOPE: "individual surfaces; minimum urban scene is incomplete"}}


def run_surfaces(config_file, output, progress=lambda phase, details: None):
    """Build a new run; errors never overwrite inputs or pre-existing results.

    All geometry is prepared/checked before output creation. Status describes
    this surface stage only, not completion of seven-class scene reconstruction.
    Resolve paths from the config file, read polygons/clouds, reconstruct each
    object and retain unresolved evidence under the configured policy. Return
    complete/partial summary; the CLI maps partial to exit 3. progress receives
    (phase, details) events. Write model, quality JSON, CSV and effective-run
    metadata only after geometry validation; later filesystem errors can still
    interrupt writing. No cross-object stitching or vertical conversion occurs.
    """
    config_file, output = Path(config_file).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError(strings.OutputDirectoryMessages.OUTPUT_EXISTS)
    config = SurfaceConfig.read(config_file)
    root = config_file.parent
    features, working = read_surfaces(config, root)
    progress("surface_inputs", {strings.ProgressEventFields.OBJECT_COUNT: len(features), strings.ReconstructionRunFields.SURFACE_CLASS_COUNTS: dict(Counter(f.surface_class for f in features))})
    samples, sampling = sample_surface_points(config, root, features, working, progress)
    meshes, records = {}, {}
    for feature in features:
        sample = samples[feature.key]
        base = {strings.SourceObjectIdentity.SOURCE_ID: feature.id, strings.SourceObjectIdentity.SOURCE_CLASS: feature.surface_class,
                strings.LidarSamplingFields.COVERAGE_COMPLETE: bool(sample[strings.LidarSamplingFields.COVERAGE_COMPLETE]), strings.ReconstructionObjectFields.STATUS: strings.ReconstructionObjectStatus.UNRESOLVED}
        try:
            if not sample[strings.LidarSamplingFields.COVERAGE_COMPLETE]:
                raise SurfaceUnresolved("incomplete_header_coverage")
            mesh, evidence = reconstruct_surface(feature, sample[strings.ShowcasePresentationFields.POINTS], config)
            meshes[feature.key] = mesh
            records[feature.key] = {**base, **evidence, strings.ReconstructionObjectFields.STATUS: strings.ReconstructionObjectStatus.RESOLVED}
        except SurfaceUnresolved as exc:
            records[feature.key] = {**base, "reason": str(exc), strings.SurfaceReconstructionFields.SAMPLE_POINTS: len(sample[strings.ShowcasePresentationFields.POINTS])}
            if config.unresolved_objects == strings.InputFailurePolicy.ERROR:
                raise ValueError(f"Unresolved {feature.key}: {exc}") from exc
    model = build_surface_cityjson(features, meshes, records, config)
    checks = validate_cityjson(model)
    unresolved = sum(r[strings.ReconstructionObjectFields.STATUS] == strings.ReconstructionObjectStatus.UNRESOLVED for r in records.values())
    summary = {strings.ReconstructionRunFields.STATUS: strings.ReconstructionRunStatus.PARTIAL if unresolved else strings.ReconstructionRunStatus.COMPLETE, strings.ReconstructionRunFields.SOURCE_OBJECTS: len(features),
               "resolved_objects": len(features)-unresolved, strings.ReconstructionFailurePolicyFields.UNRESOLVED_OBJECTS: unresolved,
               strings.ReconstructionRunFields.SURFACE_CLASS_COUNTS: dict(Counter(f.surface_class for f in features)), strings.MeshValidationFields.TRIANGLE_COUNT: checks[strings.MeshValidationFields.FACE_COUNT],
               "stitching_applied": False, "minimum_product_complete": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output/"model.surfaces.city.json", model)
    dump(output/strings.ReconstructionOutputFiles.QUALITY, {strings.ValidationReportFields.SCOPE: "individual surfaces, no cross-object stitching", strings.ReconstructionRunFields.SUMMARY: summary,
                                strings.QualityReportFields.OBJECTS: list(records.values())})
    with (output/strings.ReconstructionOutputFiles.OBJECTS_CSV).open("w", encoding=strings.TextFileEncoding.UTF8, newline="") as stream:
        columns = [strings.SourceObjectIdentity.SOURCE_ID, strings.SourceObjectIdentity.SOURCE_CLASS, strings.ReconstructionObjectFields.STATUS, "reason", strings.LidarSamplingFields.COVERAGE_COMPLETE, strings.SurfaceReconstructionFields.SAMPLE_POINTS, strings.MeshValidationFields.TRIANGLE_COUNT, strings.SurfaceReconstructionFields.METHOD]
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records.values())
    with (root/config.polygons).open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    dump(output/strings.ReconstructionOutputFiles.RUN, {strings.ReconstructionRunFields.COMMAND: "build-surfaces", strings.ReconstructionRunFields.CONFIG: config.effective(),
                            strings.ReconstructionRunFields.VERSIONS: {name: version(name) for name in ("numpy", "shapely", "pyproj", "laspy", "lodext")}
                                        | {"python": platform.python_version()},
                            "config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(),
                            strings.SourceInventoryFields.GEOPACKAGE_SHA256: source_hash, strings.ReconstructionRunFields.SURFACE_SAMPLING_EVIDENCE: sampling,
                            "checks": checks, strings.ReconstructionRunFields.SUMMARY: summary})
    progress("surface_complete", summary)
    return summary
