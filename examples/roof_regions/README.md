# Auditorium roof-region example

The CityJSON model is an extracted result of the native `roof_regions` build,
retaining the seven received cadastral parts and their explicit parent. Internal
regions remain multiple solids under the original part7 ID, not invented source
parts. Original model coordinates and attributes are unchanged by extraction.

Source data: PNOA LiDAR 2023, CC BY 4.0 scne.es; building polygons: Direccion
General del Catastro, municipal source snapshot 2026-08-21. Credit these sources
when reusing the derived example. Project code is MIT; source-data attribution
is separate. The small derived model contains no original point-cloud archive.

The two images compare original class-6 roof observations with the generated
stepped LoD1 result in 3dLodViewer. Roofs are flat approximations, including the
central tower cap. No surveyed reconstruction accuracy is established.

See the [user guide](../../docs/roof_regions.md) for configuration and limits.
