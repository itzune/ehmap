"""Download the raw source data into data/raw/ (not versioned; rerun to reproduce).

Sources and licences are listed in ATTRIBUTION.md.
"""
import csv
import io
import json
import time
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

# National LiDAR DTMs at 5 m, both free and keyless:
#  · Spain, PNOA-LiDAR MDT05 (IGN, CC BY 4.0) through the INSPIRE WCS coverage
#    Elevacion25830_5 — already in our working CRS, native COG, windowed SUBSET
#  · France, RGE ALTI (IGN, Licence Ouverte 2.0) as WMS ``terrainrgb`` (elevation
#    encoded in the PNG channels), which spares unpacking the 10 GB department archive
LIDAR_BOX = (450000, 4630000, 705000, 4835000)   # EPSG:25830: the relief frame + slack
LIDAR_RES = 5
LIDAR_WCS = "https://servicios.idee.es/wcs-inspire/mdt"
LIDAR_WCS_COVERAGE = "Elevacion25830_5"
LIDAR_WMS = "https://data.geopf.fr/wms-r/wms"
LIDAR_WMS_LAYER = "RGEALTI-MNT_PYR-ZIP_FXX_LAMB93_WMS"

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


def lidar() -> None:
    """One 5 m bare-earth DTM over the relief frame: PNOA-LiDAR plus RGE ALTI.

    Both sources store water as flat values (Spain 0, the French encoding's -10000 m), so
    a single `> 0` rule marks the sea. Blocks are merged rather than overwritten, which
    lets the two national triangulations meet cleanly along the Bidasoa instead of one
    reprojection punching holes in the other.

    PNOA always wins; RGE ALTI only fills cells PNOA left empty. The French service is
    not void outside France: it answers with a coarse, blocky filler DEM well into
    Nafarroa (tens of metres off the LiDAR near Bera and Elizondo), which must never
    replace the Spanish 5 m surface.
    """
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject
    from rasterio.windows import Window
    from rasterio.windows import from_bounds as window_from_bounds

    x0, y0, x1, y1 = LIDAR_BOX
    res = LIDAR_RES
    out = RAW / "lidar" / f"eh_lidar_{res}m.tif"
    progress = RAW / "lidar" / "blocks.json"
    if out.exists():
        done = set(json.loads(progress.read_text())) if progress.exists() else set()
    else:
        done = set()
    out.parent.mkdir(parents=True, exist_ok=True)

    def fetch(url: str, params, tries: int = 3):
        """The two national services hiccup (502s, truncated bodies, sporadic 400s);
        retry before deciding a block is genuinely absent."""
        for k in range(tries):
            try:
                r = requests.get(url, headers=UA, timeout=900, params=params)
                if r.status_code == 200:
                    return r.content
            except requests.RequestException:
                pass
            time.sleep(2 + 3 * k)
        return None

    def mark(key: str) -> None:
        done.add(key)
        progress.write_text(json.dumps(sorted(done)))
    transform = Affine(res, 0, x0, 0, -res, y1)
    shape = (int((y1 - y0) / res), int((x1 - x0) / res))
    profile = dict(driver="GTiff", width=shape[1], height=shape[0], count=1, dtype="int16",
                   crs="EPSG:25830", transform=transform, tiled=True, blockxsize=512,
                   blockysize=512, compress="DEFLATE", zlevel=6, BIGTIFF="IF_SAFER")
    if not out.exists():
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(np.zeros(shape, "int16"), 1)      # 0 stands for the sea

    def put(dst, arr, bbox, bbox_crs, src_crs, src_transform, fill_only: bool = False) -> None:
        """Reproject a block onto the mosaic grid and merge it: positive values win, or
        with `fill_only` they only fill cells that are still empty (<= 0)."""
        from rasterio.warp import transform_bounds
        if bbox_crs != dst.crs:
            try:
                bbox = transform_bounds(bbox_crs, dst.crs, *bbox)
            except Exception:
                return
        try:
            win = window_from_bounds(*bbox, dst.transform)
            win = win.intersection(Window(0, 0, dst.width, dst.height))
        except rasterio.errors.WindowError:
            return
        if win.width < 2 or win.height < 2:
            return
        win = win.round_offsets().round_lengths()
        block = np.full((int(win.height), int(win.width)), np.nan, "float32")
        reproject(arr, block, src_transform=src_transform, src_crs=src_crs,
                  dst_transform=dst.window_transform(win), dst_crs=dst.crs,
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
        block[block < -1000] = np.nan                     # the French encoding's void
        old = dst.read(1, window=win).astype("float32")
        take = np.isfinite(block) & (block > 0)
        if fill_only:
            take &= old <= 0
        merged = np.where(take, block, old)
        # rint, not astype: a cast truncates, so RGE ALTI's decimetres would all drop
        dst.write(np.rint(np.nan_to_num(merged, nan=0)).astype("int16"), 1, window=win)

    with rasterio.open(out, "r+") as dst:
        # --- Spain first: 20 km WCS windows, already on our grid ---
        for by in range(y0, y1, 20000):
            for bx in range(x0, x1, 20000):
                key = f"es:{bx}:{by}"
                if key in done:
                    continue
                body = fetch(LIDAR_WCS, [
                    ("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
                    ("COVERAGEID", LIDAR_WCS_COVERAGE), ("FORMAT", "image/tiff"),
                    ("SUBSET", f"x({bx},{min(bx + 20000, x1)})"),
                    ("SUBSET", f"y({by},{min(by + 20000, y1)})")])
                if body is None:
                    print(f"  pnoa {bx},{by}: no data", flush=True)
                    continue
                try:
                    with rasterio.io.MemoryFile(body) as mf:
                        with mf.open() as src:
                            put(dst, src.read(1).astype("float32"), tuple(src.bounds),
                                src.crs, src.crs, src.transform)
                except Exception as e:
                    print(f"  pnoa {bx},{by}: {e}", flush=True)
                    continue
                mark(key)
                print(f"  pnoa {bx},{by}", flush=True)

        # --- France second, filling only what PNOA left empty (see the docstring) ---
        step = 0.2
        n_img = int(round(step * 111320 / 4.5))           # ~4.5 m cells at this latitude
        # rows of 0.2° up to 43.75°N: the frame reaches ~43.62°N (south Landes); a
        # row short, Labenne-Capbreton came out as 0 m, i.e. as sea
        for lat in (42.75, 42.95, 43.15, 43.35, 43.55):
            for lon in (-1.95, -1.75, -1.55, -1.35, -1.15, -0.95, -0.75, -0.55, -0.35):
                key = f"fr:{lon}:{lat}"
                if key in done:
                    continue
                body = fetch(LIDAR_WMS, {
                    "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                    "LAYERS": LIDAR_WMS_LAYER, "STYLES": "terrainrgb", "CRS": "CRS:84",
                    "BBOX": f"{lon},{lat},{lon + step},{lat + step}",
                    "WIDTH": n_img, "HEIGHT": n_img, "FORMAT": "image/png"})
                if body is None:
                    print(f"  rge-alti {lon:+.2f},{lat:+.2f}: no data", flush=True)
                    continue
                try:
                    im = Image.open(io.BytesIO(body))
                    im.load()                                  # a truncated PNG raises here
                    px = np.asarray(im.convert("RGB"), "float64")
                except Exception as e:
                    print(f"  rge-alti {lon:+.2f},{lat:+.2f}: {e}", flush=True)
                    continue
                elev = -10000 + (px[..., 0] * 65536 + px[..., 1] * 256 + px[..., 2]) * 0.1
                put(dst, elev.astype("float32"), (lon, lat, lon + step, lat + step),
                    "EPSG:4326", "EPSG:4326",
                    Affine(step / n_img, 0, lon, 0, -step / n_img, lat + step),
                    fill_only=True)
                mark(key)
                print(f"  rge-alti {lon:+.2f},{lat:+.2f}", flush=True)
    print(f"lidar/{out.name}: {out.stat().st_size / 1e6:.0f} MB, "
          f"{shape[1]}x{shape[0]} at {res} m")


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
    lidar()


if __name__ == "__main__":
    main()
