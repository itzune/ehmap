# Attribution and source licences

The data in `dist/` is a derived work, published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see `LICENSE-DATA`).
When you use it, credit **"ehmap contributors" (https://github.com/itzune/ehmap)** and keep the source credits below.

Suggested credit line:

> Euskal Herria boundaries: ehmap contributors, https://github.com/itzune/ehmap (CC BY 4.0), based on IGN España (CC BY 4.0),
> IGN France ADMIN EXPRESS (Licence Ouverte 2.0) and Wikidata (CC0).
> Population: INE (CC BY 4.0) and INSEE (Licence Ouverte 2.0).
> Population grid: GHSL GHS-POP R2023A, © European Union (CC BY 4.0).

## Sources used in `dist/`

| Data | Provider | Licence | Used for |
|---|---|---|---|
| Municipal boundaries of Spain (BDLJE), via Opendatasoft dataset `georef-spain-municipio` | © Instituto Geográfico Nacional de España (ign.es) | [CC BY 4.0](https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf) | Araba, Bizkaia, Gipuzkoa, Nafarroa Garaia, Treviño |
| ADMIN EXPRESS communes, via [geo.api.gouv.fr](https://geo.api.gouv.fr) | © IGN France | [Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) | Lapurdi, Nafarroa Beherea, Zuberoa |
| Commune → historic territory (P131), Basque names, item IDs | [Wikidata](https://www.wikidata.org) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `territory`, `name_eu`, `wikidata` fields |
| Cifras oficiales de población (Padrón municipal), 1 January 2025, via the INE API (`servicios.ine.es/wstempus`) | © Instituto Nacional de Estadística (INE) | [CC BY 4.0](https://www.ine.es/dyngs/AYU/index.htm?cid=125) | `population` of the southern municipalities |
| Populations de référence 2023 (population municipale), via the INSEE Melodi API (`api.insee.fr/melodi`) | © INSEE | [Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) | `population` of the Iparralde communes |
| GHS-POP R2023A, epoch 2020, 100 m (tile R4_C18): Schiavina, Freire, Carioli, MacManus, *GHS-POP R2023A - GHS population grid multitemporal (1975-2030)*, European Commission, Joint Research Centre, [doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE](https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE) | © European Union, 1995-2026 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `dist/population_grid/`. **Changes:** reprojected from Mollweide (ESRI:54009) to ETRS89-LAEA (EPSG:3035) with sum resampling, clipped to Euskal Herria, aggregated to 1 km |

Both CC BY 4.0 and the Licence Ouverte 2.0 allow redistribution of derived data, with
attribution, under CC BY 4.0.

## Under their own licences (not CC BY)

| Data | Provider | Licence | Used for |
|---|---|---|---|
| Copernicus DEM GLO-30, 1° tiles from the [AWS Open Data registry](https://registry.opendata.aws/copernicus-dem/) | © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA | [Copernicus WorldDEM-30 licence](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf) | `dist/elevation/` — notices and changes in [`dist/elevation/LICENSE.md`](dist/elevation/LICENSE.md) |
| `natural=peak` nodes via the Overpass API | © OpenStreetMap contributors | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | `dist/osm/` — see [`dist/osm/LICENSE.md`](dist/osm/LICENSE.md) |

## Not redistributed

- **OpenStreetMap tiles** — `ehmap.rgis` only references the standard tile server as a
  basemap; no OSM data is stored here. Map data © OpenStreetMap contributors,
  [ODbL](https://opendatacommons.org/licenses/odbl/). Heavy use must follow the
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
- **[itzune/nongoeuskara](https://github.com/itzune/nongoeuskara)** — used only to cross-check
  the commune list; none of its data is included.

Data derived from OpenStreetMap is published separately under the ODbL (`dist/osm/`), as that
licence requires.
