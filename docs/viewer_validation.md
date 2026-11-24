# View and check your model

Open `scene.lod1.city.json` for direct-ground buildings and terrain together,
or `model.lod1.city.json` for buildings alone, in 3dLodViewer, Ninja or a viewer supporting
CityJSON 2.0. Open the LoD0 file separately if the viewer has no level selector.
When downloading an example, save the JSON file itself rather than a hosting
website's HTML preview.

## Check the geometry

- Look at low terraces and neighbouring bodies: do their relative heights make sense?
- Check courtyards, narrow parts and disconnected components.
- Select objects and compare source IDs with your GeoPackage.
- Review missing geometry against `objects.csv` and `quality.json`.

A parent building may have no volume of its own when its parts carry the geometry.
That prevents a second box from covering the reconstructed parts.

The combined scene contains a native `TINRelief` object, so loading a DTM is
unnecessary. The terrain uses original retained ground observations, while the
building bases use separate streaming statistics. Gaps and unstitched building
interfaces remain visible. The viewer's reference grid marks source Z=0, not
terrain or sea level.

## Check the reports

A complete-looking model can still contain inferred heights. Review the method,
point support and flags for objects important to your application. An unresolved
object remains in the inventory without an invented height. An excluded object
has an input issue recorded in the report. See [output files](outputs.md).

You can also run a structural check:

```powershell
.\.venv\Scripts\python.exe -m lodext validate-cityjson outputs/first-run/model.lod1.city.json
```

This checks supported structure, relationships and geometry consistency. It does
not establish that the source heights match the real building. For Cesium, use
[the 3D Tiles conversion guide](cesium.md).
