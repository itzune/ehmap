# Changelog

## v0.6.0 — 2026-10-26

How climate change is felt: heat, rivers and the sea.

- **Heat and frost** per station (`heat_stations.gpkg`): hot days ×2, tropical nights ×5,
  frost days halved (1961-1990 → 2016-2025, 10 quality-checked stations).
- **Rivers** (`scripts/09_rivers.py`, `dist/rivers/`): 15 gauges, their DEM-traced catchments
  and flow indicators; summer flow −24% (1991-2020) and −48% (2016-2022/25) at the near-natural
  gauges, much more on the Ebro side.
- **Sea** (`scripts/10_sea.py`, `dist/sea/`): sea temperature +1.0 °C since the 1980s, marine
  heatwave days 18 → 127 a year, sea level +3 mm a year since 1993.
- **Website**: chapter 06 gains "Beroa egunerokoan", "Ibaiek ur gutxiago" (catchment map) and
  "Itsasoa berotzen" (heatwave days chart); the rain chart moves to the data and the RustGIS
  project.
- **RustGIS project**: catchments, river gauges, tide gauges and heat stations in the "Klima
  aldaketa" group; sea and water-balance tables.

Assets added: `heat_stations.gpkg`, `river_gauges.gpkg`, `river_flow_yearly.csv`,
`sea_annual.csv`, `marine_heatwaves.csv`, `tide_gauges.gpkg`.

## v0.5.3 — 2026-10-25

"Ur gutxiago": same rain, more evaporation.

- **Evaporative demand** (Hargreaves ET₀) from the stations' maximum and minimum temperatures:
  +59 mm a year (+6%) in 2016-2025 vs 1961-1990, a steady rise; rain unchanged (−1%).
  `water_balance.csv`: a typical station's yearly rain and ET₀, 1961-2025, from 15 stations.
- **Quality control** for ET₀ too (neighbour step test, 5%); `station_quality.csv` now has a
  `variable` column (rain, et0).
- Station tables carry the monthly means of daily maxima and minima (`tx`, `tn`).
- **Website**: the rain explorer is replaced by one chart, rain and evaporative demand as
  10-year means (% of 1961-1990), under the title "Ur gutxiago".

Asset added: `water_balance.csv`.

## v0.5.2 — 2026-10-25

Rain over time: a station timeline, quality control, and a corrected conclusion.

- **Navarre's manual stations** (Government of Navarre, back to 1900) and every Météo-France
  station inside Euskal Herria join AEMET's: 91 stations in the timeline.
- **Quality control**: a neighbour test for sudden steps (station moves, new gauges); 11
  stations left out (`station_quality.csv`).
- **Rain timeline** (`rain_timeline.csv`): 10-year rain per station and season, as % of its
  1996-2025 mean, back to the 1920s where records exist.
- **Corrected conclusion**: rain swings ±20-30% from decade to decade but has **no trend since
  1960** in any season. v0.5.1's "drier springs, wetter autumns" is the difference between two
  normals, explained by unusually wet springs in the 1970s-80s and dry autumns in the 1980s.
- **Website**: the rain section is now an explorer (season tabs, a slider over the decades,
  the median of the long stations); the four-season map and the dot chart are gone.

Assets added: `rain_timeline.csv`, `rain_timeline_stations.csv`, `station_quality.csv`.

## v0.5.1 — 2026-10-25

Rain from the stations, not the model.

- **Withdrawn**: ERA5-Land precipitation (`precipitation_change.tif` and the precipitation,
  evaporation, soil moisture and snow cover columns of v0.5.0). Checked against 10 long
  station records it puts 2023 at about half the normal rain where every station measured
  102-118%, and shows summer drying most stations do not. Do not use the v0.5.0 files for rain.
- **Rain as measured** at 10 stations (4 AEMET, 6 Météo-France): `rain_stations.gpkg`, with
  the change per year and season. The yearly total has hardly changed; springs are drier and
  autumns wetter.
- **Station check** extended to AEMET (Hondarribia, Igeldo, Bilbao, Pamplona) and three
  Zuberoa stations; temperature results unchanged.
- **Website**: seasonal rain map in chapter 06; the stripes now sit below the chapter text.
- **RustGIS project**: `Klima aldaketa` group (`Tenperatura`, `Prezipitazioak` stations).

Assets added: `rain_stations.gpkg`, `station_check.csv`. Removed: `precipitation_change.tif`.

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
- **RustGIS project**: `Klima aldaketa` group with `Tenperatura` and `Prezipitazioak` layers, and a print layout.

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
