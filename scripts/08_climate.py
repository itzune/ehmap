"""Climate change in Euskal Herria from ERA5-Land monthly means, 1950-2025 (CC BY 4.0).

ERA5-Land (Muñoz-Sabater et al. 2021, doi:10.24381/cds.68d2bb30) is one reanalysis grid
(0.1°, about 9 km) that covers both sides of the border, so there is no seam between the
Spanish and French national grids. It is a model constrained by observations, not a set of
stations: its temperatures are reliable, its precipitation trends less so. The official
station records (Météo-France, AEMET, Euskalmet) are the cross-check.

Download needs a Copernicus Climate Data Store account, its key in ~/.cdsapirc, and the
dataset licence accepted on the CDS website.

Changes made to the source (as CC BY 4.0 asks us to indicate): monthly values aggregated to
years, sea cells filled from the nearest land cell, resampled bilinearly to 250 m in ETRS89 /
UTM 30N (EPSG:25830), clipped to Euskal Herria and averaged over areas.

Periods: the WMO climate normals 1961-1990 (reference) and 1991-2020 (current).

Outputs (dist/climate/):
  temperature_change.tif            °C, 1991-2020 mean minus 1961-1990 mean (250 m)
  precipitation_change.tif          %, the same for annual precipitation
  climate_by_municipality.csv       normals of both periods and their change, per municipality
  station_check.csv                 the change measured at Météo-France stations vs ERA5-Land
  climate_annual.csv                yearly values per territory, watershed side and all of
                                    Euskal Herria: temperature, precipitation, evaporation,
                                    soil moisture, snow cover, and anomalies vs 1961-1990
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "era5land"
GPKG = ROOT / "dist" / "euskal_herria.gpkg"
BASINS = ROOT / "dist" / "elevation" / "drainage_basins.gpkg"
OUT = ROOT / "dist" / "climate"
CRS = "EPSG:25830"
RES = 250
YEARS = range(1950, 2026)
REF, NOW = (1961, 1990), (1991, 2020)
AREA = [43.6, -3.6, 41.8, -0.6]  # N, W, S, E: Euskal Herria with a margin
VARIABLES = {  # CDS name: (short name in the file, our name)
    "2m_temperature": ("t2m", "temperature_c"),
    "total_precipitation": ("tp", "precipitation_mm"),
    "total_evaporation": ("e", "evaporation_mm"),
    "volumetric_soil_water_layer_1": ("swvl1", "soil_moisture"),
    "snow_cover": ("snowc", "snow_cover_pct"),
}


def download() -> None:
    import cdsapi
    RAW.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client(quiet=True, progress=False)
    for var in VARIABLES:
        out = RAW / f"monthly_{var}.nc"
        if out.exists():
            continue
        print("downloading", var)
        client.retrieve("reanalysis-era5-land-monthly-means", {
            "product_type": ["monthly_averaged_reanalysis"], "variable": [var],
            "year": [str(y) for y in YEARS], "month": [f"{m:02d}" for m in range(1, 13)],
            "time": ["00:00"], "area": AREA, "data_format": "netcdf", "download_format": "unarchived",
        }, str(out))


def annual(var: str) -> xr.DataArray:
    """Yearly values on the ERA5-Land grid, in the units of the output tables."""
    short, name = VARIABLES[var]
    da = xr.open_dataset(RAW / f"monthly_{var}.nc")[short].rename(valid_time="time")
    if short == "t2m":
        da = da - 273.15
    elif short in ("tp", "e"):
        # monthly means of daily accumulations in metres: × days in the month × 1000 = mm.
        # Evaporation is negative (towards the atmosphere) in ECMWF's convention.
        da = da * da.time.dt.days_in_month * 1000 * (-1 if short == "e" else 1)
        return da.groupby("time.year").sum(min_count=12).rename(name)
    return da.groupby("time.year").mean().rename(name)


def fill_sea(a: np.ndarray) -> np.ndarray:
    """Sea cells take the value of the nearest land cell, so coastal areas keep a value."""
    from scipy.ndimage import distance_transform_edt
    nan = np.isnan(a)
    if not nan.any():
        return a
    idx = distance_transform_edt(nan, return_distances=False, return_indices=True)
    return a[tuple(idx)]


class Grid:
    """The 250 m EPSG:25830 grid over Euskal Herria and the area rasters on it."""

    def __init__(self, outline: gpd.GeoDataFrame):
        x0, y0, x1, y1 = np.round(outline.to_crs(CRS).total_bounds / 1000) * 1000 + [-1000, -1000, 1000, 1000]
        self.transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
        self.shape = (int((y1 - y0) / RES), int((x1 - x0) / RES))

    def warp(self, da: xr.DataArray) -> np.ndarray:
        """Bilinear resampling of a (year, lat, lon) grid, one band per year."""
        lat, lon = da.latitude.values, da.longitude.values
        dx, dy = lon[1] - lon[0], lat[0] - lat[1]
        src_t = rasterio.Affine(dx, 0, lon[0] - dx / 2, 0, -dy, lat[0] + dy / 2)
        values = da.values.reshape(-1, len(lat), len(lon))
        out = np.full((len(values), *self.shape), np.nan, dtype="float32")
        for i, band in enumerate(values):
            reproject(fill_sea(band.astype("float32")), out[i], src_transform=src_t, src_crs="EPSG:4326",
                      dst_transform=self.transform, dst_crs=CRS, resampling=Resampling.bilinear)
        return out

    def zones(self, gdf: gpd.GeoDataFrame) -> np.ndarray:
        """Each cell's zone index (row number of gdf), -1 outside every zone."""
        shapes = ((g, i) for i, g in enumerate(gdf.to_crs(CRS).geometry))
        return rasterize(shapes, self.shape, transform=self.transform, fill=-1, dtype="int32")

    def write(self, a: np.ndarray, path: Path, description: str) -> None:
        profile = dict(driver="COG", width=self.shape[1], height=self.shape[0], count=1, dtype="float32",
                       crs=CRS, transform=self.transform, nodata=np.nan, compress="DEFLATE",
                       predictor=3)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(a.astype("float32"), 1)
            dst.set_band_description(1, description)
            dst.update_tags(source="ERA5-Land monthly means (Copernicus C3S/ECMWF), doi:10.24381/cds.68d2bb30",
                            licence="CC BY 4.0", periods=f"{NOW[0]}-{NOW[1]} minus {REF[0]}-{REF[1]}")


def zonal_mean(cube: np.ndarray, zones: np.ndarray, n: int) -> np.ndarray:
    """Mean of every band over each zone: an array of shape (n zones, bands)."""
    flat = cube.reshape(len(cube), -1)
    z = zones.ravel()
    ok = z >= 0
    counts = np.bincount(z[ok], minlength=n)
    sums = np.stack([np.bincount(z[ok], weights=b[ok], minlength=n) for b in flat], axis=1)
    with np.errstate(invalid="ignore"):
        return sums / counts[:, None]


def period(years: np.ndarray, p: tuple[int, int]) -> np.ndarray:
    return (years >= p[0]) & (years <= p[1])


# Météo-France stations in Iparralde with records over both normals (Licence Ouverte 2.0)
STATIONS = {64189001: "Socoa (Ziburu)", 64024001: "Biarritz", 64092002: "Banca"}


def station_check(temperature: xr.DataArray, precipitation: xr.DataArray) -> pd.DataFrame:
    """The change between the normals at each station, measured and in ERA5-Land.

    A station year counts only with all 12 months; a normal needs at least 25 such years.
    ERA5-Land is read at the station by bilinear interpolation.
    """
    raw = ROOT / "data" / "raw" / "meteofrance"
    d = pd.concat(pd.read_csv(p, sep=";", usecols=["NUM_POSTE", "AAAAMM", "TM", "RR"])
                  for p in sorted(raw.glob("MENSQ_64_*.csv.gz")))
    d = d[d.NUM_POSTE.isin(STATIONS)]
    d["year"] = d.AAAAMM // 100
    meta = pd.read_csv(sorted(raw.glob("MENSQ_64_previous-*.csv.gz"))[0], sep=";",
                       usecols=["NUM_POSTE", "LAT", "LON", "ALTI"]).drop_duplicates("NUM_POSTE").set_index("NUM_POSTE")
    rows = []
    for num, name in STATIONS.items():
        s = d[d.NUM_POSTE == num]
        lat, lon = meta.loc[num, "LAT"], meta.loc[num, "LON"]
        for col, da, how in (("TM", temperature, "mean"), ("RR", precipitation, "sum")):
            y = s.groupby("year")[col].agg([how, "count"])
            y = y[y["count"] == 12][how]
            land = xr.apply_ufunc(fill_sea, da, input_core_dims=[["latitude", "longitude"]],
                                  output_core_dims=[["latitude", "longitude"]], vectorize=True)
            model = land.interp(latitude=lat, longitude=lon).to_series()
            for src, series in (("station", y), ("era5land", model)):
                a, b = series.loc[REF[0]:REF[1]], series.loc[NOW[0]:NOW[1]]
                if min(len(a), len(b)) < 25:
                    continue
                rows.append({"station": name, "id": num, "altitude_m": meta.loc[num, "ALTI"],
                             "variable": "temperature_c" if col == "TM" else "precipitation_mm",
                             "source": src, "normal_1961_1990": a.mean(), "normal_1991_2020": b.mean(),
                             "change": b.mean() - a.mean(), "years": f"{len(a)}+{len(b)}"})
    return pd.DataFrame(rows).round(2)


def main() -> None:
    download()
    OUT.mkdir(parents=True, exist_ok=True)
    munis = gpd.read_file(GPKG, layer="municipalities")
    terrs = gpd.read_file(GPKG, layer="territories")
    outline = gpd.read_file(GPKG, layer="euskal_herria")
    sides = gpd.read_file(BASINS, layer="basins")
    grid = Grid(outline)

    inside = grid.zones(outline) == 0
    zm, zt, zs = grid.zones(munis), grid.zones(terrs), grid.zones(sides)
    # municipalities smaller than a cell get the cell under their representative point
    pts = munis.to_crs(CRS).representative_point()
    rows, cols = rasterio.transform.rowcol(grid.transform, pts.x, pts.y)

    check = station_check(annual("2m_temperature"), annual("total_precipitation"))
    check.to_csv(OUT / "station_check.csv", index=False)
    print(check.to_string(index=False))

    tables, muni_cols = [], {}
    for var in VARIABLES:
        da = annual(var)
        name, years = da.name, da.year.values
        cube = grid.warp(da)
        ref, now = cube[period(years, REF)].mean(0), cube[period(years, NOW)].mean(0)

        # yearly series per area
        for label, zones, gdf, key in (("territory", zt, terrs, "id"), ("side", zs, sides, "side")):
            means = zonal_mean(cube, zones, len(gdf))
            for i, area in enumerate(gdf[key]):
                tables.append(pd.DataFrame({"area_type": label, "area": area, "year": years,
                                            "variable": name, "value": means[i]}))
        whole = np.nanmean(cube[:, inside], axis=1)
        tables.append(pd.DataFrame({"area_type": "euskal_herria", "area": "EH", "year": years,
                                    "variable": name, "value": whole}))

        # the two normals per municipality
        for tag, a in (("1961_1990", ref), ("1991_2020", now)):
            m = zonal_mean(a[None], zm, len(munis))[:, 0]
            small = np.isnan(m)
            m[small] = a[np.array(rows)[small], np.array(cols)[small]]
            muni_cols[f"{name}_{tag}"] = m

        if name == "temperature_c":
            grid.write(np.where(inside, now - ref, np.nan), OUT / "temperature_change.tif",
                       "Mean annual temperature change, °C (1991-2020 minus 1961-1990)")
        if name == "precipitation_mm":
            grid.write(np.where(inside, 100 * (now - ref) / ref, np.nan), OUT / "precipitation_change.tif",
                       "Annual precipitation change, % (1991-2020 vs 1961-1990)")

    annual_df = pd.concat(tables)
    ref_mean = (annual_df[annual_df.year.between(*REF)]
                .groupby(["area_type", "area", "variable"]).value.mean().rename("ref"))
    annual_df = annual_df.join(ref_mean, on=["area_type", "area", "variable"])
    annual_df["anomaly"] = annual_df.value - annual_df.ref
    annual_df = annual_df.drop(columns="ref")
    annual_df[["value", "anomaly"]] = annual_df[["value", "anomaly"]].round(3)
    annual_df.to_csv(OUT / "climate_annual.csv", index=False)

    m = munis[["code", "name", "name_eu", "territory_id"]].copy()
    for k, v in muni_cols.items():
        m[k] = v
    m["temperature_change_c"] = m.temperature_c_1991_2020 - m.temperature_c_1961_1990
    m["precipitation_change_pct"] = 100 * (m.precipitation_mm_1991_2020 / m.precipitation_mm_1961_1990 - 1)
    m.round(3).to_csv(OUT / "climate_by_municipality.csv", index=False)

    # a short report
    eh = annual_df[annual_df.area_type != "municipality"]
    for (atype, area), g in eh[eh.variable == "temperature_c"].groupby(["area_type", "area"]):
        y = g.set_index("year").value
        print(f"{atype:13} {area:14} T {y.loc[REF[0]:REF[1]].mean():5.2f} → {y.loc[NOW[0]:NOW[1]].mean():5.2f} °C"
              f"   2016-2025 {y.loc[2016:2025].mean():5.2f}")
    for (atype, area), g in eh[eh.variable == "precipitation_mm"].groupby(["area_type", "area"]):
        y = g.set_index("year").value
        print(f"{atype:13} {area:14} P {y.loc[REF[0]:REF[1]].mean():6.0f} → {y.loc[NOW[0]:NOW[1]].mean():6.0f} mm"
              f"   2016-2025 {y.loc[2016:2025].mean():6.0f}")


if __name__ == "__main__":
    main()
