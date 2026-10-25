"""The sea off Euskal Herria: surface temperature, marine heatwaves and sea level.

Sea surface temperature: NOAA OISST v2.1, daily, 0.25° (Huang et al. 2021,
doi:10.1175/JCLI-D-20-0166.1), from September 1981. "The data may be used and redistributed
for free" (NOAA). Mean of the ocean cells of the box 43.25-44.0 °N, 3.5-1.25 °W (the Basque
coast, from Bilbao to Capbreton), weighted by cell area. Downloaded from NOAA's ERDDAP in
5-year chunks; the days ERDDAP's aggregate lacks are filled from NOAA PSL (identical values).

Marine heatwaves (Hobday et al. 2016): at least 5 days above the 90th percentile of the
1982-2011 climatology of that day of the year (11-day window, smoothed over 31 days); gaps
of 2 days or less join two events. With a fixed baseline, a warmer sea counts more
heatwave days: that is what the definition measures.

Sea level: tide gauges of PSMSL, revised local reference (RLR), yearly means (PSMSL 2026,
"Tide Gauge Data", retrieved 19 Oct 2026 from http://www.psmsl.org/data/obtaining/; Holgate
et al. 2013, doi:10.2112/JCOASTRES-D-12-00175.1). They measure the sea against the land; the
land near the coast sinks 0.4-1.2 mm a year (GNSS, Nevada Geodetic Lab), so part of the rise
is the land.

Outputs (dist/sea/):
  sea_annual.csv          yearly box-mean SST, July-September SST and marine heatwave days
  marine_heatwaves.csv    every event: dates, days, peak and cumulative intensity
  tide_gauges.gpkg        the gauges with their sea-level trends
  sea_level_annual.csv    yearly mean sea level per gauge, mm (RLR)
"""
import time
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "sea"
OUT = ROOT / "dist" / "sea"
UA = "ehmap (https://github.com/itzune/ehmap)"
LAT, LON = (43.25, 44.0), (-3.5, -1.25)
ERDDAP = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.nc?sst"
          "[({}T12:00:00Z):1:({}T12:00:00Z)][(0.0)][(43.125):1:(44.125)][(-3.875):1:(-1.125)]")
PSL = ("https://psl.noaa.gov/thredds/ncss/grid/Datasets/noaa.oisst.v2.highres/sst.day.mean.{y}.nc?var=sst"
       "&north=44.125&south=43.125&west=356.125&east=358.875&time_start={a}T00:00:00Z&time_end={b}T23:59:59Z"
       "&accept=netcdf")
BASE = (1982, 2011)
# PSMSL id: name. Santander I and III are one site run by two operators, joined on their overlap.
GAUGES = {1806: "Bilbo / Bilbao", 2338: "Pasaia", 469: "Ziburu / Socoa", 1801: "Bokale / Boucau",
          485: "Santander I", 1807: "Santander III"}
PSMSL = "https://psmsl.org/data/obtaining/rlr.annual.data/{}.rlrdata"


def get(url: str, path: Path) -> None:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=600) as r:
                path.write_bytes(r.read())
            time.sleep(1)
            return
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(60 * (attempt + 1))   # the server asks us to slow down
    raise RuntimeError(f"gave up on {url}")


def download() -> None:
    erd, psl, gauges = RAW / "oisst" / "erddap", RAW / "oisst" / "psl", RAW / "psmsl" / "annual"
    for d in (erd, psl, gauges):
        d.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.today().normalize() - pd.Timedelta(days=16)   # the last two weeks are preliminary
    for y0 in range(1981, today.year + 1, 5):
        out = erd / f"oisst_basque_{y0}.nc"
        if not out.exists():
            a = "1981-09-01" if y0 == 1981 else f"{y0}-01-01"
            b = min(pd.Timestamp(f"{y0 + 4}-12-31"), today).date()
            get(ERDDAP.format(a, b), out)
    have = sea_temperature_cells().time.to_index()   # ERDDAP and any PSL files already on disk
    missing = pd.date_range("1981-09-01", have.max()).difference(have)
    for q in sorted({(d.year, (d.month - 1) // 3) for d in missing}):
        a = pd.Timestamp(year=q[0], month=3 * q[1] + 1, day=1)
        b = a + pd.offsets.QuarterEnd(0)
        out = psl / f"psl_{a.date()}_{b.date()}.nc"
        if not out.exists():
            get(PSL.format(y=q[0], a=a.date(), b=b.date()), out)
    for gid in GAUGES:
        if not (gauges / f"{gid}.rlrdata").exists():
            get(PSMSL.format(gid), gauges / f"{gid}.rlrdata")


def sea_temperature_cells() -> xr.DataArray:
    """Daily SST on the box's cells; days missing from ERDDAP's aggregate come from PSL."""
    def tidy(da):
        da = da.sel(lat=slice(*LAT), lon=slice(*LON))
        t = pd.DatetimeIndex(da.time.values).normalize()
        return da.assign_coords(time=t).isel(time=~pd.Index(t).duplicated())

    files = sorted((RAW / "oisst" / "erddap").glob("*.nc"))
    e = xr.concat([xr.open_dataset(f).sst.isel(zlev=0, drop=True) for f in files], "time")
    e = tidy(e.rename(latitude="lat", longitude="lon"))
    psl = sorted((RAW / "oisst" / "psl").glob("*.nc"))
    if psl:
        p = xr.concat([xr.open_dataset(f).sst for f in psl], "time")
        p = tidy(p.assign_coords(lon=((p.lon + 180) % 360) - 180))
        p = p.sel(lat=e.lat, lon=e.lon, method="nearest").assign_coords(lat=e.lat, lon=e.lon)
        extra = p.time.to_index().difference(e.time.to_index())
        e = xr.concat([e, p.sel(time=extra)], "time").sortby("time")
    return e


def box_mean(cells: xr.DataArray) -> pd.Series:
    ocean = cells.notnull().mean("time") > 0.99
    s = cells.where(ocean).weighted(np.cos(np.deg2rad(cells.lat))).mean(("lat", "lon")).to_series()
    return s.reindex(pd.date_range(s.index[0], s.index[-1])).interpolate(limit=3)


def heatwaves(s: pd.Series, base: tuple[int, int]) -> tuple[pd.DataFrame, pd.Series]:
    """Hobday et al. (2016) marine heatwaves of a daily series: events and a daily mask."""
    t = s.index
    doy = t.dayofyear.values.copy()
    doy[~t.is_leap_year & (t.month > 2)] += 1           # 366-day calendar
    in_base = (t.year >= base[0]) & (t.year <= base[1])
    v = s.values
    clim, thr = np.full(367, np.nan), np.full(367, np.nan)
    for d in range(1, 367):
        window = [((d - 1 + k) % 366) + 1 for k in range(-5, 6)]
        vals = v[in_base & np.isin(doy, window)]
        vals = vals[~np.isnan(vals)]
        clim[d], thr[d] = vals.mean(), np.percentile(vals, 90)

    def smooth(a):
        x = np.concatenate([a[1:]] * 3)
        out = np.full(367, np.nan)
        out[1:] = np.convolve(x, np.ones(31) / 31, mode="same")[366:732]
        return out

    c, th = smooth(clim)[doy], smooth(thr)[doy]
    above = v > th
    runs, i = [], 0
    while i < len(v):
        if above[i]:
            j = i
            while j + 1 < len(v) and above[j + 1]:
                j += 1
            if j - i + 1 >= 5:
                if runs and i - runs[-1][1] - 1 <= 2:
                    runs[-1][1] = j
                else:
                    runs.append([i, j])
            i = j + 1
        else:
            i += 1
    mask = np.zeros(len(v), bool)
    rows = []
    for a, b in runs:
        mask[a:b + 1] = True
        anom = v[a:b + 1] - c[a:b + 1]
        k = int(np.nanargmax(anom))
        category = anom[k] / (th[a + k] - c[a + k])
        rows.append({"start": t[a].date(), "end": t[b].date(), "days": b - a + 1, "peak_date": t[a + k].date(),
                     "peak_sst_c": round(v[a + k], 2), "max_anomaly_c": round(anom[k], 2),
                     "cumulative_c_days": round(np.nansum(anom), 1),
                     "category": ["moderate", "strong", "severe", "extreme"][min(max(int(category), 1), 4) - 1]})
    return pd.DataFrame(rows), pd.Series(mask, index=t)


def rlr(gid: int) -> pd.Series:
    d = pd.read_csv(RAW / "psmsl" / "annual" / f"{gid}.rlrdata", sep=";", header=None, names=["year", "mm", "miss", "flag"])
    return d.set_index(d.year.astype(int)).mm.astype(float).where(lambda x: x > -99999).dropna()


def trend(s: pd.Series) -> tuple[float, float, int]:
    """Least-squares slope (per year) and its standard error, widened for lag-1 autocorrelation."""
    x, y = s.index.values.astype(float), s.values
    if len(s) < 15:
        return np.nan, np.nan, len(s)
    r = stats.linregress(x, y)
    res = y - (r.intercept + r.slope * x)
    rho = max(np.corrcoef(res[:-1], res[1:])[0, 1], 0)
    n_eff = len(s) * (1 - rho) / (1 + rho)
    return r.slope, r.stderr * np.sqrt((len(s) - 2) / max(n_eff - 2, 1)), len(s)


def main() -> None:
    download()
    OUT.mkdir(parents=True, exist_ok=True)
    s = box_mean(sea_temperature_cells())
    events, mask = heatwaves(s, BASE)
    events.to_csv(OUT / "marine_heatwaves.csv", index=False)
    years = s.groupby(s.index.year).count()
    full = years[years >= 365].index
    jas = s[s.index.month.isin([7, 8, 9])]
    annual = pd.DataFrame({"sst_c": s.groupby(s.index.year).mean(), "sst_jul_sep_c": jas.groupby(jas.index.year).mean(),
                           "heatwave_days": mask.groupby(mask.index.year).sum()}).loc[full].round(3)
    annual.rename_axis("year").to_csv(OUT / "sea_annual.csv")

    places = pd.read_csv(RAW / "psmsl" / "filelist_annual.txt", sep=";", header=None,
                         names=["id", "lat", "lon", "name", "coast", "station", "flag"]).set_index("id")
    levels, rows = {}, []
    for gid, name in GAUGES.items():
        a = rlr(gid)
        levels[name] = a
        full_slope, full_se, n = trend(a)
        s93, se93, n93 = trend(a.loc[1993:])
        rows.append({"psmsl_id": gid, "gauge": name, "first_year": int(a.index.min()), "last_year": int(a.index.max()),
                     "years": n, "trend_mm_yr": round(full_slope, 2), "trend_se": round(full_se, 2),
                     "trend_since_1993_mm_yr": round(s93, 2), "trend_since_1993_se": round(se93, 2),
                     "lon": places.loc[gid, "lon"], "lat": places.loc[gid, "lat"]})
    # Santander I and III: one site, two operators; join III onto I by their mean difference
    s1, s3 = levels["Santander I"], levels["Santander III"]
    both = pd.concat([s1, s3], axis=1).dropna()
    santander = s1.combine_first(s3 + (both.iloc[:, 0] - both.iloc[:, 1]).mean())
    sl, se, n = trend(santander)
    sl93, se93, _ = trend(santander.loc[1993:])
    rows = [r for r in rows if not r["gauge"].startswith("Santander")]
    rows.append({"psmsl_id": "485+1807", "gauge": "Santander", "first_year": int(santander.index.min()),
                 "last_year": int(santander.index.max()), "years": n, "trend_mm_yr": round(sl, 2), "trend_se": round(se, 2),
                 "trend_since_1993_mm_yr": round(sl93, 2), "trend_since_1993_se": round(se93, 2),
                 "lon": places.loc[485, "lon"], "lat": places.loc[485, "lat"]})
    t = pd.DataFrame(rows)
    gpd.GeoDataFrame(t.drop(columns=["lon", "lat"]), geometry=gpd.points_from_xy(t.lon, t.lat), crs=4326) \
        .to_file(OUT / "tide_gauges.gpkg", layer="tide_gauges", driver="GPKG")
    levels["Santander"] = santander
    pd.DataFrame(levels).rename_axis("year").round(1).to_csv(OUT / "sea_level_annual.csv")

    sst = annual.sst_c.loc[1982:]
    print(f"SST {sst.loc[1982:1991].mean():.2f} → {sst.loc[2016:2025].mean():.2f} °C, "
          f"trend {10 * trend(sst)[0]:+.2f} °C/decade; warmest {sst.idxmax()}")
    hw = annual.heatwave_days.loc[1982:]
    print(f"heatwave days {hw.loc[1982:1991].mean():.0f} → {hw.loc[2016:2025].mean():.0f} a year; "
          f"max {hw.idxmax()} ({hw.max()})")
    print(t[["gauge", "first_year", "last_year", "years", "trend_mm_yr", "trend_since_1993_mm_yr"]].to_string(index=False))


if __name__ == "__main__":
    main()
