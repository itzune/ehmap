# ehmap — open geodata for Euskal Herria

Open, reproducible base layers of **Euskal Herria and its 7 territories**
(Araba, Bizkaia, Gipuzkoa, Nafarroa Garaia, Lapurdi, Nafarroa Beherea, Zuberoa), ready to use
in any GIS or web map. The goal is that anyone building something about Euskal Herria finds
the base already done, with clear sources and licences.

The project is also a playground to learn [RustGIS](https://github.com/opengeos/RustGIS);
next topic is forest change over the last years.

![The 7 territories of Euskal Herria](docs/euskal_herria_territories.png)

## Download

Get the files from the **[latest release](https://github.com/itzune/ehmap/releases/latest/)** (stable links below always
point to it). Vector data is also in [`dist/`](dist/) in this repository.

| File | Contents |
|---|---|
| [`ehmap.rgis`](https://github.com/itzune/ehmap/releases/latest/download/ehmap.rgis) | RustGIS project, self-contained: territories, municipalities, population density and population grid (hidden layers + print layouts), over an OpenStreetMap basemap |
| [`euskal_herria.gpkg`](https://github.com/itzune/ehmap/releases/latest/download/euskal_herria.gpkg) | GeoPackage with layers `municipalities`, `territories`, `euskal_herria` (EPSG:4326) — also [`dist/`](dist/) |
| [`euskal_herria_geojson.zip`](https://github.com/itzune/ehmap/releases/latest/download/euskal_herria_geojson.zip) | The same layers as GeoJSON (RFC 7946), full detail and simplified (~50 m, shared borders kept) — also [`dist/geojson/`](dist/geojson/) |
| [`ghs_pop_2020_100m.tif`](https://github.com/itzune/ehmap/releases/latest/download/ghs_pop_2020_100m.tif) | People per 100 m cell (GHSL, 2020), Cloud-Optimized GeoTIFF, EPSG:3035 |
| [`ghs_pop_2020_1km.gpkg`](https://github.com/itzune/ehmap/releases/latest/download/ghs_pop_2020_1km.gpkg) | Inhabited 1 km cells with `grid_id` (Eurostat format), `population`, `territory_id`, EPSG:3035 — also [`dist/population_grid/`](dist/population_grid/) |
| [`copernicus_dem_25m.tif`](https://github.com/itzune/ehmap/releases/latest/download/copernicus_dem_25m.tif) | Elevation (m), 25 m, EPSG:25830, Cloud-Optimized GeoTIFF (90 MB) — Copernicus licence, see below |
| [`copernicus_dem_50m.tif`](https://github.com/itzune/ehmap/releases/latest/download/copernicus_dem_50m.tif) | Lighter elevation: 50 m, whole metres (10 MB) — Copernicus licence |
| [`peaks.gpkg`](https://github.com/itzune/ehmap/releases/latest/download/peaks.gpkg) | 6,269 OpenStreetMap peaks inside Euskal Herria — ODbL; also [`dist/osm/`](dist/osm/) |
| [`rivers.gpkg`](https://github.com/itzune/ehmap/releases/latest/download/rivers.gpkg) | 247 named OpenStreetMap rivers clipped to Euskal Herria — ODbL; also [`dist/osm/`](dist/osm/) |
| [`drainage_basins.gpkg`](https://github.com/itzune/ehmap/releases/latest/download/drainage_basins.gpkg) | Bay of Biscay / Mediterranean sides and the watershed divide, from the DEM — Copernicus licence; also [`dist/elevation/`](dist/elevation/) |
| [`SHA256SUMS`](https://github.com/itzune/ehmap/releases/latest/download/SHA256SUMS) | Checksums |

Earlier versions and what changed: [releases](https://github.com/itzune/ehmap/releases),
[CHANGELOG.md](CHANGELOG.md).

### `municipalities` (706 features)

| Field | Description |
|---|---|
| `code` | Official code: INE (Spain) or INSEE (France) |
| `country` | `ES` or `FR` |
| `type` | `municipality` (686) or `shared_land` (20 facerías, parzonerías, Bardenas Reales…) |
| `name` | Official name |
| `name_eu` | Basque name (Wikidata; official name when none) |
| `territory_id`, `territory` | One of the 7 territories (id / Basque name) |
| `admin_province` | Current administrative province or département |
| `wikidata` | Wikidata item ID |
| `note` | Why a unit was assigned where it is, when that is not obvious |
| `area_km2` | Area in km² (computed in ETRS89 / UTM 30N) |
| `population` | Municipal population (empty for shared lands) |
| `population_year` | Reference year: 2025 (INE, 1 January) or 2023 (INSEE) |
| `population_source` | `INE Padrón` or `INSEE PMUN` (population municipale) |
| `density_km2` | Inhabitants per km² |

### `territories` (7 features)

`id`, `name_eu`, `name_es`, `name_fr`, `name_en`, `iso_3166_2` (southern territories only),
`n_municipalities`, `n_shared_lands`, `population`, `area_km2`, `density_km2`.

| Territory | Municipalities | Shared lands | Population | km² | Inh./km² |
|---|---|---|---|---|---|
| Araba (incl. Treviño) | 53 | 2 | 344,194 | 3314.5 | 103.8 |
| Bizkaia | 112 | 0 | 1,162,251 | 2213.8 | 525.0 |
| Gipuzkoa | 88 | 2 | 733,365 | 1980.8 | 370.2 |
| Nafarroa Garaia | 272 | 16 | 683,500 | 10386.8 | 65.8 |
| Lapurdi | 41 | 0 | 282,954 | 866.6 | 326.5 |
| Nafarroa Beherea | 76 | 0 | 33,092 | 1334.8 | 24.8 |
| Zuberoa | 44 | 0 | 14,643 | 824.2 | 17.8 |
| **Euskal Herria** | **686** | **20** | **3,253,999** | **20921** | **155.5** |

Population figures mix reference years: 2025 for the southern territories, 2023 for Iparralde
(INSEE's latest legal populations). Use `population_year` when comparing.

## Population density

![Population density by municipality](docs/population_density.png)

Density is shown per municipality with hand-picked classes (the values are very skewed: the
median is 34 inh./km², the densest municipalities pass 14,000). In `ehmap.rgis` it is the
`Dentsitatea` layer (hidden by default) and the `Dentsitatea` print layout.

## Population grid

![Where people live: population per km²](docs/population_grid.png)

Municipal densities spread people evenly over each municipality. The
[GHSL](https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE) population grid (EU Joint
Research Centre, 2020 estimate) places them where buildings are, so valleys, coastal corridors
and empty mountains show up. It is published here clipped to Euskal Herria, at 100 m (raster)
and aggregated to the Eurostat 1 km grid (vector).

GHSL is a **model**, good for showing where people live but not for exact counts: for this area
it totals 2.97 million people against 3.25 million in the official registers (2023–2025).

| Territory | GHSL 2020 / official |
|---|---|
| Araba | 0.99 |
| Bizkaia | 0.91 |
| Gipuzkoa | 0.87 |
| Nafarroa Garaia | 0.91 |
| Lapurdi | 0.94 |
| Nafarroa Beherea | 0.97 |
| Zuberoa | 0.98 |

For counts, use the municipal `population` field. In `ehmap.rgis` the grid is the
`Biztanleria 1km` layer (zoomed out) and `Biztanleria 100m` (zoomed in), hidden by default,
and the `Biztanleria sareta` print layout.

## Elevation and peaks

![Relief and the three highest peaks of each territory](docs/elevation.png)

Elevation comes from the Copernicus DEM GLO-30, reprojected to 25 m and clipped to Euskal
Herria; it is a surface model (it includes buildings and trees), so summits come out a few
metres lower than their surveyed heights and cities slightly higher. Peaks come from
OpenStreetMap (`natural=peak`). Many summits sit on a border, so each peak lists every
territory within 100 m (`territories`) and is ranked within each of them (`rank`).

| Territory | Mean elevation | Highest peak (OSM) |
|---|---|---|
| Araba | 667 m | Gorbeiako gurutzea 1,482 m (with Bizkaia) |
| Bizkaia | 295 m | Gorbeiako gurutzea 1,482 m (with Araba) |
| Gipuzkoa | 397 m | Aketegi 1,549 m |
| Nafarroa Garaia | 603 m | Hiru Erregeen Mahaia 2,446 m |
| Lapurdi | 110 m | Artzamendi 926 m |
| Nafarroa Beherea | 355 m | Okabe 1,466 m |
| Zuberoa | 536 m | Orhi 2,017 m (with Nafarroa Garaia) |

Per-municipality and per-territory minimum, mean and maximum elevation (and the location of
each territory's highest point) are in [`dist/elevation/`](dist/elevation/). In `ehmap.rgis`:
the `Erliebea` (shaded relief), `Gailurrak` and `Gailur nagusiak` layers, hidden by default,
and the `Erliebea` print layout.

**Known data issues** (to fix upstream in OpenStreetMap): the *Aitxuri* node (usually given as
1,551 m, the top of Gipuzkoa) is tagged 1,508 m and placed where the DEM shows only ~1,425 m,
so the Aitzkorri ridge appears topped by Aketegi instead.

## Rivers and the watershed divide

![Rivers, and the Bay of Biscay and Mediterranean sides](docs/rivers.png)

**Rivers** come from OpenStreetMap (`waterway=river`): each OSM river relation, or same-named
connected segments, is one river; pieces whose names match after normalising ("Zadorra",
"Río Zadorra", "Zadorra ibaia") are joined, also across reservoirs for rivers that have a
relation. Lengths are measured inside Euskal Herria.

| River | km in Euskal Herria | Territories |
|---|---|---|
| Ebro | 160 | Araba, Nafarroa Garaia |
| Arga | 147 | Nafarroa Garaia |
| Ega | 147 | Araba, Nafarroa Garaia |
| Aragoi | 118 | Nafarroa Garaia |
| Irati | 86 | Nafarroa Garaia |
| Arakil | 77 | Araba, Nafarroa Garaia |
| Errobi | 77 | Lapurdi, Nafarroa Beherea |
| Oria | 76 | Gipuzkoa |
| Biduze | 72 | Lapurdi, Nafarroa Beherea |
| Zadorra | 69 | Araba |

**The watershed divide** was computed from the elevation model with the GeoLibre (Whitebox)
hydrology tools that RustGIS uses: breach depressions, D8 flow direction and accumulation,
streams above 10 km² of catchment with their Strahler order, and the watershed of a point on
the Ebro below Zaragoza. The work is done at 100 m over 41–44°N, 4–0°W so that water reaches
its real outlet. **58% of Euskal Herria (12,241 km²) drains to the Mediterranean through the
Ebro, 42% (8,681 km²) to the Bay of Biscay**; the divide runs 401 km inside Euskal Herria.
It is approximate at the scale of a few hundred metres along the ridges.

| Territory | Bay of Biscay km² | Mediterranean km² |
|---|---|---|
| Araba | 455 | 2,860 |
| Bizkaia | 2,153 | 60 — Otxandio, Ubide and the south slopes of Gorbeia–Urkiola |
| Gipuzkoa | 1,936 | 45 — mostly the shared land of the Aitzkorri range |
| Nafarroa Garaia | 1,164 | 9,223 |
| Lapurdi | 867 | — |
| Nafarroa Beherea | 1,302 | 32 — the Irati forest (Lekunberri, Mendibe) |
| Zuberoa | 803 | 21 — the Irati forest (Larraine) |

In `ehmap.rgis`: the `Ibaiak`, `Isurialdeak` and `Banalerroa` layers (hidden by default) and the
`Isurialdeak` print layout. The DEM-derived streams are in
[`dist/elevation/streams_dem.gpkg`](dist/elevation/).

## Decisions

The 7 territories are historical, not current administrative units, so some choices had to be
made. Each is recorded in the `note` field and can be changed in
[`data/reference/iparralde_territories.csv`](data/reference/iparralde_territories.csv) or
[`scripts/01_build_territories.py`](scripts/01_build_territories.py).

- **Treviño enclave** (Condado de Treviño, La Puebla de Arganzón — administratively Burgos) is
  counted in Araba.
- **Iparralde** = the 158 communes of the Communauté d'agglomération Pays Basque, plus Esquiule
  and Gestas (Zuberoa historically and culturally) and Escos (disputed; Nafarroa Beherea) = 161.
- **Pagola** is historically split between Zuberoa and Nafarroa Beherea; assigned to Zuberoa.
- The Spanish and French sources draw the state border slightly differently: the Spanish line
  wins where they overlap, and gaps under 1 km² are merged into the neighbouring municipality.
  The result is a clean coverage (no gaps or overlaps between neighbours).
- Real enclaves and exclaves are kept: Villaverde de Trucios (Cantabria, inside Bizkaia),
  Orduña (Bizkaia, between Araba and Burgos), Petilla de Aragón (Nafarroa, inside Aragon).

Found a mistake or disagree with a choice? Please open an issue.

## Reproduce

Requires Python ≥ 3.12 and, for the project file, [RustGIS](https://rustgis.app) ≥ 0.4.

```bash
uv venv --python 3.12 .venv            # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/00_download.py          # source data -> data/raw/
.venv/bin/python scripts/01_build_territories.py # -> dist/
.venv/bin/python scripts/03_population_grid.py   # -> dist/population_grid/
.venv/bin/python scripts/04_elevation.py         # -> dist/elevation/, dist/osm/
.venv/bin/python scripts/05_rivers.py            # -> dist/osm/rivers, dist/elevation/ drainage (needs GeoLibre)
scripts/02_build_project.sh                      # -> ehmap.rgis, docs/ previews (needs rustgis-cli)
scripts/release.sh vX.Y.Z                        # publish a GitHub Release (maintainers)
```

`ehmap.rgis` and the rasters are not versioned in git (they are large and change on every
build); they are published as release assets.

## Licences

- **Data** (`dist/` except the two folders below, `data/reference/`, `docs/` except
  `elevation.png` and `rivers.png`): [CC BY 4.0](LICENSE-DATA). Sources and how to credit them:
  [ATTRIBUTION.md](ATTRIBUTION.md).
- **Elevation** (`dist/elevation/`, the DEM files): Copernicus WorldDEM-30 licence, with its
  required notices — see [`dist/elevation/LICENSE.md`](dist/elevation/LICENSE.md).
- **Peaks and rivers** (`dist/osm/`, `peaks.gpkg`, `rivers.gpkg`): [ODbL](https://opendatacommons.org/licenses/odbl/),
  © OpenStreetMap contributors — see [`dist/osm/LICENSE.md`](dist/osm/LICENSE.md).
- `ehmap.rgis`, `docs/elevation.png` and `docs/rivers.png` combine all three: follow each
  layer's licence.
- **Code** (`scripts/`): [MIT](LICENSE).
