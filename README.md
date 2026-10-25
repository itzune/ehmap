# ehmap — open geodata for Euskal Herria

Open, reproducible base layers of **Euskal Herria and its 7 territories**
(Araba, Bizkaia, Gipuzkoa, Nafarroa Garaia, Lapurdi, Nafarroa Beherea, Zuberoa), ready to use
in any GIS or web map. The goal is that anyone building something about Euskal Herria finds
the base already done, with clear sources and licences.

The project is also a playground to learn [RustGIS](https://github.com/opengeos/RustGIS);
next topics are elevation / mountain tops and forest change over the last years.

![The 7 territories of Euskal Herria](docs/euskal_herria_territories.png)

## Download

Everything in [`dist/`](dist/) (WGS 84, EPSG:4326):

| File | Contents |
|---|---|
| `dist/euskal_herria.gpkg` | GeoPackage with layers `municipalities`, `territories`, `euskal_herria` |
| `dist/geojson/*.geojson` | Same layers as GeoJSON (RFC 7946), full detail |
| `dist/geojson/simplified/*.geojson` | Lighter versions for web maps (~50 m simplification, shared borders kept) |
| `ehmap.rgis` | RustGIS project: territories, municipalities and population density (hidden layer + print layout), over an OpenStreetMap basemap |

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
scripts/02_build_project.sh                      # -> ehmap.rgis, docs/ previews (needs rustgis-cli)
```

## Licences

- **Data** (`dist/`, `data/reference/`, `docs/`, the layers in `ehmap.rgis`):
  [CC BY 4.0](LICENSE-DATA). Sources and how to credit them: [ATTRIBUTION.md](ATTRIBUTION.md).
- **Code** (`scripts/`): [MIT](LICENSE).
