"""Topographic ("rando") raster tiles of Euskal Herria, IGN-style, for a test page.

The reference is an IGN TOP 25 randonnée sheet: hypsometric tints, a soft NW
hillshade under them, brown contours every 10 m with every fifth drawn heavier,
and rock hachures where the ground is too steep to read from contours alone.
This script bakes all of that into WebP tiles as site/data/topo.pmtiles, which
site/topo.html serves as a separate, experimental map until the style is ready.

Why raster and not vector contours: Euskal Herria carries ~403 000 km of
contour line at 10 m equidistance (measured with scripts/13_topo_tiles.py
--measure), which is far too much to ship as vector tiles. Baked into the
raster, the equidistance can follow the zoom — 100 m at z11, 50 m at z12,
25 m at z13 — and the lines keep a constant pixel weight, like a printed sheet.

The DEM is the same 5 m LiDAR mosaic as scripts/12_relief_tiles.py. Stages:
this file is stage 1 (relief + contours + rock); vegetation, hydrography, trails
and labels come next, from ESA WorldCover and OpenStreetMap.

Iterate on the look with the preview mode, which renders one area to a PNG:

    uv run --quiet --with-requirements requirements.txt python scripts/13_topo_tiles.py \
        --preview 526000 4765000 540000 4779000 700 /tmp/topo_preview.png
"""
from __future__ import annotations

import argparse
import io
import math
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
CRS = "EPSG:25830"
TILE = 256
ZMIN, ZMAX = 10, 13

# --- the sheet's palette -------------------------------------------------
TINT = [                      # hypsometric tints, metres -> colour (IGN-like)
    (0, "#F4F4E3"), (150, "#EAEED0"), (300, "#E6E6BD"), (500, "#E3DCAA"),
    (700, "#E2D096"), (900, "#E0C282"), (1100, "#DEB36E"), (1300, "#DCA158"),
    (1500, "#D68D46"), (1800, "#C5783B"), (2100, "#A86334"), (2400, "#8C502E"),
]
CONTOUR = "#CFA98C"           # intermediate contour: light, so steep ground stays legible
INDEX = "#6E3D24"             # every fifth contour, the "master curve"
ROCK = "#6B6157"              # hachures
SEA = "#DCE3E1"
SHADE_K = 0.22                # IGN's hillshade is softer than Erliebea's
CONTOUR_SMOOTH = 2.4          # cells of blur before tracing: no crinkly lines
ROCK_SLOPE = 50               # degrees: above this the contours stop describing ground
PAD = 20                      # tile pixels of halo: must exceed the blur support (3σ = 7)

# --- equidistance per zoom (m) and the index rule ---------------------------------
# IGN equips 1:50 000 with 20 m contours and a 100 m index, 1:100 000 with 50 m.
# z13 is about 1:54 000 on a 96 dpi screen, z12 about 1:108 000, z11 about 1:216 000.
CONTOURS = {10: (200, 5), 11: (100, 5), 12: (50, 5), 13: (20, 5), 14: (10, 5)}
# line half-widths in pixels: printed sheets draw contours at about 0.1 mm, which is
# 0.4 px on screen — thick enough to read, thin enough not to merge on steep ground
CONTOUR_PX, INDEX_PX = 0.30, 0.75


def to_rgb(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], "float32") / 255


def tint_of(dem: np.ndarray) -> np.ndarray:
    """Hypsometric colour for an elevation array, as float RGB in 0..1."""
    zs = [z for z, _ in TINT]
    cols = np.array([to_rgb(c) for _, c in TINT])
    flat = np.clip(np.nan_to_num(dem, nan=0.0), zs[0], zs[-1])
    return np.dstack([np.interp(flat, zs, cols[:, i]) for i in range(3)])


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
    return band(interval, CONTOUR_PX), band(index_iv, INDEX_PX)


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


def render(dem: np.ndarray, px_m: float, interval: float, every: int,
           shade_src: np.ndarray | None = None, shade_px: float | None = None,
           origin: tuple[int, int] = (0, 0), *, with_rock: bool = True) -> np.ndarray:
    """One sheet at output resolution: tints x shade, contours, hachures, sea clear."""
    from scipy.ndimage import gaussian_filter
    h, w = dem.shape
    sea = ~np.isfinite(dem)
    tint = tint_of(dem)
    if shade_src is None:
        shade = hillshade(dem, px_m)
    else:                                  # finer-grid shade, box-filtered down
        sh = Image.fromarray(hillshade(shade_src, shade_px).astype("float32"), mode="F")
        shade = np.array(sh.resize((w, h), Image.BOX))
    rgb = tint * ((1 - SHADE_K) + SHADE_K * shade[..., None])

    dem_c = gaussian_filter(np.nan_to_num(dem, nan=np.nanmedian(dem)), CONTOUR_SMOOTH)
    thin, thick = contours(dem_c, px_m, interval, every)
    for mask, colour, op in ((thin, CONTOUR, 0.85), (thick, INDEX, 1.0)):
        a = (mask * op)[..., None]
        rgb = rgb * (1 - a) + to_rgb(colour) * a

    out = np.dstack([np.clip(rgb, 0, 1) * 255, np.where(sea, 0, 255)]).astype("uint8")
    if with_rock:
        out = hachures(out, dem_c, px_m, origin)
    return out


def hachures(rgba: np.ndarray, dem: np.ndarray, px_m: float,
             origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Short strokes down the fall line where contours alone cannot describe rock.

    Drawn as real line segments (not a pixel pattern), which is what makes IGN's
    cliff drawing read as rock rather than as texture noise.
    """
    from PIL import ImageDraw
    gy, gx = np.gradient(dem, px_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    strong = slope > ROCK_SLOPE
    if not strong.any():
        return rgba
    img = Image.fromarray(rgba, "RGBA")
    d = ImageDraw.Draw(img)
    h, w = dem.shape
    colour = tuple(int(c * 255) for c in to_rgb(ROCK)) + (205,)
    # the stroke grid is anchored to absolute tile pixels, so neighbouring tiles
    # draw the same hachures across their shared edge
    ox, oy = origin
    for ay in range(oy + 2, oy + h - 2, 3):
        y = ay - oy
        for ax in range(ox + 2, ox + w - 2, 3):
            x = ax - ox
            if not strong[y, x]:
                continue
            # fall line: downhill is opposite to the gradient
            dx, dy = -gx[y, x], -gy[y, x]
            n = math.hypot(dx, dy)
            if n < 1e-6:
                continue
            length = 1.8 + 2.6 * min(1.0, (slope[y, x] - ROCK_SLOPE) / 18.0)
            ux, uy = dx / n * length, dy / n * length
            d.line([(x - ux, y - uy), (x + ux, y + uy)], fill=colour, width=1)
    return np.array(img)


def sheet(bounds, size: int, z: int) -> np.ndarray:
    """Render one square sheet for a zoom — the preview and the tiles share this path."""
    x0, y0, x1, y1 = bounds
    px_m = (x1 - x0) / size
    interval, every = CONTOURS[min(z, max(CONTOURS))]
    dem = read_dem(bounds, px_m)                    # output-resolution sampling
    fine = read_dem(bounds, px_m / 2)               # finer grid for the hillshade
    return render(dem, px_m, interval, every, shade_src=fine, shade_px=px_m / 2)


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
    mm = np.memmap(path, dtype="float32", mode="w+", shape=shape)
    band = 512
    for r0 in range(0, shape[0], band):
        r1 = min(shape[0], r0 + band)
        mm[r0:r1] = read_dem((x0, y1 - r1 * res, x1, y1 - r0 * res), res)
    mm.flush()
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs=5, metavar=("X0", "Y0", "X1", "Y1", "SIZE"))
    ap.add_argument("--zoom", type=int, default=13, help="zoom to imitate in preview")
    ap.add_argument("--output", default="preview.png")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--tiles", action="store_true")
    ap.add_argument("--zooms", default=f"{ZMIN}-{ZMAX}")
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
    dem, res, shape, scratch = build_dem_cache(bounds)
    print(f" · DEM cache {shape[1]}×{shape[0]} at {res} m ({time.time()-t0:.0f} s)")
    min_lon, min_lat, max_lon, max_lat = relief.mercator_bounds(
        Affine(res, 0, bounds[0], 0, -res, bounds[3]), shape)

    count = 0
    with OUT.open("wb") as f:
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
            interval, every = CONTOURS[min(z, max(CONTOURS))]
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    bb = tile_bbox(z, x, y)
                    px_m = (bb[2] - bb[0]) / TILE
                    # a mercator tile is a rotated quad in UTM (meridian convergence),
                    # so window the cache on the *transformed* padded box: mixing a
                    # mercator halo with a UTM window starves the tile edges of source
                    from pyproj import Transformer
                    pad = PAD * px_m
                    inv = Transformer.from_crs("EPSG:3857", CRS, always_xy=True)
                    mbox = mercator_box(z, x, y, pad)
                    xs_, ys_ = inv.transform([mbox[0], mbox[2], mbox[0], mbox[2]],
                                             [mbox[1], mbox[1], mbox[3], mbox[3]])
                    c0 = max(0, int((min(xs_) - bounds[0]) / res) - 1)
                    r0 = max(0, int((bounds[3] - max(ys_)) / res) - 1)
                    c1 = min(shape[1], int((max(xs_) - bounds[0]) / res) + 2)
                    r1 = min(shape[0], int((bounds[3] - min(ys_)) / res) + 2)
                    if c1 - c0 < 3 or r1 - r0 < 3:
                        continue
                    src = np.array(dem[r0:r1, c0:c1])
                    if not (src > 0).any():
                        continue
                    src[src <= 0] = np.nan
                    st = Affine(res, 0, bounds[0] + c0 * res, 0, -res, bounds[3] - r0 * res)
                    box = TILE + 2 * PAD
                    dst_tr = from_bounds(*mercator_box(z, x, y, pad * 1.0), box, box)
                    dem_t = np.full((box, box), np.nan, "float32")
                    reproject(src, dem_t, src_transform=st, src_crs=CRS, dst_transform=dst_tr,
                              dst_crs="EPSG:3857", dst_nodata=np.nan,
                              resampling=Resampling.bilinear)
                    fine = np.full((2 * box, 2 * box), np.nan, "float32")
                    reproject(src, fine, src_transform=st, src_crs=CRS,
                              dst_transform=from_bounds(*mercator_box(z, x, y, pad),
                                                        2 * box, 2 * box),
                              dst_crs="EPSG:3857", dst_nodata=np.nan,
                              resampling=Resampling.bilinear)
                    big = render(dem_t, px_m, interval, every,
                                 shade_src=fine, shade_px=px_m / 2,
                                 origin=(x * TILE - PAD, y * TILE - PAD))
                    img = big[PAD:PAD + TILE, PAD:PAD + TILE]
                    buf = io.BytesIO()
                    Image.fromarray(img, "RGBA").save(buf, "WEBP", quality=88, method=6)
                    wr.write_tile(zxy_to_tileid(z, x, y), buf.getvalue())
                    count += 1
            print(f" · z{z}: cumulated {count} tiles ({time.time()-t0:.0f} s)")
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
    del dem
    scratch.unlink(missing_ok=True)
    print(f" · {OUT.name}: {OUT.stat().st_size/1e6:.1f} MB, {count} tiles, "
          f"z{zmin}-{zmax}, {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
