"""Public local-files workflow: input contract -> evidence -> LoD -> CityJSON."""
from lodext import strings
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from copy import deepcopy

from .core.config import BuildConfig
from .core.geometric_policy import NONCOMPACT_FOOTPRINT_MAX, footprint_compactness
from .core.heights import PartObservation, estimate_building
from .io.native import configure_native_environment


_OWNERSHIP_REJECTIONS = frozenset({
    strings.BuildingSurfaceRejectionReason.BOUNDARY_CONTINUITY,
    strings.BuildingSurfaceRejectionReason.MULTILEVEL_NEIGHBOUR_CONTINUITY,
    strings.BuildingSurfaceRejectionReason.SIBLING_STOREY_CONFLICT,
})
_SEPARATE_LAYER_HEIGHT_MULTIPLIER = 2.0
"""Minimum rejected clearance relative to a fallback height for a separate layer.

Two complete fallback heights mean the rejected surface is at least one whole
inferred volume above that volume's roof. This dimensionless relation scales
with low patios, ordinary buildings and taller structures without an absolute
metre or footprint-area threshold.
"""


def _spatial_rejection_conflicts_with_fallback(geometry, ground_z, inferred_height_m, compactness):
    """Return whether rejected LiDAR planes overlap a contextual height layer.

    A plane attributed to an adjacent structure conflicts with a storey-derived
    fallback when both alternatives describe the same vertical layer. The
    caller retains the mapped contextual volume but records the conflict. When
    every rejected plane is at least another complete inferred building height
    above the fallback, the rejection instead provides evidence of a separate
    neighbouring layer. The low contextual volume then remains an independent
    hypothesis, for example for a podium or an inner patio.
    """
    rejected = [
        item for item in geometry.get('rejected_neighbour_planes', [])
        if item.get('reason') in _OWNERSHIP_REJECTIONS
    ]
    if not rejected or geometry.get('accepted', False):
        return False
    reasons = {item['reason'] for item in rejected}
    if (strings.BuildingSurfaceRejectionReason.SIBLING_STOREY_CONFLICT in reasons
            and compactness <= NONCOMPACT_FOOTPRINT_MAX):
        # A long/concave exterior part whose only observed layer reproduces a
        # taller sibling has no independent evidence for an unseen low roof.
        # Compact small parts can be occluded completely; for them the ordinary
        # vertical-separation test below decides whether a low fallback survives.
        return True
    if reasons == {strings.BuildingSurfaceRejectionReason.BOUNDARY_CONTINUITY} and compactness > NONCOMPACT_FOOTPRINT_MAX:
        # A compact part can lack controls beyond the uncertainty margin simply
        # because it is small. Boundary continuity rejects the observed plane,
        # but does not independently disprove a contextual low volume. Long or
        # deeply concave parts remain protected against wall-like fallbacks.
        return False
    if ground_z is None or inferred_height_m is None or inferred_height_m <= 0:
        return True
    rejected_clearances = [
        item['roof_z'] - ground_z for item in rejected
        if isinstance(item.get('roof_z'), (int, float)) and math.isfinite(item['roof_z'])
        and item['roof_z'] > ground_z
    ]
    if not rejected_clearances:
        return True
    return min(rejected_clearances) < _SEPARATE_LAYER_HEIGHT_MULTIPLIER * inferred_height_m


def _record_spatial_fallback_conflict(row, conflicts):
    """Mark a contextual height that overlaps rejected neighbour-owned planes.

    ``row`` is the mutable height-estimate mapping owned by the build pipeline.
    Only ``floor_share`` and ``regional`` heights can receive this uncertainty;
    their height, method and reference fields remain unchanged. Direct or
    unresolved estimates are left untouched. ``conflicts`` is the geometric
    decision returned by :func:`_spatial_rejection_conflicts_with_fallback`.
    """
    if conflicts and row[strings.BuildingHeightFields.METHOD] in (
            strings.HeightEstimationMethod.FLOOR_SHARE,
            strings.HeightEstimationMethod.REGIONAL):
        row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.SPATIAL_ROOF_REJECTED)


def _suppress_isolated_wall_like_fallback(row, geometry):
    """Remove storey-only volume after an isolated sub-resolution rejection.

    Native attribution owns the geometric decision. This consumer changes only
    ``floor_share``/``regional`` outcomes when no surface was accepted and the
    explicit wall-like reason is present. Direct measurements are untouched.
    The mapped footprint and ground remain available for unresolved display.
    """
    wall_like=(not geometry.get('accepted',False) and any(
        item.get('reason')==strings.BuildingSurfaceRejectionReason.ISOLATED_WALL_LIKE_SURFACE
        for item in geometry.get('rejected_neighbour_planes',[])))
    if not wall_like or row[strings.BuildingHeightFields.METHOD] not in (
            strings.HeightEstimationMethod.FLOOR_SHARE,
            strings.HeightEstimationMethod.REGIONAL):
        return False
    row[strings.BuildingHeightFields.HEIGHT_M]=None
    row[strings.BuildingHeightFields.METHOD]=strings.HeightEstimationMethod.UNRESOLVED
    row[strings.BuildingHeightFields.REFERENCE_PART_ID]=None
    row[strings.BuildingHeightFields.FLOOR_HEIGHT_M]=None
    row[strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION]=None
    row[strings.BuildingHeightFields.ROOF_REFERENCE_Z]=None
    row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.WALL_LIKE_FALLBACK_REJECTED)
    return True


def _apply_boundary_shared_roof(row,geometry,near_zero_m):
    """Apply an attributed absolute shared roof to one mutable result row.

    ``geometry`` owns the optional metre Z and ordered same-parent references.
    The value replaces direct or storey-derived height only after attribution
    has proved the target sub-resolution and the declared storey step absent.
    It never returns a floor height or a calibration anchor. False means that
    the evidence was absent or lacked positive configured ground clearance.
    """
    roof_z=geometry.get(strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_Z)
    ground_z=row.get(strings.BuildingHeightFields.GROUND_Z)
    if (not isinstance(roof_z,(int,float)) or ground_z is None
            or roof_z<=ground_z+near_zero_m):
        return False
    neighbours=geometry.get(strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_NEIGHBOURS,[])
    row[strings.BuildingHeightFields.HEIGHT_M]=roof_z-ground_z
    row[strings.BuildingHeightFields.ROOF_REFERENCE_Z]=roof_z
    row[strings.BuildingHeightFields.METHOD]=strings.HeightEstimationMethod.BOUNDARY_SHARED_ROOF
    row[strings.BuildingHeightFields.REFERENCE_PART_ID]=neighbours[0] if neighbours else None
    row[strings.BuildingHeightFields.FLOOR_HEIGHT_M]=None
    row[strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION]=None
    row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.BOUNDARY_SHARED_ROOF)
    return True


def reconcile_facade_roofs(features, records, config):
    """Resolve peripheral roof evidence against finished, independently measured siblings.

    Only larger observed parts may supply a cap. Freeze references first so a
    correction cannot propagate. All elevations use the survey vertical datum.
    """
    groups = defaultdict(list)
    for feature in features:
        if feature.parent_id and feature.geometry is not None and not feature.issues:
            groups[feature.parent_id].append(feature)
    tolerance = config.height.inferred_roof_tolerance_m
    for siblings in groups.values():
        bodies = []
        for body in siblings:
            record = records.get(body.key, {})
            if record.get('method') in ('direct', 'roof_surface') and record.get('reconstructed_top_z') is not None:
                bodies.append((body, record['reconstructed_top_z']))
        for part in siblings:
            row = records.get(part.key, {})
            evidence = row.get('building_surfaces') or {}
            ground = row.get('ground_z')
            if ground is None or evidence.get('independent_interior_support'):
                continue
            method = row.get('method')
            continuation = row.get('adjacent_ground', {}).get('trigger') == 'adjacent_exterior_plane'
            gap_limit = config.building_surfaces.registration_m
            if method not in ('floor_share', 'unresolved', 'direct', 'roof_surface'):
                continue
            planes = evidence.get('planes', [])
            top = row.get('reconstructed_top_z')
            if method == 'floor_share' and planes and top <= max(p['observed_z_range'][1] for p in planes) + tolerance:
                continue
            contacts = []
            for body, roof in bodies:
                if body.geometry.area <= part.geometry.area or roof <= ground:
                    continue
                shared = body.geometry.boundary.intersection(part.geometry.boundary).length
                gap = part.geometry.distance(body.geometry)
                close_gap = (0 < gap <= gap_limit and body.geometry.area > 10 * part.geometry.area
                             and part.geometry.buffer(-(gap_limit + evidence.get('spacing_m', 0))).is_empty)
                if close_gap:
                    shared = part.geometry.boundary.intersection(body.geometry.buffer(gap_limit + evidence.get('spacing_m', 0))).length
                if method in ('direct', 'roof_surface') and not (continuation or close_gap):
                    continue
                if shared <= 0:
                    continue
                unobserved = (not planes and method == 'floor_share'
                              and part.geometry.buffer(-gap_limit).is_empty
                              and top > roof + tolerance)
                match_tolerance = tolerance + 2 * config.building_surfaces.residual_m
                if unobserved or any(min(p['observed_z_range']) - match_tolerance <= roof <= max(p['observed_z_range']) + match_tolerance for p in planes):
                    contacts.append((shared, body.key, roof))
            if not contacts:
                continue
            shared, key, roof = max(contacts)
            if shared < part.geometry.length / 4 or (top is not None and roof >= top):
                continue
            evidence['boundary_shared_roof_z'] = roof
            evidence['boundary_shared_roof_neighbour_ids'] = [key]
            if _apply_boundary_shared_roof(row, evidence, config.height.near_zero_m):
                row['status'] = 'resolved'
                row['reconstructed_top_z'] = roof
                if row.get('reference_height_m') is not None:
                    row['delta_from_reference_m'] = row['height_m'] - row['reference_height_m']


def dump(path,data):
    """Write readable UTF-8 JSON with a trailing newline; reject NaN/infinity.

    May replace the named file. Callers own new-run directory checks; this
    low-level writer does not create parent directories or provide atomic I/O.
    """
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding=strings.TextFileEncoding.UTF8)


def run_build(config_file, output, progress=lambda phase,details: None):
    """Build from local inputs; own and always clean direct-ground scratch files.

    Optional size-capped ground samples use disposable build scratch. Only
    a fully validated build copies them into a new output run. Source files and
    previous runs remain read-only; no temporary connection escapes this call.
    """
    with TemporaryDirectory(prefix='lodext-build-') as temporary:
        return _run_build(config_file,output,progress,Path(temporary))


def _run_build(config_file, output, progress, scratch):
    """Produce new output directory. Existing outputs/inputs are never overwritten.

    Returns summary; caller maps status='partial' to CLI exit 3, complete to 0.
    Invalid input/missing capabilities raise explicit errors before output.
    Partial outputs retain identity/reasons; they never fabricate geometry.
    Resolve resources from the configuration directory, receive canonical GPKG
    identities, sample DTM/cloud evidence and estimate explicit building groups.
    Apply qualified known/external heights only through their selected policies,
    then build and validate each requested LoD before creating the output folder.

    Write CityJSON, quality JSON, CSV and effective settings/version/hash metadata.
    progress receives (phase, details) events; it does not decide reconstruction.
    This is not an atomic filesystem transaction: write errors can leave a new
    partial directory, but no supplied input or pre-existing result is replaced.
    """
    configure_native_environment()
    from .io.footprints import read_footprints
    from .io.sampling import sample_sources
    from .export.cityjson import build_cityjson,validate_cityjson
    config_path = Path(config_file).resolve()
    config = BuildConfig.read(config_path)
    root = config_path.parent
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"{strings.OutputDirectoryMessages.OUTPUT_EXISTS}; choose a new run directory")
    features,working = read_footprints(config,root)
    if config.roof_regions.enabled and config.roof_regions.object_ids is not None:
        unknown=set(config.roof_regions.object_ids)-{f.key for f in features}
        if unknown:raise ValueError('Unknown roof_regions.object_ids: '+', '.join(sorted(unknown)))
    progress("reception",{strings.ProgressEventFields.OBJECT_COUNT:len(features),strings.ProgressEventFields.EXCLUDED_COUNT:sum(bool(f.issues) for f in features)})
    artifacts={}
    samples,cloud = sample_sources(config,root,features,working,progress,scratch=scratch,artifacts=artifacts)
    if config.height_source==strings.BuildingHeightSource.LIDAR and 1 in config.lods:
        from .io.building_surfaces import sample_building_surfaces
        sample_building_surfaces(config,root,features,samples,working,progress)
    kind = strings.BuildingObjectType.BUILDING_PART if config.geometry_mode==strings.BuildingGeometryMode.PARTS else strings.BuildingObjectType.BUILDING
    units = [f for f in features if f.kind==kind and not f.issues]
    largest_area=defaultdict(float)
    for feature in units:
        group_id=feature.parent_id if kind==strings.BuildingObjectType.BUILDING_PART else feature.id
        largest_area[group_id]=max(largest_area[group_id],feature.geometry.area)
    groups = defaultdict(list)
    for feature in units:
        sample = samples[feature.key]
        ground = sample[strings.BuildingHeightFields.GROUND_Z]
        attributed_surface=sample.get(strings.BuildingHeightFields.BUILDING_SURFACES,{})
        boundary_shared_roof_z=attributed_surface.get(
            strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_Z)
        usable_roof=(tuple(sample[strings.BuildingHeightFields.ROOF_Z])
            if sample[strings.LidarSamplingFields.COVERAGE_COMPLETE]
            and boundary_shared_roof_z is None else ())
        attributed_roof_z=_accepted_attributed_roof_z(sample)
        local_context_roof_z=_accepted_local_context_roof_z(sample)
        context_roof_z=tuple(item[strings.BuildingHeightFields.ROOF_Z] for item in attributed_surface.get('rejected_neighbour_planes',[])
                             if item.get('reason')=='explained_by_adjacent_structure'
                             and isinstance(item.get(strings.BuildingHeightFields.ROOF_Z),(int,float)))
        local_storey_neighbour_ids=tuple(attributed_surface.get(
            strings.BuildingSurfaceFields.LOCAL_STOREY_NEIGHBOURS,()))
        calibration_roof_z=attributed_surface.get(strings.BuildingSurfaceFields.CALIBRATION_ROOF_Z)
        group_id=feature.parent_id if kind==strings.BuildingObjectType.BUILDING_PART else feature.id
        groups[group_id].append(PartObservation(
            part_id=feature.key,building_id=group_id,
            area_m2=feature.geometry.area,sample_area_m2=sample[strings.BuildingHeightFields.SAMPLE_AREA_M2],
            roof_z=usable_roof,ground_z=ground,
            ground_is_measured=strings.BuildingHeightFields.ADJACENT_GROUND not in sample,
            check_small_part_coherence=feature.geometry.area<largest_area[group_id],
            storeys_above=feature.properties[strings.BuildingInputFields.STOREYS_ABOVE],storeys_below=feature.properties[strings.BuildingInputFields.STOREYS_BELOW],
            attributed_roof_z=attributed_roof_z,
            context_roof_z=context_roof_z,
            local_storey_neighbour_ids=local_storey_neighbour_ids,
            local_context_roof_z=local_context_roof_z,
            calibration_roof_z=calibration_roof_z,
        ))
    estimates = {}
    for observations in groups.values():
        for estimate in estimate_building(observations,config.height):
            estimates[estimate.part_id] = asdict(estimate)
    records = {}
    for feature in features:
        if feature.kind != kind:
            if feature.issues:
                records[feature.key] = {strings.SourceObjectIdentity.SOURCE_ID:feature.id,strings.ReconstructionObjectFields.STATUS:strings.ReconstructionObjectStatus.EXCLUDED,strings.BuildingHeightFields.FLAGS:feature.issues,strings.BuildingHeightFields.GROUND_Z:None,strings.BuildingHeightFields.HEIGHT_M:None}
            continue
        if feature.issues:
            records[feature.key] = {strings.SourceObjectIdentity.SOURCE_ID:feature.id,strings.ReconstructionObjectFields.STATUS:strings.ReconstructionObjectStatus.EXCLUDED,strings.BuildingHeightFields.FLAGS:feature.issues,strings.BuildingHeightFields.GROUND_Z:None,strings.BuildingHeightFields.HEIGHT_M:None}
            continue
        row = estimates[feature.key]
        row[strings.BuildingHeightFields.FLAGS] = list(row[strings.BuildingHeightFields.FLAGS])
        sample = samples[feature.key]
        row.update({k:v for k,v in sample.items() if k!=strings.BuildingHeightFields.ROOF_Z})
        if strings.BuildingHeightFields.ADJACENT_GROUND in sample:
            reconciled='original_ground_z' in sample[strings.BuildingHeightFields.ADJACENT_GROUND]
            row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.GROUND_RECONCILED_FROM_ADJACENT_PARTS if reconciled else strings.BuildingHeightReason.GROUND_INFERRED_FROM_ADJACENT_PARTS)
            if sample[strings.BuildingHeightFields.ADJACENT_GROUND]['conflicting_references']:
                row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.ADJACENT_GROUND_DISAGREEMENT)
        recovery=sample.get(strings.BuildingHeightFields.ROOF_RECOVERY)
        surface=sample.get(strings.BuildingHeightFields.ROOF_SURFACE)
        # Direct measurements and target-attributed roof bands already identify
        # a roof reference. A broader fitted envelope must not silently replace
        # that reference with a higher neighbouring plane or rooftop structure.
        geometry=sample.get(strings.BuildingHeightFields.BUILDING_SURFACES,{})
        shared_conflict='shared_roof_storey_conflict' in row[strings.BuildingHeightFields.FLAGS]
        local_storey_conflict=(strings.BuildingHeightReason.ADJACENT_ROOF_STOREY_CONFLICT
                               in row[strings.BuildingHeightFields.FLAGS])
        inward_seed_owned=_inward_seed_owns_surface(
            geometry,surface,config.height.inferred_roof_tolerance_m)
        contextual_surface_conflict=('small_part_incoherent' in row[strings.BuildingHeightFields.FLAGS] and
            any(candidate.get('accepted') and candidate.get('continuous_neighbour_ids') for candidate in geometry.get('candidates',[])))
        contextual_estimator_warning=(shared_conflict or local_storey_conflict
                                      or contextual_surface_conflict)
        seed_conflict_override=contextual_estimator_warning and inward_seed_owned
        estimator_conflict=contextual_estimator_warning and not inward_seed_owned
        spatial_rejected=_spatial_rejection_conflicts_with_fallback(
            geometry,row[strings.BuildingHeightFields.GROUND_Z],row[strings.BuildingHeightFields.HEIGHT_M],
            footprint_compactness(feature.geometry),
        )
        # The footprint establishes that the mapped part exists. Rejecting a
        # LiDAR plane as neighbour-owned must not erase an independently
        # established contextual volume.
        _record_spatial_fallback_conflict(row,spatial_rejected)
        _suppress_isolated_wall_like_fallback(row,geometry)
        if contextual_surface_conflict:row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.ADJACENT_ROOF_STOREY_CONFLICT)
        tall_sibling_conflict=geometry.get(strings.BuildingSurfaceFields.TALL_SIBLING_CONFLICT,False)
        if tall_sibling_conflict and strings.BuildingHeightReason.ADJACENT_ROOF_STOREY_CONFLICT not in row[strings.BuildingHeightFields.FLAGS]:
            row[strings.BuildingHeightFields.FLAGS].append(strings.BuildingHeightReason.ADJACENT_ROOF_STOREY_CONFLICT)
        spatial_owned=(seed_conflict_override or
            (geometry.get(strings.BuildingSurfaceFields.INDEPENDENT_INTERIOR,False)
             and geometry.get(strings.BuildingSurfaceFields.ENVELOPE_REQUIRED,False)
             and not estimator_conflict))
        if surface:surface['applied_to_height']=False
        _apply_boundary_shared_roof(row,geometry,config.height.near_zero_m)
        # Qualified modes/bands are retained unless independent geometric
        # controls establish a continuous inclined or comparable stepped roof.
        # An uncertain boundary-only shared-roof conflict cannot bypass the
        # estimator's contextual inference through an envelope fallback.
        preserve_contextual_height=tall_sibling_conflict and row[strings.BuildingHeightFields.HEIGHT_M] is not None
        preserve_boundary_shared_height=(row[strings.BuildingHeightFields.METHOD]
            ==strings.HeightEstimationMethod.BOUNDARY_SHARED_ROOF)
        if surface and surface['accepted'] and not estimator_conflict and not preserve_contextual_height and not preserve_boundary_shared_height and (spatial_owned or row[strings.BuildingHeightFields.METHOD] not in (strings.HeightEstimationMethod.DIRECT,strings.HeightEstimationMethod.ROOF_BAND)):
            surface['applied_to_height']=True
            row[strings.BuildingHeightFields.HEIGHT_M]=surface['roof_z']-row[strings.BuildingHeightFields.GROUND_Z]
            row[strings.BuildingHeightFields.ROOF_REFERENCE_Z]=surface['roof_z']
            row[strings.BuildingHeightFields.METHOD]=strings.HeightEstimationMethod.ROOF_SURFACE
            row[strings.BuildingHeightFields.REFERENCE_PART_ID]=None
            row[strings.BuildingHeightFields.FLOOR_HEIGHT_M]=None
            row[strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION]=None
            row[strings.BuildingHeightFields.FLAGS].extend(['spatial_roof_surface','lod1_flat_surface_approximation'])
        if row[strings.BuildingHeightFields.HEIGHT_M] is None and recovery and recovery['accepted'] and not spatial_rejected:
            top=recovery['roof_z']
            row[strings.BuildingHeightFields.HEIGHT_M]=top-row[strings.BuildingHeightFields.GROUND_Z]
            row[strings.BuildingHeightFields.ROOF_REFERENCE_Z]=top
            row[strings.BuildingHeightFields.METHOD]=strings.HeightEstimationMethod.FOOTPRINT_RECOVERY
            row[strings.BuildingHeightFields.REFERENCE_PART_ID]=None
            row[strings.BuildingHeightFields.FLOOR_HEIGHT_M]=None
            row[strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION]=None
            row[strings.BuildingHeightFields.FLAGS].extend(['roof_class_override','lod1_flat_surface_approximation'])
        row["sampled_roof_points"] = len(sample[strings.BuildingHeightFields.ROOF_Z])
        row[strings.SourceObjectIdentity.SOURCE_ID] = feature.id
        if config.height_source==strings.BuildingHeightSource.LIDAR and not sample[strings.LidarSamplingFields.COVERAGE_COMPLETE] and 1 in config.lods:
            row[strings.BuildingHeightFields.FLAGS].append("incomplete_lidar_coverage")
        reference = feature.properties[strings.BuildingInputFields.REFERENCE_HEIGHT_M]
        if config.height_source==strings.BuildingHeightSource.KNOWN:
            row[strings.BuildingHeightFields.HEIGHT_M] = reference if row[strings.BuildingHeightFields.GROUND_Z] is not None else None
            row[strings.BuildingHeightFields.METHOD] = strings.BuildingReconstructionMethod.KNOWN_HEIGHT if row[strings.BuildingHeightFields.HEIGHT_M] is not None else strings.HeightEstimationMethod.UNRESOLVED
            row[strings.BuildingHeightFields.FLAGS] = ["explicit_known_height_mode"] + ([strings.BuildingHeightReason.MISSING_GROUND] if row[strings.BuildingHeightFields.GROUND_Z] is None else ["missing_reference_height"] if reference is None else [])
            row[strings.BuildingHeightFields.REFERENCE_PART_ID],row[strings.BuildingHeightFields.FLOOR_HEIGHT_M] = None,None
        elif config.external_height_fallback and row[strings.BuildingHeightFields.HEIGHT_M] is None and reference is not None and row[strings.BuildingHeightFields.GROUND_Z] is not None:
            row[strings.BuildingHeightFields.HEIGHT_M],row[strings.BuildingHeightFields.METHOD] = reference,strings.BuildingReconstructionMethod.EXTERNAL_HEIGHT
            row[strings.BuildingHeightFields.FLAGS].append("explicit_external_height_fallback")
        if row[strings.BuildingHeightFields.METHOD] in (strings.BuildingReconstructionMethod.KNOWN_HEIGHT,strings.BuildingReconstructionMethod.EXTERNAL_HEIGHT):
            row[strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION] = None
            row[strings.BuildingHeightFields.ROOF_REFERENCE_Z] = None
        row[strings.BuildingInputFields.REFERENCE_HEIGHT_M] = reference
        row[strings.BuildingHeightFields.REFERENCE_ROLE] = strings.AuxiliaryHeightRole.INPUT if row[strings.BuildingHeightFields.METHOD] in (strings.BuildingReconstructionMethod.KNOWN_HEIGHT,strings.BuildingReconstructionMethod.EXTERNAL_HEIGHT) else strings.AuxiliaryHeightRole.COMPARISON
        row[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] = row[strings.BuildingHeightFields.HEIGHT_M]-reference if row[strings.BuildingHeightFields.HEIGHT_M] is not None and reference is not None and row[strings.BuildingHeightFields.REFERENCE_ROLE]==strings.AuxiliaryHeightRole.COMPARISON else None
        row[strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z] = row[strings.BuildingHeightFields.GROUND_Z]+row[strings.BuildingHeightFields.HEIGHT_M] if row[strings.BuildingHeightFields.GROUND_Z] is not None and row[strings.BuildingHeightFields.HEIGHT_M] is not None else None
        row[strings.ReconstructionObjectFields.STATUS] = strings.ReconstructionObjectStatus.RESOLVED if row[strings.BuildingHeightFields.GROUND_Z] is not None and (1 not in config.lods or row[strings.BuildingHeightFields.HEIGHT_M] is not None) else strings.ReconstructionObjectStatus.UNRESOLVED
        if 1 not in config.lods:
            row[strings.BuildingHeightFields.METHOD] = (strings.PointGroundMethod.LOD0 if config.dtm is None else strings.BuildingReconstructionMethod.DTM_SURFACE) if row[strings.BuildingHeightFields.GROUND_Z] is not None else strings.HeightEstimationMethod.UNRESOLVED
            row[strings.BuildingHeightFields.HEIGHT_M],row[strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z],row[strings.BuildingHeightFields.FLOOR_HEIGHT_M],row[strings.BuildingHeightFields.REFERENCE_PART_ID] = None,None,None,None
            row[strings.BuildingHeightFields.REFERENCE_ROLE] = strings.AuxiliaryHeightRole.COMPARISON
            row[strings.HeightTrialFields.DELTA_FROM_REFERENCE_M] = None
            row[strings.BuildingHeightFields.FLAGS] = [] if row[strings.BuildingHeightFields.GROUND_Z] is not None else [strings.BuildingHeightReason.MISSING_GROUND]
        records[feature.key] = row
    if 1 in config.lods and config.height_source == strings.BuildingHeightSource.LIDAR:
        reconcile_facade_roofs(features, records, config)
    if config.roof_regions.enabled:
        from .io.roof_regions import reconstruct_roof_regions
        reconstruct_roof_regions(config,root,features,records,samples,working,progress)
    unresolved = [r for r in records.values() if r[strings.ReconstructionObjectFields.STATUS]==strings.ReconstructionObjectStatus.UNRESOLVED]
    excluded = [f for f in features if f.issues]
    if unresolved and config.unresolved_objects==strings.InputFailurePolicy.ERROR:
        raise ValueError(f"{len(unresolved)} objects unresolved; no outputs written under the error policy")
    models = {}
    checks = {}
    for lod in config.lods:
        model = build_cityjson(features,records,config,lod)
        checks[str(lod)] = validate_cityjson(model)
        models[lod] = model
    terrain=artifacts.get('terrain_model')
    scene=None
    if terrain is not None and 1 in models:
        scene=combine_ground_scene(models[1],terrain)
        cloud['terrain']['scene_checks']=validate_cityjson(scene)
    status = strings.ReconstructionRunStatus.PARTIAL if excluded or unresolved else strings.ReconstructionRunStatus.COMPLETE
    versions = {}
    for name in ("lodext","numpy","shapely","pyproj","rasterio","laspy","lazrs"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not_installed"
    summary = {strings.ReconstructionRunFields.STATUS:status,strings.DatasetIdentityFields.DATASET_ID:config.dataset_id,strings.ReconstructionRunFields.SOURCE_OBJECTS:len(features),
               "source_buildings":sum(f.kind==strings.BuildingObjectType.BUILDING for f in features),"source_parts":sum(f.kind==strings.BuildingObjectType.BUILDING_PART for f in features),
               "resolved_units":sum(r[strings.ReconstructionObjectFields.STATUS]==strings.ReconstructionObjectStatus.RESOLVED for r in records.values()),
               "unresolved_units":len(unresolved),"excluded_objects":len(excluded),
               strings.BuildingHeightFields.METHODS:dict(Counter(r.get(strings.BuildingHeightFields.METHOD,strings.ReconstructionObjectStatus.EXCLUDED) for r in records.values())),"models":checks}
    report = {strings.ReportEnvelopeFields.VERSION:strings.ReportSchemaVersion.QUALITY,strings.ReconstructionRunFields.SUMMARY:summary,strings.ReconstructionRunFields.CLOUD:cloud,
              strings.QualityReportFields.OBJECTS:[{"key":f.key,strings.SourceObjectIdentity.SOURCE_ID:f.id,strings.SourceObjectIdentity.KIND:f.kind,"parent_id":f.parent_id,
                          strings.ReconstructionObjectFields.ISSUES:f.issues,"parent_relation":f.parent_relation,**records.get(f.key,{strings.ReconstructionObjectFields.STATUS:strings.ReconstructionObjectStatus.PARENT,strings.BuildingHeightFields.FLAGS:[]})} for f in features]}
    manifest = {"run_version":strings.ReportSchemaVersion.BUILDING_RUN,strings.ReconstructionRunFields.CREATED_AT_UTC:datetime.now(timezone.utc).isoformat(),
                "configuration":config.effective(),strings.ReconstructionRunFields.VERSIONS:versions,strings.ReconstructionRunFields.SUMMARY:summary,
                strings.GeospatialInputFields.VERTICAL_REFERENCE:config.vertical_reference,strings.TileConversionFields.CLAMPING_APPLIED:False,
                strings.ReconstructionRunFields.INPUTS:{"configuration_sha256":hashlib.sha256(config_path.read_bytes()).hexdigest(),
                          "footprints_sha256":hashlib.sha256((root/config.footprints).read_bytes()).hexdigest()},
                "outputs":[f"model.lod{lod}.city.json" for lod in config.lods]+[strings.ReconstructionOutputFiles.QUALITY,strings.ReconstructionOutputFiles.OBJECTS_CSV,strings.ReconstructionOutputFiles.RUN]}
    if terrain is not None:manifest['outputs'].append(strings.PointGroundFiles.TERRAIN)
    if scene is not None:manifest['outputs'].append(strings.PointGroundFiles.SCENE)
    if 'ground_points_path' in artifacts:manifest['outputs'].append(strings.PointGroundFiles.POINTS)
    # Do all geometry work/checks first. A failed reception or build leaves no run.
    output.mkdir(parents=True,exist_ok=False)
    for lod,model in models.items():
        dump(output/f"model.lod{lod}.city.json",model)
    if terrain is not None:dump(output/strings.PointGroundFiles.TERRAIN,terrain)
    if scene is not None:dump(output/strings.PointGroundFiles.SCENE,scene)
    if 'ground_points_path' in artifacts:shutil.copyfile(artifacts['ground_points_path'],output/strings.PointGroundFiles.POINTS)
    dump(output/strings.ReconstructionOutputFiles.QUALITY,report)
    dump(output/strings.ReconstructionOutputFiles.RUN,manifest)
    columns = ["key",strings.SourceObjectIdentity.SOURCE_ID,strings.SourceObjectIdentity.KIND,"parent_id",strings.ReconstructionObjectFields.STATUS,strings.BuildingHeightFields.METHOD,strings.BuildingHeightFields.HEIGHT_M,strings.BuildingHeightFields.GROUND_Z,strings.PointGroundFields.METHOD,strings.PointGroundFields.EXCLUDED_INSIDE,strings.PointGroundFields.Z_MIN,strings.PointGroundFields.Z_MAX,strings.PointGroundFields.MEDIAN_ERROR_BOUND,strings.BuildingHeightFields.RECONSTRUCTED_TOP_Z,strings.BuildingHeightFields.REFERENCE_ROLE,strings.BuildingInputFields.REFERENCE_HEIGHT_M,strings.BuildingHeightFields.REFERENCE_PART_ID,strings.BuildingHeightFields.FLOOR_HEIGHT_M,strings.BuildingHeightFields.INFERRED_ROOF_SUPPORT_FRACTION,strings.BuildingHeightFields.ROOF_REFERENCE_Z,strings.BuildingHeightFields.N_POINTS,"sampled_roof_points",strings.BuildingHeightFields.DENSITY_POINTS_M2,strings.BuildingHeightFields.FLAGS,strings.ReconstructionObjectFields.ISSUES]
    with (output/strings.ReconstructionOutputFiles.OBJECTS_CSV).open("w",encoding=strings.TextFileEncoding.UTF8,newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for row in report[strings.QualityReportFields.OBJECTS]:
            writer.writerow({k:";".join(row[k]) if k in (strings.BuildingHeightFields.FLAGS,strings.ReconstructionObjectFields.ISSUES) else row.get(k) for k in columns})
    progress("export",summary)
    return summary


def _accepted_attributed_roof_z(sample):
    """Return only a structurally owned and usable flat LoD1 elevation.

    ``building_surfaces.accepted`` establishes XYZ ownership. The separate
    ``roof_surface.accepted`` result establishes that the area-oriented LoD1
    reduction has positive configured clearance above ground. A rejected
    reduction remains auditable but cannot calibrate siblings or enter the
    immutable height-estimator contract.
    """
    ownership=sample.get(strings.BuildingHeightFields.BUILDING_SURFACES,{})
    reduction=sample.get('roof_surface',{})
    if (not ownership.get('accepted',False) or not reduction.get('accepted',False)
            or not ownership.get(strings.BuildingSurfaceFields.SIBLING_CALIBRATION_ALLOWED,False)):
        return None
    return reduction.get(strings.BuildingHeightFields.ROOF_Z)


def _accepted_local_context_roof_z(sample):
    """Return an owned interior roof usable only by an explicit local neighbour.

    Parent-wide calibration can be unsafe for a multilevel body, so this route
    intentionally ignores ``sibling_calibration_allowed``. It still requires
    accepted ownership, positive LoD1 reduction and independent interior XYZ;
    :class:`PartObservation` prevents this value from becoming a global anchor.
    """
    ownership=sample.get(strings.BuildingHeightFields.BUILDING_SURFACES,{})
    reduction=sample.get(strings.BuildingHeightFields.ROOF_SURFACE,{})
    if (not ownership.get('accepted',False) or not reduction.get('accepted',False)
            or ownership.get(strings.BuildingSurfaceFields.LOCAL_STOREY_ALIGNED,False)
            or ownership.get(strings.BuildingSurfaceFields.BOUNDARY_SHARED_ROOF_Z) is not None
            or not ownership.get(strings.BuildingSurfaceFields.INDEPENDENT_INTERIOR,False)):
        return None
    return reduction.get(strings.BuildingHeightFields.ROOF_Z)


def _inward_seed_owns_surface(geometry,surface,tolerance_m):
    """Recognise a selected roof that starts inside its mapped footprint.

    A contextual storey warning cannot erase an accepted geometric surface
    whose matching candidate grows from the footprint interior and has no
    positive ownership rejection. Boundary-only or neighbour-rejected planes
    remain blocked.
    """
    if not surface or not surface.get('accepted') or not geometry.get('accepted'):
        return False
    if geometry.get('rejected_neighbour_planes'):
        return False
    roof=surface.get(strings.BuildingHeightFields.ROOF_Z)
    if not isinstance(roof,(int,float)) or not math.isfinite(roof):return False
    return any(candidate.get('accepted')
               and candidate.get(strings.BuildingSurfaceFields.INWARD_SEED_SUPPORT,False)
               and isinstance(candidate.get(strings.BuildingHeightFields.ROOF_Z),(int,float))
               and abs(candidate[strings.BuildingHeightFields.ROOF_Z]-roof)<=tolerance_m
               for candidate in geometry.get('candidates',[]))


def combine_ground_scene(buildings,terrain):
    """Merge ground onto the building model's existing grid without moving it.

    Building vertices/relationships remain byte-for-byte equivalent as data.
    Only terrain indices are remapped and terrain coordinates quantized to the
    common grid. This creates a viewable scene, not stitched scene topology.
    """
    from .export.cityjson import Vertices
    import numpy as np
    scene=deepcopy(buildings)
    step=scene['transform']['scale'][0];origin=scene['transform']['translate']
    vertex=Vertices(step,origin);vertex.vertices=scene['vertices'];vertex.index={tuple(v):i for i,v in enumerate(vertex.vertices)}
    scale=terrain['transform']['scale'];offset=terrain['transform']['translate']
    mapping=[vertex(tuple(v[i]*scale[i]+offset[i] for i in range(3))) for v in terrain['vertices']]
    for key,obj in terrain['CityObjects'].items():
        if key in scene['CityObjects']:raise ValueError('Ground object identity collides with a source object')
        copied=deepcopy(obj)
        for geometry in copied['geometry']:
            geometry['boundaries']=[[[mapping[i] for i in ring] for ring in face] for face in geometry['boundaries']]
        scene['CityObjects'][key]=copied
    coords=np.asarray(scene['vertices'])*step+np.asarray(origin)
    scene['metadata']['geographicalExtent']=[*coords.min(axis=0).tolist(),*coords.max(axis=0).tolist()]
    scene['metadata']['identifier']+='-with-ground';scene['lodext']['stitching_applied']=False
    return scene
