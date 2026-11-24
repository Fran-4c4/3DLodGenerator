"""Modal roof height with explicit reliability and within-building fallbacks.

This is a new implementation of the documented method, not a runtime import of
the source system. It intentionally fixes the unreachable density path and does
not invent ground, storeys or a worldwide regional floor height.
"""
from __future__ import annotations
from lodext import strings

from collections import Counter
from dataclasses import dataclass
import math
from statistics import median
from typing import Literal, Sequence


def finite_number(value, name):
    """Reject booleans, non-numeric values and NaN/infinity with a named error.

    Return None on success; never coerce input or supply a default. Callers
    validate the units and allowed ranges belonging to their own contracts.
    """
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(strings.ContractValidationMessages.FINITE_NUMBER.format(name=name))


@dataclass(frozen=True)
class HeightConfig:
    """Authoritative algorithm settings; parsers must use these defaults.

    roof_bin_m: metres >0; Z is rounded to nearest multiples, ties-to-even.
      Highest count wins; tied bins choose the lowest elevation deterministically.
      Strength is the fraction within ±one bin width of that mode.
    min_points_absolute: integer >=min_points_statistical; absolute evidence
      route. Density can independently satisfy quantity, but never the hard
      statistical floor. This avoids the source's unreachable density route.
    min_points_statistical: integer >=3; absolute minimum even for high density.
    min_density_points_m2: points/m² >0, or None to disable the density route.
      Denominator is the actual sample support, not the original footprint.
    min_mode_strength: fraction in (0,1]; inclusive reliability threshold.
    secondary_peak_ratio: fraction in (0,1]; a secondary bin at/above this
      proportion of the winning count, farther than bimodal_gap_m, marks a mix.
    bimodal_gap_m: metres >0; strict separation threshold. Mixed-roof strength
      is halved, matching the documented reference method; mixture remains a flag.
    coherence_max_ratio: ratio >=1; for observations explicitly marked small,
      reject height/storeys > this times the building reference floor height.
      Mandatory geometric attribution also requires competing peer surfaces to
      be separated by more than this ratio times an observed neighbouring
      floor unit before storeys may rank them. This only ranks target XYZ
      alternatives; it never caps or scales a measured roof.
    min_floor_height_m/max_floor_height_m: metres >0, ordered inclusive range
      for selecting a building floor-height reference. The upper value also
      supplies a permissive storey span and neighbour-roof matching window in
      spatial attribution, only when a supported lower alternative exists.
      Reliable direct
      observations outside the range are preserved (e.g. terraces or halls).
    near_zero_m: metres >=0; direct heights strictly below it are suspect and
      require an explicit fallback. Zero disables this additional test, while
      nonpositive measured heights always remain unresolved.
    regional_floor_height_m: None (default, no global assumption) or finite
      metres within the floor range; only used when there is no building anchor.
    anchor_consensus_min_parts: integer >=3; eligible measured references needed
      to activate the same-building consensus check. Below it use the largest
      eligible measured anchor provisionally, with area ties broken by source
      ID. Sparse contradictory references need local roof evidence under the
      inference support guard; they do not become a trustworthy majority.
    anchor_consensus_max_ratio: dimensionless >=1; max/min storey height in a
      candidate cluster. At/above the count gate require one uniquely largest
      strict-majority cluster. Choose its measured reference nearest the median,
      then larger area/source ID for equal-distance ties. Ambiguity removes the
      building anchor, not the direct measurements. There is no world-wide
      assumed storey size and no cap on measured building heights.
    inferred_roof_tolerance_m/min_inferred_roof_support: inclusive metre band
      and required fraction for adequately sampled mixed/weak target roofs in
      building-based inference. With guard enabled, an unsupported preferred
      reference can be replaced only by mutually consistent qualified candidates
      supported by those target points. Otherwise leave the height unresolved.
      Explicitly rejected small-part/near-zero returns are not independent checks;
      their fallback is labelled unverified. Zero support threshold disables this
      guard and target-band adjustment, including sparse-reference conflict rejection. Regional/known-height
      policies are separate. Support fractions are diagnostics, not confidence.

    Changes affect reliability, anchor choice and inferred heights. Invalid
    fields/cross-field combinations are rejected, never clamped. No rounding
    of final heights occurs here: serializers choose display precision.
    """

    roof_bin_m: float = 0.5  # Metres: histogram step and modal-support half-width.
    min_points_absolute: int = 12  # Sufficient quantity without the density route.
    min_points_statistical: int = 3  # Hard point-count floor for both quantity routes.
    min_density_points_m2: float | None = 3.0  # Alternative quantity route; None disables it.
    min_mode_strength: float = 0.35  # Minimum modal fraction after any mixture penalty.
    secondary_peak_ratio: float = 0.6  # Secondary-bin count relative to the winning count.
    bimodal_gap_m: float = 2.0  # Strictly greater peak separation marks a mixture.
    coherence_max_ratio: float = 1.6  # Dimensionless small-part/anchor limit; also minimum peer-level separation in observed neighbouring floor units before contextual ranking. Never a measured-height cap.
    min_floor_height_m: float = 2.5  # Lower anchor-storey bound, not a terrace minimum.
    max_floor_height_m: float = 8.0  # Upper anchor-storey bound and contextual attribution span/window; not a measured building-height cap.
    near_zero_m: float = 1.0  # Positive direct heights below this need explicit fallback.
    regional_floor_height_m: float | None = None  # Opt-in metre fallback without an anchor.
    # Dimensionless >=1: maximum largest/smallest floor-height ratio within a
    # same-building anchor cluster. At/above anchor_consensus_min_parts, only a
    # unique largest cluster containing a strict majority can supply inference.
    # Select the measured candidate nearest the cluster's median floor height;
    # area then source ID break equal-distance ties. No majority/tied clusters
    # means no building anchor. Direct observations
    # remain measurements; this controls reference selection, not a height cap.
    anchor_consensus_max_ratio: float = 1.6
    # Integer >=3: eligible direct anchors needed to activate consensus. Below
    # this count prefer the largest-qualified anchor, subject to sparse conflict
    # and local-support checks when enabled. Consumers are
    # estimate_building and serialized height settings; no global storey size.
    anchor_consensus_min_parts: int = 3
    # Metres >0, inclusive half-band around an inferred absolute roof elevation.
    # Used only for building-based inference with adequately sampled mixed/weak
    # roof observations, never
    # roof points already rejected as small-part contamination or near-zero data.
    # It does not move ground, clip a measured height or establish accuracy.
    # Also supplies slack for the permissive storey span used to distinguish a
    # low supported alternative from a competing taller sibling's roof planes.
    inferred_roof_tolerance_m: float = 1.5
    # Fraction in [0,1]; 0 disables the inference check and target-band adjustment.
    # When applicable, at least this fraction of target roof points must lie in
    # the band above. An unsupported preferred anchor may be replaced by a
    # supported qualified same-building reference. Conflicting supported floor
    # ratios or no support leave the part unresolved, not capped to a roof point.
    min_inferred_roof_support: float = 0.1

    def __post_init__(self):
        """Reject invalid thresholds and contradictory reliability/floor ranges."""
        for name in ("roof_bin_m", "min_mode_strength", "secondary_peak_ratio", "bimodal_gap_m",
                     "coherence_max_ratio", "min_floor_height_m", "max_floor_height_m", "near_zero_m", "anchor_consensus_max_ratio", "inferred_roof_tolerance_m", "min_inferred_roof_support"):
            finite_number(getattr(self, name), name)
        for name in ("min_points_absolute", "min_points_statistical", "anchor_consensus_min_parts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.min_points_statistical < 3 or self.min_points_absolute < self.min_points_statistical:
            raise ValueError("Point thresholds must satisfy absolute >= statistical >= 3")
        if self.anchor_consensus_min_parts < 3 or self.anchor_consensus_max_ratio < 1:
            raise ValueError("Anchor consensus requires at least 3 candidates and ratio >=1")
        if self.inferred_roof_tolerance_m <= 0 or not 0 <= self.min_inferred_roof_support <= 1:
            raise ValueError("Inference support requires positive metre tolerance and fraction in [0,1]")
        if min(self.roof_bin_m, self.bimodal_gap_m, self.min_floor_height_m) <= 0:
            raise ValueError("Histogram width, peak gap and minimum floor height must be positive")
        if not 0 < self.min_mode_strength <= 1 or not 0 < self.secondary_peak_ratio <= 1:
            raise ValueError("Strength and peak-ratio fractions must be in (0,1]")
        if self.coherence_max_ratio < 1 or self.max_floor_height_m < self.min_floor_height_m or self.near_zero_m < 0:
            raise ValueError("Invalid coherence, floor range or near-zero threshold")
        if self.min_density_points_m2 is not None:
            finite_number(self.min_density_points_m2, "min_density_points_m2")
            if self.min_density_points_m2 <= 0:
                raise ValueError("Density must be positive; None disables it")
        if self.regional_floor_height_m is not None:
            finite_number(self.regional_floor_height_m, "regional_floor_height_m")
            if not self.min_floor_height_m <= self.regional_floor_height_m <= self.max_floor_height_m:
                raise ValueError("Regional floor height must lie within the reference range")


@dataclass(frozen=True)
class PartObservation:
    """Normalized evidence for one part; ground and roof share the trial's Z basis.

    IDs: required nonempty text; building_id is explicit, never parsed from IDs.
    area_m2: original footprint m² >0, used for anchors and relative context.
    sample_area_m2: actual crop support m² >0 and <=area_m2; density denominator.
    roof_z: finite elevations in metres already selected by the caller's
      geometry-only attribution. Empty tuple means no attributable roof points.
      Provider classes never select, reject or weight these observations.
    ground_z: finite elevation on the same local Z basis, or None (missing).
      Missing ground always prevents an estimate, including inferred heights.
    check_small_part_coherence: required bool; true means the part is smaller
      than another part in its explicit parent group and should undergo relative
      context checks. No fixed square-metre threshold is owned by the estimator.
    storeys_above/storeys_below: integer >=0 or None (unknown, the sole default).
      Zero is known zero; only positive above-ground counts support inference.
      Below-ground counts only add provenance, never increase visible height.
    attributed_roof_z: optional absolute roof elevation in metres from a
      geometrically accepted full-footprint surface. None is the sole default.
      It can supply a measured same-building floor-height anchor when the raw
      modal distribution is mixed, but does not itself create a direct estimate
      or override roof_z. The caller owns geometric acceptance; changing this
      value can change sibling floor-share inference.
    context_roof_z: immutable elevations in metres from target planes rejected
      specifically because an adjacent structure also explained them. Empty is
      the sole default. These values may verify a spatial-anchor fallback near
      its predicted top; they never anchor, select or directly set a height.
    local_storey_neighbour_ids: immutable class-qualified IDs of measured parts
      in this same batch that share a positive-length mapped boundary with a
      target lacking an owned roof, or with a boundary-dominated target. Empty
      is the authoritative default and disables local preference. A multistorey
      target refuses to extrapolate a selected one-storey local anchor: it
      reselects among listed multistorey candidates with a different, then
      closest, storey count when available. Equal-storey terraces can have
      different bases and do not establish a storey step. The estimator may use only listed, positive-storey,
      independently measured direct or attributed roofs; unknown/duplicate/self
      IDs are rejected rather than ignored. This can replace a parent-wide
      fallback reference but never changes source geometry or provider labels.
    local_context_roof_z: optional absolute roof elevation in metres from this
      part's accepted, independently interior-supported geometric surface. None
      is the sole default. Unlike attributed_roof_z it cannot enter parent-wide
      calibration; it is consumed only when another boundary-dominated part
      explicitly lists this part in local_storey_neighbour_ids. If the source
      also has unreliable raw observations, its floor scale must predict the
      target within the independent parent fallback tolerance; this prevents
      rooftop equipment or a lateral terrace reference from bypassing the
      structural roof-band decision.
    calibration_roof_z: optional absolute roof elevation in metres from this
      part's pre-local-alignment owned level. None is the sole default. It may
      enter same-parent storey-anchor selection when this part's locally aligned
      roof is withheld from calibration, but it never resolves or changes this
      part's own height. Producer: native surface attribution; consumer:
      estimate_building anchor selection.
    """

    part_id: str  # Required nonempty part identity; preserved in the estimate.
    building_id: str  # Explicit parent identity used to group parts and share an anchor.
    area_m2: float  # Original footprint area >0 m²; ranks potential building anchors.
    sample_area_m2: float  # Actual roof support area in (0, area_m2]; density denominator.
    roof_z: tuple[float, ...]  # Finite roof elevations in metres; () means no observations.
    ground_z: float | None  # Same-reference ground elevation in metres; None blocks estimation.
    check_small_part_coherence: bool  # Explicit parent-relative decision to check anchor/roof conflicts; false for the largest or sole part.
    storeys_above: int | None = None  # Above-ground count; None unknown, 0 known zero; >0 enables inference.
    storeys_below: int | None = None  # Basement count; None unknown; provenance only, never extruded.
    ground_is_measured: bool = True  # False when base was inferred from adjacent parts: own roof-minus-base estimate remains usable but cannot supply a measured storey-height anchor to other parts. True preserves existing injected/measured evidence semantics.
    attributed_roof_z: float | None = None  # Accepted geometry-only absolute roof Z in metres; None supplies no anchor. Used only for same-parent storey calibration, never as a direct result by itself.
    context_roof_z: tuple[float, ...] = ()  # Target-plane Z rejected as explained by adjacent structures; verifies spatial fallback only. Empty supplies no local verification.
    local_storey_neighbour_ids: tuple[str, ...] = ()  # Same-batch same-parent positive-boundary neighbours selected for local storey calibration when the target lacks an owned roof or is boundary-dominated; a multistorey target prefers listed multistorey candidates with a different, then closest, storey count because equal-storey terraces may have different bases. () disables local preference. Producer: native attribution/pipeline; consumer: estimate_building.
    local_context_roof_z: float | None = None  # Accepted independently interior-supported roof Z for explicit local neighbours; with unreliable raw observations it is eligible only when its predicted target top is coherent with the independent parent fallback. None supplies no local anchor and it never enters parent-wide calibration.
    calibration_roof_z: float | None = None  # Pre-local-alignment absolute roof Z used only for same-parent storey-anchor selection; None supplies no anchor and this field never resolves its own part.

    def __post_init__(self):
        """Validate immutable evidence, sample-area bounds and explicit storeys."""
        if any(not isinstance(v, str) or not v.strip() for v in (self.part_id, self.building_id)):
            raise ValueError("Part and building IDs must be nonempty strings")
        for name in (strings.PolygonFootprintFields.AREA_M2, strings.BuildingHeightFields.SAMPLE_AREA_M2):
            finite_number(getattr(self, name), name)
        if self.area_m2 <= 0 or self.sample_area_m2 <= 0 or self.sample_area_m2 > self.area_m2:
            raise ValueError("Sample area must be positive and cannot exceed the footprint")
        if not isinstance(self.check_small_part_coherence, bool):
            raise ValueError("Small-part coherence decision must be explicit boolean")
        if type(self.ground_is_measured) is not bool:raise ValueError('ground_is_measured must be boolean')
        for name in (strings.BuildingInputFields.STOREYS_ABOVE, strings.BuildingInputFields.STOREYS_BELOW):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.ground_z is not None:
            finite_number(self.ground_z, strings.BuildingHeightFields.GROUND_Z)
        if self.attributed_roof_z is not None:
            finite_number(self.attributed_roof_z, 'attributed_roof_z')
            if self.ground_z is None or self.attributed_roof_z <= self.ground_z:
                raise ValueError('attributed_roof_z requires measured positive clearance above ground')
        if self.local_context_roof_z is not None:
            finite_number(self.local_context_roof_z, 'local_context_roof_z')
            if self.ground_z is None or self.local_context_roof_z <= self.ground_z:
                raise ValueError('local_context_roof_z requires measured positive clearance above ground')
        if self.calibration_roof_z is not None:
            finite_number(self.calibration_roof_z, 'calibration_roof_z')
            if self.ground_z is None or self.calibration_roof_z <= self.ground_z:
                raise ValueError('calibration_roof_z requires measured positive clearance above ground')
        if not isinstance(self.context_roof_z,tuple):raise ValueError('context_roof_z must be an immutable tuple')
        for value in self.context_roof_z:finite_number(value,'context_roof_z')
        if (not isinstance(self.local_storey_neighbour_ids,tuple)
                or any(not isinstance(value,str) or not value.strip() for value in self.local_storey_neighbour_ids)
                or len(set(self.local_storey_neighbour_ids))!=len(self.local_storey_neighbour_ids)
                or self.part_id in self.local_storey_neighbour_ids):
            raise ValueError('local_storey_neighbour_ids must be unique nonempty other-part IDs in a tuple')
        if not isinstance(self.roof_z, tuple):
            raise ValueError("roof_z must be an immutable tuple")
        for value in self.roof_z:
            finite_number(value, strings.BuildingHeightFields.ROOF_Z)


@dataclass(frozen=True)
class HeightEstimate:
    """Auditable outcome; no field here is an absolute geodetic datum assertion.

    height_m: positive visible height, or None when unresolved. ground_z and
      roof_mode_z preserve their original local elevations separately.
    method: direct | roof_band | floor_share | regional | unresolved. roof_band
      uses the upper observed Z of the highest stable local peak compatible with the qualified reference
      context; height is that observed band Z minus ground. Context attribution
      is not labelled an unambiguous direct observation. Storey multiplication
      is confined to explicitly inferred floor_share/regional outcomes.
    n_points/density_points_m2/roof_strength/bimodal: quantity and modal evidence,
      including the mixture penalty when applicable. Density uses sample area.
    floor_height_m: direct height/storeys when known, reference floor size for
      band attribution or multiplier for inference; None when unavailable.
    reference_part_id: explicit same-building anchor for roof_band/floor_share,
      otherwise None. flags preserve attribution and rejected direct evidence.
    IDs preserve the input identity; no serializer precision is imposed.
    """

    part_id: str  # Input part identity, retained for joining results to evidence.
    building_id: str  # Explicit building identity; fallback never crosses this group.
    height_m: float | None  # Positive height above ground in metres; None is unresolved.
    method: Literal["direct", "roof_band", "floor_share", "regional", "unresolved"]  # Evidence/inference route, not a quality score.
    ground_z: float | None  # Input ground elevation in metres; None remains missing.
    roof_mode_z: float | None  # Observed binned roof elevation; None without roof points, not a fallback top.
    n_points: int  # Number of supplied roof observations, including rejected direct evidence.
    density_points_m2: float  # n_points / actual sample support area, not original footprint area.
    roof_strength: float  # Modal-support fraction in [0,1], after any mixture penalty.
    bimodal: bool  # Strong separated secondary peak detected; does not alone force rejection.
    floor_height_m: float | None  # Measured ratio, band-attribution reference or inferred metre multiplier; None unavailable.
    reference_part_id: str | None  # Same-building context anchor for roof_band/floor_share; None for other methods.
    flags: tuple[str, ...]  # Stable diagnostic codes consumed by quality reports, including successful fallbacks.
    inferred_roof_support_fraction: float | None = None  # Fraction [0,1] of target roof points within the configured inferred-roof band. None (sole default) means not checked, including direct estimates, insufficient/rejected support or disabled guard; 0 is checked with no supporting points. Output evidence in quality/CityJSON/CSV, not a confidence probability or accuracy measure.
    roof_reference_z: float | None = None  # Absolute source-Z roof reference in metres: direct mode or upper observed Z of the highest stable local histogram peak attributed using same-building context. Height is this Z minus ground when present. None (sole default) means no attributable local reference; floor-share remains explicitly inferred. Not a raw maximum across competing planes or a reconstructed pitched plane.


def modal_roof(z: tuple[float, ...], config: HeightConfig):
    """Summarise finite roof elevations in metres as (mode Z, strength, mixed).

    Bins use HeightConfig's step with ties-to-even rounding; equal counts select
    the lowest bin. Strength measures points within one step of the winning Z
    and is halved for a strong separated peak. Empty input returns (None, 0,
    False). This statistic alone does not establish a reliable building height;
    estimate_building also checks ground, quantity and per-building coherence.
    """
    if not z:
        return None, 0.0, False
    histogram = Counter(round(value / config.roof_bin_m) for value in z)
    winning_count = max(histogram.values())
    winning_bin = min(b for b, count in histogram.items() if count == winning_count)
    mode = winning_bin * config.roof_bin_m
    strength = sum(abs(value - mode) <= config.roof_bin_m for value in z) / len(z)
    bimodal = any(count >= winning_count * config.secondary_peak_ratio
                  and abs(b - winning_bin) * config.roof_bin_m > config.bimodal_gap_m
                  for b, count in histogram.items())
    return mode, strength * (0.5 if bimodal else 1.0), bimodal


def roof_band_candidates(z: tuple[float, ...], config: HeightConfig):
    """Return stable local Z-band peaks, ascending, without assigning ownership.

    Use the existing histogram step and statistical point floor. A peak must
    contain that many points and have the configured minimum target support in
    ±one bin width. A flat histogram plateau selects its upper end. Isolated
    returns cannot establish a roof. Footprint/class sampling precedes this;
    estimate_building attributes competing bands with same-building evidence.
    No percentile, raw maximum, Z translation or geometric roof split is used.
    """
    histogram = Counter(round(value/config.roof_bin_m) for value in z)
    return sorted(b*config.roof_bin_m for b,count in histogram.items()
                  if count>=config.min_points_statistical
                  and count>=histogram.get(b-1,0) and count>histogram.get(b+1,0)
                  and sum(abs(value-b*config.roof_bin_m)<=config.roof_bin_m for value in z)/len(z)>=config.min_inferred_roof_support)


def estimate_building(parts: Sequence[PartObservation], config: HeightConfig | None = None):
    """Return one auditable HeightEstimate per part, in input order, without I/O.

    Require unique part IDs belonging to one explicit building; empty input
    returns []. None config selects HeightConfig's defaults. First evaluate
    modal roofs, count-or-density support and roof-minus-ground height. Then
    choose a same-building measured floor-height anchor. With enough eligible
    candidates, require a unique majority cluster and select the measured
    candidate nearest its median; otherwise use the largest qualified part.
    This protects inference from an isolated ground/storey exception without
    replacing reliable direct measurements with a generic storey height.

    Reliable direct heights take priority, subject to the small-part coherence
    check. Unresolved parts with positive storeys may share that anchor or use
    an explicitly configured regional floor height. Missing ground and
    nonpositive measured heights never acquire invented geometry. Rejections
    and inference remain in flags/method; results are not rounded here.
    """
    config = HeightConfig() if config is None else config
    if not isinstance(config, HeightConfig):
        raise TypeError("config must be HeightConfig or None")
    if not parts:
        return []
    if len({p.building_id for p in parts}) != 1 or len({p.part_id for p in parts}) != len(parts):
        raise ValueError("A batch requires one building and unique part IDs")
    measurements = {}
    quantities = {}
    for part in parts:
        mode, strength, mixed = modal_roof(part.roof_z, config)
        n = len(part.roof_z)
        density = n / part.sample_area_m2
        enough = n >= config.min_points_statistical and (
            n >= config.min_points_absolute
            or (config.min_density_points_m2 is not None and density >= config.min_density_points_m2)
        )
        raw = mode - part.ground_z if mode is not None and part.ground_z is not None else None
        reliable = enough and strength >= config.min_mode_strength and raw is not None and raw > 0 and raw >= config.near_zero_m
        measurements[part.part_id] = (mode, strength, mixed, density, raw, reliable)
        quantities[part.part_id] = enough

    candidates = []
    for part in sorted(parts, key=lambda p: (-p.area_m2, p.part_id)):
        *_, raw, reliable = measurements[part.part_id]
        calibration_raw=(part.calibration_roof_z-part.ground_z
                         if part.calibration_roof_z is not None and part.ground_z is not None else None)
        if (reliable or calibration_raw is not None) and part.storeys_above and part.ground_is_measured:
            floor = (raw if reliable else calibration_raw) / part.storeys_above
            if config.min_floor_height_m <= floor <= config.max_floor_height_m:
                candidates.append((part, floor))

    def select_anchor(source,resolve_spatial_overlap=False):
        """Select a coherent reference within one ordered evidence tier."""
        eligible=source
        consensus_active=len(source)>=config.anchor_consensus_min_parts
        if not source:return eligible,consensus_active,None,set(),False
        if consensus_active:
            ordered=sorted(source,key=lambda item:(item[1],item[0].part_id))
            groups={frozenset(p.part_id for p,floor in ordered if low<=floor<=low*config.anchor_consensus_max_ratio)
                    for _,low in ordered}
            size=max(map(len,groups));winners=[group for group in groups if len(group)==size]
            # Sliding ratio windows can produce two equally large, overlapping
            # groups that differ only at their low/high extremes. Resolve that
            # tie with diminishing footprint support: a broader part normally
            # offers more spatial controls, while sqrt(area) prevents one hall
            # from outweighing several mutually coherent parts. Equal support
            # remains ambiguous rather than inventing a reference.
            if resolve_spatial_overlap and len(winners)>1 and size>len(source)/2:
                by_id={p.part_id:p for p,_ in source}
                support={group:sum(math.sqrt(by_id[part_id].area_m2) for part_id in group) for group in winners}
                best=max(support.values())
                winners=[group for group in winners if math.isclose(support[group],best,rel_tol=1e-12,abs_tol=1e-12)]
            accepted=winners[0] if len(winners)==1 and size>len(source)/2 else frozenset()
            eligible=[(p,floor) for p,floor in source if p.part_id in accepted]
        if consensus_active and eligible:
            middle=median(floor for _,floor in eligible)
            eligible=sorted(eligible,key=lambda item:(abs(item[1]-middle),-item[0].area_m2,item[0].part_id))
        anchor=(eligible[0][0].part_id,eligible[0][1]) if eligible else None
        outliers={p.part_id for p,_ in source}-{p.part_id for p,_ in eligible}
        sparse_conflict=(not consensus_active and len(eligible)>1 and
                         max(f for _,f in eligible)/min(f for _,f in eligible)>config.anchor_consensus_max_ratio)
        return eligible,consensus_active,anchor,outliers,sparse_conflict

    eligible,consensus_active,anchor,outliers,sparse_reference_conflict=select_anchor(candidates)
    # A coherent direct tier remains authoritative. Geometry-attributed roof
    # references are a secondary rescue only when direct candidates are absent
    # or mutually contradictory; the two tiers never vote against each other.
    fallback_eligible=eligible
    fallback_consensus_active=consensus_active
    fallback_anchor=anchor
    fallback_sparse_reference_conflict=sparse_reference_conflict
    fallback_spatial_anchor_used=False
    if fallback_sparse_reference_conflict and candidates:
        dominant=max(candidates,key=lambda item:(item[0].area_m2,-item[1]))
        dominant_part,dominant_floor=dominant
        compatible=[item for item in candidates
                    if max(item[1],dominant_floor)/min(item[1],dominant_floor)<=config.anchor_consensus_max_ratio]
        conflicting=[item for item in candidates if item not in compatible]
        # A recovered surface on a smaller sibling can be valid for that
        # footprint yet imply a very different per-storey height.  The same
        # part is rejected later by the parent-relative coherence gate, so it
        # must not first make the larger independent reference ambiguous.
        # This is a fallback-only choice: reliable direct heights are not
        # rewritten, and ordinary conflicting references remain unresolved.
        small_recovered_conflicts=(not dominant_part.check_small_part_coherence and conflicting and
            all(part.check_small_part_coherence and part.attributed_roof_z is not None and
                part.area_m2<dominant_part.area_m2
                for part,_ in conflicting))
        if small_recovered_conflicts:
            fallback_eligible=compatible
            fallback_anchor=(dominant_part.part_id,dominant_floor)
            fallback_sparse_reference_conflict=False
    # An overlapping-window tie is not strong enough to demote any reliable
    # direct measurement. It can still supply a fallback-only reference when
    # the same majority has clearly greater diminishing footprint support.
    if anchor is None and consensus_active:
        soft_eligible,soft_consensus_active,soft_anchor,_,soft_sparse_conflict=select_anchor(
            candidates,resolve_spatial_overlap=True)
        if soft_anchor is not None and not soft_sparse_conflict:
            fallback_eligible=soft_eligible
            fallback_consensus_active=soft_consensus_active
            fallback_anchor=soft_anchor
            fallback_sparse_reference_conflict=False
    if fallback_anchor is None or fallback_sparse_reference_conflict:
        spatial_candidates=[]
        for part in sorted(parts,key=lambda p:(-p.area_m2,p.part_id)):
            if part.attributed_roof_z is None or not part.storeys_above or not part.ground_is_measured:continue
            floor=(part.attributed_roof_z-part.ground_z)/part.storeys_above
            if config.min_floor_height_m<=floor<=config.max_floor_height_m:
                spatial_candidates.append((part,floor))
        if spatial_candidates:
            spatial_eligible,spatial_consensus_active,spatial_anchor,_,spatial_sparse_conflict=select_anchor(
                spatial_candidates,resolve_spatial_overlap=True)
            if spatial_anchor is not None and not spatial_sparse_conflict:
                fallback_eligible=spatial_eligible
                fallback_consensus_active=spatial_consensus_active
                fallback_anchor=spatial_anchor
                fallback_sparse_reference_conflict=False
                fallback_spatial_anchor_used=True

    by_id={part.part_id:part for part in parts}
    target_fallback_anchors={target.part_id:fallback_anchor for target in parts}
    local_anchors={}
    for target in parts:
        local=[]
        for neighbour_id in target.local_storey_neighbour_ids:
            neighbour=by_id.get(neighbour_id)
            if neighbour is None or neighbour.building_id!=target.building_id:
                raise ValueError('local_storey_neighbour_ids must reference parts in the same building batch')
            if not neighbour.storeys_above or not neighbour.ground_is_measured:continue
            *_,raw,reliable=measurements[neighbour.part_id]
            used_context=False
            if reliable:
                floor=raw/neighbour.storeys_above
            elif neighbour.attributed_roof_z is not None or neighbour.local_context_roof_z is not None:
                roof=(neighbour.attributed_roof_z if neighbour.attributed_roof_z is not None
                      else neighbour.local_context_roof_z)
                floor=(roof-neighbour.ground_z)/neighbour.storeys_above
                used_context=True
            else:continue
            parent_anchor=target_fallback_anchors[target.part_id]
            if (used_context and neighbour.roof_z and
                    (parent_anchor is None or not target.storeys_above or
                     abs(floor-parent_anchor[1])*target.storeys_above
                     >config.inferred_roof_tolerance_m)):
                continue
            if config.min_floor_height_m<=floor<=config.max_floor_height_m:
                local.append((neighbour,floor))
        local=sorted(local,key=lambda item:(-item[0].area_m2,item[0].part_id))
        selection_pool=local
        if target.storeys_above and target.storeys_above>1:
            multistorey=[item for item in local if item[0].storeys_above and item[0].storeys_above>1]
            if multistorey:
                different=[item for item in multistorey
                    if item[0].storeys_above!=target.storeys_above]
                if different:
                    multistorey=different
                distance=min(abs(item[0].storeys_above-target.storeys_above) for item in multistorey)
                selection_pool=[item for item in multistorey
                    if abs(item[0].storeys_above-target.storeys_above)==distance]
        _,_,chosen,_,conflict=select_anchor(selection_pool,resolve_spatial_overlap=True)
        if (chosen and target.storeys_above and target.storeys_above>1
                and by_id[chosen[0]].storeys_above==1):
            if (fallback_anchor is None or
                  max(chosen[1],fallback_anchor[1])/min(chosen[1],fallback_anchor[1])
                  >config.anchor_consensus_max_ratio):
                chosen=None
            elif (target_fallback_anchors[target.part_id] and
                  by_id[target_fallback_anchors[target.part_id][0]].storeys_above>1):
                chosen=None
        local_anchors[target.part_id]=None if conflict else chosen

    results = []
    for part in parts:
        mode, strength, mixed, density, raw, reliable = measurements[part.part_id]
        flags = []
        local_anchor=local_anchors[part.part_id]
        target_fallback_anchor=target_fallback_anchors[part.part_id]
        if reliable and local_anchor and part.storeys_above:
            local_top=part.ground_z+part.storeys_above*local_anchor[1]
            if abs(mode-local_top)>config.inferred_roof_tolerance_m:
                reliable=False
                flags.append(strings.BuildingHeightReason.ADJACENT_ROOF_STOREY_CONFLICT)
        if consensus_active and part.part_id in outliers:
            flags.append("floor_reference_outlier" if anchor else "ambiguous_floor_reference")
        if part.storeys_below:
            flags.append("basement_not_extruded")
        if mixed:
            flags.append("mixed_roof_planes")
        if not part.roof_z:
            flags.append("no_roof_points")
        elif len(part.roof_z) < config.min_points_statistical:
            flags.append("below_statistical_point_floor")
        else:
            if len(part.roof_z) < config.min_points_absolute:
                if config.min_density_points_m2 is not None and density >= config.min_density_points_m2:
                    flags.append("quantity_supported_by_density")
                else:
                    flags.append("insufficient_point_quantity")
            if strength < config.min_mode_strength:
                flags.append("weak_roof_mode")
        if reliable and anchor and part.check_small_part_coherence and part.storeys_above:
            if raw / part.storeys_above > config.coherence_max_ratio * anchor[1]:
                # A matching neighbouring plane can be either a shared roof or
                # exactly the contamination this gate detects. Record it as a
                # review conflict; do not treat scalar Z agreement as proof that
                # the small footprint owns those points.
                shared_plane = any(other.part_id!=part.part_id and other.area_m2>part.area_m2
                                   and measurements[other.part_id][-1]
                                   and abs(measurements[other.part_id][0]-mode)<=config.inferred_roof_tolerance_m
                                   for other in parts)
                if shared_plane:
                    flags.append("shared_roof_storey_conflict")
                largest_reliable=max((other.area_m2 for other in parts if measurements[other.part_id][-1]),default=part.area_m2)
                contextually_smaller=part.area_m2*config.coherence_max_ratio<largest_reliable
                if shared_plane or contextually_smaller:
                    reliable = False
                    flags.append("small_part_incoherent")
        if raw is not None and 0 < raw < config.near_zero_m:
            flags.append("near_zero_direct_height")
        height = floor_height = reference = None
        inferred_support = None
        roof_reference = None
        method = strings.HeightEstimationMethod.UNRESOLVED
        if part.ground_z is None:
            flags.append(strings.BuildingHeightReason.MISSING_GROUND)
        elif raw is not None and raw <= 0:
            flags.append("ground_not_below_roof")
        elif reliable:
            height, method = raw, strings.HeightEstimationMethod.DIRECT
            roof_reference = mode
            floor_height = height / part.storeys_above if part.storeys_above else None
            if floor_height is not None and floor_height < config.min_floor_height_m:
                flags.append("below_reference_floor_range")
        elif not part.storeys_above:
            flags.append("no_positive_storeys_for_fallback")
        elif (local_anchor or (target_fallback_anchor and not
                (target_fallback_anchor[0]==part.part_id and part.calibration_roof_z is not None))):
            using_local=local_anchor is not None
            reference, floor_height = local_anchor or target_fallback_anchor
            if using_local:
                flags.append(strings.BuildingHeightReason.ADJACENT_FLOOR_REFERENCE)
            if (not using_local and target_fallback_anchor==fallback_anchor
                    and fallback_spatial_anchor_used and part.attributed_roof_z is None):
                expected_top=part.ground_z+part.storeys_above*floor_height
                if not any(abs(z-expected_top)<=config.inferred_roof_tolerance_m for z in part.context_roof_z):
                    reference=floor_height=None
                    flags.append('unsupported_inferred_roof')
            check_support = floor_height is not None and config.min_inferred_roof_support>0 and quantities[part.part_id] and (mixed or strength<config.min_mode_strength) and "small_part_incoherent" not in flags and "near_zero_direct_height" not in flags
            if check_support:
                def support_for(floor):
                    """Fraction of eligible target Z in the inclusive inferred absolute-roof band."""
                    top = part.ground_z + part.storeys_above*floor
                    return sum(abs(z-top)<=config.inferred_roof_tolerance_m for z in part.roof_z)/len(part.roof_z)
                inferred_support = support_for(floor_height)
                if (inferred_support < config.min_inferred_roof_support
                        or (fallback_sparse_reference_conflict and not using_local)):
                    if inferred_support < config.min_inferred_roof_support:
                        flags.append("unsupported_preferred_floor_reference")
                    source_eligible=([(by_id[reference],floor_height)] if using_local
                                     else fallback_eligible)
                    supported = [(p,floor) for p,floor in source_eligible if support_for(floor)>=config.min_inferred_roof_support]
                    if supported and max(f for _,f in supported)/min(f for _,f in supported)<=config.anchor_consensus_max_ratio:
                        middle = median(floor for _,floor in supported)
                        source,floor_height = min(supported,key=lambda item:(abs(item[1]-middle),-item[0].area_m2,item[0].part_id))
                        reference = source.part_id
                        inferred_support = support_for(floor_height)
                        flags.append("roof_supported_floor_reference")
                    else:
                        reference = floor_height = None
                        flags.append("ambiguous_inferred_roof" if supported else "unsupported_inferred_roof")
            elif floor_height is not None:
                flags.append("inferred_roof_unverified")
                if (fallback_sparse_reference_conflict and not using_local
                        and config.min_inferred_roof_support>0):
                    reference = floor_height = None
                    flags.append("ambiguous_floor_reference")
            if floor_height is not None:
                if check_support:
                    expected_top = part.ground_z + part.storeys_above*floor_height
                    own_bands = [level for level in roof_band_candidates(part.roof_z,config)
                                 if abs(level-expected_top)<=config.inferred_roof_tolerance_m and level>part.ground_z]
                    if own_bands:
                        selected_bin = round(max(own_bands)/config.roof_bin_m)
                        # Upper observed Z of the attributed stable peak, not
                        # the maximum of all competing planes/isolated returns.
                        roof_reference = max(z for z in part.roof_z if round(z/config.roof_bin_m)==selected_bin)
                        height,method = roof_reference-part.ground_z,strings.HeightEstimationMethod.ROOF_BAND
                        inferred_support = sum(abs(z-roof_reference)<=config.inferred_roof_tolerance_m for z in part.roof_z)/len(part.roof_z)
                        flags.append("roof_reference_from_target_points")
                    else:
                        flags.append("no_attributable_roof_band")
                else:
                    height, method = part.storeys_above * floor_height, strings.HeightEstimationMethod.FLOOR_SHARE
                if fallback_consensus_active and not using_local:
                    flags.append("floor_reference_consensus")
        elif config.regional_floor_height_m is not None:
            floor_height = config.regional_floor_height_m
            height, method = part.storeys_above * floor_height, strings.HeightEstimationMethod.REGIONAL
        else:
            flags.append("no_floor_reference")
            if fallback_consensus_active and not fallback_anchor:
                flags.append("ambiguous_floor_reference")
        results.append(HeightEstimate(
            part.part_id, part.building_id, height, method, part.ground_z, mode,
            len(part.roof_z), density, strength, mixed, floor_height, reference, tuple(flags), inferred_support, roof_reference,
        ))
    return results
