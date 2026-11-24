# Building surfaces and point ownership

A footprint can cover several LiDAR elevations. For example, returns along the
edge of a low terrace may come from the taller building next door. 3DLodExt
compares the XYZ observations across the footprint and its neighbours to
estimate a roof elevation for each mapped body. A standard LoD1 result has a
flat top, even when the observed roof slopes.

## Check a building part

1. Select the part in the CityJSON viewer and find its source ID in
   `objects.csv`. Check its status, base elevation, roof elevation and height.
   Roof elevation and base elevation use the same vertical reference. Their
   difference gives the height above the base.
2. Look up the same part in `quality.json`. The `building_surfaces` evidence
   includes the observed spacing, candidate surfaces and neighbouring IDs.
   Where a `roof_surface` record is present, `applied_to_height` tells you
   whether that estimate contributed to the final height.
3. Compare the footprint and the original points along a cross-section that
   includes the adjacent roof. On a setback terrace, look for observations
   extending into the terrace interior. On a narrow façade, the point spacing
   can exceed the width of the whole part. Check whether the reported height
   uses an adjacent part as a reference.

A rooftop room with its own mapped outline can have a separate height above
the main roof. Where several roof levels share one footprint, use
[internal roof regions](roof_regions.md) to represent supported steps in LoD1.
Sparse coverage or an uncertain base can leave a part unresolved. With the
default visibility settings, its footprint remains available for inspection.

Building reconstruction uses XYZ coordinates. LAS classifications can colour
the points during inspection. For input settings and a guide to the exported
fields, see the [CLI reference](cli_reference.md) and [run outputs](outputs.md).
