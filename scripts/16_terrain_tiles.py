"""Elevation tiles of Euskal Herria, so the topographic sheet can be tilted into 3D.

site/data/topo.pmtiles is a drawing: tilted, it is a flat sheet with painted shade.
This archive carries the heights themselves — the same 5 m LiDAR mosaic, in the
Terrarium encoding (height = R·256 + G + B/256 − 32768 m) MapLibre reads as a
`raster-dem` source and uses to lift the ground under the sheet.

Heights are stored as whole metres, which leaves the blue channel empty and the
tiles a third of their size; at the archive's deepest zoom a pixel is ~28 m, so a
metre of height is far below what the terrain mesh can show. Tiles are lossless
WebP (a lossy codec would scramble the encoding). The sea and the gaps are 0 m.

Zooms 9-12 (256 px tiles: MapLibre asks for z+1 at map zoom z, and stretches z12
beyond map zoom 11 — the mesh is coarser than the drawing on purpose, the drawing
carries the detail).

    uv run --quiet --with-requirements requirements.txt python scripts/16_terrain_tiles.py
"""
from __future__ import annotations

import importlib.util
import io
import math
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "terrain.pmtiles"
ZMIN, ZMAX = 9, 12
RES = 20.0                    # working grid, metres: finer than a z12 pixel (~28 m)
TILE = 256

_spec = importlib.util.spec_from_file_location("topo", ROOT / "scripts" / "13_topo_tiles.py")
topo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(topo)


def encode(height: np.ndarray) -> bytes:
    """Whole metres -> a Terrarium tile, as lossless WebP."""
    v = np.clip(np.rint(np.nan_to_num(height, nan=0.0)), -1000, 9000).astype(np.int32) + 32768
    rgb = np.dstack([v >> 8, v & 255, np.zeros_like(v)]).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "WEBP", lossless=True, method=6)
    return buf.getvalue()


def main() -> None:
    t0 = time.time()
    with rasterio.open(topo.LIDAR_TIF) as src:
        b = src.bounds
    bounds = (b.left, b.bottom, b.right, b.top)
    dem = np.nan_to_num(topo.read_dem(bounds, RES), nan=0.0)        # sea -> 0 m
    st = Affine(RES, 0, b.left, 0, -RES, b.top)
    print(f" · DEM {dem.shape[1]}×{dem.shape[0]} at {RES:.0f} m ({time.time() - t0:.0f} s)", flush=True)

    fwd = Transformer.from_crs(topo.CRS, "EPSG:4326", always_xy=True)
    lons, lats = fwd.transform([b.left, b.right, b.left, b.right], [b.bottom, b.bottom, b.top, b.top])
    min_lon, max_lon, min_lat, max_lat = min(lons), max(lons), min(lats), max(lats)

    count = 0
    tmp = OUT.with_suffix(".pmtiles.part")
    with tmp.open("wb") as f:
        wr = Writer(f)
        for z in range(ZMIN, ZMAX + 1):
            n = 2 ** z
            ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
            tx = lambda lon: int((lon + 180) / 360 * n)
            # several grid cells per pixel at the low zooms: average, do not point-sample
            px = 2 * 20037508.342789244 / n / TILE * math.cos(math.radians(43))
            how = Resampling.average if px > 1.5 * RES else Resampling.bilinear
            for x in range(tx(min_lon), tx(max_lon) + 1):
                for y in range(ty(max_lat), ty(min_lat) + 1):
                    out = np.zeros((TILE, TILE), "float32")
                    reproject(dem, out, src_transform=st, src_crs=topo.CRS,
                              dst_transform=from_bounds(*topo.mercator_box(z, x, y, 0), TILE, TILE),
                              dst_crs="EPSG:3857", resampling=how)
                    wr.write_tile(zxy_to_tileid(z, x, y), encode(out))
                    count += 1
            print(f" · z{z}: cumulated {count} tiles ({time.time() - t0:.0f} s)", flush=True)
        wr.finalize(
            {"tile_type": TileType.WEBP, "tile_compression": Compression.NONE,
             "min_lon_e7": int(min_lon * 1e7), "min_lat_e7": int(min_lat * 1e7),
             "max_lon_e7": int(max_lon * 1e7), "max_lat_e7": int(max_lat * 1e7),
             "center_lon_e7": int((min_lon + max_lon) / 2 * 1e7),
             "center_lat_e7": int((min_lat + max_lat) / 2 * 1e7), "center_zoom": 10},
            {"name": "terrain", "encoding": "terrarium",
             "description": "ehmap: elevation of Euskal Herria, Terrarium-encoded whole metres",
             "attribution": "Relief: 5 m LiDAR — PNOA-LiDAR MDT05, © IGN España (CC BY 4.0) "
                            "and RGE ALTI®, © IGN France (Licence Ouverte 2.0)"})
    tmp.replace(OUT)
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z{ZMIN}-{ZMAX}, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
