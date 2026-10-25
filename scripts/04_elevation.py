"""Elevation of Euskal Herria (Copernicus DEM GLO-30) and its peaks (OpenStreetMap).

Inputs (from scripts/00_download.py):
  data/raw/copdem/*.tif      Copernicus DEM GLO-30 tiles, 1 arc-second, EPSG:4326
  data/raw/osm/peaks.json    natural=peak nodes from Overpass
  dist/euskal_herria.gpkg    municipalities, territories and outline

Outputs, kept apart from the CC BY data because their licences differ:
  dist/elevation/copernicus_dem_25m.tif            elevation (m, 0.1 m steps), 25 m, EPSG:25830 (COG)
  dist/elevation/copernicus_dem_50m.tif            lighter version: whole metres (Int16), 50 m
  dist/elevation/elevation_by_municipality.csv     min / mean / max elevation per municipality
  dist/elevation/elevation_by_territory.csv        the same per territory, with its highest point
  dist/osm/peaks.gpkg, dist/osm/peaks.geojson      peaks (natural=peak) inside Euskal Herria (ODbL)
"""
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
GPKG = ROOT / "dist" / "euskal_herria.gpkg"
OUT_DEM = ROOT / "dist" / "elevation"
OUT_OSM = ROOT / "dist" / "osm"
CRS = "EPSG:25830"
RES = 25
NODATA = -9999.0


def build_dem(outline: gpd.GeoDataFrame) -> tuple[np.ndarray, rasterio.Affine]:
    """Mosaic the tiles over Euskal Herria, reproject to UTM 30N at 25 m, clip to the outline."""
    tiles = [rasterio.open(p) for p in sorted((RAW / "copdem").glob("*.tif"))]
    w, s, e, n = outline.buffer(1000).to_crs(4326).total_bounds
    src, src_transform = merge(tiles, bounds=(w, s, e, n))
    src_crs = tiles[0].crs
    for t in tiles:
        t.close()

    x0, y0, x1, y1 = outline.total_bounds
    x0, y0 = np.floor([x0 / RES, y0 / RES]) * RES
    x1, y1 = np.ceil([x1 / RES, y1 / RES]) * RES
    transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
    dem = np.full((int((y1 - y0) / RES), int((x1 - x0) / RES)), NODATA, dtype="float32")
    reproject(src[0], dem, src_transform=src_transform, src_crs=src_crs,
              dst_transform=transform, dst_crs=CRS, dst_nodata=NODATA,
              resampling=Resampling.bilinear)
    dem[geometry_mask(outline.geometry, dem.shape, transform)] = NODATA
    return dem, transform


def write_cog(dem: np.ndarray, transform: rasterio.Affine, path: Path) -> None:
    profile = dict(driver="COG", width=dem.shape[1], height=dem.shape[0], count=1,
                   dtype="float32", crs=CRS, transform=transform, nodata=NODATA,
                   compress="DEFLATE", predictor=3, overview_resampling="average")
    with rasterio.open(path, "w", **profile) as dst:
        # 0.1 m steps compress much better and are far below the DEM's accuracy (a few metres)
        dst.write(np.where(dem == NODATA, NODATA, np.round(dem, 1)).astype("float32"), 1)
        dst.update_tags(1, units="m", source="Copernicus DEM GLO-30 (DSM)",
                        notice=NOTICE_DERIVED)


def write_light(dem: np.ndarray, transform: rasterio.Affine, path: Path) -> None:
    """50 m, whole metres as Int16: small enough for web maps and the RustGIS project."""
    d = np.where(dem == NODATA, np.nan, dem)
    h, w = d.shape[0] // 2, d.shape[1] // 2
    with np.errstate(all="ignore"):
        d50 = np.nanmean(d[:h * 2, :w * 2].reshape(h, 2, w, 2), axis=(1, 3))
    out = np.where(np.isnan(d50), -32768, np.round(d50)).astype("int16")
    profile = dict(driver="COG", width=w, height=h, count=1, dtype="int16", crs=CRS,
                   transform=transform * rasterio.Affine.scale(2), nodata=-32768,
                   compress="DEFLATE", predictor=2, overview_resampling="average")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(1, units="m", source="Copernicus DEM GLO-30 (DSM)", notice=NOTICE_DERIVED)


def zonal(dem: np.ndarray, transform: rasterio.Affine, polys: gpd.GeoDataFrame,
          key: str) -> pd.DataFrame:
    """Min / mean / max elevation and the location of the maximum for each polygon."""
    rows = []
    for k, geom in zip(polys[key], polys.geometry):
        win = from_bounds(*geom.bounds, transform=transform).round_offsets().round_lengths()
        r0, c0 = max(int(win.row_off), 0), max(int(win.col_off), 0)
        sub = dem[r0:r0 + int(win.height) + 1, c0:c0 + int(win.width) + 1]
        sub_t = transform * rasterio.Affine.translation(c0, r0)
        inside = ~geometry_mask([geom], sub.shape, sub_t, all_touched=True) & (sub != NODATA)
        if not inside.any():
            rows.append((k, None, None, None, None, None))
            continue
        vals = np.where(inside, sub, -np.inf)
        r, c = np.unravel_index(np.argmax(vals), vals.shape)
        x, y = sub_t * (c + 0.5, r + 0.5)
        rows.append((k, float(sub[inside].min()), float(sub[inside].mean()),
                     float(sub[inside].max()), x, y))
    df = pd.DataFrame(rows, columns=[key, "elev_min", "elev_mean", "elev_max", "x", "y"])
    return df.round({"elev_min": 1, "elev_mean": 1, "elev_max": 1})


def parse_ele(v: str | None) -> float | None:
    """OSM 'ele' tag in metres ('1234', '1234 m', '1234.5', '1234,5') -> float; else None."""
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*m?", (v or "").strip())
    return float(m.group(1).replace(",", ".")) if m else None


def peaks(territories: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    nodes = json.loads((RAW / "osm" / "peaks.json").read_text())["elements"]
    rows = [{"osm_id": n["id"], "name": n["tags"].get("name"), "name_eu": n["tags"].get("name:eu"),
             "ele": parse_ele(n["tags"].get("ele")),
             "wikidata": n["tags"].get("wikidata"), "lon": n["lon"], "lat": n["lat"]}
            for n in nodes]
    g = gpd.GeoDataFrame(rows, geometry=gpd.points_from_xy([r["lon"] for r in rows],
                                                           [r["lat"] for r in rows]), crs=4326)
    g = g.drop(columns=["lon", "lat"]).to_crs(CRS)
    # many summits sit on a border: territory_id is the territory holding the point (else the
    # nearest within 100 m), territories lists every territory within 100 m ("araba;bizkaia")
    t = territories[["id", "geometry"]]
    near = g.sjoin(t, predicate="dwithin", distance=100, how="inner")
    g = g.loc[near.index.unique()]
    g["territories"] = near.groupby(level=0)["id"].agg(lambda ids: ";".join(sorted(set(ids))))
    nearest = g[["geometry"]].sjoin_nearest(t, how="left")
    g["territory_id"] = nearest[~nearest.index.duplicated()]["id"]
    g["label"] = g.name.where(g.ele.isna(), g.name + " " + g.ele.round().astype("Int64").astype(str))
    # rank: position of the peak among the named peaks of its territory (best over all the
    # territories it touches), 1 = highest
    per = g[g.name.notna() & g.ele.notna()].assign(t=g.territories.str.split(";")).explode("t")
    per["r"] = per.groupby("t").ele.rank(ascending=False, method="first")
    g["rank"] = per.groupby(level=0).r.min().astype("Int64")
    return g.sort_values("ele", ascending=False, na_position="last").reset_index(drop=True)


NOTICE_DERIVED = ("produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus "
                  "Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European "
                  "Union and ESA; all rights reserved")


def main() -> None:
    mun = gpd.read_file(GPKG, layer="municipalities").to_crs(CRS)
    ter = gpd.read_file(GPKG, layer="territories").to_crs(CRS)
    outline = gpd.read_file(GPKG, layer="euskal_herria").to_crs(CRS)

    dem, transform = build_dem(outline)
    OUT_DEM.mkdir(parents=True, exist_ok=True)
    write_cog(dem, transform, OUT_DEM / "copernicus_dem_25m.tif")
    write_light(dem, transform, OUT_DEM / "copernicus_dem_50m.tif")
    valid = dem[dem != NODATA]
    print(f"DEM: {dem.shape[1]} x {dem.shape[0]} cells at {RES} m, "
          f"{valid.min():.0f}-{valid.max():.0f} m, mean {valid.mean():.0f} m")

    zm = zonal(dem, transform, mun, "code").drop(columns=["x", "y"])
    zm = mun[["code", "name_eu", "territory_id"]].merge(zm, on="code")
    zm.to_csv(OUT_DEM / "elevation_by_municipality.csv", index=False)

    zt = zonal(dem, transform, ter, "id")
    hp = gpd.GeoSeries(gpd.points_from_xy(zt.x, zt.y), crs=CRS).to_crs(4326)
    zt = zt.drop(columns=["x", "y"]).assign(highest_lon=hp.x.round(5), highest_lat=hp.y.round(5))
    zt = ter[["id", "name_eu"]].merge(zt, on="id").rename(columns={"id": "territory_id"})
    zt.to_csv(OUT_DEM / "elevation_by_territory.csv", index=False)
    print(zt.to_string(index=False))

    p = peaks(ter)
    OUT_OSM.mkdir(parents=True, exist_ok=True)
    p = p.to_crs(4326)
    for path, driver in ((OUT_OSM / "peaks.gpkg", "GPKG"), (OUT_OSM / "peaks.geojson", "GeoJSON")):
        path.unlink(missing_ok=True)
        p.to_file(path, driver=driver, layer="peaks")
    print(f"\nPeaks inside Euskal Herria: {len(p)} ({p.ele.notna().sum()} with elevation)")
    per = p.dropna(subset=["ele"]).assign(territory=p.territories.str.split(";")).explode("territory")
    top = per.sort_values("ele", ascending=False).groupby("territory").head(3)
    print(top.sort_values(["territory", "ele"], ascending=[True, False])
          [["territory", "name", "ele", "territories"]].to_string(index=False))


if __name__ == "__main__":
    main()
