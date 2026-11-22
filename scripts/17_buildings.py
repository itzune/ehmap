"""Buildings of Euskal Herria for the topographic sheet, from OpenStreetMap, as PMTiles.

An IGN sheet draws every building as a small dark shape; without them a town is a
knot of streets. There are well over a million in the frame, so they get their own
archive (site/data/buildings.pmtiles, ODbL) and a lean path: geometry only, no tags,
no shapely clipping — a building is written whole into every tile its bounding box
touches, and the renderer's own tile clip does the rest.

Layer (Mapbox Vector Tile, gzip, extent 4096):
  buildings  z13-14  polygons (outer rings of building=* ways). At z13 the ones
                     under about a screen pixel are left out.

The Overpass query is split into cells — the whole frame at once times out — and
each response is cached under data/raw/osm/buildings/ (gitignored).

    uv run --quiet --with-requirements requirements.txt python scripts/17_buildings.py
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import time
from pathlib import Path

import mapbox_vector_tile
import numpy as np
from mapbox_vector_tile.encoder import on_invalid_geometry_ignore
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "buildings.pmtiles"
ZOOMS = (13, 14)
EXTENT = 4096
CELL = (0.45, 0.6)            # degrees of latitude, longitude per Overpass query
MIN_AREA_Z13 = 60.0           # tile units² (~1 px² on screen) under which z13 skips a building

_spec = importlib.util.spec_from_file_location("bideak", ROOT / "scripts" / "14_bideak.py")
bideak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bideak)
bideak.RAW = ROOT / "data" / "raw" / "osm" / "buildings"
FRAME = bideak.BBOX            # south, west, north, east


def cells():
    s, w, n, e = FRAME
    lat = s
    while lat < n - 1e-9:
        lon = w
        while lon < e - 1e-9:
            yield (round(lat, 4), round(lon, 4),
                   round(min(n, lat + CELL[0]), 4), round(min(e, lon + CELL[1]), 4))
            lon += CELL[1]
        lat += CELL[0]


def main() -> None:
    t0 = time.time()
    tiles: dict[tuple[int, int, int], list[np.ndarray]] = {}
    seen: set[int] = set()
    missing = 0
    for i, cell in enumerate(cells()):
        bideak.BBOX = cell
        data = bideak.overpass(f"b_{cell[0]}_{cell[1]}", 'way["building"]', out="out skel geom;")
        if data is None:
            missing += 1
            continue
        kept = 0
        for el in data.get("elements", []):
            geom = el.get("geometry")
            if el["id"] in seen or not geom or len(geom) < 4:
                continue
            seen.add(el["id"])
            ll = np.array([(p["lon"], p["lat"]) for p in geom], "float64")
            mx = (ll[:, 0] + 180) / 360
            my = (1 - np.arcsinh(np.tan(np.radians(ll[:, 1]))) / np.pi) / 2
            for z in ZOOMS:
                n = 1 << z
                px = np.rint(np.column_stack([mx, my]) * n * EXTENT).astype(np.int64)
                px = px[np.r_[True, (np.diff(px, axis=0) != 0).any(1)]]     # drop repeated points
                if len(px) < 4:
                    continue
                x, y = px[:, 0], px[:, 1]
                if z == 13 and abs(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2 < MIN_AREA_Z13:
                    continue
                for tx in range(x.min() // EXTENT, x.max() // EXTENT + 1):
                    for ty in range(y.min() // EXTENT, y.max() // EXTENT + 1):
                        tiles.setdefault((z, tx, ty), []).append(
                            (px - (tx * EXTENT, ty * EXTENT)).astype(np.int32))
            kept += 1
        del data
        print(f" · cell {i + 1} {cell}: {kept} buildings ({time.time() - t0:.0f} s)", flush=True)
    if missing:
        raise SystemExit(f"{missing} cells are still missing (Overpass): run again, the rest is cached")

    count = 0
    tmp = OUT.with_suffix(".pmtiles.part")
    with tmp.open("wb") as f:
        wr = Writer(f)
        for (z, tx, ty) in sorted(tiles, key=lambda k: zxy_to_tileid(*k)):
            feats = [{"geometry": Polygon(a), "properties": {}} for a in tiles[(z, tx, ty)]]
            body = gzip.compress(mapbox_vector_tile.encode(
                [{"name": "buildings", "features": feats}],
                default_options={"y_coord_down": True, "extents": EXTENT,
                                 "on_invalid_geometry": on_invalid_geometry_ignore}))
            wr.write_tile(zxy_to_tileid(z, tx, ty), body)
            count += 1
        s, w, n, e = FRAME
        wr.finalize(
            {"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
             "min_lon_e7": int(w * 1e7), "min_lat_e7": int(s * 1e7),
             "max_lon_e7": int(e * 1e7), "max_lat_e7": int(n * 1e7),
             "center_lon_e7": int((w + e) / 2 * 1e7), "center_lat_e7": int((s + n) / 2 * 1e7),
             "center_zoom": 14},
            {"name": "buildings", "description": "ehmap: building footprints for the topographic sheet",
             "attribution": "© OpenStreetMap contributors (ODbL 1.0)", "licence": "ODbL 1.0",
             "vector_layers": [{"id": "buildings", "description": "building footprints", "fields": {}}]})
    tmp.replace(OUT)
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, {len(seen)} buildings, "
          f"z{ZOOMS[0]}-{ZOOMS[-1]}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
