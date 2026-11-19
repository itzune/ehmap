"""Shaded-relief raster tiles of Euskal Herria, as a PMTiles archive.

The printed Erliebea map (scripts/07_site_maps.py) colours the DEM hypsometrically
and shades it with a soft multi-directional hillshade; the interactive map's
Erliebea theme wants the same look under its borders and labels. This script
composes that exact background — hypsometric earth ramp over [0, 2300] m,
NW-weighted hillshade, faint paper relief in the context ring around Euskal
Herria, sea left transparent — and then warps it into a WebP pyramid of 256 px
web-mercator tiles packed as site/data/erliebea.pmtiles.

The relief maths is copied from 07_site_maps.py (regional_dem, hillshade, ramp,
Base.background); keep the two in sync if the printed look ever changes.

The DEM is the national **LiDAR bare earth at 5 m**: PNOA-LiDAR MDT05 (IGN España,
CC BY 4.0) south of the Bidasoa and RGE ALTI (IGN France, Licence Ouverte 2.0)
north of it, fetched onto one grid by scripts/00_download.py. Both store water as
a flat value, so `dem <= 0` is the sea. Below HD_Z the relief is sampled at 100 m
(the printed grid, cheap to ship); from HD_Z up it is composed at the LiDAR's own
5 m — at zoom 13 a tile is 18 m per pixel, where anything coarser blurs.

These LiDAR products carry their own notices and are not CC BY (RGE ALTI is
Licence Ouverte), so they drive this picture only: the elevation figures the atlas
quotes (dist/elevation) stay on Copernicus GLO-30. See ATTRIBUTION.md.

Preview like the vector archive: `pmtiles serve site/data --port 7999 --cors='*'`.
"""
import importlib.util
import io
import math
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "erliebea.pmtiles"
LIDAR_TIF = ROOT / "data" / "raw" / "lidar" / "eh_lidar_5m.tif"
SCRATCH = ROOT / "out" / "erliebea_5m.rgba"

RES = 100          # m per cell below HD_Z, as in the printed maps
HD_RES = 5         # m per cell of the LiDAR source, from HD_Z up
HD_Z = 11          # first zoom composed from the 5 m DEM
SMOOTH = 0.8       # cells of blur that hide the LiDAR's integer-metre terracing
CRS = "EPSG:25830"  # UTM 30N, the project's working CRS
RELIEF = 1.15      # Erliebea's shading strength in 07_site_maps.map_relief
ZMIN, ZMAX = 5, 13
TILE = 256
FLAT_BYTES = 5120  # tiles encoding under this at q85 are re-encoded at q95 (no blocking)

PAL = {  # from site/palette.json
    "paper": "#F3EEE3", "card": "#FAF7F0", "sea": "#DCE3E1",
    "earth": ["#BCA273", "#A08455", "#82663F", "#624A2C", "#43311D"],
}


def to_rgb(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], "float32") / 255


def ensure_sources() -> None:
    """Fetch the 5 m LiDAR mosaic into data/raw/, reusing 00_download.py."""
    spec = importlib.util.spec_from_file_location("dl", ROOT / "scripts" / "00_download.py")
    dl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dl)
    dl.lidar()   # skips the mosaic if it is already on disk


def outline():
    """Euskal Herria as one (multi)polygon in the working CRS."""
    import geopandas as gpd
    return gpd.read_file(ROOT / "dist" / "euskal_herria.gpkg", layer="euskal_herria").to_crs(CRS)


def frame(eh) -> tuple[float, float, float, float]:
    """The relief frame: Euskal Herria plus the printed maps' 5 % margin."""
    x0, y0, x1, y1 = eh.total_bounds
    dx, dy = (x1 - x0) * 0.05, (y1 - y0) * 0.05
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def dem_window(transform: Affine, shape: tuple[int, int], res: float) -> np.ndarray:
    """The LiDAR bare earth on the given grid; water (<= 0) becomes NaN."""
    x0, y1 = transform.c, transform.f
    x1, y0 = x0 + shape[1] * res, y1 - shape[0] * res
    dem = np.full(shape, np.nan, "float32")
    with rasterio.open(LIDAR_TIF) as src:
        try:
            win = window_from_bounds(x0, y0, x1, y1, src.transform)
            win = win.intersection(Window(0, 0, src.width, src.height))
        except rasterio.errors.WindowError:          # the whole strip is sea
            return dem
        if win.width < 2 or win.height < 2:
            return dem
        # sample straight to the target cell size; averaging keeps 5 m detail from
        # aliasing into the 100 m tier, and is a no-op at 5 m
        ow = max(2, int(round(win.width * abs(src.res[0]) / res)))
        oh = max(2, int(round(win.height * abs(src.res[1]) / res)))
        a = src.read(1, window=win, out_shape=(oh, ow),
                     resampling=Resampling.average if res > abs(src.res[0]) else Resampling.bilinear
                     ).astype("float32")
        a[a < -1000] = np.nan                        # RGE ALTI's void encoding
        st = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
        reproject(a, dem, src_transform=st, src_crs=src.crs, dst_transform=transform,
                  dst_crs=CRS, dst_nodata=np.nan, resampling=Resampling.bilinear)
    dem[dem <= 0] = np.nan                           # both sources store water as 0
    if res < 10:
        dem = smooth(dem)
    return dem


def smooth(dem: np.ndarray, sigma: float = SMOOTH) -> np.ndarray:
    """Kill the terracing of integer-metre heights without touching the landforms.

    PNOA stores whole metres at 5 m, so a 3° slope steps 0.26 m per cell: rounding
    turns gentle ground into flat facets separated by one-cell cliffs, which the
    hillshade then draws as a staircase. A sub-cell blur (a normalised convolution,
    so the sea never bleeds inland) restores the continuous surface.
    """
    from scipy.ndimage import gaussian_filter
    ok = np.isfinite(dem)
    if not ok.any():
        return dem
    num = gaussian_filter(np.where(ok, dem, 0.0).astype("float64"), sigma)
    den = gaussian_filter(ok.astype("float64"), sigma)
    out = np.where(den > 0.02, num / np.maximum(den, 1e-9), dem).astype("float32")
    out[~ok] = np.nan
    return out


def render(dem: np.ndarray, transform: Affine, res: float, eh) -> np.ndarray:
    """The printed Erliebea background: hypsometric colour × hillshade, RGBA uint8."""
    d = np.nan_to_num(dem, nan=0.0)
    gy, gx = np.gradient(d, res)
    slope = np.arctan(2.2 * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    alt = math.radians(45)
    shade = np.zeros_like(d)
    for az, w in ((315, 0.5), (270, 0.2), (360, 0.2), (225, 0.1)):
        a = math.radians(az)
        shade += w * (np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(a - aspect))
    shade = np.clip(shade, 0, 1)[..., None]

    inside = ~geometry_mask(eh.geometry, dem.shape, transform)
    sea = np.isnan(dem)

    hypso = [PAL["card"], "#E3D5B3", *PAL["earth"]]       # as in map_relief
    c = np.array([to_rgb(h) for h in hypso])
    t = np.clip(np.nan_to_num(dem, nan=0) / 2300, 0, 1) * (len(c) - 1)
    i = np.clip(np.floor(t).astype(int), 0, len(c) - 2)
    f = (t - i)[..., None]
    hyp_rgb = c[i] * (1 - f) + c[i + 1] * f

    k = 0.36 * RELIEF
    lit = hyp_rgb * ((1 - k) + k * shade) + 0.05 * RELIEF * (shade - 0.5)
    paper = to_rgb(PAL["paper"])
    context = paper * (0.84 + 0.16 * shade)                # faint relief outside EH
    rgb = np.where(sea[..., None], to_rgb(PAL["sea"]), context)
    land = (inside & ~sea)[..., None]
    rgb = np.where(land, np.clip(lit, 0, 1), rgb)

    rgba = np.dstack([np.clip(rgb, 0, 1) * 255, np.where(sea, 0, 255)]).astype("uint8")
    rgba[..., :3] *= ~sea[..., None]                        # keep transparent pixels black
    return rgba


def relief(bounds, eh, res: float, scratch: Path | None = None):
    """The whole frame at one cell size; `scratch` keeps a big one off the RAM."""
    x0, y0, x1, y1 = bounds
    transform = Affine(res, 0, x0, 0, -res, y1)
    shape = (int(round((y1 - y0) / res)), int(round((x1 - x0) / res)))
    band = 256 if scratch else shape[0]
    if scratch:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        rgba = np.memmap(scratch, dtype="uint8", mode="w+", shape=(*shape, 4))
    else:
        rgba = np.empty((*shape, 4), "uint8")
    for r0 in range(0, shape[0], band):
        r1 = min(shape[0], r0 + band)
        halo = 5 if scratch else 2                     # 5 rows cover the blur footprint
        h0, h1 = max(0, r0 - halo), min(shape[0], r1 + halo)
        st = Affine(res, 0, x0, 0, -res, y1 - h0 * res)
        dem = dem_window(st, (h1 - h0, shape[1]), res)
        rgba[r0:r1] = render(dem, st, res, eh)[r0 - h0:r1 - h0]
    if scratch:
        rgba.flush()
    return rgba, transform, shape


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Web-mercator (EPSG:3857) bounds of a tile, west, south, east, north."""
    n = 2 ** z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat = lambda ty: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    X = lambda lon: 6378137.0 * math.radians(lon)
    Y = lambda la: 6378137.0 * math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    return X(lon0), Y(lat(y + 1)), X(lon1), Y(lat(y))


def mercator_bounds(b: Affine, shape) -> tuple[float, float, float, float]:
    """The composed raster's bounds, as lon/lat."""
    h, w = shape
    from pyproj import Transformer
    fwd = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    xs = [b * (px, py) for px in (0, w) for py in (0, h)]
    lons, lats = zip(*(fwd.transform(x, y) for x, y in xs))
    return min(lons), min(lats), max(lons), max(lats)


def warp_tile(src, src_transform: Affine, res: float, z: int, x: int, y: int):
    """Cut the tile's footprint (+2 px) out of the relief raster and warp it to 256²."""
    from pyproj import Transformer
    b = tile_bounds(z, x, y)
    inv = Transformer.from_crs("EPSG:3857", CRS, always_xy=True)
    xs, ys = inv.transform([b[0], b[2], b[0], b[2]], [b[1], b[1], b[3], b[3]])
    halo = 2 * res
    win = window_from_bounds(min(xs) - halo, min(ys) - halo, max(xs) + halo, max(ys) + halo,
                             src_transform)
    c0 = max(0, int(math.floor(win.col_off)))
    r0 = max(0, int(math.floor(win.row_off)))
    c1 = min(src.shape[1], int(math.ceil(win.col_off + win.width)))
    r1 = min(src.shape[0], int(math.ceil(win.row_off + win.height)))
    if c1 - c0 < 2 or r1 - r0 < 2:
        return None                                   # tile fully outside the frame
    sub = np.asarray(src[r0:r1, c0:c1])
    st = src_transform * Affine.translation(c0, r0)
    dst = np.zeros((4, TILE, TILE), "uint8")
    for band in range(4):
        reproject(sub[..., band], dst[band], src_transform=st, src_crs=CRS,
                  dst_transform=Affine((b[2] - b[0]) / TILE, 0, b[0],
                                       0, (b[1] - b[3]) / TILE, b[3]),
                  dst_crs="EPSG:3857", resampling=Resampling.bilinear)
    return dst


def main() -> None:
    t0 = time.time()
    ensure_sources()
    eh = outline()
    bounds = frame(eh)
    print(f" · frame: {bounds[0]:.0f},{bounds[1]:.0f} – {bounds[2]:.0f},{bounds[3]:.0f} ({CRS})")

    coarse, coarse_t, coarse_shape = relief(bounds, eh, RES)
    print(f" · composed {coarse_shape[1]}×{coarse_shape[0]} relief at {RES} m "
          f"for z{ZMIN}-{HD_Z - 1} ({time.time() - t0:.0f} s)")
    hd, hd_t, hd_shape = relief(bounds, eh, HD_RES, scratch=SCRATCH)
    print(f" · composed {hd_shape[1]}×{hd_shape[0]} relief at {HD_RES} m "
          f"for z{HD_Z}-{ZMAX} ({time.time() - t0:.0f} s)")

    min_lon, min_lat, max_lon, max_lat = mercator_bounds(coarse_t, coarse_shape)
    count = 0
    with OUT.open("wb") as f:
        wr = Writer(f)
        for z in range(ZMIN, ZMAX + 1):
            n = 2 ** z
            def tx(lon):
                return max(0, min(n - 1, int((lon + 180) / 360 * n)))
            def ty(lat):
                la = max(-85.05112878, min(85.05112878, lat))
                return max(0, min(n - 1, int((1 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2 * n)))
            x0, x1 = tx(min_lon), tx(math.nextafter(max_lon, min_lon))
            y0, y1 = ty(max_lat), ty(math.nextafter(min_lat, max_lat))
            src, src_t, res = (hd, hd_t, HD_RES) if z >= HD_Z else (coarse, coarse_t, RES)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    dst = warp_tile(src, src_t, res, z, x, y)
                    if dst is None:
                        continue
                    img = Image.fromarray(np.transpose(dst, (1, 2, 0)), "RGBA")
                    if not dst[3].any():
                        # Sea inside the frame: MapLibre keeps raster tiles that the
                        # archive simply lacks forever "pending" (and idle never fires),
                        # so every tile in the frame is written — empty ones as a
                        # transparent placeholder they all share.
                        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
                    buf = io.BytesIO()
                    img.save(buf, "WEBP", quality=85, method=6)
                    if len(buf.getvalue()) < FLAT_BYTES:
                        # A low-entropy tile (a valley floor, a calm sea horizon) is cheap
                        # even at high quality, and at q85 WebP flattens its gradient into
                        # visible 16 px blocks with straight edges.
                        buf = io.BytesIO()
                        img.save(buf, "WEBP", quality=95, method=6)
                    wr.write_tile(zxy_to_tileid(z, x, y), buf.getvalue())
                    count += 1
            print(f" · z{z}: cumulated {count} tiles ({(time.time() - t0):.0f} s)")
        wr.finalize(
            {
                "tile_type": TileType.WEBP,
                "tile_compression": Compression.NONE,
                "min_lon_e7": int(min_lon * 1e7), "min_lat_e7": int(min_lat * 1e7),
                "max_lon_e7": int(max_lon * 1e7), "max_lat_e7": int(max_lat * 1e7),
                "center_lon_e7": int((min_lon + max_lon) / 2 * 1e7),
                "center_lat_e7": int((min_lat + max_lat) / 2 * 1e7),
                "center_zoom": 8,
            },
            {
                "name": "erliebea",
                "description": "ehmap: shaded relief and hypsometric colour of Euskal Herria",
                "attribution": "Relief: 5 m LiDAR bare-earth DTMs — PNOA-LiDAR MDT05, "
                               "© IGN España (CC BY 4.0) and RGE ALTI®, © IGN France "
                               "(Licence Ouverte 2.0)",
            },
        )
    del hd
    SCRATCH.unlink(missing_ok=True)
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z{ZMIN}-{ZMAX}, {(time.time() - t0):.0f} s")


if __name__ == "__main__":
    main()
