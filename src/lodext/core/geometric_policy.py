"""Dimensionless geometric policies shared by building attribution stages."""
import math


NONCOMPACT_FOOTPRINT_MAX = 0.25
"""Maximum 4πA/P² for a footprint treated as strongly non-compact.

The value compares a footprint with an equal-area circle and therefore has no
metre or area dependency. At or below this value the perimeter is at least
twice that circle's perimeter, characteristic of long strips, deep concavities
and multi-wing bodies whose boundary evidence can dominate their interior.
"""

LOCAL_STOREY_FOOTPRINT_MAX = 0.30
"""Maximum 4πA/P² for sub-resolution local-storey preference.

This deliberately narrow extension above ``NONCOMPACT_FOOTPRINT_MAX`` admits
simple cadastral strips whose short side disappears inside the observed
spacing-plus-registration margin but whose rectangular perimeter remains just
too compact for the broader non-compact-body policy. It does not classify an
isolated footprint as wall-like and has no metre or area dependency.
"""

LOCAL_STOREY_FALLBACK_COMPACTNESS_MAX = 0.55
"""Maximum 4πA/P² for a constrained multistorey local fallback.

This wider limit covers elongated rooftop bodies whose oriented short side is
below the observation uncertainty, or whose incomplete candidate was rejected
specifically for continuing through an adjacent boundary. It never changes
one-storey targets or a surface with deep interior ownership.
"""

REPEATED_FACADE_SHAPE_RATIO_MAX = 1.25
"""Maximum area and perimeter ratio for repeated facade-part evidence.

Native attribution uses this dimensionless bound only for sub-resolution parts
of the same parent with the same declared storeys and compatible dominant roof
Z. At least two peers must satisfy both ratios; changing it alters which
cadastral balcony/facade repetitions can corroborate an absolute shared roof.
"""

BOUNDARY_SHARED_MIN_PERIMETER_FRACTION = 0.75
"""Minimum target-perimeter fraction shared with one larger roof body.

The dimensionless fraction is consumed only by sub-resolution absolute-roof
attribution. It requires a facade-like attachment rather than a short corner;
two-neighbour and repeated-family evidence use their stricter independent
contracts instead.
"""


def footprint_compactness(geometry):
    """Return the dimensionless isoperimetric compactness of a geometry."""
    return 4 * math.pi * geometry.area / geometry.length**2 if geometry.length else 0.0


def has_touching_rings(geometry):
    """Return whether valid polygon rings meet at one or more boundary points.

    This is topological evidence only. It does not repair, buffer, translate or
    otherwise change metric coordinates. Consumers decide whether the contact
    requires manifold LoD1 partitioning or guarded roof-attribution handling.
    """
    polygons=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
    return any(any(rings[i].intersects(rings[j])
                   for i in range(len(rings)) for j in range(i))
               for polygon in polygons for rings in [[polygon.exterior,*polygon.interiors]])
