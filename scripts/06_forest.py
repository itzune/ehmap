"""Current forest of Euskal Herria from ESA WorldCover 2021 (10 m, CC BY 4.0).

Inputs (from scripts/00_download.py):
  data/raw/worldcover/*.tif   ESA WorldCover 10 m 2021 v200 tiles (EPSG:4326)
  dist/euskal_herria.gpkg     municipalities, territories and outline

Changes made to the source (as CC BY 4.0 asks us to indicate): mosaicked, reprojected to
ETRS89 / UTM 30N (EPSG:25830) at 10 m with nearest-neighbour resampling, clipped to Euskal
Herria; tree cover aggregated to 100 m.

Outputs:
  dist/forest/landcover_2021_10m.tif        all WorldCover classes, 10 m (COG with colour table)
  dist/forest/forest_cover_100m.tif         % of tree cover per 100 m cell (0-100, COG)
  dist/forest/forest_by_municipality.csv    tree cover km² and % per municipality
  dist/forest/forest_by_territory.csv       the same per territory
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "worldcover"
GPKG = ROOT / "dist" / "euskal_herria.gpkg"
OUT = ROOT / "dist" / "forest"
CRS = "EPSG:25830"
RES = 10
TREE = 10  # WorldCover class "Tree cover"

# WorldCover classes and their official colours
CLASSES = {10: ("Tree cover", "#006400"), 20: ("Shrubland", "#FFBB22"), 30: ("Grassland", "#FFFF4C"),
           40: ("Cropland", "#F096FF"), 50: ("Built-up", "#FA0000"), 60: ("Bare / sparse vegetation", "#B4B4B4"),
           70: ("Snow and ice", "#F0F0F0"), 80: ("Permanent water bodies", "#0064C8"),
           90: ("Herbaceous wetland", "#0096A0"), 95: ("Mangroves", "#00CF75"), 100: ("Moss and lichen", "#FAE6A0")}


def landcover(outline: gpd.GeoDataFrame) -> tuple[np.ndarray, rasterio.Affine]:
    """All tiles reprojected onto one 10 m EPSG:25830 grid, 0 (nodata) outside Euskal Herria."""
    x0, y0, x1, y1 = outline.total_bounds
    x0, y0 = np.floor([x0 / 100, y0 / 100]) * 100  # whole 100 m so 10 m cells nest in 100 m
    x1, y1 = np.ceil([x1 / 100, y1 / 100]) * 100
    transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
    lc = np.zeros((int((y1 - y0) / RES), int((x1 - x0) / RES)), dtype="uint8")
    w, s, e, n = transform_bounds(CRS, "EPSG:4326", x0, y0, x1, y1)
    for path in sorted(RAW.glob("*.tif")):
        with rasterio.open(path) as src:
            win = from_bounds(w, s, e, n, src.transform).intersection(
                rasterio.windows.Window(0, 0, src.width, src.height))
            if win.width < 1 or win.height < 1:
                continue
            win = win.round_offsets().round_lengths()
            data = src.read(1, window=win)
            reproject(data, lc, src_transform=src.window_transform(win), src_crs=src.crs,
                      src_nodata=0, dst_transform=transform, dst_crs=CRS, dst_nodata=0,
                      init_dest_nodata=False, resampling=Resampling.nearest)
    lc[geometry_mask(outline.geometry, lc.shape, transform)] = 0
    return lc, transform


def write_landcover(lc: np.ndarray, transform: rasterio.Affine, path: Path) -> None:
    profile = dict(driver="COG", width=lc.shape[1], height=lc.shape[0], count=1, dtype="uint8",
                   crs=CRS, transform=transform, nodata=0, compress="DEFLATE",
                   overview_resampling="mode")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(lc, 1)
        dst.write_colormap(1, {k: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
                               for k, (_, c) in CLASSES.items()})
        dst.update_tags(1, source="ESA WorldCover 10 m 2021 v200",
                        classes="; ".join(f"{k}={v[0]}" for k, v in CLASSES.items()))


def forest_100m(lc: np.ndarray, transform: rasterio.Affine, path: Path) -> None:
    """% of the valid 10 m cells in each 100 m cell that are tree cover (255 = outside)."""
    h, w = lc.shape[0] // 10, lc.shape[1] // 10
    blocks = lc[:h * 10, :w * 10].reshape(h, 10, w, 10)
    valid = (blocks > 0).sum(axis=(1, 3))
    trees = (blocks == TREE).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(valid > 0, np.round(100 * trees / valid), 255).astype("uint8")
    profile = dict(driver="COG", width=w, height=h, count=1, dtype="uint8", crs=CRS,
                   transform=transform * rasterio.Affine.scale(10), nodata=255,
                   compress="DEFLATE", overview_resampling="average")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(pct, 1)
        dst.update_tags(1, units="% tree cover", source="ESA WorldCover 10 m 2021 v200")


def zonal(lc: np.ndarray, transform: rasterio.Affine, mun: gpd.GeoDataFrame) -> pd.DataFrame:
    """Tree cover and land (valid) cells per municipality, by rasterising their index."""
    ids = rasterize(((g, i + 1) for i, g in enumerate(mun.geometry)), out_shape=lc.shape,
                    transform=transform, dtype="int32")
    n = len(mun) + 1
    land = np.bincount(ids.ravel(), weights=(lc > 0).ravel(), minlength=n)[1:]
    trees = np.bincount(ids.ravel(), weights=(lc == TREE).ravel(), minlength=n)[1:]
    cell_km2 = RES * RES / 1e6
    return pd.DataFrame({"code": mun.code.values, "land_km2": land * cell_km2,
                         "forest_km2": trees * cell_km2})


def main() -> None:
    mun = gpd.read_file(GPKG, layer="municipalities").to_crs(CRS)
    outline = gpd.read_file(GPKG, layer="euskal_herria").to_crs(CRS)
    lc, transform = landcover(outline)
    OUT.mkdir(parents=True, exist_ok=True)
    write_landcover(lc, transform, OUT / "landcover_2021_10m.tif")
    forest_100m(lc, transform, OUT / "forest_cover_100m.tif")

    z = mun[["code", "name_eu", "territory_id"]].merge(zonal(lc, transform, mun), on="code")
    z["forest_pct"] = (100 * z.forest_km2 / z.land_km2).round(1)
    z.round({"land_km2": 2, "forest_km2": 2}).to_csv(OUT / "forest_by_municipality.csv", index=False)
    t = z.groupby("territory_id")[["land_km2", "forest_km2"]].sum()
    t["forest_pct"] = (100 * t.forest_km2 / t.land_km2).round(1)
    t.loc["euskal_herria"] = [t.land_km2.sum(), t.forest_km2.sum(),
                              round(100 * t.forest_km2.sum() / t.land_km2.sum(), 1)]
    t.round(1).reset_index().to_csv(OUT / "forest_by_territory.csv", index=False)

    counts = pd.Series(np.bincount(lc.ravel(), minlength=101)[list(CLASSES)], index=[v[0] for v in CLASSES.values()])
    share = (100 * counts / counts.sum()).round(1)
    print("Land cover 2021 (% of Euskal Herria):\n" + share[share > 0].to_string())
    print("\n" + t.round(1).to_string())


if __name__ == "__main__":
    main()
