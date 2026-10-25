# Changelog

## v0.5.0 — 2026-10-25

Climate change.

- **Temperature and precipitation change** between the climate normals 1961-1990 and
  1991-2020 from ERA5-Land (Copernicus C3S, CC BY 4.0): +0.82 °C over Euskal Herria, from
  +0.68 °C in Lapurdi to +0.91 °C in Nafarroa Garaia; 2016-2025 is +1.59 °C.
- **Yearly series 1950-2025** per territory and watershed side: temperature, precipitation,
  evaporation, topsoil moisture and snow cover.
- **Station check** against Météo-France records (Socoa, Biarritz, Banca): the model is
  conservative on temperature; its precipitation decline is not confirmed on the coast.
- **Website**: chapter 06, "Klima aldatzen ari da", with a warming map and warming stripes.
- **RustGIS project**: `Klima aldaketa` layer and print layout.

Assets added: `temperature_change.tif`, `precipitation_change.tif`, `climate_annual.csv`,
`climate_by_municipality.csv`.

## v0.4.0 — 2026-10-25

Current forest.

- **Land cover 2021** (ESA WorldCover, 10 m, all classes) clipped to Euskal Herria, and
  **% tree cover per 100 m cell** (CC BY 4.0).
- **Tree cover per municipality and territory**: 49.5% of Euskal Herria, from 41% in
  Nafarroa Garaia to 73% in Gipuzkoa.
- **RustGIS project**: `Basoa` and `Lurzorua 2021` layers and a `Basoa` print layout.

Assets added: `forest_cover_100m.tif`, `landcover_2021_10m.tif`.

## v0.3.0 — 2026-10-25

Rivers and the watershed divide.

- **Rivers**: 247 named OpenStreetMap rivers clipped to Euskal Herria (ODbL), merged across
  inconsistent names and reservoirs, with length and territories.
- **Drainage** computed from the Copernicus DEM with the GeoLibre (Whitebox) tools: streams
  with Strahler order, the Bay of Biscay and Mediterranean (Ebro) sides, and the watershed
  divide (Copernicus licence).
- **RustGIS project**: `Ibaiak`, `Isurialdeak` and `Banalerroa` layers and an `Isurialdeak`
  print layout.

Assets added: `rivers.gpkg`, `drainage_basins.gpkg`.

## v0.2.0 — 2026-10-25

Elevation and mountain peaks.

- **Elevation model**: Copernicus DEM GLO-30 clipped to Euskal Herria, at 25 m (float, 0.1 m)
  and 50 m (whole metres), EPSG:25830, under the Copernicus WorldDEM-30 licence.
- **Elevation statistics** (min / mean / max) per municipality and per territory, with each
  territory's highest point.
- **Peaks**: 6,269 OpenStreetMap peaks inside Euskal Herria (ODbL), with every territory they
  touch and their rank within it.
- **RustGIS project**: shaded relief (`Erliebea`), peak layers and an `Erliebea` print layout.

Assets added: `copernicus_dem_25m.tif`, `copernicus_dem_50m.tif`, `peaks.gpkg`.

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
