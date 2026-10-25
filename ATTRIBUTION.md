# Attribution and source licences

The data in `dist/` is a derived work, published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (see `LICENSE-DATA`).
When you use it, credit **"ehmap contributors" (https://github.com/itzune/ehmap)** and keep the source credits below.

Suggested credit line:

> Euskal Herria boundaries: ehmap contributors, https://github.com/itzune/ehmap (CC BY 4.0), based on IGN España (CC BY 4.0),
> IGN France ADMIN EXPRESS (Licence Ouverte 2.0) and Wikidata (CC0).
> Population: INE (CC BY 4.0) and INSEE (Licence Ouverte 2.0).

## Sources used in `dist/`

| Data | Provider | Licence | Used for |
|---|---|---|---|
| Municipal boundaries of Spain (BDLJE), via Opendatasoft dataset `georef-spain-municipio` | © Instituto Geográfico Nacional de España (ign.es) | [CC BY 4.0](https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf) | Araba, Bizkaia, Gipuzkoa, Nafarroa Garaia, Treviño |
| ADMIN EXPRESS communes, via [geo.api.gouv.fr](https://geo.api.gouv.fr) | © IGN France | [Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) | Lapurdi, Nafarroa Beherea, Zuberoa |
| Commune → historic territory (P131), Basque names, item IDs | [Wikidata](https://www.wikidata.org) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `territory`, `name_eu`, `wikidata` fields |
| Cifras oficiales de población (Padrón municipal), 1 January 2025, via the INE API (`servicios.ine.es/wstempus`) | © Instituto Nacional de Estadística (INE) | [CC BY 4.0](https://www.ine.es/dyngs/AYU/index.htm?cid=125) | `population` of the southern municipalities |
| Populations de référence 2023 (population municipale), via the INSEE Melodi API (`api.insee.fr/melodi`) | © INSEE | [Licence Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) | `population` of the Iparralde communes |

Both CC BY 4.0 and the Licence Ouverte 2.0 allow redistribution of derived data, with
attribution, under CC BY 4.0.

## Not redistributed

- **OpenStreetMap tiles** — `ehmap.rgis` only references the standard tile server as a
  basemap; no OSM data is stored here. Map data © OpenStreetMap contributors,
  [ODbL](https://opendatacommons.org/licenses/odbl/). Heavy use must follow the
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
- **[itzune/nongoeuskara](https://github.com/itzune/nongoeuskara)** — used only to cross-check
  the commune list; none of its data is included.

Data derived from OpenStreetMap (e.g. mountain peaks) will be published separately under the
ODbL, as that licence requires.
