"""Hiking-trail vector tiles of Euskal Herria, from OpenStreetMap, as PMTiles.

The topographic sheet (scripts/13_topo_tiles.py) carries the ground; this carries
what a walker actually follows: the path network, the marked itineraries and the
shelters, springs and viewpoints along them. It is a **separate archive** from
site/data/euskal_herria.pmtiles on purpose — this data is ODbL, not CC BY, so the
map shows its attribution only while these layers are on screen.

Layers (Mapbox Vector Tile, gzip, extent 4096):
  trails   z11-13  highway=track, then path/footway/steps/bridleway from z12,
                   with sac_scale where OSM records it
  routes   z10-13  relation route=hiking, carrying network (nwn/rwn/lwn) and ref
                   (GR 121, ...), drawn as an overlay on the ways they follow
  pois     z12-13  refuges, wilderness huts, shelters, viewpoints, campsites, springs

Queries are split by highway class: a single Overpass call for the whole 373 533-way
network times out. Responses are cached under data/raw/osm/bideak/ (gitignored).

Preview: `pmtiles serve site/data --port 7999 --cors='*'`, then read
http://localhost:7999/bideak/{z}/{x}/{y}.
"""
import gzip
import json
import math
import time
from pathlib import Path

import mapbox_vector_tile
import numpy as np
import requests
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import LineString, Point, shape

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "osm" / "bideak"
OUT = ROOT / "site" / "data" / "bideak.pmtiles"

BBOX = (41.85, -3.55, 43.65, -0.55)      # south, west, north, east
OVERPASS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.openstreetmap.ru/api/interpreter",
            "https://overpass.nchc.org.tw/api/interpreter")
UA = {"User-Agent": "ehmap/0.1 (https://github.com/itzune/ehmap)"}
EXTENT = 4096
SIMPLIFY_PX = 2

TRAIL_CLASSES = (("track", 11), ("path", 12), ("footway", 12), ("steps", 12), ("bridleway", 12))
# one union query: four separate ones multiply the odds of hitting a busy server
POI_QUERY = ("(",
             'nwr["tourism"~"^(alpine_hut|wilderness_hut|camp_site|viewpoint)$"]',
             'nwr["amenity"="shelter"]',
             'nwr["natural"="spring"]',
             ")")


def norm_y(lat: float) -> float:
    lat = max(-85.05112878, min(85.05112878, lat))
    return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2


def merc_px(arr, n: int, tx: int, ty: int):
    """lon/lat array -> tile pixel array, y down."""
    lon, lat = arr[:, 0], arr[:, 1]
    my = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2
    return np.column_stack([((lon + 180) / 360 * n - tx) * EXTENT,
                            ((my * n - ty) * EXTENT)])


def overpass(name: str, query: str, out: str = "out tags geom;",
             union: tuple[str, ...] | None = None) -> dict | None:
    """Run one Overpass query, cached under data/raw/osm/bideak/."""
    out = RAW / f"{name}.json"
    if out.exists():
        return json.loads(out.read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    bb = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    if union:
        lines = "\n".join(f"  {part}({bb});" for part in union if part not in ("(", ")"))
        q = "[out:json][timeout:900];\n(\n" + lines + "\n);\n" + out
    else:
        q = f"[out:json][timeout:900];{query}({bb});{out}"
    for attempt in range(9):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, headers=UA, timeout=1200)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                out.write_text(r.text)
                print(f"  {name}: {len(r.content) / 1e6:.0f} MB", flush=True)
                return json.loads(r.text)
            print(f"  {name}: HTTP {r.status_code} from {url.split('/')[2]}", flush=True)
        except requests.RequestException as e:
            print(f"  {name}: {type(e).__name__} from {url.split('/')[2]}", flush=True)
        time.sleep(15 * (attempt + 1))
    print(f"  {name}: giving up for now", flush=True)
    return None


def lines_from(data: dict) -> list[tuple[LineString, dict, int]]:
    """Line geometries out of an Overpass `out geom` response."""
    out = []
    for el in data.get("elements", []):
        geom = el.get("geometry")
        if not geom:
            continue
        pts = [(p["lon"], p["lat"]) for p in geom if p]
        if len(pts) < 2:
            continue
        out.append((LineString(pts), el.get("tags", {}), el.get("id")))
    return out


def points_from(data: dict) -> list[tuple[Point, dict]]:
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if el.get("lat") is not None:
            out.append((Point(el["lon"], el["lat"]), tags))
        elif el.get("center"):
            c = el["center"]
            out.append((Point(c["lon"], c["lat"]), tags))
        elif el.get("geometry"):
            pts = [(p["lon"], p["lat"]) for p in el["geometry"] if p]
            if pts:
                out.append((Point(pts[len(pts) // 2]), tags))
    return out


def route_membership(data: dict) -> dict[int, dict]:
    """{way id: {"net": ..., "ref": ...}} from route=hiking relations.

    The lines themselves already come in as trails; a route only decides how they
    are marked, so the archive carries no duplicate geometry.
    """
    rank = {"iwn": 0, "nwn": 1, "rwn": 2, "lwn": 3, "": 9}
    out: dict[int, dict] = {}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        net = tags.get("network", "")
        ref = tags.get("ref", "")
        for m in el.get("members", []):
            if m.get("type") != "way":
                continue
            cur = out.get(m["ref"])
            if cur is None or rank.get(net, 9) < rank.get(cur["net"], 9):
                out[m["ref"]] = {"net": net, "ref": ref}
    return out


def build_layer(feats, zmin: int, zmax: int, tiles: dict, keep: tuple[str, ...],
                layer: str) -> None:
    """Simplify per zoom, bucket into tiles, clip."""
    for z in range(zmin, zmax + 1):
        n = 1 << z
        tol = 360 / n / EXTENT * SIMPLIFY_PX
        for geom, tags in feats:
            props = {k: tags[k] for k in keep if tags.get(k)}
            simple = geom.simplify(tol, preserve_topology=True)
            if simple.is_empty:
                simple = geom
            b = simple.bounds
            tx0, tx1 = int((b[0] + 180) / 360 * n), min(int((b[2] + 180) / 360 * n), n - 1)
            ty0, ty1 = int(norm_y(b[3]) * n), min(int(norm_y(b[1]) * n), n - 1)
            if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 64:      # a stray world-spanning way
                continue
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    box = (-180 + tx / n * 360, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n)))),
                           -180 + (tx + 1) / n * 360, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n)))))
                    clipped = shapely.intersection(simple, shapely.geometry.box(*box))
                    if clipped.is_empty:
                        continue
                    for part in getattr(clipped, "geoms", [clipped]):
                        if part.is_empty or part.geom_type not in ("LineString", "Point"):
                            continue
                        tiles.setdefault((z, tx, ty), {}).setdefault(layer, []).append({
                                "geometry": shapely.transform(part, lambda a: merc_px(a, n, tx, ty)),
                                "properties": props})


def main() -> None:
    t0 = time.time()
    RAW.mkdir(parents=True, exist_ok=True)
    tiles: dict[tuple[int, int, int], dict[str, list]] = {}

    # --- which ways are part of a marked itinerary ---
    data = overpass("routes", 'relation["route"="hiking"]', out="out body;")
    marked = route_membership(data) if data else {}
    print(f" · routes: {len(marked)} ways belong to a hiking relation", flush=True)

    # --- trails, one Overpass query per class (a single one times out) ---
    for cls, zmin in TRAIL_CLASSES:
        data = overpass(cls, f'way["highway"="{cls}"]')
        if data is None:
            continue
        feats = []
        for g, t, oid in lines_from(data):
            t = dict(t, highway=cls)
            if oid in marked:
                t["route_net"] = marked[oid]["net"]
                t["route_ref"] = marked[oid]["ref"]
            feats.append((g, t))
        print(f" · {cls}: {len(feats)} ways "
              f"({sum(1 for _, t in feats if t.get('route_net'))} marked)", flush=True)
        build_layer(feats, zmin, 13, tiles,
                    ("highway", "sac_scale", "surface", "name", "trail_visibility",
                     "route_net", "route_ref"), "trails")

    # --- huts, shelters, viewpoints, springs ---
    data = overpass("pois", "", out="out center;", union=POI_QUERY)
    if data is not None:
        feats = points_from(data)
        print(f" · pois: {len(feats)}", flush=True)
        build_layer(feats, 12, 13, tiles,
                    ("name", "tourism", "amenity", "natural", "ele"), "pois")

    count = 0
    with OUT.open("wb") as f:
        wr = Writer(f)
        for (z, tx, ty), layers in sorted(tiles.items()):
            mvt_layers = [{"name": name, "features": items}
                          for name, items in layers.items() if items]
            if not mvt_layers:
                continue
            body = gzip.compress(mapbox_vector_tile.encode(
                mvt_layers, default_options={"y_coord_down": True, "extents": EXTENT}))
            wr.write_tile(zxy_to_tileid(z, tx, ty), body)
            count += 1
        lons = [-180 + tx / (1 << z) * 360 for (z, tx, ty) in tiles]
        lats = [math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / (1 << z)))))
                for (z, tx, ty) in tiles]
        wr.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_lon_e7": int(min(lons) * 1e7), "min_lat_e7": int(min(lats) * 1e7),
                "max_lon_e7": int((max(lons) + 0.05) * 1e7),
                "max_lat_e7": int((max(lats) + 0.05) * 1e7),
                "center_lon_e7": int((min(lons) + max(lons)) / 2 * 1e7),
                "center_lat_e7": int((min(lats) + max(lats)) / 2 * 1e7),
                "center_zoom": 12,
            },
            {
                "name": "bideak",
                "description": "ehmap: hiking trails, marked itineraries and trail-side points",
                "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
                "licence": "ODbL 1.0",
                "vector_layers": [
                    {"id": "trails", "description": "path network (highway)", "fields": {}},
                    {"id": "pois", "description": "huts, shelters, viewpoints, springs", "fields": {}},
                ],
            })
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
