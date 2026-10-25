# Changelog

## v0.1.0 — 2026-10-25

First release: the base layers of Euskal Herria and its population.

- **Boundaries** of the 7 territories and their 706 units (686 municipalities, 20 shared lands),
  from IGN España, IGN France and Wikidata, as one clean coverage across the state border.
- **Attributes**: official INE/INSEE codes, Basque names, territory names in eu/es/fr/en,
  ISO codes, Wikidata IDs.
- **Population** per municipality (INE Padrón 2025, INSEE 2023), with density, and totals per
  territory.
- **Population grid**: GHSL GHS-POP 2020 at 100 m (raster) and 1 km (vector).
- **RustGIS project** with territories, municipalities, density and grid layers, and print
  layouts for the density and grid maps.

Assets: `ehmap.rgis`, `euskal_herria.gpkg`, `euskal_herria_geojson.zip`,
`ghs_pop_2020_100m.tif`, `ghs_pop_2020_1km.gpkg`, `SHA256SUMS`.
