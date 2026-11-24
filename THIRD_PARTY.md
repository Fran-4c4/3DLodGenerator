# Provenance and third-party components

This project contains original implementation/documentation, portable procedures
and synthetic examples. It includes no source code from 3dfier, roofer or the
reviewed converters, and distributes no third-party engine binaries or complete real input datasets.
Selected analytical figures derived from public geographic data accompany the
user manual; they retain their own source terms and attribution.

| Component | Role and notices |
|---|---|
| 3dfier | Design reference only; reviewed commit contains GPL v3/v3-or-later notices; [reviewed source](https://github.com/tudelft3d/3dfier/tree/9f7fece6bb2624095dc7e7059defa1a9dbd4276e) |
| roofer | Independent engine, distributed separately; [upstream](https://github.com/3DBAG/roofer) declares GPL-3.0 |
| GDAL/PROJ/GEOS and LiDAR readers | Accessed through Rasterio/PyProj/Shapely/laspy/lazrs wheels, retaining their notices; no copied DLLs |
| Triangulation/GLB | Original writer using Shapely/GEOS; no copied converter implementation |
| Height core | Original implementation of the documented method, contracts and tests; no source-system imports |
| Surface lifting/TIN | Original observed-rank, quadratic fitting and constrained insertion code; documented 3dfier concepts, without copied source |
| Test libraries | Direct versions recorded in `tests/requirements.txt`; their binaries are not versioned |
| Synthetic data | Original building, surface, neighbourhood and parameter examples under `examples/`, under MIT; real resources/results ignored |
| Las Canteras figures | Derived PNOA imagery/LiDAR and Catastro building-outline analyses; [credits](examples/las_canteras/NOTICE.txt) and [source metadata](examples/las_canteras/sources.json); not relicensed as MIT source data |
| Las Canteras promenade inputs | [Downloadable crop](examples/las_canteras/promenade.zip) of PNOA LiDAR 2023 (CC BY 4.0 scne.es) and Dirección General del Catastro INSPIRE building polygons. The enclosed README identifies both sources, transformations and reuse terms. |
| CityJSON 2.0.1 schema | Official self-contained offline test copy, CC0; notice and source/hash in `tests/schemas/` |
| glTF-Validator | Optional Khronos Apache-2.0 development check installed under ignored `work/` |
| CesiumJS | External Apache-2.0 preview/QA client, version 1.137; optional CDN, no bundled engine library |
| Three.js | Optional showcase preview uses version 0.128.0 through jsDelivr; [MIT licence](https://github.com/mrdoob/three.js/blob/r128/LICENSE), copyright 2010–2021 Three.js authors; no library source is bundled |
| Documentation tools | MkDocs BSD-2-Clause and Material for MkDocs MIT; installed separately through `docs/requirements.txt` |

Contract/output-safety skills were adapted from existing development procedures;
CRS/pipeline skills are specific to this project. None requires external files.

Original material uses [MIT](LICENSE). Before incorporating or redistributing
components, record author, version, licence and modifications and preserve
applicable original notices. This table does not replace them. Installed
libraries and geographic datasets retain their upstream terms. Native libraries
in wheels (including GDAL, PROJ and GEOS) retain their own notices.
