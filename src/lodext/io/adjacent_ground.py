"""Infer missing interior bases from original same-building adjacent ground."""
from collections import defaultdict
from shapely import STRtree
from lodext import strings
from lodext.core.adjacent_ground import (AdjacentGroundEvidence,AdjacentGroundReference,
    AdjacentGroundSelection,AdjacentGroundTrigger)
from lodext.core.heights import modal_roof


def _boundary_graph(c,units):
    """Return positive shared-boundary edges for one explicit parent group."""
    tree=STRtree([f.geometry for f in units]);edges=[{} for _ in units]
    for i,f in enumerate(units):
        for j in tree.query(f.geometry.buffer(c.tolerance_m)):
            j=int(j)
            if j<=i:continue
            other=units[j].geometry
            if f.geometry.intersection(other).area>c.tolerance_m**2:continue
            shared=f.geometry.boundary.intersection(other.boundary.buffer(c.tolerance_m) if c.tolerance_m else other.boundary).length
            if shared>=c.min_shared_boundary_m:edges[i][j]=shared;edges[j][i]=shared
    return edges


def _nearest_frontier(target,edges,anchors,max_hops):
    """Find nearest anchored graph frontier with path bottleneck weights."""
    visited={target};frontier={target:(float('inf'),[target])};references={}
    for hop in range(1,max_hops+1):
        next_frontier={}
        for i,(weight,path) in sorted(frontier.items()):
            for j,shared in sorted(edges[i].items()):
                if j in visited:continue
                candidate=(min(weight,shared),path+[j]);current=next_frontier.get(j)
                if current is None or candidate[0]>current[0] or (candidate[0]==current[0] and candidate[1]<current[1]):next_frontier[j]=candidate
        references={j:v for j,v in next_frontier.items() if j in anchors}
        if references or not next_frontier:return hop,references
        visited.update(next_frontier);frontier=next_frontier
    return max_hops,references


def _weighted_median(ordered,references):
    """Select lower exact-tie weighted median from ground-sorted indices."""
    half=sum(references[i][0] for i in ordered)/2;weight=0
    for selected in ordered:
        weight+=references[selected][0]
        if weight>=half:return selected


def infer_adjacent_ground(config,features,samples):
    """Mutate missing sample bases using nearest-frontier measured neighbours.

    Build a metric shared-boundary graph within explicit parent groups. Exclude
    positive-area overlaps (possible stacking), isolated vertex contacts and
    other buildings. References are a frozen snapshot of originally available
    ground values. Breadth-first paths can cross missing-base parts, but no
    inferred result becomes independent reference evidence. At the first
    anchored hop choose a shared-boundary bottleneck weighted median; exact
    half-weight ties choose the lower observed reference. Conflicting references
    remain visible as uncertainty, not a silently invented average or roof shift.
    """
    c=config.adjacent_ground
    if not c.enabled or config.geometry_mode!='parts':return
    groups=defaultdict(list)
    for f in features:
        if f.kind=='BuildingPart' and not f.issues and f.key in samples:groups[f.parent_id].append(f)
    for units in groups.values():
        units.sort(key=lambda f:f.key)
        anchors={i:samples[f.key]['ground_z'] for i,f in enumerate(units) if samples[f.key]['ground_z'] is not None}
        missing=[i for i in range(len(units)) if i not in anchors]
        if not anchors or not missing:continue
        edges=_boundary_graph(c,units)
        for target in missing:
            hop,references=_nearest_frontier(target,edges,anchors,c.max_hops)
            if not references:continue
            ordered=sorted(references,key=lambda i:(anchors[i],units[i].key));selected=_weighted_median(ordered,references)
            zs=[anchors[i] for i in ordered];spread=max(zs)-min(zs);sample=samples[units[target].key]
            sample['ground_z']=anchors[selected]
            sample[strings.PointGroundFields.METHOD]=strings.PointGroundMethod.ADJACENT
            sample[strings.PointGroundFields.MEDIAN_ERROR_BOUND]=None
            sample[strings.PointGroundFields.Z_MIN]=None;sample[strings.PointGroundFields.Z_MAX]=None
            sample[strings.BuildingHeightFields.ADJACENT_GROUND]=AdjacentGroundEvidence(accepted=True,hops=hop,selection=AdjacentGroundSelection.MISSING_BASE,
                selected_reference_id=units[selected].key,reference_spread_m=spread,conflicting_references=spread>c.disagreement_m,
                references=[AdjacentGroundReference(id=units[i].key,ground_z=anchors[i],boundary_weight_m=references[i][0],
                              path=[units[j].key for j in references[i][1]]) for i in ordered])


def reconcile_exterior_planes(config, features, samples):
    """Select the flat LoD base from agreeing measured exterior planes along a shared edge."""
    policy = config.adjacent_ground
    if not policy.enabled:
        return
    groups = defaultdict(list)
    for part in features:
        if (part.parent_id and not part.issues and samples.get(part.key, {}).get('ground_plane')
                and not samples[part.key].get('adjacent_ground')):
            groups[part.parent_id].append(part)
    for parts in groups.values():
        edges = _boundary_graph(policy, parts)
        pending = []
        for i, part in enumerate(parts):
            sample = samples[part.key]
            plane = sample['ground_plane']
            sparse = plane['cells'] <= 4 and plane['slope_deg'] > 15
            refs = []
            for j, length in edges[i].items():
                body = parts[j]
                ref = samples[body.key]
                rp = ref['ground_plane']
                if rp['cells'] <= plane['cells'] or rp['slope_deg'] > 6:
                    continue
                gap = sample['ground_z'] - ref['ground_z']
                if gap <= config.building_surfaces.residual_m:
                    continue
                facade = (body.geometry.area > 10 * part.geometry.area
                          and length >= part.geometry.length / 4
                          and sample['ground_z'] <= ref['ground_max_z']
                          and abs(plane['slope_deg'] - rp['slope_deg']) <= 2)
                if facade or (sparse and gap > policy.disagreement_m):
                    refs.append((length, body.key, ref['ground_z']))
            if not refs:
                continue
            length, key, z = max(refs)
            if sparse and sum(w for w, _, _ in refs) <= sum(edges[i].values()) / 2:
                continue
            if max(v for _, _, v in refs) - min(v for _, _, v in refs) > policy.disagreement_m:
                continue
            pending.append((sample, z, key, part.key, length))
        for sample, z, key, target, length in pending:
            sample['adjacent_ground'] = AdjacentGroundEvidence(accepted=True, hops=1,
                selection=AdjacentGroundSelection.IMPLAUSIBLE_BASE, selected_reference_id=key,
                reference_spread_m=0., conflicting_references=False, original_ground_z=sample['ground_z'],
                trigger=AdjacentGroundTrigger.EXTERIOR_PLANE, references=[AdjacentGroundReference(
                    id=key, ground_z=z, boundary_weight_m=length, path=[target,key])])
            sample['ground_z'] = z
            sample['ground_method'] = strings.PointGroundMethod.ADJACENT


def reconcile_inconsistent_ground(config,features,samples):
    """Replace only physically contradictory bases with majority neighbour evidence.

    LAS labels never participate. A target must have a dominant own-footprint Z,
    positive declared storeys and an original measured base. The base is reviewed
    when the roof is not above it. Declared storeys add a second trigger when
    the implied per-storey height is below the configured plausible range by
    the existing coherence ratio, but they are not required to detect the
    physical roof/base contradiction. The nearest
    shared-boundary frontier must contain one unique strict-majority cluster of
    plausible original bases. This protects slopes, tall halls, low terraces and
    ambiguous split levels from automatic normalization.
    """
    c=config.adjacent_ground
    if not c.enabled or config.geometry_mode!='parts':return
    groups=defaultdict(list)
    all_units=[]
    for f in features:
        if f.kind=='BuildingPart' and not f.issues and f.key in samples:
            groups[f.parent_id].append(f);all_units.append(f)
    def reconcile_units(units,allow_reconciled=False):
        units.sort(key=lambda f:f.key);edges=_boundary_graph(c,units);observed={};anchors={}
        for i,f in enumerate(units):
            sample=samples[f.key];ground=sample.get(strings.BuildingHeightFields.GROUND_Z);storeys=f.properties.get(strings.BuildingInputFields.STOREYS_ABOVE)
            roof=tuple(sample.get(strings.BuildingHeightFields.ROOF_Z,()))
            mode=modal_roof(roof,config.height)[0] if roof else None
            raw=mode-ground if mode is not None and ground is not None else None
            observed[i]=(ground,mode,raw,storeys)
            transferred=(allow_reconciled and strings.BuildingHeightFields.ADJACENT_GROUND in sample)
            if (ground is not None and ((transferred) or
                    (strings.BuildingHeightFields.ADJACENT_GROUND not in sample and raw is not None
                     and raw>=config.height.near_zero_m
                     and (not storeys or raw/storeys>=config.height.min_floor_height_m/config.height.coherence_max_ratio)))):
                anchors[i]=ground
        for target,(ground,mode,raw,storeys) in observed.items():
            sample=samples[units[target].key]
            if ground is None or mode is None or strings.BuildingHeightFields.ADJACENT_GROUND in sample:continue
            if raw<config.height.near_zero_m:trigger=AdjacentGroundTrigger.ROOF_NOT_ABOVE_GROUND
            elif storeys and raw/storeys<config.height.min_floor_height_m/config.height.coherence_max_ratio:trigger=AdjacentGroundTrigger.IMPLAUSIBLE_STOREY_RATIO
            else:continue
            hop,references=_nearest_frontier(target,edges,{i:z for i,z in anchors.items() if i!=target},c.max_hops)
            if not references:continue
            total=sum(weight for weight,_ in references.values());clusters={}
            for i in references:
                members=frozenset(j for j in references if abs(anchors[j]-anchors[i])<=c.disagreement_m)
                clusters[members]=sum(references[j][0] for j in members)
            maximum=max(clusters.values());weight_tolerance=max(1e-9,c.tolerance_m)
            winners=[members for members,weight in clusters.items() if maximum-weight<=weight_tolerance]
            if len(winners)!=1 or maximum-total/2<=weight_tolerance:continue
            accepted=winners[0];accepted_refs={i:references[i] for i in accepted}
            ordered=sorted(accepted,key=lambda i:(anchors[i],units[i].key));selected=_weighted_median(ordered,accepted_refs);replacement=anchors[selected]
            if (abs(replacement-ground)<=c.disagreement_m and
                    trigger!=AdjacentGroundTrigger.ROOF_NOT_ABOVE_GROUND):continue
            if mode-replacement<config.height.near_zero_m:continue
            spread=max(anchors[i] for i in ordered)-min(anchors[i] for i in ordered)
            sample[strings.BuildingHeightFields.GROUND_Z]=replacement
            sample[strings.PointGroundFields.METHOD]=strings.PointGroundMethod.ADJACENT
            sample[strings.PointGroundFields.MEDIAN_ERROR_BOUND]=None
            sample[strings.PointGroundFields.Z_MIN]=None;sample[strings.PointGroundFields.Z_MAX]=None
            sample[strings.BuildingHeightFields.ADJACENT_GROUND]=AdjacentGroundEvidence(accepted=True,hops=hop,selection=AdjacentGroundSelection.IMPLAUSIBLE_BASE,
                selected_reference_id=units[selected].key,reference_spread_m=spread,conflicting_references=False,original_ground_z=ground,trigger=trigger,
                references=[AdjacentGroundReference(id=units[i].key,ground_z=anchors[i],boundary_weight_m=accepted_refs[i][0],
                              path=[units[j].key for j in accepted_refs[i][1]]) for i in ordered])
    # Prefer the explicit building's own parts. If they cannot establish an
    # access level, repeat the same strict physical-contradiction test across
    # directly connected mapped buildings. Corrected values never become
    # anchors in the second pass, so inference cannot cascade across a block.
    for units in groups.values():reconcile_units(units)
    reconcile_units(all_units)
    # A cross-building access reference may then serve the remaining parts of
    # that same explicit building. The propagation is deliberately bounded to
    # its parent and cannot continue through another building.
    for units in groups.values():reconcile_units(units,allow_reconciled=True)
