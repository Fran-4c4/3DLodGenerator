# Contributing

Use Python 3.12 and install the package with development extras:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints/python312.txt -e ".[geo,test]"
.\.venv\Scripts\python.exe -m pytest tests -q
```

Optional real-data tests skip when their fixtures are absent. An explicitly
configured incomplete path fails. Synthetic inputs are generated from code
and exercise geometry, height policies, NoData, CLI and formats without a database.
Documentation, examples and contribution discussions in repository documents
should use English.

## Organisation

- `core/`: pure estimator and authoritative configuration/field contracts.
- `io/`: read-only GeoPackage, point clouds, raster and XY transforms.
- `reconstruction/`: LoD0 surfaces and oriented LoD1 extrusion.
- `export/`: CityJSON, triangulation, GLB and tileset conversion.
- `pipeline.py`, `cli/`: coordination, policies and per-run output.
- `demo.py`: reproducible, original public synthetic data.

The height core uses the standard library; the complete CLI needs `geo`.
Do not import `tools/` into the installed package or depend on another checkout.
Numerical tests must not require roofer.

## Verification

See the [test matrix](tests/README.md). Optional GLB verification:

```powershell
npm install --prefix work/validators gltf-validator@2.0.0-dev.3.10
node tools/validate_glb.cjs outputs/first-run-tiles/model.glb
```

This Apache-2.0 development tool is not part of the engine and its downloaded
dependencies are not versioned. The included official CityJSON test schema
retains CC0. Do not replace third-party notices with the project's MIT licence.

Update guides/limitations when behaviour changes. Tests should demonstrate
physical/geometric results rather than mirror implementation text. Preserve
inputs and earlier outputs; use new run directories. Real datasets require
permission and attribution before entering Git.

## Documentation website

Install `docs/requirements.txt` in a separate environment and run
`python tools/build_docs.py --strict`. Use `--serve` for local preview.
Add user-guide pages to the public list in `tools/build_docs.py` and to the
navigation in `mkdocs.yml`. The build checks local links and stages downloadable
examples. On GitHub, select **Settings → Pages → GitHub Actions** to use the
included Documentation workflow. Generated site files stay out of Git.
