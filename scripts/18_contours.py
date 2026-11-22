"""Vector contours of Euskal Herria for the topographic sheet's deep zooms, as PMTiles.

scripts/13_topo_tiles.py bakes the contours into the raster, which is right while
the equidistance follows the zoom (200 m at z10 ... 20 m at z13). From there on it
is 10 m for good, and a baked line only softens as the sheet is stretched. So the
10 m contours are drawn once more here as vectors — sharp at any zoom, and able to
carry their height along the line — and the raster's two deepest zooms leave them out.

Layer (Mapbox Vector Tile, gzip, extent 4096):
  contours  z12-14  one (multi)line per level and tile: ele (m), and idx = 1 on the
                    index curves (every 50 m)

The page shows them from map zoom 12.5, where MapLibre swaps the raster to its z14.

The lines are traced on the same 5 m LiDAR cache as the raster, smoothed like it
(or PNOA's whole metres would crinkle every line), one z12 tile at a time with a
halo, so two neighbouring blocks trace the very same surface and their lines meet.
Loops shorter than ~60 m are dropped. ~170 MB, so it lives on R2 with the sheet:

    uv run --quiet --with-requirements requirements.txt python scripts/18_contours.py
    scripts/upload_tiles.sh site/data/contours.pmtiles
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import math
import multiprocessing as mp
import os
import time
from pathlib import Path

import mapbox_vector_tile
import numpy as np
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "contours.pmtiles"
BLOCK_Z, ZMAX = 12, 14
EXTENT = 4096
INTERVAL, INDEX_EVERY = 10, 5
SMOOTH = 2.4                  # cells (12 m) of blur before tracing, as the raster's z14
MIN_LEN = 140                 # z14 tile units (~60 m): shorter lines are noise
SIMPLIFY = 1.6                # tile units at each zoom
HALF = 20037508.342789244


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


topo = _load("topo", "13_topo_tiles.py")
_W: dict = {}


def _init(path: str, shape, res: float, bounds) -> None:
    from pyproj import Transformer
    _W.update(dem=np.memmap(path, dtype="float32", mode="r", shape=shape), shape=shape, res=res,
              bounds=bounds,
              to_utm=Transformer.from_crs("EPSG:3857", topo.CRS, always_xy=True),
              to_merc=Transformer.from_crs(topo.CRS, "EPSG:3857", always_xy=True))


def block(xy: tuple[int, int]) -> list[tuple[int, bytes]]:
    """Every contour tile (z12-14) under one z12 tile."""
    import contourpy
    from scipy.ndimage import gaussian_filter
    bx, by = xy
    dem, shape, res, bounds = _W["dem"], _W["shape"], _W["res"], _W["bounds"]
    side = 2 * HALF / 2 ** BLOCK_Z
    pad = side / 16                              # mercator metres of overlap past the tile
    mx0, my1 = -HALF + bx * side - pad, HALF - by * side + pad
    mx1, my0 = mx0 + side + 2 * pad, my1 - side - 2 * pad
    xs, ys = _W["to_utm"].transform([mx0, mx1, mx0, mx1], [my0, my0, my1, my1])
    halo = int(4 * SMOOTH) + 2
    c0 = max(0, int((min(xs) - bounds[0]) / res) - halo)
    c1 = min(shape[1], int((max(xs) - bounds[0]) / res) + halo + 1)
    r0 = max(0, int((bounds[3] - max(ys)) / res) - halo)
    r1 = min(shape[0], int((bounds[3] - min(ys)) / res) + halo + 1)
    if c1 - c0 < 8 or r1 - r0 < 8:
        return []
    z = np.nan_to_num(np.array(dem[r0:r1, c0:c1]), nan=0.0)        # the sea is 0 m
    if z.max() < INTERVAL:
        return []
    z = gaussian_filter(z, SMOOTH)
    lo = max(INTERVAL, math.ceil(float(z.min()) / INTERVAL) * INTERVAL)
    gen = contourpy.contour_generator(z=z, line_type="Separate")
    unit = 2 ** ZMAX * EXTENT / (2 * HALF)       # z14 tile units per mercator metre
    eles, geoms = [], []
    for level in range(lo, int(z.max()) + 1, INTERVAL):
        parts = []
        for line in gen.lines(float(level)):
            if len(line) < 2:
                continue
            ux = bounds[0] + (c0 + line[:, 0] + 0.5) * res
            uy = bounds[3] - (r0 + line[:, 1] + 0.5) * res
            mx, my = _W["to_merc"].transform(ux, uy)
            pts = np.column_stack([(mx + HALF) * unit, (HALF - my) * unit])
            if np.hypot(*np.diff(pts, axis=0).T).sum() >= MIN_LEN:
                parts.append(pts)
        if parts:
            eles.append(level)
            geoms.append(shapely.multilinestrings([shapely.linestrings(p) for p in parts]))
    if not geoms:
        return []
    geoms = np.array(geoms, dtype=object)
    out = []
    for zoom in range(BLOCK_Z, ZMAX + 1):
        f = 2 ** (ZMAX - zoom)                   # z14 units per unit of this zoom
        simple = shapely.simplify(geoms, SIMPLIFY * f, preserve_topology=False)
        n = 2 ** (zoom - BLOCK_Z)
        for tx in range(bx * n, bx * n + n):
            for ty in range(by * n, by * n + n):
                m = 48 * f                       # a little past the edge, so line ends overlap
                clipped = shapely.clip_by_rect(simple, tx * EXTENT * f - m, ty * EXTENT * f - m,
                                               (tx + 1) * EXTENT * f + m, (ty + 1) * EXTENT * f + m)
                feats = []
                for ele, g in zip(eles, clipped):
                    if g.is_empty or g.geom_type not in ("LineString", "MultiLineString"):
                        continue
                    local = shapely.transform(g, lambda a: a / f - (tx * EXTENT, ty * EXTENT))
                    props = {"ele": ele}
                    if ele % (INTERVAL * INDEX_EVERY) == 0:
                        props["idx"] = 1
                    feats.append({"geometry": local, "properties": props})
                if feats:
                    body = gzip.compress(mapbox_vector_tile.encode(
                        [{"name": "contours", "features": feats}],
                        default_options={"y_coord_down": True, "extents": EXTENT}))
                    out.append((zxy_to_tileid(zoom, tx, ty), body))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--only", nargs=2, type=float, metavar=("LON", "LAT"),
                    help="build just the z12 block holding this point, into out/ (a test)")
    args = ap.parse_args()

    t0 = time.time()
    relief = _load("relief", "12_relief_tiles.py")
    bounds = relief.frame(relief.outline())
    dem, res, shape, scratch = topo.build_dem_cache(bounds, res=5.0)
    del dem
    print(f" · DEM cache {shape[1]}×{shape[0]} at {res} m ({time.time() - t0:.0f} s)", flush=True)
    from rasterio.transform import Affine
    min_lon, min_lat, max_lon, max_lat = relief.mercator_bounds(
        Affine(res, 0, bounds[0], 0, -res, bounds[3]), shape)
    n = 2 ** BLOCK_Z
    tx = lambda lon: int((lon + 180) / 360 * n)
    ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    todo = [(x, y) for x in range(tx(min_lon), tx(max_lon) + 1)
            for y in range(ty(max_lat), ty(min_lat) + 1)]
    out = OUT
    if args.only:
        todo = [(tx(args.only[0]), ty(args.only[1]))]
        out = ROOT / "out" / "contours_test.pmtiles"

    count = size = 0
    tmp = out.with_suffix(".pmtiles.part")
    with tmp.open("wb") as f, mp.Pool(args.jobs, _init, (str(scratch), shape, res, bounds)) as pool:
        wr = Writer(f)
        for i, tiles in enumerate(pool.imap_unordered(block, todo)):
            for tid, body in tiles:
                wr.write_tile(tid, body)
                count += 1
                size += len(body)
            if (i + 1) % 100 == 0:
                print(f" · {i + 1}/{len(todo)} blocks, {count} tiles, {size / 1e6:.0f} MB "
                      f"({time.time() - t0:.0f} s)", flush=True)
        wr.finalize(
            {"tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
             "min_lon_e7": int(min_lon * 1e7), "min_lat_e7": int(min_lat * 1e7),
             "max_lon_e7": int(max_lon * 1e7), "max_lat_e7": int(max_lat * 1e7),
             "center_lon_e7": int((min_lon + max_lon) / 2 * 1e7),
             "center_lat_e7": int((min_lat + max_lat) / 2 * 1e7), "center_zoom": 14},
            {"name": "contours", "description": "ehmap: 10 m contours of Euskal Herria",
             "attribution": "Relief: 5 m LiDAR — PNOA-LiDAR MDT05, © IGN España (CC BY 4.0) "
                            "and RGE ALTI®, © IGN France (Licence Ouverte 2.0)",
             "vector_layers": [{"id": "contours", "description": "10 m contours",
                                "fields": {"ele": "Number", "idx": "Number"}}]})
    tmp.replace(out)
    print(f" · {out.name}: {out.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z{BLOCK_Z}-{ZMAX}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
