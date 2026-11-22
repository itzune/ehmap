# Changelog

## Unreleased

The topographic test page (`site/topo.html`, still unlinked) becomes a full hiking sheet in
the manner of IGN's TOP 25 *cartes de randonnée*.

- **An IGN palette.** The hypsometric tints are gone: open ground is white paper, woodland
  a light green (ESA WorldCover 2021 tree cover, smoothed to wood edges), the hillshade a
  soft grey that only darkens shaded slopes, contours orange. Marked itineraries are a
  translucent magenta overprint with the path showing through (GR wider than PR), tracks a
  thin black line, paths black dashes, tourist points magenta, water cyan.
- **Water, roads, rail and names** (`scripts/15_topo_osm.py` → `site/data/topo_osm.pmtiles`,
  18.6 MB, ODbL): lakes and reservoirs, rivers and streams with their names, the road
  network cased and coloured by rank with road numbers, railways, cities to hamlets, and
  9 686 named summits and passes with their heights (at low zooms only the highest of each
  ~5 km cell). Names prefer `name:eu`.
- **Zoom 15.** The sheet is baked one zoom deeper (z10–15, 86 168 tiles, 1.4 GB), so it is
  pixel for pixel at map zoom 14 and the page zooms to 16.
- **Buildings** (`scripts/17_buildings.py` → `site/data/buildings.pmtiles`, 27 MB, ODbL):
  956 462 OpenStreetMap footprints as small dark shapes from map zoom 13, fetched from
  Overpass in 20 cells.
- **Vector contours at the deep zooms** (`scripts/18_contours.py` → `contours.pmtiles`,
  219 MB on R2, z12–14): from map zoom 12.5 the 10 m curves are vector lines, sharp however
  far you zoom (the page now goes to 17), and the index curves carry their height. The
  raster's z14–15 no longer bake contours in; lower zooms, where the equidistance follows
  the zoom, still do.
- **GPS.** A locate button shows and follows the walker's position. It never prompts on
  its own: the browser asks on the first press, and later visits locate straight away
  unless the link already points somewhere.
- **Pictograms.** Trail-side points are no longer coloured dots: huts, shelters, campsites,
  viewpoints and picnic sites in magenta, springs and waterfalls in blue, and — new, in the
  `landmarks` layer of `topo_osm.pmtiles` (22 692 points) — churches and hermitages,
  megaliths, caves, castles, ruins and towers in black. The icons are SVG drawn in the page
  (no sprite file) and the legend shows them. Buildings are a warm grey that firms up with
  the zoom instead of near-black.
- **3D.** A "3D" button lifts the sheet over real heights and tilts the view
  (`scripts/16_terrain_tiles.py` → `site/data/terrain.pmtiles`, 32 MB: the LiDAR as
  Terrarium-encoded whole metres, lossless WebP, zooms 9–12, exaggerated 1.3×). Without
  it the sheet is a drawing, and tilting it showed a flat page with painted shade.
- **Zoom 14, with 10 m contours.** The sheet is now baked for z10–14 from a 5 m DEM cache
  (it was z10–13 from 10 m). MapLibre counts zooms on 512 px tiles, so the sheet's z14 is
  pixel for pixel at map zoom 13 and the page lets you go two zooms past it (15), stretched.
  The legend's "Kurba arrunta" was one zoom off for the same reason and now names the
  equidistance actually on screen.
- **Contours that read as contours.** Intermediate curves were almost invisible (0.6 px,
  pale); they are darker and 1 px wide. Where they would merge into a brown wash (under
  1.6 px apart) they fade out and the index curves carry the slope, as on a printed sheet.
- **Rock is an area, not a ladder.** Steep ground (> 45°) is measured on the unsmoothed
  fine grid instead of the blurred contour surface, where a cliff shrank to a one-pixel
  thread with a row of ticks on it. It is drawn as greyed ground under antialiased,
  jittered fall-line strokes; contours fade inside it.
- **Low zooms average the ground** instead of point-sampling it, on blocks anchored to the
  DEM grid so neighbouring tiles agree along their shared edge.
- **Build**: tiles are rendered by a process pool (`--jobs`, ~14 min for 21 644 tiles on
  six workers), written to a `.part` file so a failed build keeps the old archive, and
  `--keep-cache` keeps the 8 GB DEM scratch for restyling.
- **Page**: GR / PR references along the itineraries, line and point sizes that follow the
  zoom, a collapsible legend (folded on phones) that now lists every symbol on the map,
  panning limited to the sheet's frame. A PR route's white blaze no longer shows one zoom
  before its yellow dash.
- **Hosting**: `site/data/topo.pmtiles` (~1.4 GB) is over GitHub's 100 MB push limit and
  leaves git; it is served from a Cloudflare R2 bucket at `tiles.itzune.eus`, which the
  page reads directly, and uploaded with `scripts/upload_tiles.sh` (credentials in a
  gitignored `.env`). A local preview still reads the file in `site/data/`.

## v0.9.1 — 2026-11-17

Fixes to the 5 m LiDAR relief of v0.9.0, and to the topographic test page.

- **Northern Nafarroa had lost its LiDAR.** The French service is not void outside
  France: it answers with a coarse, blocky filler DEM well into Nafarroa, and because the
  French blocks were merged last with "positive values win", that filler replaced the
  PNOA 5 m surface around Bera, Elizondo and the Baztan (22–38 m mean error against PNOA).
  The merge now lets PNOA always win and RGE ALTI only fill what PNOA left empty; the
  42 affected PNOA blocks were re-fetched, and the mosaic now matches PNOA exactly there.
- **South Landes was sea.** The French request grid stopped at 43.55°N while the frame
  reaches ~43.62°N, so Labenne–Capbreton and the land south of Dax were 0 m (sea). A
  fifth row was added; a corner of ~4 × 8 km north-east of Orthez, outside Euskal Herria,
  is still empty (the service refuses those requests).
- **No dark rim along the coast**: transparent sea pixels kept black RGB, which each tile's
  resampling blended into the shoreline; they now carry the sea colour.
- RGE ALTI heights are rounded, not truncated, when stored as whole metres.
- **Topographic test page** (`site/topo.html`, `scripts/13_topo_tiles.py`): every tile was
  rendered ~4.6 px short of its own edges (the halo was sized in UTM metres on a mercator
  grid), so contours and shading jumped at every tile boundary — edge steps fall from
  15.3 to 8.6 levels at z13, against 7.8 inside a tile. All-sea tiles are now written as a
  shared transparent placeholder (coastal views never finished loading); the sea is 0 m
  before the contour blur, not the tile's median height, and no 0 m contour traces the
  shore; rock hachures are composited instead of punching alpha into the sheet. The
  attribution starts folded so it no longer runs under the legend.
- **Trails** (`scripts/14_bideak.py`): pavements, crossings and paved footways are dropped
  unless a marked route follows them (115 291 → 48 817 footways), which clears the dashes
  off every town; the Overpass query was broken on a fresh run (a variable shadowed the
  output clause) and only worked from the local cache.

Assets changed: `scripts/00_download.py`, `scripts/12_relief_tiles.py`,
`scripts/13_topo_tiles.py`, `scripts/14_bideak.py`, `site/data/erliebea.pmtiles`,
`site/data/topo.pmtiles`, `site/data/bideak.pmtiles`, `site/topo.html`.

## v0.9.0 — 2026-11-19

Erliebea now shades the map from the **national LiDAR bare-earth DTMs at 5 m**, so the
relief is a genuine survey of the ground rather than a 15 m photogrammetric estimate —
and the French Basque country stops being the soft spot it was.

- **One 5 m LiDAR DTM across the whole map** (`scripts/00_download.py` →
  `data/raw/lidar/eh_lidar_5m.tif`, 679 MB, 51 000 × 41 000): PNOA-LiDAR **MDT05** south of
  the Bidasoa (IGN España, CC BY 4.0) fetched as 20 km WCS windows on our own EPSG:25830
  grid, and **RGE ALTI®** north of it (IGN France, Licence Ouverte 2.0) decoded from the
  Géoplateforme's `terrainrgb` PNG tiles — no 10 GB archive to unpack. Both store water as
  a flat value, so `<= 0` is the sea, and blocks merge rather than overwrite so the two
  triangulations meet cleanly: the largest step across the border is 4 m, invisible here.
- **5 m everywhere it shows**: zooms 5–10 keep the printed 100 m grid, 11–13 are composed
  at the LiDAR's own 5 m (a z13 tile is 18 m per pixel). Anboto's crags and gullies gain
  roughly three times the detail; Iparralde gains it from nothing.
- **Two artifacts found and fixed on the way**: PNOA stores whole metres, which on gentle
  ground rounds into flat facets separated by one-cell cliffs — a sub-cell normalised blur
  (σ 0.8) restores a continuous surface without touching landforms; and WebP at q85 puts
  up to 8/255 of error into low-entropy tiles (valley floors), so tiles that encode under
  5 KB are re-encoded at q95 (3.3/255).
- `site/data/erliebea.pmtiles`: 23 → **34 MB**, same 5 428 tiles, still lazy-loaded. Legend
  credit reads "Erliebea: LiDAR 5 m · PNOA / RGE ALTI"; the archive metadata and
  `ATTRIBUTION.md` carry both licences.
- GEM-15 is dropped (it was the v0.8.0 stopgap); the elevation figures the atlas quotes
  still come from Copernicus GLO-30.

Assets changed: `scripts/00_download.py`, `scripts/12_relief_tiles.py`,
`site/data/erliebea.pmtiles`, `site/mapa.html`, `site/mapa.js`, `ATTRIBUTION.md`.

## v0.8.0 — 2026-11-18

Erliebea gets **high-definition relief** where it matters: the map now draws its own
hillshade from a 15 m bare-earth DEM, so the theme holds up at street zoom instead of
smoothing into mush.

- **GEM-15 as the relief's DEM** (`scripts/12_relief_tiles.py`): Google's 15 m near-global
  `dtm` band — bare earth, canopy removed, CC BY 4.0 — replaces the 30 m surface model the
  raster was resampled from. At zoom 13 a tile is 18 m per pixel, so the printed atlas's
  100 m grid was five times too coarse there; now the karst crags, gullies and ridge lines
  of Anboto read as landforms rather than as blobs.
- **Two tiers in one archive**: z5–10 stay on the 100 m composition (unchanged look, a few
  bytes), z11–13 are composed at 15 m. Frame, ramp, lighting, context ring and sea are the
  same recipe at both tiers, and measured tone across the z10/z11 seam differs by under 1 %
  (mean luminance 172.7 vs 172.5) — the only visible change is detail, as intended.
- **GEM-15's masked water bodies are filled from Copernicus GLO-30**, which also still
  defines the sea at 30 m; the ~49 km² of reservoirs and river defiles GEM-15 leaves empty
  are invisible (Ullibarri-Ganboa checked). GLO-30 keeps the elevation figures the atlas
  quotes — GEM-15 is orthometric EGM96 with metre-scale bias, so it drives the picture
  only.
- `site/data/erliebea.pmtiles`: **9.1 → 23 MB**, 5 428 tiles, still lazy-loaded (the plain
  map requests none of it). Legend credit now reads "Erliebea: GEM-15 (Google) · ura
  Copernicus DEM"; the archive metadata and `ATTRIBUTION.md` carry both licences.
- `scripts/00_download.py` fetches the 12 mosaics (`gem15()`, streamed, ~1.8 GB, gitignored).

Assets added: none. Assets changed: `scripts/00_download.py`, `scripts/12_relief_tiles.py`,
`site/data/erliebea.pmtiles`, `site/mapa.html`, `site/mapa.js`, `ATTRIBUTION.md`,
`requirements.txt` (comment only).

## v0.7.2 — 2026-11-17

Erliebea stops being a choropleth of mean elevation and becomes the printed atlas's actual
**shaded relief** on screen, and the other themes gain its shadow.

- **Erliebea = the printed relief raster** (`scripts/12_relief_tiles.py` →
  `site/data/erliebea.pmtiles`, 9.1 MB of WebP tiles, z5–13): the exact recipe from
  `07_site_maps.py` — NW-weighted multi-directional hillshade over the Copernicus DEM at
  100 m, the hypsometric ramp, the paper-toned relief ring around Euskal Herria, transparent
  sea — composed once in EPSG:25830 and warped to Web Mercator. It is fetched lazily: the
  plain map never requests it, and a theme that needs it pays for it once.
- **Shaded choropleths**: Basoa, Jendea and Beroa lay a faint desaturated relief over their
  fills (opacity 0.22), like the printed chapter maps.
- **Relief legend** with the printed ramp (0–1.000–2.300 m) and a WorldDEM-30 credit line;
  legend cards can now carry credits and gradient bars. Municipality and territory cards
  still pop up under the relief (transparent fills stay queryable).
- **Fixes along the way**: the raster is rebuilt from the raw 1° GLO-30 tiles (the Release
  DEM had holes in eastern Nafarroa); raster tiles missing over in-frame sea now ship as
  shared transparent placeholders, so coastal views reach "Kargatuta ✓" instead of
  idling on tiles the archive never answers.

Assets added: `scripts/12_relief_tiles.py`, `site/data/erliebea.pmtiles`.
Assets changed: `site/mapa.html`, `site/mapa.js`, `ATTRIBUTION.md`, `requirements.txt`
(rasterio, pyproj).

## v0.7.1 — 2026-11-16

The interactive map gets **themes** ("gaia"): the printed chapter maps' choropleths,
recoloured live over the same tiles.

- **Theme switcher** in the map card: Lurraldeak (the plain map), Erliebea, Basoa, Jendea
  and Beroa. Each recolours the 706 municipality fills with the printed atlas's own classes
  and ramps (`site/palette.json`): mean elevation (hypsometric), tree cover % (10/30/50/70/90),
  population density (25/100/500/2500/10000) and warming between the 1961-1990 and 1991-2020
  climate normals (0.7/0.8/0.9/1.0 °C). Switching is instant — the figures ride along in the
  tiles, so no new requests.
- **Per-municipality figures baked into the tiles** (`scripts/11_pmtiles.py` joins the
  `dist/` CSVs by INE/INSEE code): `forest_pct`, `temperature_change_c`, `elev_mean` — about
  0.4 MB more in `site/data/euskal_herria.pmtiles` (3.3 MB).
- **Legend** over the map (bottom left, above the scale bar): the theme's classes or a
  gradient bar, in the site's card style; hidden for the plain map.
- **Popups** pick up the active theme (Basoa 34 %, Beroa +0,8 °C, Altitudea 596 m…);
  Jendea already showed density. Theme fills are visible from z7, one zoom short of the
  hairline municipal borders, so the choropleth owns the country view too.
- **Deep links** gain a theme segment — `#gaia/zoom/lat/lon` (e.g. `#beroa/9.5/42.85/-2.67`);
  old `#zoom/lat/lon` links still work. Dark mode re-applies the theme with a lifted
  below-threshold tone so low values read as land, not void.

Assets changed: `site/mapa.html`, `site/mapa.js`, `site/data/euskal_herria.pmtiles`,
`scripts/11_pmtiles.py`, `ATTRIBUTION.md`, `requirements.txt` (pmtiles pin corrected to 3.8).

## v0.7.0 — 2026-11-16

The atlas becomes interactive: **mapa.html**, a panning, zooming map of everything ehmap
publishes, served as plain files from GitHub Pages.

- **Interactive map** (`site/mapa.html` + `site/mapa.js`): the whole of Euskal Herria — the
  7 territories and 706 municipal units — with the printed map's look: warm paper land, pale
  sea, thick territory borders, hairline municipal borders, uppercase letter-spaced labels.
  Hover highlights a municipality; clicking opens its card (lurraldea, kodea, biztanleria,
  dentsitatea), or the territory's at country scale. Deep links (`#zoom/lat/lon`) are kept in
  sync with the view; dark mode follows the colour scheme.
- **Vector tiles** (`scripts/11_pmtiles.py` → `site/data/euskal_herria.pmtiles`, 2.9 MB,
  2 509 tiles, zooms 4–13): ehmap's own CC BY 4.0 layers as PMTiles, built with
  shapely + mapbox-vector-tile — per-zoom simplification, tile clipping, one label point per
  feature, and dedicated boundary-line layers (clipping polygons to tiles leaves straight
  clip edges that would otherwise show as a grid). Range requests keep a session to a few MB.
- **No build step, no server**: MapLibre GL JS 5.24.1 and the PMTiles client 4.5.0 are
  vendored in `site/vendor/`; Open Sans SDF glyphs in `site/fonts/glyphs/`; tiles load
  straight off GitHub Pages. Licences in `ATTRIBUTION.md`.
- **Navigation**: Mapa link in the header of every page.

Assets added: `site/mapa.html`, `site/mapa.js`, `site/data/euskal_herria.pmtiles`,
`site/vendor/` (maplibre-gl.js, maplibre-gl.css, pmtiles.js), `site/fonts/glyphs/`.

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
