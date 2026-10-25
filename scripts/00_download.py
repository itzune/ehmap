"""Download the raw source data into data/raw/ (not versioned; rerun to reproduce).

Sources and licences are listed in ATTRIBUTION.md.
"""
import csv
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "ehmap/0.1 (https://github.com/itzune/ehmap)"}

ODS = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
       "georef-spain-municipio/exports/geojson")
WIKIDATA = "https://query.wikidata.org/sparql"

DOWNLOADS = {
    # IGN municipal boundaries (BDLJE, CC BY 4.0) republished by Opendatasoft
    "es/municipios_01_20_31_48.geojson": (ODS, {"where": 'prov_code in ("01","20","31","48")'}),
    "es/municipios_burgos_trevino.geojson": (ODS, {"where": 'mun_code in ("09109","09276")'}),
    # IGN ADMIN EXPRESS via the French government geo API (Licence Ouverte 2.0)
    "fr/communes_64.geojson": ("https://geo.api.gouv.fr/departements/64/communes",
                               {"format": "geojson", "geometry": "contour",
                                "fields": "nom,code,population,codeEpci"}),
}

# INE municipal population (Padrón, latest year; CC BY 4.0), one table per province
INE_TABLES = {"01": 2854, "20": 2873, "31": 2884, "48": 2905, "09": 2862}
INE = "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/{}"

# INSEE reference populations (Licence Ouverte 2.0): municipal population (PMUN)
INSEE = "https://api.insee.fr/melodi/data/DS_POPULATIONS_REFERENCE"
INSEE_YEAR = "2023"  # populations légales 2023, in force from 1 January 2026
INSEE_GEO = "2025-COM-{}"  # commune boundaries of 1 January 2025

# Wikidata (CC0): Basque labels of Spanish municipalities by INE code (P772).
# Iparralde Basque names live in data/reference/iparralde_territories.csv.
SPARQL = {
    "wikidata/names_eu_es.csv": """
        SELECT ?code ?wikidata ?name_eu WHERE {
          ?wikidata wdt:P772 ?code ; wdt:P31 wd:Q2074737 .
          FILTER(REGEX(?code, "^(01|20|31|48)[0-9]{3}$|^(09109|09276)$"))
          OPTIONAL { ?wikidata rdfs:label ?name_eu FILTER(LANG(?name_eu) = "eu") }
        }""",
}


def fetch(path: str, url: str, params: dict, headers: dict | None = None) -> None:
    out = RAW / path
    out.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=300)
    r.raise_for_status()
    out.write_bytes(r.content)
    print(f"{path}: {len(r.content) / 1e6:.1f} MB")


def insee_population(codes: list[str], batch: int = 40) -> None:
    """Municipal population of the given communes, as one JSON list of observations."""
    obs = []
    for i in range(0, len(codes), batch):
        params = [("GEO", INSEE_GEO.format(c)) for c in codes[i:i + batch]]
        params += [("POPREF_MEASURE", "PMUN"), ("TIME_PERIOD", INSEE_YEAR), ("maxResult", 1000)]
        r = requests.get(INSEE, params=params, headers=UA, timeout=300)
        r.raise_for_status()
        obs += r.json()["observations"]
    out = RAW / "insee" / f"population_{INSEE_YEAR}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obs))
    print(f"{out.relative_to(RAW)}: {len(obs)} communes")


def main() -> None:
    for path, (url, params) in DOWNLOADS.items():
        fetch(path, url, params)
    for path, query in SPARQL.items():
        fetch(path, WIKIDATA, {"query": query}, {"Accept": "text/csv"})
    for prov, table in INE_TABLES.items():
        fetch(f"ine/population_{prov}.json", INE.format(table), {"nult": 1, "tip": "AM"})
    with open(ROOT / "data" / "reference" / "iparralde_territories.csv") as f:
        insee_population([row["insee"] for row in csv.DictReader(f)])


if __name__ == "__main__":
    main()
