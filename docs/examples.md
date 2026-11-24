# Examples

Use the small building dataset for your first run. The neighbourhood example
shows the wider range of objects; the surface dataset demonstrates relief and
level water separately. These downloadable datasets are original synthetic
examples supplied under MIT. The real-data figures below retain their own
source credits.

## Las Canteras: real observations

The [Las Canteras example](las_canteras.md) shows mapped building parts, mixed
roof returns and a DTM derived from PNOA LiDAR. Its figures explain why sampling,
roof-group attribution and ground interpolation need separate checks. The page
includes the observed roof reference and height for one mixed part, without
claiming surveyed accuracy. [Reconstruct the promenade](las_canteras.md#reconstruct-the-promenade)
uses a small downloadable crop of the original LiDAR and cadastral footprints.

## First building model

Four buildings and five parts include a courtyard, low terrace, L-shaped body,
disconnected components and a body with sparse roof observations. Follow
[your first model](first_run.md) to generate and inspect this result.

- [GeoPackage footprints](../examples/first_run/footprints.gpkg)
- [LiDAR cloud](../examples/first_run/cloud.las) and [DTM](../examples/first_run/dtm.tif)
- [Direct LiDAR configuration](../examples/first_run/build.lidar.json)
- [Optional raster-ground configuration](../examples/first_run/build.json)
- [Ready-made LoD1 model](../examples/first_run/model.lod1.city.json)
- [Buildings and ground together](../examples/first_run/scene.lod1.city.json)
- [Observed-point ground TIN](../examples/first_run/ground.city.json)

## Compare parameter settings

The [parameter examples](parameter_examples.md) compare erosion, LAS classes,
small-body density, supplied-height fallback, storey references, DTM searches,
LoD0/LoD1, water percentiles and road smoothing. Each comparison includes the
same inputs for every variant, ready-made models, measured results and a ZIP
you can run locally.

## Neighbourhood example

This example contains 48 buildings with 53 parts, roads, a canal and land-cover
surfaces. Use [the interactive preview](../examples/showcase/preview.html) to switch
between the classified map, synthetic observations and generated geometry.
The same scene illustrates [how reconstruction works](how_it_works.md).

- [Building CityJSON](../examples/showcase/model.buildings.city.json)
- [Surface CityJSON](../examples/showcase/model.surfaces.city.json)

The scene combines separate building and surface outputs without automatic
stitching. Roof observations use a nominal 5 points/m² grid; ground uses a
separate 2 m grid with additional boundary controls. It is a teaching dataset,
not a survey or an accuracy comparison.

## Roads, terrain and water

A sloping road, a terrain hill, forest ground and level water illustrate the
surface workflow. Follow [generate surfaces](surface_workflow.md) to run it.

- [GeoPackage](../examples/surfaces_first_run/footprints.gpkg)
- [LiDAR cloud](../examples/surfaces_first_run/surfaces.las)
- [Configuration](../examples/surfaces_first_run/surfaces.json)
- [Ready-made surface model](../examples/surfaces_first_run/model.surfaces.city.json)

Download linked files together and preserve the configuration's relative paths.
