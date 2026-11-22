"""Topographic ("rando") raster tiles of Euskal Herria, IGN-style, for a test page.

The reference is an IGN TOP 25 randonnée sheet: white paper for open ground, a
light green for woodland (ESA WorldCover tree cover), a soft grey NW hillshade that
only darkens the shaded slopes, orange contours every 10 m with every fifth drawn
heavier, and rock — a grey ground under fall-line hachures — where the ground is
too steep to read from contours alone (there, and wherever they would merge into a
wash, the intermediate curves fade and the index curves carry the slope).
This script bakes all of that into WebP tiles as site/data/topo.pmtiles, which
site/topo.html serves as a separate, experimental map until the style is ready.

Why raster and not vector contours: Euskal Herria carries ~403 000 km of
contour line at 10 m equidistance (measured with scripts/13_topo_tiles.py
--measure), which is far too much to ship as vector tiles. Baked into the
raster, the equidistance can follow the zoom — 200 m at z10, 100 m at z11,
50 m at z12, 20 m at z13, 10 m from z14 — and the lines keep a constant pixel
weight, like a printed sheet.

The z10-15 archive is ~1.4 GB, over GitHub's 100 MB per-file push limit, so it
is not committed: it lives in a Cloudflare R2 bucket served at tiles.itzune.eus,
which site/topo.html reads directly. After a rebuild:

    uv run --quiet --with-requirements requirements.txt python scripts/13_topo_tiles.py --tiles
    scripts/upload_tiles.sh

The build runs on all cores but two (--jobs) and takes about 45 minutes on eight;
--keep-cache leaves the DEM scratch in out/ so a restyle does not re-read the LiDAR.

The DEM is the same 5 m LiDAR mosaic as scripts/12_relief_tiles.py, cached for
the tiles at 5 m when z14 is built (10 m when the build stops at z13). Stages:
this file is the ground (woodland, relief, contours, rock); scripts/14_bideak.py adds
the trails and scripts/15_topo_osm.py the water, roads, rail and names, as vectors.

Iterate on the look with the preview mode, which renders one area to a PNG:

    uv run --quiet --with-requirements requirements.txt python scripts/13_topo_tiles.py \
        --preview 526000 4765000 540000 4779000 700 /tmp/topo_preview.png
"""
from __future__ import annotations

import argparse
import io
import json
import math
import multiprocessing as mp
import os
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.transform import from_bounds
from rasterio.warp import reproject

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "topo.pmtiles"
LIDAR_TIF = ROOT / "data" / "raw" / "lidar" / "eh_lidar_5m.tif"
WORLDCOVER = ROOT / "data" / "raw" / "worldcover"
CRS = "EPSG:25830"
TILE = 256
ZMIN, ZMAX = 10, 15

# --- the sheet's palette -------------------------------------------------
PAPER = "#FDFCF7"             # open ground is the paper itself, as on a TOP 25
FOREST = "#CDE5B2"            # woodland: the sheet's light green
CONTOUR = "#DD9154"           # intermediate contour: IGN's orange bistre, thin
INDEX = "#C46A22"             # every fifth contour, the "master curve"
ROCK = "#6A625A"              # hachures
ROCK_BASE = "#DAD6CE"         # bare rock under them: the paper greys out
ROCK_TINT = 0.45              # ... by this much where a pixel is all rock
SEA = "#DCE3E1"
SHADE_K = 0.27                # shadow depth: only the shaded slopes darken, flat ground
SHADE_FLAT = 0.707            # (this shade value) and lit slopes stay paper-white
FOREST_RES = 10.0             # ESA WorldCover's own resolution
FOREST_SMOOTH = 1.1           # px of blur on the tree mask: wood edges, not pixels
CONTOUR_SMOOTH = 1.8          # cells of blur before tracing: no crinkly lines
CONTOUR_MIN_GAP = 1.6         # px between intermediate curves under which they fade out
ROCK_SLOPE = 45               # degrees: above this the contours stop describing ground
PAD = 20                      # tile pixels of halo: must exceed the blur support (3σ = 7)

# --- equidistance per zoom (m) and the index rule ---------------------------------
# IGN equips 1:50 000 with 20 m contours and a 100 m index, 1:100 000 with 50 m.
# z13 is about 1:54 000 on a 96 dpi screen, z12 about 1:108 000, z11 about 1:216 000.
CONTOURS = {10: (200, 5), 11: (100, 5), 12: (50, 5), 13: (20, 5), 14: (10, 5), 15: (10, 5)}
# line half-widths in pixels: printed sheets draw contours at about 0.1 mm, which is
# 0.4 px on screen — thick enough to read, thin enough not to merge on steep ground
CONTOUR_PX, INDEX_PX = 0.48, 0.78


def to_rgb(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], "float32") / 255


def forest_cache() -> tuple[np.memmap, tuple[float, float], tuple[int, int]]:
    """Tree cover (ESA WorldCover class 10) over the LiDAR frame at 10 m, as a 0/1 memmap.

    Built once into out/topo_forest.u8 and reused while the WorldCover tiles do not change.
    """
    with rasterio.open(LIDAR_TIF) as src:
        b = src.bounds
    shape = (int((b.top - b.bottom) / FOREST_RES), int((b.right - b.left) / FOREST_RES))
    path = ROOT / "out" / "topo_forest.u8"
    meta = path.with_suffix(".json")
    tiles = sorted(WORLDCOVER.glob("*.tif"))
    if not tiles:
        raise SystemExit(f"no WorldCover tiles in {WORLDCOVER}: run scripts/00_download.py")
    key = json.dumps({"bounds": list(b), "tiles": [[t.name, t.stat().st_size] for t in tiles]})
    if (path.exists() and meta.exists() and meta.read_text() == key
            and path.stat().st_size == shape[0] * shape[1]):
        return np.memmap(path, dtype="uint8", mode="r", shape=shape), (b.left, b.top), shape
    path.parent.mkdir(parents=True, exist_ok=True)
    meta.unlink(missing_ok=True)
    mm = np.memmap(path, dtype="uint8", mode="w+", shape=shape)
    for r0 in range(0, shape[0], 2048):
        rows = min(2048, shape[0] - r0)
        tr = Affine(FOREST_RES, 0, b.left, 0, -FOREST_RES, b.top - r0 * FOREST_RES)
        acc = np.zeros((rows, shape[1]), "uint8")
        for t in tiles:
            with rasterio.open(t) as src:
                tmp = np.zeros_like(acc)
                reproject(rasterio.band(src, 1), tmp, dst_transform=tr, dst_crs=CRS,
                          resampling=Resampling.nearest)
                acc |= tmp == 10
        mm[r0:r0 + rows] = acc
    mm.flush()
    meta.write_text(key)
    return mm, (b.left, b.top), shape


def forest_at(cache, utm_box, dst_transform, dst_crs: str, shape: tuple[int, int]) -> np.ndarray:
    """Share of tree cover (0..1) on a destination grid, averaged from the 10 m mask."""
    mm, (fx0, fy1), fshape = cache
    c0 = max(0, int((utm_box[0] - fx0) / FOREST_RES) - 2)
    c1 = min(fshape[1], int((utm_box[2] - fx0) / FOREST_RES) + 3)
    r0 = max(0, int((fy1 - utm_box[3]) / FOREST_RES) - 2)
    r1 = min(fshape[0], int((fy1 - utm_box[1]) / FOREST_RES) + 3)
    out = np.zeros(shape, "float32")
    if c1 - c0 < 2 or r1 - r0 < 2:
        return out
    src = np.asarray(mm[r0:r1, c0:c1], "float32")
    st = Affine(FOREST_RES, 0, fx0 + c0 * FOREST_RES, 0, -FOREST_RES, fy1 - r0 * FOREST_RES)
    coarse = abs(dst_transform.a) * (0.73 if dst_crs != CRS else 1) > 1.5 * FOREST_RES
    reproject(src, out, src_transform=st, src_crs=CRS, dst_transform=dst_transform,
              dst_crs=dst_crs, resampling=Resampling.average if coarse else Resampling.bilinear)
    return out


def hillshade(dem: np.ndarray, res: float) -> np.ndarray:
    """The printed maps' NW-weighted multi-directional shade, 0..1."""
    d = np.nan_to_num(dem, nan=0.0)
    gy, gx = np.gradient(d, res)
    slope = np.arctan(2.2 * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    alt = math.radians(45)
    shade = np.zeros_like(d)
    for az, w in ((315, 0.5), (270, 0.2), (360, 0.2), (225, 0.1)):
        a = math.radians(az)
        shade += w * (np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(a - aspect))
    return np.clip(shade, 0, 1)


def read_dem(bounds, res: float) -> np.ndarray:
    """LiDAR bare earth on a grid of `res` metres over `bounds` (water -> NaN)."""
    x0, y0, x1, y1 = bounds
    shape = (max(2, int(round((y1 - y0) / res))), max(2, int(round((x1 - x0) / res))))
    dem = np.full(shape, np.nan, "float32")
    with rasterio.open(LIDAR_TIF) as src:
        win = rasterio.windows.from_bounds(x0, y0, x1, y1, src.transform)
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        ow = max(2, int(round(win.width * abs(src.res[0]) / res)))
        oh = max(2, int(round(win.height * abs(src.res[1]) / res)))
        a = src.read(1, window=win, out_shape=(oh, ow),
                     resampling=Resampling.average if res > 5 else Resampling.bilinear
                     ).astype("float32")
        a[a < -1000] = np.nan
        st = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
        reproject(a, dem, src_transform=st, src_crs=src.crs,
                  dst_transform=Affine(res, 0, x0, 0, -res, y1), dst_crs=CRS,
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
    dem[dem <= 0] = np.nan
    return dem


def contours(dem: np.ndarray, px_m: float, interval: float, every: int):
    """Antialiased contour coverage (0..1) for intermediate and index curves.

    The distance to the nearest level is converted to pixels through the local
    gradient, so a line stays ~1 px wide however steep the ground is.
    """
    z = np.nan_to_num(dem, nan=-9999.0)
    gy, gx = np.gradient(z, px_m)
    g = np.hypot(gx, gy)
    ok = np.isfinite(dem) & (g > 1e-4)

    def band(iv: float, width_px: float) -> np.ndarray:
        dz = np.abs(((z + iv / 2) % iv) - iv / 2)          # metres to the nearest level
        d_px = dz / np.maximum(g, 1e-6) / px_m             # ... as pixels across
        return np.clip(1.0 - d_px / width_px, 0, 1) * ok

    index_iv = interval * every
    spacing = interval / np.maximum(g, 1e-6) / px_m        # pixels between two curves
    return band(interval, CONTOUR_PX), band(index_iv, INDEX_PX), spacing


def sample(dem: np.ndarray, res: float, bounds, bb, size: int) -> np.ndarray:
    """Bilinear sample of the cached DEM on a regular grid over `bb`.

    Coordinates are absolute UTM, so two neighbouring tiles read the very same
    surface and cannot disagree along their shared edge.
    """
    from scipy.ndimage import map_coordinates
    x0, y0, x1, y1 = bb
    xs = x0 + (np.arange(size) + 0.5) * (x1 - x0) / size
    ys = y1 - (np.arange(size) + 0.5) * (y1 - y0) / size
    cols = (xs - bounds[0]) / res - 0.5
    rows = (bounds[3] - ys) / res - 0.5
    c, r = np.meshgrid(cols, rows)
    out = map_coordinates(dem, [r, c], order=1, mode="nearest").astype("float32")
    out[out <= 0] = np.nan
    return out


def rock_cover(fine: np.ndarray, fine_px: float, shape: tuple[int, int]) -> np.ndarray:
    """Share (0..1) of each output pixel that is rock: ground steeper than ROCK_SLOPE.

    Measured on the finer, unsmoothed grid — on the blurred contour surface a cliff
    shrinks to a one-pixel thread and its hachures read as a ladder, not as rock.
    """
    from scipy.ndimage import binary_erosion
    land = np.isfinite(fine)
    gy, gx = np.gradient(np.nan_to_num(fine, nan=0.0), fine_px)
    steep = np.degrees(np.arctan(np.hypot(gx, gy))) > ROCK_SLOPE
    steep &= binary_erosion(land, iterations=2)      # the shoreline step is not a cliff
    h, w = shape
    return np.array(Image.fromarray(steep.astype("float32"), mode="F").resize((w, h), Image.BOX))


def render(dem: np.ndarray, px_m: float, interval: float, every: int,
           shade_src: np.ndarray | None = None, shade_px: float | None = None,
           origin: tuple[int, int] = (0, 0), *, forest: np.ndarray | None = None,
           with_rock: bool = True) -> np.ndarray:
    """One sheet at output resolution: paper, woodland, shade, contours, rock; sea clear."""
    from scipy.ndimage import gaussian_filter
    h, w = dem.shape
    sea = ~np.isfinite(dem)
    base = np.empty((h, w, 3), "float32")
    base[:] = to_rgb(PAPER)
    if forest is not None:
        a = np.clip((gaussian_filter(forest, FOREST_SMOOTH) - 0.35) / 0.3, 0, 1)
        a = (a * a * (3 - 2 * a))[..., None]
        base = base * (1 - a) + to_rgb(FOREST) * a
    if shade_src is None:
        shade_src, shade_px = dem, px_m
        shade = hillshade(dem, px_m)
    else:                                  # finer-grid shade, box-filtered down
        sh = Image.fromarray(hillshade(shade_src, shade_px).astype("float32"), mode="F")
        shade = np.array(sh.resize((w, h), Image.BOX))
    # a grey shade over white paper: shadows only, so the open ground stays clean
    rgb = base * np.clip(1 + SHADE_K * (shade[..., None] - SHADE_FLAT) / SHADE_FLAT, 0, 1)

    rock = None
    if with_rock:
        rock = gaussian_filter(rock_cover(shade_src, shade_px, (h, w)), 0.7)
        if rock.max() < 0.05:
            rock = None
    if rock is not None:
        # bare rock: the tint greys out and takes a harder shade than the slopes around
        a = np.clip(rock * 1.3, 0, 1)[..., None] * ROCK_TINT
        stone = to_rgb(ROCK_BASE) * (0.78 + 0.22 * shade[..., None])
        rgb = rgb * (1 - a) + stone * a

    # the sea is 0 m: filling it with anything higher (e.g. the tile's median) would
    # pull the shore up through the blur and stack false contours along the coast
    dem_c = gaussian_filter(np.nan_to_num(dem, nan=0.0), CONTOUR_SMOOTH)
    thin, thick, spacing = contours(dem_c, px_m, interval, every)
    shore = dem_c < interval / 2                # no "0 m contour" tracing the coastline
    thin[shore] = 0
    thick[shore] = 0
    # where the intermediate curves would merge into a brown wash they bow out, as on
    # a printed sheet, and the index curves carry the slope on their own
    thin *= np.clip((spacing - CONTOUR_MIN_GAP) / CONTOUR_MIN_GAP, 0, 1)
    if rock is not None:                        # ... and rock is drawn, not contoured
        thin *= 1 - np.clip(rock * 1.5, 0, 1)
        thick *= 1 - 0.5 * np.clip(rock * 1.5, 0, 1)
    for mask, colour, op in ((thin, CONTOUR, 0.9), (thick, INDEX, 1.0)):
        a = (mask * op)[..., None]
        rgb = rgb * (1 - a) + to_rgb(colour) * a

    out = np.dstack([np.clip(rgb, 0, 1) * 255, np.where(sea, 0, 255)]).astype("uint8")
    if rock is not None:
        out = hachures(out, dem_c, rock, px_m, origin)
    return out


def hachures(rgba: np.ndarray, dem: np.ndarray, rock: np.ndarray, px_m: float,
             origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Short strokes down the fall line where contours alone cannot describe rock.

    Drawn as real line segments (not a pixel pattern), which is what makes IGN's
    cliff drawing read as rock rather than as texture noise.
    """
    from PIL import ImageDraw
    h, w = dem.shape
    ox, oy = origin
    # the stroke grid is anchored to absolute tile pixels and jittered by a hash of
    # them, so neighbouring tiles draw the very same strokes across their shared edge
    # and no row of ticks lines up into a ladder
    ay = np.arange(oy + 3 - oy % 3, oy + h - 3, 3, dtype=np.int64)
    ax = np.arange(ox + 3 - ox % 3, ox + w - 3, 3, dtype=np.int64)
    AX, AY = np.meshgrid(ax, ay)
    hsh = (AX * 73856093) ^ (AY * 19349663)
    xs = AX - ox + (hsh & 3) - 1
    ys = AY - oy + ((hsh >> 2) & 3) - 1
    keep = (rock[ys, xs] > 0.45 + 0.4 * ((hsh >> 4) & 7) / 7) & (rgba[ys, xs, 3] > 0)
    if not keep.any():
        return rgba
    gy, gx = np.gradient(dem, px_m)
    xs, ys, hk = xs[keep], ys[keep], hsh[keep]
    dx, dy = -gx[ys, xs], -gy[ys, xs]           # fall line: downhill, against the gradient
    n = np.hypot(dx, dy)
    ok = n > 1e-6
    length = 1.3 + 1.5 * rock[ys, xs] + 0.7 * ((hk >> 7) & 3) / 3
    ux = np.where(ok, dx / np.maximum(n, 1e-6), 0) * length
    uy = np.where(ok, dy / np.maximum(n, 1e-6), 0) * length
    # strokes go on their own layer and are composited: drawing a translucent colour
    # straight into an RGBA image replaces the pixel, alpha included, which would
    # leave the sheet 80 % opaque under every stroke
    S = 3                                       # supersampled, for antialiased strokes
    ink = Image.new("L", (w * S, h * S), 0)
    d = ImageDraw.Draw(ink)
    for x, y, vx, vy, good in zip(xs.tolist(), ys.tolist(), ux.tolist(), uy.tolist(), ok.tolist()):
        if good:
            d.line([((x - vx + .5) * S, (y - vy + .5) * S), ((x + vx + .5) * S, (y + vy + .5) * S)],
                   fill=255, width=2)
    a = (np.asarray(ink.resize((w, h), Image.BOX), "float32") / 255 * 0.62)[..., None]
    out = rgba.copy()
    out[..., :3] = (rgba[..., :3] * (1 - a) + to_rgb(ROCK) * 255 * a).astype("uint8")
    return out                                  # alpha untouched: nothing spills on the sea


def sheet(bounds, size: int, z: int) -> np.ndarray:
    """Render one square sheet for a zoom — the preview and the tiles share this path."""
    x0, y0, x1, y1 = bounds
    px_m = (x1 - x0) / size
    interval, every = CONTOURS[min(z, max(CONTOURS))]
    dem = read_dem(bounds, px_m)                    # output-resolution sampling
    fine = read_dem(bounds, px_m / 2)               # finer grid for the hillshade
    forest = forest_at(forest_cache(), bounds, Affine(px_m, 0, x0, 0, -px_m, y1), CRS, dem.shape)
    return render(dem, px_m, interval, every, shade_src=fine, shade_px=px_m / 2, forest=forest)


def measure() -> None:
    """How much contour line the country holds at each equidistance."""
    import geopandas as gpd
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    eh = gpd.read_file(ROOT / "dist" / "euskal_herria.gpkg", layer="euskal_herria").to_crs(CRS)
    x0, y0, x1, y1 = eh.total_bounds
    res = 100.0
    tr = from_origin(x0, y1, res, res)
    shape = (int((y1 - y0) / res), int((x1 - x0) / res))
    dem = read_dem((x0, y0, x1, y1), res)
    land = rasterize([(g, 1) for g in eh.geometry], out_shape=shape, transform=tr).astype(bool)
    land &= np.isfinite(dem)
    gy, gx = np.gradient(np.nan_to_num(dem, nan=0), res)
    g = np.hypot(gx, gy)
    area = land.sum() * (res / 1000) ** 2
    print(f"EH land {area:,.0f} km², median |slope| {np.median(g[land]):.3f}")
    for iv in (10, 20, 25, 50, 100):
        print(f"  {iv:3d} m equidistance: ~{(g[land] * res * res).sum() / iv / 1000:,.0f} km of line")


def build_dem_cache(bounds, res: float = 10.0) -> tuple[np.memmap, float, tuple[int, int], Path]:
    """The whole frame's DEM at `res`, once, in a scratch memmap (not RAM)."""
    x0, y0, x1, y1 = bounds
    shape = (int(round((y1 - y0) / res)), int(round((x1 - x0) / res)))
    path = ROOT / "out" / "topo_dem.f32"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = path.with_suffix(".json")
    key = json.dumps({"bounds": [round(v, 3) for v in bounds], "res": res,
                      "lidar_mtime": LIDAR_TIF.stat().st_mtime})
    if (path.exists() and meta.exists() and meta.read_text() == key
            and path.stat().st_size == shape[0] * shape[1] * 4):
        return np.memmap(path, dtype="float32", mode="r", shape=shape), res, shape, path
    meta.unlink(missing_ok=True)                 # a half-written cache is never reused
    mm = np.memmap(path, dtype="float32", mode="w+", shape=shape)
    band = 512
    for r0 in range(0, shape[0], band):
        r1 = min(shape[0], r0 + band)
        mm[r0:r1] = read_dem((x0, y1 - r1 * res, x1, y1 - r0 * res), res)
    mm.flush()
    meta.write_text(key)
    return mm, res, shape, path


def tile_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """A web-mercator tile's footprint, expressed in EPSG:25830."""
    from pyproj import Transformer
    w, s, e, n = mercator_to_lonlat_bounds(z, x, y)
    inv = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    xs, ys = inv.transform([w, e, w, e], [s, s, n, n])
    return min(xs), min(ys), max(xs), max(ys)


def mercator_box(z: int, x: int, y: int, pad_m: float) -> tuple[float, float, float, float]:
    """EPSG:3857 extent of a tile, grown by `pad_m` on every side."""
    n = 2 ** z
    world = 2 * 20037508.342789244
    side = world / n
    left = -20037508.342789244 + x * side
    top = 20037508.342789244 - y * side
    return left - pad_m, top - side - pad_m, left + side + pad_m, top + pad_m


def mercator_to_lonlat_bounds(z: int, x: int, y: int):
    n = 2 ** z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
    return lon0, lat(y + 1), lon1, lat(y)


_W: dict = {}                 # per-process state of the tile workers


def _init_worker(path: str, shape: tuple[int, int], res: float, bounds) -> None:
    from pyproj import Transformer
    _W.update(dem=np.memmap(path, dtype="float32", mode="r", shape=shape), shape=shape,
              res=res, bounds=bounds,
              inv=Transformer.from_crs("EPSG:3857", CRS, always_xy=True),
              forest=forest_cache())


def render_tile(zxy: tuple[int, int, int]) -> tuple[int, bytes | None]:
    """One WebP tile from the cached DEM; None where the tile holds no land."""
    z, x, y = zxy
    dem, shape, res, bounds = _W["dem"], _W["shape"], _W["res"], _W["bounds"]
    n = 2 ** z
    interval, every = CONTOURS[min(z, max(CONTOURS))]
    bb = tile_bbox(z, x, y)
    px_m = (bb[2] - bb[0]) / TILE
    # a mercator tile is a rotated quad in UTM (meridian convergence), so window the
    # cache on the *transformed* padded box: mixing a mercator halo with a UTM window
    # starves the tile edges of source. The halo lives on the mercator grid, so it is
    # PAD *mercator* pixels: anything else makes the padded box's pixels a different
    # size from the tile's, and the cropped centre no longer lines up with the tile
    pad = PAD * (2 * 20037508.342789244 / n) / TILE
    mbox = mercator_box(z, x, y, pad)
    xs_, ys_ = _W["inv"].transform([mbox[0], mbox[2], mbox[0], mbox[2]],
                                   [mbox[1], mbox[1], mbox[3], mbox[3]])
    c0 = max(0, int((min(xs_) - bounds[0]) / res) - 1)
    r0 = max(0, int((bounds[3] - max(ys_)) / res) - 1)
    c1 = min(shape[1], int((max(xs_) - bounds[0]) / res) + 2)
    r1 = min(shape[0], int((bounds[3] - min(ys_)) / res) + 2)
    tid = zxy_to_tileid(z, x, y)
    if c1 - c0 < 3 or r1 - r0 < 3:
        return tid, None
    if not (np.asarray(dem[r0:r1:4, c0:c1:4]) > 0).any() and not (dem[r0:r1, c0:c1] > 0).any():
        return tid, None
    box = TILE + 2 * PAD

    def warp(size: int) -> np.ndarray:
        # several cache cells per output pixel: average them first, or the low zooms
        # would point-sample the 5 m ground and alias. The blocks are anchored to the
        # cache's own grid, so two neighbouring tiles average the very same cells
        # (GDAL's own "average" warp does not, and leaves a step at every tile edge)
        f = max(1, int(px_m * box / size / res))
        a0, b0 = r0 - r0 % f, c0 - c0 % f
        a1 = min(shape[0], r1 + (-r1) % f) // f * f
        b1 = min(shape[1], c1 + (-c1) % f) // f * f
        src = np.array(dem[a0:a1, b0:b1])
        land = src > 0
        if f > 1:
            blocks = (src.shape[0] // f, f, src.shape[1] // f, f)
            cnt = land.reshape(blocks).sum((1, 3))
            tot = np.where(land, src, 0).reshape(blocks).sum((1, 3), dtype="float64")
            src = np.where(cnt * 2 >= f * f, tot / np.maximum(cnt, 1), np.nan).astype("float32")
        else:
            src[~land] = np.nan
        st = Affine(res * f, 0, bounds[0] + b0 * res, 0, -res * f, bounds[3] - a0 * res)
        out = np.full((size, size), np.nan, "float32")
        reproject(src, out, src_transform=st, src_crs=CRS,
                  dst_transform=from_bounds(*mbox, size, size), dst_crs="EPSG:3857",
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
        return out

    forest = forest_at(_W["forest"], (min(xs_), min(ys_), max(xs_), max(ys_)),
                       from_bounds(*mbox, box, box), "EPSG:3857", (box, box))
    big = render(warp(box), px_m, interval, every, shade_src=warp(2 * box),
                 shade_px=px_m / 2, origin=(x * TILE - PAD, y * TILE - PAD), forest=forest)
    img = big[PAD:PAD + TILE, PAD:PAD + TILE]
    if not img[..., 3].any():
        return tid, None
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=88, method=6)
    return tid, buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs=5, metavar=("X0", "Y0", "X1", "Y1", "SIZE"))
    ap.add_argument("--zoom", type=int, default=13, help="zoom to imitate in preview")
    ap.add_argument("--output", default="preview.png")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--tiles", action="store_true")
    ap.add_argument("--zooms", default=f"{ZMIN}-{ZMAX}")
    ap.add_argument("--keep-cache", action="store_true",
                    help="leave out/topo_dem.f32 in place, to rebuild without re-reading the LiDAR")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()

    if args.measure:
        measure()
        return
    if args.preview:
        x0, y0, x1, y1 = (float(v) for v in args.preview[:4])
        size, out = int(args.preview[4]), args.output
        t0 = time.time()
        img = sheet((x0, y0, x1, y1), size, args.zoom)
        Image.fromarray(img, "RGBA").save(out)
        print(f"{out}: {size}px over {int(x1-x0)}×{int(y1-y0)} m at z{args.zoom} "
              f"in {time.time()-t0:.1f} s")
        return
    if not args.tiles:
        print("nothing to do: pass --preview or --tiles")
        return

    import importlib.util
    spec = importlib.util.spec_from_file_location("relief", ROOT / "scripts" / "12_relief_tiles.py")
    relief = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relief)

    zmin, zmax = (int(v) for v in args.zooms.split("-"))
    t0 = time.time()
    eh = relief.outline()
    bounds = relief.frame(eh)
    # a z14 pixel is ~7 m here, so z14 needs the LiDAR's own 5 m (an 8 GB scratch
    # memmap); up to z13 (~14 m) a 10 m cache is finer than any pixel
    dem, res, shape, scratch = build_dem_cache(bounds, res=5.0 if zmax >= 14 else 10.0)
    forest_cache()                               # built here, once, before the workers open it
    print(f" · DEM cache {shape[1]}×{shape[0]} at {res} m ({time.time()-t0:.0f} s)", flush=True)
    min_lon, min_lat, max_lon, max_lat = relief.mercator_bounds(
        Affine(res, 0, bounds[0], 0, -res, bounds[3]), shape)

    buf = io.BytesIO()
    Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0)).save(buf, "WEBP", lossless=True)
    EMPTY = buf.getvalue()

    count = 0
    tmp = OUT.with_suffix(".pmtiles.part")       # the old archive survives a failed build
    with tmp.open("wb") as f, mp.Pool(args.jobs, _init_worker,
                                      (str(scratch), shape, res, bounds)) as pool:
        wr = Writer(f)
        for z in range(zmin, zmax + 1):
            n = 2 ** z
            def tx(lon):
                return max(0, min(n - 1, int((lon + 180) / 360 * n)))
            def ty(lat):
                la = max(-85.05112878, min(85.05112878, lat))
                return max(0, min(n - 1, int((1 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2 * n)))
            x0, x1 = tx(min_lon), tx(math.nextafter(max_lon, min_lon))
            y0, y1 = ty(max_lat), ty(math.nextafter(min_lat, max_lat))
            todo = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
            for tid, data in pool.imap(render_tile, todo, chunksize=8):
                # sea (or beyond the frame): MapLibre keeps tiles the archive lacks
                # "pending" forever, so write the shared transparent one
                wr.write_tile(tid, data or EMPTY)
                count += 1
            print(f" · z{z}: cumulated {count} tiles ({time.time()-t0:.0f} s)", flush=True)
        wr.finalize(
            {"tile_type": TileType.WEBP, "tile_compression": Compression.NONE,
             "min_lon_e7": int(min_lon * 1e7), "min_lat_e7": int(min_lat * 1e7),
             "max_lon_e7": int(max_lon * 1e7), "max_lat_e7": int(max_lat * 1e7),
             "center_lon_e7": int((min_lon + max_lon) / 2 * 1e7),
             "center_lat_e7": int((min_lat + max_lat) / 2 * 1e7), "center_zoom": 11},
            {"name": "topo",
             "description": "ehmap: topographic sheet of Euskal Herria (test)",
             "attribution": "Relief: 5 m LiDAR — PNOA-LiDAR MDT05, © IGN España (CC BY 4.0) "
                            "and RGE ALTI®, © IGN France (Licence Ouverte 2.0)"})
    tmp.replace(OUT)
    del dem
    if not args.keep_cache:
        scratch.unlink(missing_ok=True)
        scratch.with_suffix(".json").unlink(missing_ok=True)
    print(f" · {OUT.name}: {OUT.stat().st_size/1e6:.1f} MB, {count} tiles, "
          f"z{zmin}-{zmax}, {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
