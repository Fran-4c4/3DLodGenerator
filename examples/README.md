# Public examples

[Parameter comparisons](../docs/parameter_examples.md) provide nine original
datasets with runnable configurations, generated CityJSON, evidence and ZIP
downloads under `parameters/`. Regenerate them with
`tools/generate_parameter_examples.py --output <new-directory>`.

[showcase/](showcase/README.md) explains the GIS-to-3D process with an original
neighbourhood, actual generated buildings/surfaces and an optional interactive
preview. Its source inputs are reproducible with `tools/generate_showcase.py`.

[surfaces_first_run/](surfaces_first_run/README.md) adds original Road, Terrain,
Forest and Water controls and a generated model for the first surface stage.
The existing building controls are retained for future integration regression;
the models are not yet stitched into one scene.

[first_run/](first_run/README.md) contains GeoPackage, DTM, LAS, configurations,
synthetic control dimensions and generated CityJSON. These are original MIT
data, not a database extract or third-party survey.

The [tutorial](../docs/first_run.md) needs no data downloads. Regenerate the
dataset with `lodext demo --output` into a new directory.

The [Las Canteras promenade tutorial](../docs/las_canteras.md#reconstruct-the-promenade)
uses a real GeoPackage and LAZ crop in `las_canteras/promenade.zip`. Source credits
and reuse terms accompany the inputs inside the archive.
