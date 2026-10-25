"""Population grid of Euskal Herria from GHSL GHS-POP (JRC, R2023A, epoch 2020, 100 m).

Input (from scripts/00_download.py):
  data/raw/ghsl/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R4_C18.tif  (Mollweide, people per cell)
  dist/euskal_herria.gpkg                                            (outline and territories)

Changes made to the source (as CC BY 4.0 asks us to indicate): reprojected from Mollweide
(ESRI:54009) to ETRS89-LAEA (EPSG:3035) with sum resampling, clipped to Euskal Herria (by cell
centre), and aggregated to 1 km.

Outputs:
  dist/population_grid/ghs_pop_2020_100m.tif   people per 100 m cell (Cloud-Optimized GeoTIFF)
  dist/population_grid/ghs_pop_2020_1km.gpkg   1 km cells with people > 0 (Eurostat grid IDs)
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, reproject
from shapely import box

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "ghsl" / "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R4_C18.tif"
GPKG = ROOT / "dist" / "euskal_herria.gpkg"
OUT = ROOT / "dist" / "population_grid"
CRS = "EPSG:3035"
RES = 100
NODATA = -1.0


def warp_to_laea(outline: gpd.GeoDataFrame) -> tuple[np.ndarray, rasterio.Affine]:
    """People per 100 m cell on the EPSG:3035 grid, outside Euskal Herria set to NODATA."""
    x0, y0, x1, y1 = outline.total_bounds
    # snap the extent to whole kilometres so 100 m cells nest in the 1 km grid
    x0, y0 = np.floor([x0 / 1000, y0 / 1000]) * 1000
    x1, y1 = np.ceil([x1 / 1000, y1 / 1000]) * 1000
    transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
    pop = np.zeros((int((y1 - y0) / RES), int((x1 - x0) / RES)), dtype="float64")
    with rasterio.open(SRC) as src:
        reproject(rasterio.band(src, 1), pop, dst_transform=transform, dst_crs=CRS,
                  dst_nodata=0, resampling=Resampling.sum)
    outside = geometry_mask(outline.geometry, pop.shape, transform)  # True outside
    pop[outside] = NODATA
    return pop, transform


def write_cog(pop: np.ndarray, transform: rasterio.Affine, path: Path) -> None:
    profile = dict(driver="COG", width=pop.shape[1], height=pop.shape[0], count=1,
                   dtype="float32", crs=CRS, transform=transform, nodata=NODATA,
                   compress="DEFLATE", predictor=3, overview_resampling="average")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(pop.astype("float32"), 1)
        dst.update_tags(1, units="people per 100 m cell", source="GHSL GHS-POP R2023A, epoch 2020")


def grid_1km(pop: np.ndarray, transform: rasterio.Affine) -> gpd.GeoDataFrame:
    """Sum 10 x 10 blocks into 1 km cells; keep cells with people."""
    p = np.where(pop == NODATA, 0, pop)
    rows, cols = p.shape[0] // 10, p.shape[1] // 10
    km = p[:rows * 10, :cols * 10].reshape(rows, 10, cols, 10).sum(axis=(1, 3))
    r, c = np.nonzero(km >= 0.5)
    x = transform.c + c * 1000
    y = transform.f - (r + 1) * 1000
    g = gpd.GeoDataFrame({
        "grid_id": [f"CRS3035RES1000mN{int(n)}E{int(e)}" for n, e in zip(y, x)],
        "population": km[r, c].round(1),
    }, geometry=[box(a, b, a + 1000, b + 1000) for a, b in zip(x, y)], crs=CRS)
    g["density_km2"] = g.population  # 1 km² cells
    return g


def main() -> None:
    outline = gpd.read_file(GPKG, layer="euskal_herria").to_crs(CRS)
    pop, transform = warp_to_laea(outline)
    OUT.mkdir(parents=True, exist_ok=True)
    write_cog(pop, transform, OUT / "ghs_pop_2020_100m.tif")

    g = grid_1km(pop, transform)
    t = gpd.read_file(GPKG, layer="territories").to_crs(CRS)
    # each cell goes to the territory holding its centre (coast/border cells: the nearest)
    centres = gpd.GeoDataFrame(geometry=g.geometry.centroid, crs=CRS)
    nearest = centres.sjoin_nearest(t[["id", "geometry"]], how="left")
    g["territory_id"] = nearest[~nearest.index.duplicated()]["id"].values
    out = OUT / "ghs_pop_2020_1km.gpkg"
    out.unlink(missing_ok=True)
    g.to_file(out, layer="population_grid_1km", driver="GPKG")

    total = pop[pop != NODATA].sum()
    print(f"100 m raster: {pop.shape[1]} x {pop.shape[0]} cells, {total:,.0f} people")
    print(f"1 km grid: {len(g)} cells, {g.population.sum():,.0f} people, max {g.population.max():,.0f}/km²")
    official = t.set_index("id").population
    ghsl = g.groupby("territory_id").population.sum()
    print((ghsl / official).round(3).rename("GHSL 2020 / official").to_string())


if __name__ == "__main__":
    main()
