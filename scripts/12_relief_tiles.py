"""Shaded-relief raster tiles of Euskal Herria, as a PMTiles archive.

The printed Erliebea map (scripts/07_site_maps.py) colours the DEM hypsometrically
and shades it with a soft multi-directional hillshade; the interactive map's
Erliebea theme wants the same look under its borders and labels. This script
composes that exact background once — hypsometric earth ramp over [0, 2300] m,
NW-weighted hillshade at 100 m cells, faint paper relief in the context ring
around Euskal Herria, sea left transparent — and then warps it into a WebP
pyramid of 256 px web-mercator tiles packed as site/data/erliebea.pmtiles.

The relief maths is copied from 07_site_maps.py (regional_dem, hillshade, ramp,
Base.background); keep the two in sync if the printed look ever changes. The
source is the same twelve 1° Copernicus GLO-30 tiles the printed maps use
(data/raw/copdem/, fetched by scripts/00_download.py) — including the context
ring around Euskal Herria. See ATTRIBUTION.md for the licence and the notices
in dist/elevation/LICENSE.md.

Preview like the vector archive: `pmtiles serve site/data --port 7999 --cors='*'`.
"""
import importlib.util
import io
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import reproject

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "erliebea.pmtiles"

RES = 100          # m per cell of the shaded relief, as in the printed maps
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


def ensure_tiles() -> None:
    """Fetch the 1° GLO-30 tiles into data/raw/copdem/, reusing 00_download.py."""
    spec = importlib.util.spec_from_file_location("dl", ROOT / "scripts" / "00_download.py")
    dl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dl)
    dl.copdem()   # skips tiles already on disk


def compose() -> tuple[np.ndarray, rasterio.Affine]:
    """The printed Erliebea background: hypsometric colour × hillshade, RGBA uint8."""
    import geopandas as gpd

    outline = gpd.read_file(ROOT / "dist" / "euskal_herria.gpkg",
                            layer="euskal_herria").to_crs(CRS)
    x0, y0, x1, y1 = outline.total_bounds
    dx, dy = (x1 - x0) * 0.05, (y1 - y0) * 0.05   # the printed maps' 5 % frame margin
    x0, y0, x1, y1 = x0 - dx, y0 - dy, x1 + dx, y1 + dy

    # --- regional_dem from 07_site_maps.py: merge the 1° tiles, warp to 100 m ---
    transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
    dem = np.full((int((y1 - y0) / RES), int((x1 - x0) / RES)), np.nan, "float32")
    tiles = [rasterio.open(p) for p in sorted((ROOT / "data" / "raw" / "copdem").glob("*.tif"))]
    src, src_t = merge(tiles, res=1 / 1200)
    crs = tiles[0].crs
    for t in tiles:
        t.close()
    reproject(src[0].astype("float32"), dem, src_transform=src_t, src_crs=crs,
              dst_transform=transform, dst_crs=CRS, dst_nodata=np.nan,
              resampling=rasterio.warp.Resampling.bilinear)
    del src
    dem[dem <= 0.5] = np.nan        # sea

    # --- everything below mirrors 07_site_maps.hillshade / Base.background ---
    d = np.nan_to_num(dem, nan=0.0)
    gy, gx = np.gradient(d, RES)
    slope = np.arctan(2.2 * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    alt = math.radians(45)
    shade = np.zeros_like(d)
    for az, w in ((315, 0.5), (270, 0.2), (360, 0.2), (225, 0.1)):
        a = math.radians(az)
        shade += w * (np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(a - aspect))
    shade = np.clip(shade, 0, 1)[..., None]

    inside = ~geometry_mask(outline.geometry, dem.shape, transform)
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
    return rgba, transform


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Web-mercator (EPSG:3857) bounds of a tile, west, south, east, north."""
    n = 2 ** z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat = lambda ty: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    X = lambda lon: 6378137.0 * math.radians(lon)
    Y = lambda la: 6378137.0 * math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    return X(lon0), Y(lat(y + 1)), X(lon1), Y(lat(y))


def mercator_bounds(b: rasterio.Affine, shape) -> tuple[float, float, float, float]:
    """The composed raster's bounds, as lon/lat."""
    h, w = shape
    xs = [b * (px, py) for px in (0, w) for py in (0, h)]
    from pyproj import Transformer
    fwd = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    lons, lats = zip(*(fwd.transform(x, y) for x, y in xs))
    return min(lons), min(lats), max(lons), max(lats)


def main() -> None:
    t0 = time.time()
    ensure_tiles()
    rgba, transform = compose()
    h, w = rgba.shape[:2]
    print(f" · composed {w}×{h} relief at {RES} m "
          f"({(time.time() - t0):.1f} s)")

    min_lon, min_lat, max_lon, max_lat = mercator_bounds(transform, (h, w))
    print(f" · frame: {min_lon:.3f},{min_lat:.3f} – {max_lon:.3f},{max_lat:.3f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
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
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    dst = np.zeros((4, TILE, TILE), "uint8")
                    ok = True
                    for b in range(4):
                        try:
                            reproject(
                                rgba[..., b], dst[b],
                                src_transform=transform, src_crs=CRS,
                                dst_transform=from_bounds(*tile_bounds(z, x, y), TILE, TILE),
                                dst_crs="EPSG:3857",
                                resampling=rasterio.warp.Resampling.bilinear)
                        except Exception as e:      # fully-outside tiles etc.
                            ok = False
                            break
                    if not ok:
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
                "attribution": "Contains Copernicus WorldDEM-30 data: © DLR e.V. 2010-2014, "
                               "© Airbus Defence and Space GmbH 2014-2018 (Copernicus WorldDEM-30 licence)",
            },
        )
    print(f" · {OUT.name}: {OUT.stat().st_size / 1e6:.1f} MB, {count} tiles, "
          f"z{ZMIN}-{ZMAX}, {(time.time() - t0):.0f} s")


if __name__ == "__main__":
    main()
