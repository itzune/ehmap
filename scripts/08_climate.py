"""Climate change in Euskal Herria, 1950-2025: temperature from ERA5-Land, rain from stations.

ERA5-Land (Muñoz-Sabater et al. 2021, doi:10.24381/cds.68d2bb30, CC BY 4.0) is one reanalysis
grid (0.1°, about 9 km) that covers both sides of the border, so there is no seam between the
Spanish and French national grids. It is a model constrained by observations, checked here
against the long station records of Météo-France and AEMET:
- temperature agrees (the model is slightly conservative on the coast), so it is published;
- precipitation does not: ERA5-Land has 2023 at about half the normal rain where every long
  station measured 102-118%, and summer drying most stations do not show. Rain is therefore
  published only as measured at the stations (rain_stations.gpkg); the model's rain is used
  only in station_check.csv, to document the disagreement.

Download needs a Copernicus Climate Data Store account, its key in ~/.cdsapirc, and the
dataset licence accepted on the CDS website.

Changes made to the source (as CC BY 4.0 asks us to indicate): monthly values aggregated to
years, sea cells filled from the nearest land cell, resampled bilinearly to 250 m in ETRS89 /
UTM 30N (EPSG:25830), clipped to Euskal Herria and averaged over areas.

Periods: the WMO climate normals 1961-1990 (reference) and 1991-2020 (current).

Outputs (dist/climate/):
  temperature_change.tif            °C, 1991-2020 mean minus 1961-1990 mean (250 m)
  climate_by_municipality.csv       temperature normals of both periods and their change
  climate_annual.csv                yearly temperature per territory, watershed side and all
                                    of Euskal Herria, and its anomaly vs 1961-1990
  station_check.csv                 each long station record next to ERA5-Land at its place
  rain_stations.gpkg                stations with their measured rainfall change, per year and
                                    season (© AEMET; © Météo-France, Licence Ouverte 2.0;
                                    Gobierno de Navarra)
  station_quality.csv               the neighbour test for sudden steps (rain, ET0); failures left out
  water_balance.csv                 yearly rain and evaporative demand (Hargreaves ET0) of a typical
                                    station, 1961-2025, from the same stations every year
  rain_timeline.csv                 10-year rain per station and season, % of its 1996-2025 mean
  rain_timeline_stations.csv        the stations of the timeline
"""
import json
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
    "total_precipitation": ("tp", "precipitation_mm"),  # station check only, see above
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


def annual_temperature() -> xr.DataArray:
    """Yearly mean temperature on the ERA5-Land grid, °C."""
    da = xr.open_dataset(RAW / "monthly_2m_temperature.nc")["t2m"].rename(valid_time="time") - 273.15
    return da.groupby("time.year").mean().rename("temperature_c")


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


# AEMET stations in Hegoalde that may hold records over both normals ("© AEMET", reuse with
# attribution). The API needs a free key (opendata.aemet.es) in ~/.aemet_key.
AEMET_STATIONS = ["1024E", "1082", "1014A", "1014", "1060X", "1069Y", "9087", "9091O", "9091R", "9122I",
                  "9171K", "9218A", "9228T", "9252X", "9262", "9263D", "9283X", "9294E", "9302Y", "1002Y",
                  "1010X", "1021X", "1025A", "1037Y", "1049N", "9995Y"]
AEMET_API = "https://opendata.aemet.es/opendata/api/valores/climatologicos/mensualesanuales/datos"


def download_aemet() -> None:
    """Monthly climatology per station, 1961-2025, in the 3-year chunks the API allows."""
    import time
    import requests
    key_file = Path.home() / ".aemet_key"
    if not key_file.exists():
        print("no ~/.aemet_key: skipping AEMET")
        return
    headers = {"api_key": key_file.read_text().strip(), "User-Agent": "ehmap (https://github.com/itzune/ehmap)"}
    raw = ROOT / "data" / "raw" / "aemet"
    raw.mkdir(parents=True, exist_ok=True)
    for station in AEMET_STATIONS:
        for y0 in [*range(1919, 1961, 3), *range(1961, 2026, 3)]:  # 3-year chunks aligned on 1961
            y1 = min(y0 + 2, 2025)
            out = raw / f"{station}_{y0}_{y1}.json"
            if out.exists():
                continue
            for attempt in range(6):
                try:
                    r = requests.get(f"{AEMET_API}/anioini/{y0}/aniofin/{y1}/estacion/{station}",
                                     headers=headers, timeout=60)
                    meta = r.json()
                    if meta.get("estado") == 404:      # no data for these years
                        rows = []
                        break
                    if meta.get("estado") != 200:
                        raise RuntimeError(meta)
                    rows = requests.get(meta["datos"], timeout=60).json()
                    break
                except Exception as e:  # rate limit (429) or a transient error: wait and retry
                    print(station, y0, "retry:", str(e)[:80])
                    time.sleep(20 * (attempt + 1))
            else:
                raise RuntimeError(f"AEMET {station} {y0}-{y1} failed")
            out.write_text(json.dumps(rows, ensure_ascii=False))
            time.sleep(1.5)
        print("AEMET", station)


# Navarre's manual stations (Government of Navarre with AEMET): daily maximum and minimum
# temperature and rain, one CSV per year, on meteo.navarra.es; locations from IDENA (CC BY 4.0).
NAVARRA = "https://meteo.navarra.es"
NAVARRA_STATIONS = "https://idena.navarra.es/descargas/METEOR_Sym_EstMetManu.zip"


def download_navarra() -> None:
    """Every yearly daily file of the manual stations that report today and began by 1996
    (so they cover the 1996-2025 reference of the timeline)."""
    import re
    import time
    import urllib.parse
    import requests
    raw = ROOT / "data" / "raw" / "navarra"
    raw.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "ehmap (https://github.com/itzune/ehmap)"
    shp = raw / "METEOR_Sym_EstMetManu.zip"
    if not shp.exists():
        shp.write_bytes(session.get(NAVARRA_STATIONS, timeout=60).content)
    for sid in gpd.read_file(f"zip://{shp}").CESTACION:
        out = raw / str(sid)
        if (out / "complete").exists():
            continue
        page = session.get(f"{NAVARRA}/estaciones/descargardatos_estacion.cfm?IDEstacion={sid}", timeout=60).text
        files = {int(y): f for f, y in re.findall(r"'(/_data/[^']*?_((?:19|20)\d\d)(?:_dia)?\.csv)'", page)}
        if not files or min(files) > 1996 or max(files) < 2025:
            continue
        out.mkdir(exist_ok=True)
        for year in sorted(files):
            if year in files and not (out / f"{year}.csv").exists():
                r = session.get(NAVARRA + urllib.parse.quote(files[year]), timeout=60)
                r.raise_for_status()
                (out / f"{year}.csv").write_bytes(r.content)
                time.sleep(0.5)
        (out / "complete").touch()
        print("Navarra", sid)


# Météo-France stations (Licence Ouverte 2.0): every station of département 64 inside
# Euskal Herria is used; these are shown with a cleaner name than Météo-France's
STATIONS = {64189001: "Socoa (Ziburu)", 64024001: "Biarritz", 64092002: "Banca", 64316001: "Larrau",
            64342001: "Licq-Athérey", 64537001: "Trois-Villes"}


def monthly(var: str) -> xr.DataArray:
    """Monthly ERA5-Land values (°C or mm per month), sea cells filled from the nearest land."""
    short = VARIABLES[var][0]
    da = xr.open_dataset(RAW / f"monthly_{var}.nc")[short].rename(valid_time="time")
    # precipitation: monthly means of daily accumulations in metres, × days × 1000 = mm
    da = da - 273.15 if short == "t2m" else da * da.time.dt.days_in_month * 1000
    return xr.apply_ufunc(fill_sea, da, input_core_dims=[["latitude", "longitude"]],
                          output_core_dims=[["latitude", "longitude"]], vectorize=True)


def dms(v: str) -> float:
    """AEMET coordinates, e.g. '431824N' -> 43.3067."""
    d, m, s_ = int(v[:-5]), int(v[-5:-3]), int(v[-3:-1])
    return (d + m / 60 + s_ / 3600) * (-1 if v[-1] in "WS" else 1)


def stations() -> pd.DataFrame:
    """Monthly station records: network, id, name, lat, lon, altitude_m, year, month,
    t (mean temperature), tx and tn (means of the daily maxima and minima), p (rain, mm)."""
    frames = []
    mf = ROOT / "data" / "raw" / "meteofrance"
    d = pd.concat(pd.read_csv(p, sep=";", usecols=["NUM_POSTE", "NOM_USUEL", "LAT", "LON", "ALTI", "AAAAMM", "TM", "TX", "TN", "RR"])
                  for p in sorted(mf.glob("MENSQ_64_*.csv.gz")))
    names = d.NUM_POSTE.map(STATIONS).fillna(d.NOM_USUEL.str.title())
    frames.append(pd.DataFrame({"network": "Météo-France", "id": d.NUM_POSTE.astype(str), "name": names,
                                "lat": d.LAT, "lon": d.LON, "altitude_m": d.ALTI, "year": d.AAAAMM // 100,
                                "month": d.AAAAMM % 100, "t": d.TM, "tx": d.TX, "tn": d.TN, "p": d.RR}))
    raw = ROOT / "data" / "raw" / "aemet"
    if (raw / "inventario.json").exists():
        inv = {i["indicativo"]: i for i in json.loads((raw / "inventario.json").read_text())}
        rows = []
        for f in sorted(raw.glob("*_*_*.json")):
            for r in json.loads(f.read_text()):
                y, m = map(int, r["fecha"].split("-"))
                if m == 13:  # the annual summary row
                    continue
                st = inv[r["indicativo"]]
                p_ = r.get("p_mes")
                rows.append({"network": "AEMET", "id": r["indicativo"], "name": st["nombre"].title(),
                             "lat": dms(st["latitud"]), "lon": dms(st["longitud"]), "altitude_m": float(st["altitud"]),
                             "year": y, "month": m, "t": pd.to_numeric(r.get("tm_mes"), errors="coerce"),
                             "tx": pd.to_numeric(r.get("tm_max"), errors="coerce"),
                             "tn": pd.to_numeric(r.get("tm_min"), errors="coerce"),
                             # "Ip" is a trace of rain, under 0.1 mm
                             "p": 0.0 if p_ == "Ip" else pd.to_numeric(p_, errors="coerce")})
        frames.append(pd.DataFrame(rows))
    nav = ROOT / "data" / "raw" / "navarra"
    if (nav / "METEOR_Sym_EstMetManu.zip").exists():
        meta = gpd.read_file(f"zip://{nav / 'METEOR_Sym_EstMetManu.zip'}").to_crs(4326).set_index("CESTACION")
        for d in sorted(p for p in nav.iterdir() if (p / "complete").exists()):
            st = meta.loc[int(d.name)]
            days = pd.concat(pd.read_csv(f, sep=";", encoding="latin-1", decimal=".", na_values=["", "-"],
                                         usecols=[0, 1, 2, 3], names=["date", "tmax", "tmin", "p"], header=0)
                             for f in sorted(d.glob("*.csv")))
            days["date"] = pd.to_datetime(days.date.str[:10], format="%d/%m/%Y")
            days = days.set_index("date").apply(pd.to_numeric, errors="coerce")
            m = days.resample("MS").agg({"tmax": ["mean", "count"], "tmin": ["mean", "count"], "p": ["sum", "count"]})
            full_p = m[("p", "count")] == m.index.days_in_month          # every day measured
            full_t = ((m[("tmax", "count")] >= m.index.days_in_month - 2)   # at most 2 days missing
                      & (m[("tmin", "count")] >= m.index.days_in_month - 2))
            frames.append(pd.DataFrame({
                "network": "Gobierno de Navarra", "id": d.name, "name": st.NOMBRE_eus,
                "lat": st.geometry.y, "lon": st.geometry.x, "altitude_m": st.ALTITUD,
                "year": m.index.year, "month": m.index.month,
                "t": ((m[("tmax", "mean")] + m[("tmin", "mean")]) / 2).where(full_t).values,
                "tx": m[("tmax", "mean")].where(full_t).values, "tn": m[("tmin", "mean")].where(full_t).values,
                "p": m[("p", "sum")].where(full_p).values}))
    st = pd.concat(frames, ignore_index=True)
    # Navarre's manual stations include AEMET ones (e.g. Pamplona, 9262): keep Navarre's copy,
    # which is the longer record, and drop the AEMET duplicate
    if (nav / "METEOR_Sym_EstMetManu.zip").exists():
        twins = set(meta.loc[[int(i) for i in st[st.network == "Gobierno de Navarra"].id.unique()], "IDAEMET"].dropna())
        st = st[~((st.network == "AEMET") & st.id.isin(twins))]
    # only stations inside Euskal Herria (with 2 km of slack for coastal and border stations)
    outline = gpd.read_file(GPKG, layer="euskal_herria").to_crs(CRS).buffer(2000).iloc[0]
    places = st.drop_duplicates(["network", "id"])
    pts = gpd.GeoSeries(gpd.points_from_xy(places.lon, places.lat), crs=4326).to_crs(CRS)
    keep = set(zip(places.network[pts.within(outline).values], places.id[pts.within(outline).values]))
    return st[[k in keep for k in zip(st.network, st.id)]].reset_index(drop=True)


SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


def summarise(m: pd.DataFrame) -> dict:
    """Normals, changes and recent years from one monthly series (columns year, month, t, p).

    A year counts only with all 12 months, a season with its 3; a normal needs 25 such years.
    December counts with the next year's winter.
    """
    out = {}
    m = m.assign(season=m.month.map(SEASONS), syear=m.year + (m.month == 12))

    def change(v, how, by="year", season=None):
        x = m if season is None else m[m.season == season]
        g = x.dropna(subset=[v]).groupby(by)[v].agg([how, "count"])
        g = g[g["count"] == (12 if season is None else 3)][how]
        a, b = g.loc[REF[0]:REF[1]], g.loc[NOW[0]:NOW[1]]
        return g, (a.mean(), b.mean()) if min(len(a), len(b)) >= 25 else (np.nan, np.nan)

    t, (ta, tb) = change("t", "mean")
    out.update(t_1961_1990=ta, t_1991_2020=tb, t_change=tb - ta)
    p, (pa, pb) = change("p", "sum")
    out.update(p_1961_1990=pa, p_1991_2020=pb, p_change_pct=100 * (pb / pa - 1))
    for se in ("DJF", "MAM", "JJA", "SON"):
        _, (a, b) = change("p", "sum", "syear", se)
        out[f"p_{se.lower()}_change_pct"] = 100 * (b / a - 1)
    for y in (2022, 2023):
        out[f"p_{y}_pct_of_normal"] = 100 * p.get(y, np.nan) / pb if pb == pb else np.nan
    return out


def yearly(st: pd.DataFrame, column: str) -> pd.DataFrame:
    """Yearly totals of a monthly column, complete years only: one column per (network, id)."""
    return (st.dropna(subset=[column]).groupby(["network", "id", "year"])[column].agg(["sum", "count"])
            .query("count == 12")["sum"].unstack([0, 1]).sort_index())


def homogeneity(ann: pd.DataFrame, places: pd.DataFrame, min_step: float) -> pd.DataFrame:
    """Look for a sudden step in each station's yearly series relative to its neighbours.

    A station move or a new instrument shifts one record but not its neighbours; a change of
    climate shifts them all. For each station with 40+ complete years in 1961-2020 and 3+
    neighbours within 35 km, the ratio of its yearly value to the neighbours' median is split
    at the year that best separates two means (8+ years each side). `stat` is that
    difference in standard deviations, scaled by the sample sizes (a two-sample t, maximised
    over the split year). Stations with stat > 3.5 and a step of min_step % or more are left
    out. Steps shared by the whole network cannot be found this way.
    """
    xy = gpd.GeoSeries(gpd.points_from_xy(places.lon, places.lat), crs=4326).to_crs(CRS)
    xy.index = places.index
    rows = []
    for k in ann.columns:
        if ann[k].loc[1961:2020].count() < 40:
            continue
        dist = xy.distance(xy[k]).sort_values()
        near = [n for n in dist.index[1:9] if n in ann.columns and dist[n] < 35000]
        if len(near) < 3:
            continue
        ref = ann[near].median(axis=1)[ann[near].notna().sum(axis=1) >= 2]
        q = (ann[k] / ref).dropna().loc[1950:2025]
        if len(q) < 30:
            continue
        stat, year, step = 0.0, None, None
        for y in q.index[8:-8]:
            a, b = q.loc[:y - 1], q.loc[y:]
            t = abs(b.mean() - a.mean()) / q.std() * np.sqrt(len(a) * len(b) / len(q))
            if t > stat:
                stat, year, step = t, y, 100 * (b.mean() / a.mean() - 1)
        rows.append({"network": k[0], "id": k[1], "station": places.loc[k, "name"], "neighbours": len(near),
                     "years": len(q), "stat": round(stat, 2), "break_year": year, "step_pct": round(step, 1),
                     "excluded": stat > 3.5 and abs(step) >= min_step})
    return pd.DataFrame(rows)


def extraterrestrial_radiation(lat: np.ndarray, month: np.ndarray) -> np.ndarray:
    """Ra on the middle day of each month, MJ m-2 day-1 (FAO-56, equations 21-25)."""
    day = np.array([17, 47, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344])[month - 1]
    phi = np.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * day / 365)
    decl = 0.409 * np.sin(2 * np.pi * day / 365 - 1.39)
    ws = np.arccos(-np.tan(phi) * np.tan(decl))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.sin(ws))


def add_et0(st: pd.DataFrame) -> pd.DataFrame:
    """Monthly reference evapotranspiration, mm, by Hargreaves (FAO-56, equation 52).

    ET0 = 0.0023 · (T + 17.8) · √(Tmax − Tmin) · Ra, with Ra in mm of water a day. It needs
    only the monthly means of the daily maxima and minima, which all three networks publish.
    It is the water the air could take from well-watered grass, not what really evaporates.
    """
    days = pd.to_datetime(dict(year=st.year, month=st.month, day=1)).dt.days_in_month
    ok = st.tx > st.tn
    ra = extraterrestrial_radiation(st.lat.values, st.month.values) * 0.408   # MJ → mm of water
    et0 = 0.0023 * ((st.tx + st.tn) / 2 + 17.8) * np.sqrt((st.tx - st.tn).clip(lower=0)) * ra * days
    return st.assign(et0=et0.where(ok))


def water_balance(st: pd.DataFrame, places: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Yearly rain and ET0 for Euskal Herria from the stations that have both, 1961-2025.

    Stations need 45+ years with complete rain and ET0 in 1961-2025 and must pass the step test
    for ET0 (5%). The regional value of a year is the mean of the stations' departures from
    their own 1961-2025 means, added to the median of those means: a typical station, built
    from the same stations every year.
    """
    rain, et0 = yearly(st, "p"), yearly(st, "et0")
    quality = homogeneity(et0, places, 5).assign(variable="et0")
    bad = set(zip(quality.network[quality.excluded], quality.id[quality.excluded]))
    both = rain.where(et0.notna()).loc[1961:2025]
    keep = [k for k in both.columns if both[k].count() >= 45 and k in et0.columns and k not in bad]
    out = {}
    for name, table in (("rain_mm", rain), ("et0_mm", et0)):
        t = table[keep].loc[1961:2025].where(both[keep].notna())
        out[name] = (t - t.mean()).mean(axis=1) + t.mean().median()
    wb = pd.DataFrame(out).rename_axis("year")
    wb["stations"] = both[keep].notna().sum(axis=1)
    for name in ("rain_mm", "et0_mm"):
        wb[name.replace("_mm", "_10y_mm")] = wb[name].rolling(10, min_periods=8).mean()
    return wb.round(1).reset_index(), quality


TIMELINE_BASE = (1996, 2025)   # the reference every current station covers
WINDOW = 10                    # years per window of the timeline


def rain_timeline(st: pd.DataFrame) -> pd.DataFrame:
    """10-year mean rain per station, year and season, as % of the station's 1996-2025 mean.

    A season (or year) counts only when complete; the reference needs 20 of its 30, a window
    7 of its 10. Windows are named by their last year: 2025 = 2016-2025.
    """
    rows = []
    for (net, sid), s in st.dropna(subset=["p"]).groupby(["network", "id"]):
        s = s.assign(season=s.month.map(SEASONS), syear=s.year + (s.month == 12))
        series = {"year": s.groupby("year").p.agg(["sum", "count"]).query("count == 12")["sum"]}
        for se in ("DJF", "MAM", "JJA", "SON"):
            g = s[s.season == se].groupby("syear").p.agg(["sum", "count"])
            series[se.lower()] = g[g["count"] == 3]["sum"]
        for key, y in series.items():
            base = y.loc[TIMELINE_BASE[0]:TIMELINE_BASE[1]]
            if len(base) < 20 or base.mean() <= 0:
                continue
            full = y.reindex(range(y.index.min(), 2026))
            mean = full.rolling(WINDOW, min_periods=7).mean()
            for end, v in mean.dropna().items():
                rows.append({"network": net, "id": sid, "season": key, "window_end": end,
                             "pct_of_1996_2025": round(100 * v / base.mean(), 1)})
    return pd.DataFrame(rows)


def station_check(st: pd.DataFrame) -> pd.DataFrame:
    """Each station's record next to ERA5-Land at the same place (bilinear interpolation)."""
    temperature, precipitation = monthly("2m_temperature"), monthly("total_precipitation")
    t_index = pd.to_datetime(temperature.time.values)
    rows = []
    for (net, sid), s in st.groupby(["network", "id"]):
        first = s.iloc[0]
        measured = summarise(s)
        if np.isnan(measured["t_change"]) and np.isnan(measured["p_change_pct"]):
            continue  # record too short for the normals
        model = summarise(pd.DataFrame({
            "year": t_index.year, "month": t_index.month,
            "t": temperature.interp(latitude=first.lat, longitude=first.lon).values,
            "p": precipitation.interp(latitude=first.lat, longitude=first.lon).values}))
        for src, v in (("station", measured), ("era5land", model)):
            rows.append({"network": net, "id": sid, "station": first["name"], "lat": round(first.lat, 4),
                         "lon": round(first.lon, 4), "altitude_m": first.altitude_m, "source": src, **v})
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

    download_aemet()
    download_navarra()
    st = stations()
    places = st.drop_duplicates(["network", "id"]).set_index(["network", "id"])
    quality = homogeneity(yearly(st, "p"), places, 10).assign(variable="rain")
    bad = set(zip(quality.network[quality.excluded], quality.id[quality.excluded]))
    print("left out (step against neighbours):", sorted(quality.station[quality.excluded]))
    st = st[[k not in bad for k in zip(st.network, st.id)]]
    wb, quality_et0 = water_balance(add_et0(st), places)
    wb.to_csv(OUT / "water_balance.csv", index=False)
    pd.concat([quality, quality_et0]).to_csv(OUT / "station_quality.csv", index=False)
    print("water balance from", int(wb.stations.max()), "stations; ET0 left out:",
          sorted(quality_et0.station[quality_et0.excluded]))
    places = st.drop_duplicates(["network", "id"])[["network", "id", "name", "lat", "lon", "altitude_m"]]
    timeline = rain_timeline(st)
    places[places.set_index(["network", "id"]).index.isin(timeline.set_index(["network", "id"]).index.unique())] \
        .to_csv(OUT / "rain_timeline_stations.csv", index=False)
    timeline.to_csv(OUT / "rain_timeline.csv", index=False)
    check = station_check(st)
    check.to_csv(OUT / "station_check.csv", index=False)
    print(check.to_string(index=False))
    rain = check[check.source == "station"].drop(columns=["source", "lat", "lon"])
    rain = gpd.GeoDataFrame(rain, geometry=gpd.points_from_xy(check.loc[rain.index, "lon"],
                                                              check.loc[rain.index, "lat"]), crs=4326)
    rain.to_file(OUT / "rain_stations.gpkg", layer="rain_stations", driver="GPKG")
    (OUT / "precipitation_change.tif").unlink(missing_ok=True)  # withdrawn in v0.5.1

    tables, muni_cols = [], {}
    for da in (annual_temperature(),):
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
    m.round(3).to_csv(OUT / "climate_by_municipality.csv", index=False)

    # a short report
    eh = annual_df[annual_df.area_type != "municipality"]
    for (atype, area), g in eh[eh.variable == "temperature_c"].groupby(["area_type", "area"]):
        y = g.set_index("year").value
        print(f"{atype:13} {area:14} T {y.loc[REF[0]:REF[1]].mean():5.2f} → {y.loc[NOW[0]:NOW[1]].mean():5.2f} °C"
              f"   2016-2025 {y.loc[2016:2025].mean():5.2f}")


if __name__ == "__main__":
    main()
