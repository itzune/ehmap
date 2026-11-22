"""What the topographic sheet names and crosses: water, roads, rail, places and
summits of Euskal Herria, from OpenStreetMap, as vector PMTiles.

scripts/13_topo_tiles.py bakes the ground (relief, contours, rock) into a raster and
scripts/14_bideak.py carries the trails. This is the rest of a hiking sheet's
drawing, kept as vectors so the lines and the lettering stay sharp past the
raster's deepest zoom. Like bideak.pmtiles it is ODbL, in its own archive:
site/data/topo_osm.pmtiles.

Layers (Mapbox Vector Tile, gzip, extent 4096; tile zoom = map zoom):
  water        z9-13   lakes, reservoirs and wide rivers, as polygons (the smallest
                       are dropped at the low zooms)
  waterways    z9-13   river and canal from z9, stream from z12; name
  roads        z9-13   kind = motorway | trunk | primary (z9) | secondary (z10) |
                       tertiary (z11) | minor (z12); ref, name, tunnel
  rail         z10-13  railway=rail; tunnel
  places       z9-13   kind = city | town (z9) | village (z11) | hamlet (z13);
                       name (Basque where OSM has one), population
  landmarks    z12-13  kind = church | cave | picnic | megalith | castle | ruins |
                       waterfall | fountain | tower; name
  summits      z10-13  kind = peak | saddle; name, ele (m). Below z12 only the
                       summits a map of that scale would name: the highest of each
                       ~5 km cell

Names prefer name:eu, then name. Overpass responses are cached under
data/raw/osm/topo/ (gitignored); the Overpass plumbing and the line/point tiling
are scripts/14_bideak.py's.

    uv run --quiet --with-requirements requirements.txt python scripts/15_topo_osm.py
"""
from __future__ import annotations

import gzip
import importlib.util
import math
import time
from pathlib import Path

import mapbox_vector_tile
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "topo_osm.pmtiles"
ZMAX = 13

_spec = importlib.util.spec_from_file_location("bideak", ROOT / "scripts" / "14_bideak.py")
bideak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bideak)
bideak.RAW = ROOT / "data" / "raw" / "osm" / "topo"      # this script's own cache
EXTENT = bideak.EXTENT

ROADS = (  # (cache name, Overpass filter)
    ("road_major", 'way["highway"~"^(motorway|trunk|primary)(_link)?$"]'),
    ("road_secondary", 'way["highway"~"^(secondary|tertiary)(_link)?$"]'),
    ("road_unclassified", 'way["highway"="unclassified"]'),
    ("road_residential", 'way["highway"~"^(residential|living_street)$"]'),
)
ROAD_ZMIN = {"motorway": 9, "trunk": 9, "primary": 9, "secondary": 10, "tertiary": 11, "minor": 12}
PLACE_ZMIN = {"city": 9, "town": 9, "village": 11, "hamlet": 13}
WATER_QUERY = ("(", 'nwr["natural"="water"]', 'nwr["waterway"="riverbank"]',
               'nwr["landuse"="reservoir"]', ")")
PLACE_QUERY = ("(", 'node["place"~"^(city|town|village|hamlet)$"]', ")")
LANDMARK_QUERY = ("(",
                  'nwr["amenity"="place_of_worship"]',
                  'nwr["natural"="cave_entrance"]',
                  'nwr["tourism"="picnic_site"]',
                  'nwr["historic"~"^(archaeological_site|castle|ruins|tower)$"]',
                  'nwr["waterway"="waterfall"]',
                  'nwr["amenity"="drinking_water"]',
                  'nwr["man_made"="tower"]["tower:type"~"^(communication|observation)$"]',
                  ")")
SUMMIT_QUERY = ("(", 'node["natural"~"^(peak|saddle)$"]', 'node["mountain_pass"="yes"]', ")")
# water smaller than this many square pixels of a 256 px tile is not drawn at a zoom
WATER_MIN_PX2 = 6


def name_of(tags: dict) -> str | None:
    return tags.get("name:eu") or tags.get("name")


def number(text: str | None) -> float | None:
    """'1 234 m', '1234.5' -> a number, or None."""
    if not text:
        return None
    try:
        return float(text.replace(",", ".").replace("m", "").replace(" ", ""))
    except ValueError:
        return None


def landmark_kind(t: dict) -> str | None:
    """One of church | cave | picnic | megalith | castle | ruins | waterfall | fountain | tower."""
    if t.get("amenity") == "place_of_worship":
        return "church"
    if t.get("natural") == "cave_entrance":
        return "cave"
    if t.get("tourism") == "picnic_site":
        return "picnic"
    if t.get("waterway") == "waterfall":
        return "waterfall"
    if t.get("amenity") == "drinking_water":
        return "fountain"
    h = t.get("historic")
    if h == "archaeological_site":
        return "megalith"
    if h in ("castle", "tower"):
        return "castle"
    if h == "ruins":
        return "ruins"
    if t.get("man_made") == "tower":
        return "tower"
    return None


def polygons_from(data: dict) -> list[tuple[Polygon, dict]]:
    """Polygons out of an Overpass `out geom` response: closed ways and multipolygons."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "way":
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
            if len(pts) >= 4 and pts[0] == pts[-1]:
                out.append((Polygon(pts), tags))
        elif el["type"] == "relation":
            rings = {"outer": [], "inner": []}
            for m in el.get("members", []):
                pts = [(p["lon"], p["lat"]) for p in m.get("geometry") or [] if p]
                if m.get("type") == "way" and len(pts) >= 2:
                    rings["inner" if m.get("role") == "inner" else "outer"].append(LineString(pts))
            if not rings["outer"]:
                continue
            # a ring is usually split over several member ways: stitch, then polygonize
            outer = unary_union(list(polygonize(unary_union(rings["outer"]))))
            if rings["inner"]:
                outer = outer.difference(unary_union(list(polygonize(unary_union(rings["inner"])))))
            if not outer.is_empty:
                out.append((outer, tags))
    return [(shapely.make_valid(g), t) for g, t in out]


def build_polygons(feats, zmin: int, zmax: int, tiles: dict, layer: str) -> None:
    """Simplify per zoom, drop what is too small to see, clip to each tile.

    Tiles are clipped a little wide: a fill cut exactly on the tile edge leaves a
    hairline between two neighbours.
    """
    for z in range(zmin, zmax + 1):
        n = 1 << z
        px = 360 / n / 256                           # one screen pixel, in degrees
        tol = 360 / n / EXTENT * bideak.SIMPLIFY_PX
        for geom, props in feats:
            if geom.area < WATER_MIN_PX2 * px * px * 0.73:      # ~cos(43°): lat degrees are longer
                continue
            simple = geom.simplify(tol, preserve_topology=True)
            if simple.is_empty:
                continue
            b = simple.bounds
            tx0, tx1 = int((b[0] + 180) / 360 * n), min(int((b[2] + 180) / 360 * n), n - 1)
            ty0, ty1 = int(bideak.norm_y(b[3]) * n), min(int(bideak.norm_y(b[1]) * n), n - 1)
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
                    m = 64 / EXTENT
                    box = shapely.geometry.box(-180 + (tx - m) / n * 360, lat(ty + 1 + m),
                                               -180 + (tx + 1 + m) / n * 360, lat(ty - m))
                    clipped = shapely.intersection(simple, box)
                    for part in getattr(clipped, "geoms", [clipped]):
                        if part.is_empty or part.geom_type != "Polygon":
                            continue
                        tiles.setdefault((z, tx, ty), {}).setdefault(layer, []).append({
                            "geometry": shapely.transform(
                                part, lambda a: bideak.merc_px(a, n, tx, ty)),
                            "properties": props})


def lines(name: str, query: str) -> list:
    data = bideak.overpass(name, query)
    return bideak.lines_from(data) if data else []


def main() -> None:
    t0 = time.time()
    tiles: dict[tuple[int, int, int], dict[str, list]] = {}

    # --- water ---------------------------------------------------------------
    data = bideak.overpass("water_area", "", out="out geom;", union=WATER_QUERY)
    areas = [(g, {"name": name_of(t)} if name_of(t) else {}) for g, t in polygons_from(data or {})]
    print(f" · water: {len(areas)} polygons", flush=True)
    build_polygons(areas, 9, ZMAX, tiles, "water")

    for cache, query, zmin in (("water_river", 'way["waterway"~"^(river|canal)$"]', 9),
                               ("water_stream", 'way["waterway"="stream"]', 12)):
        feats = [(g, {"kind": t.get("waterway"), "name": name_of(t),
                      "tunnel": 1 if t.get("tunnel") in ("yes", "culvert") else None})
                 for g, t, _ in lines(cache, query)]
        print(f" · {cache}: {len(feats)} ways", flush=True)
        bideak.build_layer(feats, zmin, ZMAX, tiles, ("kind", "name", "tunnel"), "waterways")

    # --- roads and rail ----------------------------------------------------------
    by_kind: dict[str, list] = {}
    for cache, query in ROADS:
        for g, t, _ in lines(cache, query):
            kind = t["highway"].removesuffix("_link")
            kind = kind if kind in ROAD_ZMIN else "minor"
            by_kind.setdefault(kind, []).append(
                (g, {"kind": kind, "ref": t.get("ref"), "name": name_of(t),
                     "link": 1 if t["highway"].endswith("_link") else None,
                     "tunnel": 1 if t.get("tunnel") == "yes" else None}))
    for kind, feats in by_kind.items():
        print(f" · roads/{kind}: {len(feats)} ways", flush=True)
        bideak.build_layer(feats, ROAD_ZMIN[kind], ZMAX, tiles,
                           ("kind", "ref", "name", "link", "tunnel"), "roads")

    feats = [(g, {"tunnel": 1 if t.get("tunnel") == "yes" else None})
             for g, t, _ in lines("rail", 'way["railway"="rail"]')
             if t.get("service") not in ("yard", "siding", "spur", "crossover")]
    print(f" · rail: {len(feats)} ways", flush=True)
    bideak.build_layer(feats, 10, ZMAX, tiles, ("tunnel",), "rail")

    # --- places ------------------------------------------------------------------
    data = bideak.overpass("places", "", out="out body;", union=PLACE_QUERY)
    by_kind = {}
    for g, t in bideak.points_from(data or {}):
        if name_of(t):
            pop = number(t.get("population"))
            by_kind.setdefault(t["place"], []).append(
                (g, {"kind": t["place"], "name": name_of(t),
                     "population": int(pop) if pop else None}))
    for kind, feats in by_kind.items():
        print(f" · places/{kind}: {len(feats)}", flush=True)
        bideak.build_layer(feats, PLACE_ZMIN[kind], ZMAX, tiles,
                           ("kind", "name", "population"), "places")

    # --- summits and passes ------------------------------------------------------
    data = bideak.overpass("summits", "", out="out body;", union=SUMMIT_QUERY)
    summits = []
    for g, t in bideak.points_from(data or {}):
        if not name_of(t):
            continue
        ele = number(t.get("ele"))
        kind = "peak" if t.get("natural") == "peak" else "saddle"
        summits.append((g, {"kind": kind, "name": name_of(t),
                            "ele": int(round(ele)) if ele else None}))
    # the low zooms name one summit per cell — the highest — as a small-scale map does
    for z, cell in ((10, 0.10), (11, 0.05)):
        best: dict[tuple[int, int], tuple] = {}
        for g, p in summits:
            if p["kind"] != "peak" or not p["ele"]:
                continue
            key = (int(g.x / cell), int(g.y / (cell * 0.73)))
            if key not in best or p["ele"] > best[key][1]["ele"]:
                best[key] = (g, p)
        bideak.build_layer(list(best.values()), z, z, tiles, ("kind", "name", "ele"), "summits")
    print(f" · summits: {len(summits)} named", flush=True)
    bideak.build_layer(summits, 12, ZMAX, tiles, ("kind", "name", "ele"), "summits")

    # --- landmarks: what a walker steers by or stops at -----------------------------
    data = bideak.overpass("landmarks", "", out="out center;", union=LANDMARK_QUERY)
    feats = []
    for g, t in bideak.points_from(data or {}):
        kind = landmark_kind(t)
        if kind:
            feats.append((g, {"kind": kind, "name": name_of(t)}))
    print(f" · landmarks: {len(feats)}", flush=True)
    bideak.build_layer(feats, 12, ZMAX, tiles, ("kind", "name"), "landmarks")

    # --- archive -----------------------------------------------------------------
    count = 0
    tmp = OUT.with_suffix(".pmtiles.part")
    with tmp.open("wb") as f:
        wr = Writer(f)
        for (z, tx, ty), layers in sorted(tiles.items(), key=lambda kv: zxy_to_tileid(*kv[0])):
            mvt_layers = [{"name": name, "features": items}
                          for name, items in layers.items() if items]
            if not mvt_layers:
                continue
            body = gzip.compress(mapbox_vector_tile.encode(
                mvt_layers, default_options={"y_coord_down": True, "extents": EXTENT}))
            wr.write_tile(zxy_to_tileid(z, tx, ty), body)
            count += 1
        s, w, n, e = bideak.BBOX
        wr.finalize(
            {"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
             "min_lon_e7": int(w * 1e7), "min_lat_e7": int(s * 1e7),
             "max_lon_e7": int(e * 1e7), "max_lat_e7": int(n * 1e7),
             "center_lon_e7": int((w + e) / 2 * 1e7), "center_lat_e7": int((s + n) / 2 * 1e7),
             "center_zoom": 12},
            {"name": "topo_osm",
             "description": "ehmap: water, roads, rail, places and summits for the topographic sheet",
             "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
             "licence": "ODbL 1.0",
             "vector_layers": [
                 {"id": i, "description": d, "fields": {}} for i, d in (
                     ("water", "lakes, reservoirs, wide rivers"),
                     ("waterways", "rivers, canals, streams"),
                     ("roads", "road network by class"), ("rail", "railways"),
                     ("places", "cities, towns, villages, hamlets"),
                     ("landmarks", "churches, caves, megaliths, castles, waterfalls, ..."),
                     ("summits", "named peaks and saddles"))]})
    tmp.replace(OUT)
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z9-{ZMAX}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
