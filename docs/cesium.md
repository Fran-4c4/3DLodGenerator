# From CityJSON to Cesium

CityJSON is the semantic exchange model. Cesium loads glTF/GLB or 3D Tiles.
The included converter creates **GLB + 3D Tiles 1.1** from the supported
LoD0/LoD1 CityJSON subset.

## Explicit vertical placement

Building height and placement on the globe are separate decisions. ECEF needs
ellipsoidal heights compatible with horizontal coordinates. The command requires
an explicitly declared constant adjustment:

```text
ellipsoidal_height = CityJSON_Z + z_offset_m
```

The synthetic example has ground 25, deliberately placed at ellipsoidal zero:

```powershell
.\.venv\Scripts\python.exe -m lodext tiles outputs/first-run/model.lod1.city.json --output outputs/first-run-tiles --z-offset-m -25
```

For real data justify placement using the vertical reference or control points
compatible with the client's terrain. Do not transfer the example's -25 or
interpret zero offset as automatic detection. A constant offset cannot replace
a spatially varying geoid transformation. This version downloads no vertical
grids and performs no ground clamping.

Reconstruction preserves heights and differences between bases. A later Cesium
terrain adjustment must be documented separately: moving a tileset neither
recalculates building heights nor adapts each building individually.

## Serve files

```powershell
.\.venv\Scripts\python.exe -m http.server 8012 --bind 127.0.0.1 --directory .
```

Open `http://127.0.0.1:8012/examples/cesium-preview.html`. This minimal preview
loads CesiumJS 1.137 from a CDN, without an ion token or third-party imagery.
The preview library needs network access; the generator and tileset do not.
For offline viewing, use an application with a local Cesium installation.

The tileset URL is
`http://127.0.0.1:8012/outputs/first-run-tiles/tileset.json`.
Keep `model.glb` beside it and preserve relative URIs.

In an existing CesiumJS application:

```javascript
const tileset = await Cesium.Cesium3DTileset.fromUrl(
  "/outputs/first-run-tiles/tileset.json"
);
viewer.scene.primitives.add(tileset);
await viewer.zoomTo(tileset);
```

Use the same HTTP origin, or configure CORS on the file server. The example's
standard server does not add CORS for applications on another host/port.
Do not use `file://`. Hosting your own files does not require Cesium ion.

## Display limits

The initial exporter has one content, without hierarchy, compression, textures
or `EXT_mesh_features` picking tables. Attributes live in glTF node `extras`.
Successful loading proves neither source accuracy nor correctness of the chosen
vertical adjustment.

Normative references: [CityJSON 2.0.1](https://www.cityjson.org/specs/2.0.1/),
[3D Tiles](https://github.com/CesiumGS/3d-tiles/tree/main/specification),
[glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html) and
[Cesium3DTileset](https://cesium.com/learn/cesiumjs/ref-doc/Cesium3DTileset.html).
