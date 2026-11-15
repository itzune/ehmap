"""Vector tiles of Euskal Herria for web maps, as a single PMTiles file.

PMTiles (https://protomaps.com) packs a whole tileset into one file that any static
host can serve over HTTP range requests — GitHub Pages included. This script turns
the CC BY 4.0 boundary layers already published in dist/geojson/ into
site/data/euskal_herria.pmtiles, served from https://itzune.eus/ehmap/data/ and used
by site/mapa.html. No server, no API keys: the map viewer (MapLibre GL) reads the
file straight from GitHub Pages.

Layers (Mapbox Vector Tile, gzip, extent 4096):
  euskal_herria       z4-13  the union, for the land/sea fill
  territories         z4-8   the 7 territories
  municipalities      z7-13  706 municipal units: code, names, population, density
  eh-outline          z4-13  Euskal Herria's outer boundary, as lines
  territory-borders   z4-8   boundaries between the 7 territories, as lines
  municipality-borders z7-13 municipal boundaries, as lines

The *-borders layers exist because polygons clipped to a tile carry straight clip
edges: drawn through a line layer they would show as a spurious charcoal grid along
every tile boundary. Lines clipped as lines just end at the edge and continue in the
neighbouring tile, so borders are cut once per feature into line layers instead.
Labeled layers also carry one point per feature (its representative point, in the
single tile containing it) so the viewer can label without duplicating.

Geometries come from the simplified GeoJSON (~50 m, shared borders kept) and are
simplified further per zoom to ~2 px of a 4096-px tile, then clipped to each tile.
Everything is derived from CC BY 4.0 sources, so the tiles are CC BY 4.0 too; the
ODbL OpenStreetMap layers (peaks, rivers) are deliberately left out — anyone
wanting a full OSM basemap of Euskal Herria can extract one from the Protomaps
daily builds (ODbL), about 265 MB at z0-15 or 81 MB capped at z13:

  pmtiles extract https://build.protomaps.com/<date>.pmtiles ehmap_osm.pmtiles \\
      --bbox=-3.4503,41.9099,-0.6526,43.5473 [--maxzoom=13]

Preview locally: drag the file onto https://maps.protomaps.com, or serve the data
directory (`pmtiles serve site/data --port 7999 --cors='*'`) and read tiles from
http://localhost:7999/euskal_herria/{z}/{x}/{y}. A range-capable plain static
server works too: the viewer fetches only the tiles it needs.
"""
import gzip
import json
import math
import time
from pathlib import Path

import mapbox_vector_tile
import numpy as np
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import box, shape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "euskal_herria.pmtiles"

EXTENT = 4096        # MVT tile extent in pixels
SIMPLIFY_PX = 2      # per-zoom simplification target, in tile pixels
CENTER_ZOOM = 8

# Layers that carry a label point: a polygon clipped into N tiles would
# otherwise get N labels (one per clipped centroid). One point per feature,
# in the single tile that contains it, keeps labels singular.
LABELED = frozenset(("territories", "municipalities"))

LAYERS = {  # name: (file under dist/geojson/simplified/, minzoom, maxzoom, properties)
    "euskal_herria": ("euskal_herria.geojson", 4, 13, ("population", "area_km2")),
    "territories": ("territories.geojson", 4, 8,
                    ("id", "name_eu", "name_es", "name_fr", "name_en",
                     "population", "area_km2", "density_km2")),
    "municipalities": ("municipalities.geojson", 7, 13,
                       ("code", "country", "type", "name", "name_eu", "territory",
                        "population", "density_km2")),
}

# Boundary-line layers, derived from the polygon layers above. Lines are
# clipped as lines, so a tile edge simply truncates them (no artifacts);
# polygons clipped to tiles carry straight clip edges, which would render
# as a spurious charcoal "grid" if drawn through line layers.
BORDERS = {                                 # line layer -> (source, zmin, zmax)
    "eh-outline": ("euskal_herria", 4, 13),
    "territory-borders": ("territories", 4, 8),
    "municipality-borders": ("municipalities", 7, 13),
}
NUMERIC = frozenset(("population", "area_km2", "density_km2"))


def norm_y(lat: float) -> float:
    """Web-mercator normalized northing: 0 at the north pole, 1 at the south."""
    lat = max(-85.05112878, min(85.05112878, lat))
    return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2


def tile_lat(y: int, z: int, top: bool = True) -> float:
    """Latitude of a tile's northern (top) or southern edge."""
    t = y / (1 << z) if top else (y + 1) / (1 << z)
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t))))


def merc_px(arr, n: int, tx: int, ty: int):
    """lon/lat array -> tile pixel array, y down."""
    lon, lat = arr[:, 0], arr[:, 1]
    my = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2
    return np.column_stack([((lon + 180) / 360 * n - tx) * EXTENT,
                            ((my * n - ty) * EXTENT)])


def load(name: str) -> list[tuple[object, dict]]:
    file, _, _, props = LAYERS[name]
    gj = json.loads((ROOT / "dist" / "geojson" / "simplified" / file).read_text())
    out = []
    for f in gj["features"]:
        p = f["properties"]
        out.append((shape(f["geometry"]), {k: p[k] for k in props if p.get(k) is not None}))
    return out


def main() -> None:
    t0 = time.time()
    feats = {name: load(name) for name in LAYERS}
    print(" · " + ", ".join(f"{n}: {len(v)} features" for n, v in feats.items()))

    # Euskal Herria's bounds, for the archive header
    bounds = [f.bounds for fs in feats.values() for f, _ in fs]
    minx, miny = min(b[0] for b in bounds), min(b[1] for b in bounds)
    maxx, maxy = max(b[2] for b in bounds), max(b[3] for b in bounds)

    tiles: dict[tuple[int, int, int], dict[str, list]] = {}
    for z in range(4, 14):
        n = 1 << z
        tol = 360 / n / EXTENT * SIMPLIFY_PX          # ~2 px, in degrees
        for name, (_, zmin, zmax, _) in LAYERS.items():
            if not zmin <= z <= zmax:
                continue
            for geom, props in feats[name]:
                simple = geom.simplify(tol, preserve_topology=True)
                if simple.is_empty:
                    simple = geom
                b = simple.bounds
                tx0, tx1 = int((b[0] + 180) / 360 * n), min(int((b[2] + 180) / 360 * n), n - 1)
                ty0, ty1 = int(norm_y(b[3]) * n), min(int(norm_y(b[1]) * n), n - 1)

                if name in LABELED:
                    lp = simple.representative_point()
                    lpx, lpy = int((lp.x + 180) / 360 * n), min(int(norm_y(lp.y) * n), n - 1)
                    tiles.setdefault((z, lpx, lpy), {}).setdefault(name, []).append(
                        {"geometry": shapely.transform(lp, lambda arr: merc_px(arr, n, lpx, lpy)),
                         "properties": props})

                for ty in range(ty0, ty1 + 1):
                    north, south = tile_lat(ty, z), tile_lat(ty, z, top=False)
                    for tx in range(tx0, tx1 + 1):
                        west, east = tx / n * 360 - 180, (tx + 1) / n * 360 - 180
                        clipped = simple.intersection(box(west, south, east, north))
                        if clipped.is_empty:
                            continue

                        tile = tiles.setdefault((z, tx, ty), {})
                        tile.setdefault(name, []).append(
                            {"geometry": shapely.transform(clipped, lambda arr: merc_px(arr, n, tx, ty)),
                             "properties": props})

            # boundary lines for this zoom
            for lname, (src, zmin, zmax) in BORDERS.items():
                if not zmin <= z <= zmax:
                    continue
                for geom, _ in feats[src]:
                    border = geom.simplify(tol, preserve_topology=True).boundary
                    if border.is_empty:
                        continue
                    b = border.bounds
                    tx0, tx1 = int((b[0] + 180) / 360 * n), min(int((b[2] + 180) / 360 * n), n - 1)
                    ty0, ty1 = int(norm_y(b[3]) * n), min(int(norm_y(b[1]) * n), n - 1)
                    for ty in range(ty0, ty1 + 1):
                        north, south = tile_lat(ty, z), tile_lat(ty, z, top=False)
                        for tx in range(tx0, tx1 + 1):
                            west, east = tx / n * 360 - 180, (tx + 1) / n * 360 - 180
                            seg = border.intersection(box(west, south, east, north))
                            if seg.is_empty or seg.geom_type not in ("LineString", "MultiLineString"):
                                continue
                            tile = tiles.setdefault((z, tx, ty), {})
                            tile.setdefault(lname, []).append(
                                {"geometry": shapely.transform(seg, lambda arr: merc_px(arr, n, tx, ty)),
                                 "properties": {}})
        print(f" · z{z}: {sum(1 for t in tiles if t[0] == z)} tiles")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("wb") as f:
        w = Writer(f)
        for (z, x, y), layers in sorted(tiles.items(), key=lambda kv: zxy_to_tileid(*kv[0])):
            mvt = mapbox_vector_tile.encode(
                [{"name": name, "features": fs} for name, fs in layers.items()],
                default_options={"y_coord_down": True, "extents": EXTENT})
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(mvt, mtime=0))
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_lon_e7": int(minx * 1e7), "min_lat_e7": int(miny * 1e7),
                "max_lon_e7": int(maxx * 1e7), "max_lat_e7": int(maxy * 1e7),
                "center_lon_e7": int((minx + maxx) / 2 * 1e7),
                "center_lat_e7": int((miny + maxy) / 2 * 1e7),
                "center_zoom": CENTER_ZOOM,
            },
            {
                "name": "euskal_herria",
                "description": "ehmap: Euskal Herria, its territories and municipalities",
                "attribution": "ehmap contributors (https://github.com/itzune/ehmap)",
                "licence": "CC BY 4.0",
                "vector_layers": [
                    {"id": n, "description": d,
                     "fields": {p: ("Number" if p in NUMERIC else "String") for p in LAYERS[n][3]}}
                    for n, d in (("euskal_herria", "the union of Euskal Herria"),
                                 ("territories", "the 7 territories"),
                                 ("municipalities", "706 municipal units"))
                ] + [
                    {"id": n, "description": d, "fields": {}}
                    for n, d in (("eh-outline", "Euskal Herria's outer boundary, as lines"),
                                 ("territory-borders", "boundaries between the 7 territories, as lines"),
                                 ("municipality-borders", "municipal boundaries, as lines"))
                ],
            },
        )

    zooms = sorted({t[0] for t in tiles})
    print(f" · {OUT.relative_to(ROOT)}: {OUT.stat().st_size / 1e6:.1f} MB, {len(tiles)} tiles, "
          f"z{zooms[0]}-{zooms[-1]}, {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
