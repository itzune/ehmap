"""Download the raw source data into data/raw/ (not versioned; rerun to reproduce).

Sources and licences are listed in ATTRIBUTION.md.
"""
import csv
import io
import json
import zipfile
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

# GHSL GHS-POP R2023A, epoch 2020, 100 m Mollweide (JRC, CC BY 4.0); tile R4_C18 covers Euskal Herria
GHSL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/")
GHSL_TILE = "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R4_C18"

# Copernicus DEM GLO-30 (Copernicus WorldDEM-30 licence), 1° tiles on AWS Open Data
COPDEM = "https://copernicus-dem-30m.s3.amazonaws.com/{0}/{0}.tif"
COPDEM_TILE = "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM"
COPDEM_LATS, COPDEM_LONS = (41, 42, 43), (4, 3, 2, 1)  # 41-44°N, 4-0°W

# ESA WorldCover 2021 v200 (CC BY 4.0), 3°x3° tiles covering Euskal Herria
WORLDCOVER = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_{}_Map.tif")
WORLDCOVER_TILES = ("N39W006", "N39W003", "N42W006", "N42W003")

# OpenStreetMap peaks (ODbL) via Overpass, in the Euskal Herria bounding box
OVERPASS = "https://overpass-api.de/api/interpreter"
PEAKS_QUERY = """[out:json][timeout:180];
node["natural"="peak"](41.85,-3.55,43.65,-0.55);
out body;"""
RIVERS_QUERY = """[out:json][timeout:300];
way["waterway"="river"](41.85,-3.55,43.65,-0.55)->.w;
.w out geom;
rel["type"="waterway"](bw.w);
out body;"""

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


def ghsl() -> None:
    """Download the GHSL tile and extract only its GeoTIFF."""
    out = RAW / "ghsl" / f"{GHSL_TILE}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(f"{GHSL}{GHSL_TILE}.zip", headers=UA, timeout=600)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        out.write_bytes(z.read(f"{GHSL_TILE}.tif"))
    print(f"{out.relative_to(RAW)}: {out.stat().st_size / 1e6:.1f} MB")


def copdem() -> None:
    for lat in COPDEM_LATS:
        for lon in COPDEM_LONS:
            tile = COPDEM_TILE.format(lat=lat, lon=lon)
            out = RAW / "copdem" / f"{tile}.tif"
            if not out.exists():
                fetch(f"copdem/{tile}.tif", COPDEM.format(tile), {})


def worldcover() -> None:
    for tile in WORLDCOVER_TILES:
        if not (RAW / "worldcover" / f"{tile}.tif").exists():
            fetch(f"worldcover/{tile}.tif", WORLDCOVER.format(tile), {})


def main() -> None:
    for path, (url, params) in DOWNLOADS.items():
        fetch(path, url, params)
    for path, query in SPARQL.items():
        fetch(path, WIKIDATA, {"query": query}, {"Accept": "text/csv"})
    for prov, table in INE_TABLES.items():
        fetch(f"ine/population_{prov}.json", INE.format(table), {"nult": 1, "tip": "AM"})
    with open(ROOT / "data" / "reference" / "iparralde_territories.csv") as f:
        insee_population([row["insee"] for row in csv.DictReader(f)])
    ghsl()
    copdem()
    fetch("osm/peaks.json", OVERPASS, {"data": PEAKS_QUERY})
    fetch("osm/rivers.json", OVERPASS, {"data": RIVERS_QUERY})
    worldcover()


if __name__ == "__main__":
    main()
