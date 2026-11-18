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

The DEM is GEM-15 (Google, CC BY 4.0): a 15 m bare-earth DTM, which is what makes
the map's own relief hold up at street zoom — at zoom 13 a tile is 18 m per pixel,
so the printed maps' 100 m grid looked blurred there. Below HD_Z the relief is
sampled at 100 m (the printed grid, cheap to ship); from HD_Z up it is composed at
15 m. GEM-15 masks inland water bodies with a 9 m buffer, and Copernicus GLO-30
(fetched by scripts/00_download.py) fills those holes and defines the sea.

GEM-15 is orthometric EGM96 with metre-scale regional bias, so it drives this
picture only: the elevation figures the map quotes (dist/elevation) stay on
Copernicus GLO-30. See ATTRIBUTION.md for both licences.

Preview like the vector archive: `pmtiles serve site/data --port 7999 --cors='*'`.
"""
import importlib.util
import io
import math
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "erliebea.pmtiles"
RAW = ROOT / "data" / "raw"
GEM15 = RAW / "gem15"

RES = 100          # m per cell below HD_Z, as in the printed maps
HD_RES = 15        # m per cell of the GEM-15 source, from HD_Z up
HD_Z = 11          # first zoom composed from the 15 m DEM
CRS = "EPSG:25830"  # UTM 30N, the project's working CRS
RELIEF = 1.15      # Erliebea's shading strength in 07_site_maps.map_relief
ZMIN, ZMAX = 5, 13
TILE = 256

PAL = {  # from site/palette.json
    "paper": "#F3EEE3", "card": "#FAF7F0", "sea": "#DCE3E1",
    "earth": ["#BCA273", "#A08455", "#82663F", "#624A2C", "#43311D"],
}


def to_rgb(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], "float32") / 255


def ensure_sources() -> None:
    """Fetch the GLO-30 and GEM-15 tiles into data/raw/, reusing 00_download.py."""
    spec = importlib.util.spec_from_file_location("dl", ROOT / "scripts" / "00_download.py")
    dl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dl)
    dl.copdem()   # skips tiles already on disk
    dl.gem15()


def outline():
    """Euskal Herria as one (multi)polygon in the working CRS."""
    import geopandas as gpd
    return gpd.read_file(ROOT / "dist" / "euskal_herria.gpkg", layer="euskal_herria").to_crs(CRS)


def frame(eh) -> tuple[float, float, float, float]:
    """The relief frame: Euskal Herria plus the printed maps' 5 % margin."""
    x0, y0, x1, y1 = eh.total_bounds
    dx, dy = (x1 - x0) * 0.05, (y1 - y0) * 0.05
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def glodem(bounds, shape, transform) -> np.ndarray:
    """Copernicus GLO-30 on the given grid: the sea, and a patch for GEM's holes."""
    from pyproj import Transformer
    fwd = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    x0, y0, x1, y1 = bounds
    lons, lats = fwd.transform([x0, x1], [y0, y1])
    tiles = [rasterio.open(p) for p in sorted((RAW / "copdem").glob("*.tif"))]
    try:
        src, src_t = merge(tiles, bounds=(min(lons), min(lats), max(lons), max(lats)),
                           res=1 / 3600)
        crs = tiles[0].crs
    finally:
        for t in tiles:
            t.close()
    dem = np.full(shape, np.nan, "float32")
    reproject(src[0].astype("float32"), dem, src_transform=src_t, src_crs=crs,
              dst_transform=transform, dst_crs=CRS, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    dem[dem <= 0.5] = np.nan        # sea
    return dem


def gerdem(bounds, shape, transform, res, glo) -> np.ndarray:
    """GEM-15 DTM on the given grid, its masked water bodies filled from GLO-30."""
    dem = np.full(shape, np.nan, "float32")
    x0, y0, x1, y1 = bounds
    for path in sorted(GEM15.glob("*.tif")):
        with rasterio.open(path) as src:
            try:
                win = window_from_bounds(x0, y0, x1, y1, src.transform)
                win = win.intersection(Window(0, 0, src.width, src.height))
            except rasterio.errors.WindowError:      # no overlap with this mosaic
                continue
            if win.width < 2 or win.height < 2:
                continue
            # sample straight to about the target cell size; the mosaics overlap
            # each other and carry zero-filled sea, hence the merge by first value
            ow = max(2, int(round(win.width * abs(src.res[0]) / res)))
            oh = max(2, int(round(win.height * abs(src.res[1]) / res)))
            a = src.read(1, window=win, out_shape=(oh, ow)).astype("float32")
            st = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
            tmp = np.full(shape, np.nan, "float32")
            reproject(a, tmp, src_transform=st, src_crs=src.crs, dst_transform=transform,
                      dst_crs=CRS, dst_nodata=np.nan, resampling=Resampling.bilinear)
            take = np.isfinite(tmp) & (tmp > 0) & ~np.isfinite(dem)
            dem[take] = tmp[take]
    return np.where(np.isfinite(dem), dem, glo)      # GLO-30 patches the holes


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


def relief(res: float, bounds, eh) -> tuple[np.ndarray, Affine]:
    """The whole frame at one cell size, as one RGBA array."""
    x0, y0, x1, y1 = bounds
    transform = Affine(res, 0, x0, 0, -res, y1)
    shape = (int(round((y1 - y0) / res)), int(round((x1 - x0) / res)))
    glo = glodem(bounds, shape, transform)
    return render(gerdem(bounds, shape, transform, res, glo), transform, res, eh), transform


def relief_hd(bounds, eh) -> tuple[np.memmap, Affine, tuple[int, int], Path]:
    """The frame at 15 m, composed strip by strip into a scratch memmap (not RAM)."""
    x0, y0, x1, y1 = bounds
    transform = Affine(HD_RES, 0, x0, 0, -HD_RES, y1)
    shape = (int(round((y1 - y0) / HD_RES)), int(round((x1 - x0) / HD_RES)))
    glo30 = glodem(bounds, shape=(int(round((y1 - y0) / 30)), int(round((x1 - x0) / 30))),
                   transform=Affine(30, 0, x0, 0, -30, y1))
    path = Path(tempfile.gettempdir()) / "ehmap_erliebea_hd.u8"
    band = 288                                        # rows per strip, +2 halo rows
    hd = np.memmap(path, dtype="uint8", mode="w+", shape=(*shape, 4))
    for r0 in range(0, shape[0], band):
        r1 = min(shape[0], r0 + band)
        h0, h1 = max(0, r0 - 2), min(shape[0], r1 + 2)
        st = Affine(HD_RES, 0, x0, 0, -HD_RES, y1 - h0 * HD_RES)
        sub = (h1 - h0, shape[1])
        # GLO-30 at 30 m, nearest-neighbour doubled onto the 15 m grid
        g = glo30[h0 * HD_RES // 30:h1 * HD_RES // 30]
        glo = np.repeat(np.repeat(g, 2, axis=0), 2, axis=1)[:sub[0], :shape[1]]
        if glo.shape[0] < sub[0]:
            glo = np.vstack([glo, np.full((sub[0] - glo.shape[0], shape[1]), np.nan, "float32")])
        dem = gerdem((x0, y1 - h1 * HD_RES, x1, y1 - h0 * HD_RES), sub, st, HD_RES, glo)
        hd[r0:r1] = render(dem, st, HD_RES, eh)[r0 - h0:r1 - h0]
    hd.flush()
    return hd, transform, shape, path


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

    coarse, coarse_t = relief(RES, bounds, eh)
    print(f" · composed {coarse.shape[1]}×{coarse.shape[0]} relief at {RES} m "
          f"for z{ZMIN}-{HD_Z - 1} ({time.time() - t0:.0f} s)")
    hd, hd_t, hd_shape, hd_path = relief_hd(bounds, eh)
    print(f" · composed {hd_shape[1]}×{hd_shape[0]} relief at {HD_RES} m "
          f"for z{HD_Z}-{ZMAX} ({time.time() - t0:.0f} s)")

    min_lon, min_lat, max_lon, max_lat = mercator_bounds(coarse_t, coarse.shape[:2])
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
            hd_level = z >= HD_Z
            src, src_t, res = (hd, hd_t, HD_RES) if hd_level else (coarse, coarse_t, RES)
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
                    img.save(buf, "WEBP", quality=85, method=4)
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
                "attribution": "Relief: GEM-15, produced by Google (CC BY 4.0) — "
                               "inland water bodies filled from Copernicus WorldDEM-30: "
                               "© DLR e.V. 2010-2014, © Airbus Defence and Space GmbH 2014-2018",
            },
        )
    del hd
    hd_path.unlink(missing_ok=True)
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z{ZMIN}-{ZMAX}, {(time.time() - t0):.0f} s")


if __name__ == "__main__":
    main()
