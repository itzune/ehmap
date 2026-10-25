"""River flow in Euskal Herria since the 1960s: is less water reaching the rivers?

Daily flows of gauges with long records and little upstream regulation:
  - France: Hub'Eau hydrométrie (Hydroportail / HYDRO, OFB), Licence Ouverte Etalab:
    "librement et gratuitement utilisables et réutilisables, y compris dans un but
    commercial", citing the author.
  - Spain: Anuario de Aforos (ROEA, CEDEX for MITECO), edition 2021-22, downloaded from
    MITECO, whose conditions allow free use "siempre que se mencione al Ministerio":
    Fuente: © Ministerio para la Transición Ecológica y el Reto Demográfico. The Spanish
    series end in September 2022 (water year 2022).

Indicators per year (complete only, 95% of the days): mean flow of the water year
(October-September), of July-September and of September-November, and the lowest 7-day
mean of June-December. Changes are against 1971-1990, the reference every gauge covers (the
1960s were wet, so starting there would exaggerate the decline). Trends: Kendall's tau and
Sen's slope over the complete years from 1961. Breaks: Pettitt's test on each gauge's yearly
flow relative to the other gauges of its side.

"Core" gauges are the near-natural ones: forested headwaters, no large dam, few users.
The others are kept for reference with a note: abstractions, regulated low flows, a joined
record or a step in the series.

Outputs (dist/rivers/):
  river_gauges.gpkg        the gauges, their changes and trends (layer river_gauges), and the
                           area draining to each gauge, traced on the Copernicus DEM with
                           GeoLibre (layer catchments; nested catchments keep only the part
                           not drained by an upstream gauge)
  river_flow_yearly.csv    yearly indicators per gauge, m³/s
  river_flow_pooled.csv    the gauges of a group pooled, each as % of its 1971-2020 mean
"""
import io
import json
import time
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "rivers"
OUT = ROOT / "dist" / "rivers"
UA = "ehmap (https://github.com/itzune/ehmap)"
HUBEAU = ("https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?code_entite={}&grandeur_hydro_elab=QmnJ"
          "&date_debut_obs_elab=1900-01-01&size=20000&format=json")
MITECO = ("https://www.miteco.gob.es/content/dam/miteco/es/agua/temas/evaluacion-de-los-recursos-hidricos/"
          "sistema-informacion-anuario-aforos/Anuario-21-22-csv.zip")
REF = (1971, 1990)

# key: (river, gauge, side, source, codes (joined in order), core, note)
GAUGES = {
    "nive_aldudes": ("Nive des Aldudes", "Baigorri", "biscay", "Hub'Eau", ["Q916461001"], True, ""),
    "nive": ("Errobi / Nive", "Itsasu + Kanbo", "biscay", "Hub'Eau", ["Q930251001", "Q931251001"], True,
             "Itsasu (1967-1999) joined to Kanbo (1999-), same catchment, no overlap"),
    "bidouze": ("Bidouze", "Donapaleu", "biscay", "Hub'Eau", ["Q803251001"], True, ""),
    "saison": ("Uhaitza / Saison", "Maule", "biscay", "Hub'Eau", ["Q732252002", "Q732252001"], False,
               "low flows influenced by hydropower; two stations joined in 2007"),
    "bidasoa": ("Bidasoa", "Endarlatsa", "biscay", "MITECO", [1106], False,
                "step in low flows from 2013 (environmental flows or a new rating)"),
    "ibaizabal": ("Ibaizabal", "Lemoa", "biscay", "MITECO", [1163], False, "urban and industrial catchment"),
    "salazar": ("Zaraitzu / Salazar", "Aspurtz", "mediterranean", "MITECO", [9064], True, ""),
    "ulzama": ("Ultzama", "Olabe", "mediterranean", "MITECO", [9067], True, ""),
    "erro": ("Erro", "Urrotz", "mediterranean", "MITECO", [9079], True, ""),
    "arga_eugi": ("Arga", "Eugi", "mediterranean", "MITECO", [9152], True, "upstream of the Eugi dam"),
    "ayuda": ("Ayuda", "Berantevilla", "mediterranean", "MITECO", [9075], True, ""),
    "ega_estella": ("Ega", "Lizarra / Estella", "mediterranean", "MITECO", [9071], False, "irrigation abstractions"),
    "ega_maranon": ("Ega", "Marañón", "mediterranean", "MITECO", [9006], False,
                    "low flows fall to near zero: abstractions likely; record ends 2017-2019"),
    "onsella": ("Onsella", "Zangoza / Sangüesa", "mediterranean", "MITECO", [9073], False,
                "agricultural catchment, mostly in Aragon; step around 1988"),
    "zidacos": ("Zidacos", "Garinoain", "mediterranean", "MITECO", [9086], False,
                "agricultural catchment; step around 1992"),
}
INDICATORS = {"annual": "mean flow of the water year (Oct-Sep)", "jas": "mean flow of July-September",
              "son": "mean flow of September-November", "q7min": "lowest 7-day mean flow of June-December"}


def catchments(gauges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The land draining to each gauge, from the DEM-derived flow directions of 05_rivers.py."""
    import importlib
    import sys
    import tempfile
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape
    sys.path.insert(0, str(ROOT / "scripts"))
    hydro = importlib.import_module("05_rivers")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        hydro.regional_dem(t / "dem.tif")
        hydro.geolibre("breach_depressions_least_cost", dem=t / "dem.tif", output=t / "breached.tif", fill_deps="true")
        hydro.geolibre("d8_pointer", dem=t / "breached.tif", output=t / "pntr.tif")
        hydro.geolibre("d8_flow_accum", input=t / "breached.tif", output=t / "accum.tif", out_type="cells")
        hydro.geolibre("extract_streams", flow_accumulation=t / "accum.tif", output=t / "streams.tif",
                       threshold=10e6 / hydro.HYDRO_RES ** 2)   # streams draining 10 km² or more
        pts = gauges[["key", "geometry"]].to_crs(hydro.CRS).reset_index(drop=True)
        pts["fid"] = np.arange(1, len(pts) + 1)
        pts.to_file(t / "gauges.shp")
        hydro.geolibre("jenson_snap_pour_points", pour_pts=t / "gauges.shp", streams=t / "streams.tif",
                       snap_dist=1500, output=t / "snapped.shp")
        hydro.geolibre("watershed", d8_pntr=t / "pntr.tif", pour_pts=t / "snapped.shp", output=t / "sheds.tif")
        with rasterio.open(t / "sheds.tif") as r:
            sheds = r.read(1)
            polys = [(shape(g), int(v)) for g, v in shapes(sheds.astype("int32"), mask=(sheds > 0) & (sheds != r.nodata),
                                                          transform=r.transform)]
    p = gpd.GeoDataFrame({"value": [v for _, v in polys]}, geometry=[g for g, _ in polys], crs=hydro.CRS)
    p = p.dissolve("value").reset_index()
    # the watershed tool numbers areas by the pour points' order
    p["key"] = p.value.map(dict(zip(range(1, len(pts) + 1), pts.key)))
    p["traced_km2"] = (p.area / 1e6).round(1)
    return p[["key", "traced_km2", "geometry"]].to_crs(4326)


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=600) as r:
        return r.read()


def download() -> None:
    hub = RAW / "hubeau"
    hub.mkdir(parents=True, exist_ok=True)
    codes = [c for g in GAUGES.values() if g[3] == "Hub'Eau" for c in g[4]]
    for code in codes:
        out = hub / f"{code}_QmnJ.json"
        if out.exists():
            continue
        rows, url = [], HUBEAU.format(code)
        while url:
            page = json.loads(get(url))
            rows += page["data"]
            url = page.get("next") if page["data"] else None
            time.sleep(1.5)
        out.write_text(json.dumps(rows))
        print("Hub'Eau", code, len(rows))
    if not (hub / "referentiel_stations_dep64.json").exists():
        url = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_departement=64&size=1000&format=json"
        (hub / "referentiel_stations_dep64.json").write_text(json.dumps(json.loads(get(url))["data"]))
    zpath = RAW / "miteco" / "Anuario-21-22-csv.zip"
    if not zpath.exists():
        zpath.parent.mkdir(parents=True, exist_ok=True)
        zpath.write_bytes(get(MITECO))
        print("MITECO", zpath.stat().st_size)


def series() -> tuple[dict[str, pd.Series], dict[str, tuple[float, float, float]]]:
    """Daily flow (m³/s) per gauge, and (lon, lat, catchment km²)."""
    hub = RAW / "hubeau"
    data = json.loads((hub / "referentiel_stations_dep64.json").read_text())
    ref = {s["code_station"]: s for s in (data["data"] if isinstance(data, dict) else data)}
    sites = {}
    sites_file = hub / "referentiel_sites_dep64.json"
    if sites_file.exists():
        data = json.loads(sites_file.read_text())
        sites = {s["code_site"]: s for s in (data.get("data", data) if isinstance(data, dict) else data)}
    z = zipfile.ZipFile(RAW / "miteco" / "Anuario-21-22-csv.zip")
    flows, places = {}, {}
    for basin in ("EBRO", "CANTABRICO"):
        est = pd.read_csv(io.BytesIO(z.read(f"{basin}/estaf.csv")), sep=";", encoding="latin-1").set_index("indroea")
        q = pd.read_csv(io.BytesIO(z.read(f"{basin}/afliq.csv")), sep=";", encoding="latin-1",
                        usecols=["indroea", "fecha", "caudal"]).dropna(subset=["caudal"])
        for key, (_, _, _, src, codes, _, _) in GAUGES.items():
            if src != "MITECO" or codes[0] not in est.index:
                continue
            s = q[q.indroea == codes[0]]
            s = pd.Series(s.caudal.astype(float).values, index=pd.to_datetime(s.fecha, format="%d/%m/%Y"))
            flows[key] = s[~s.index.duplicated()].sort_index()
            e = est.loc[codes[0]]
            pt = gpd.GeoSeries(gpd.points_from_xy([e.xetrs89], [e.yetrs89]), crs=25830).to_crs(4326)[0]
            places[key] = (pt.x, pt.y, float(e.suprest))
    for key, (_, _, _, src, codes, _, _) in GAUGES.items():
        if src != "Hub'Eau":
            continue
        parts = []
        for code in codes:
            d = pd.DataFrame(json.loads((hub / f"{code}_QmnJ.json").read_text()))
            parts.append(pd.Series(d.resultat_obs_elab.astype(float).values / 1000,   # L/s → m³/s
                                   index=pd.to_datetime(d.date_obs_elab)).sort_index())
        s = parts[0]
        for later in parts[1:]:   # the older station until the newer one starts
            s = pd.concat([s[s.index < later.index.min()], later])
        flows[key] = s
        st = ref[codes[-1]]
        area = sites.get(st.get("code_site"), {}).get("surface_bv", np.nan)
        places[key] = (st["longitude_station"], st["latitude_station"], area)
    return flows, places


def indicators(s: pd.Series) -> pd.DataFrame:
    """Yearly indicators, each only when 95% of its days have a value."""
    full = s[s >= 0].asfreq("D")
    rows = {}
    for y in range(1955, 2027):
        r = {}
        windows = {"annual": (f"{y - 1}-10-01", f"{y}-09-30", 365), "jas": (f"{y}-07-01", f"{y}-09-30", 92),
                   "son": (f"{y}-09-01", f"{y}-11-30", 91)}
        for name, (a, b, n) in windows.items():
            w = full[a:b]
            if w.notna().sum() >= 0.95 * n:
                r[name] = w.mean()
        low = full[f"{y}-06-01":f"{y}-12-31"]
        if low.notna().sum() >= 0.95 * 214:
            r["q7min"] = low.rolling(7, min_periods=7).mean().min()
        rows[y] = r
    return pd.DataFrame.from_dict(rows, orient="index", columns=list(INDICATORS)).rename_axis("year")


def pettitt(x: np.ndarray) -> tuple[int, float]:
    n = len(x)
    u = np.array([np.sign(x[:t + 1, None] - x[None, t + 1:]).sum() for t in range(n - 1)])
    k = np.abs(u).max()
    return int(np.abs(u).argmax()), float(min(1, 2 * np.exp(-6 * k ** 2 / (n ** 3 + n ** 2))))


def pooled(ind: dict[str, pd.DataFrame], keys: list[str], v: str) -> pd.Series:
    """Mean of the gauges, each as % of its 1971-2020 mean; years with 70% of them."""
    p = pd.DataFrame({k: 100 * ind[k][v] / ind[k][v].loc[1971:2020].mean() for k in keys}).loc[1961:]
    return p.mean(axis=1)[p.notna().sum(axis=1) >= 0.7 * len(keys)]


def main() -> None:
    download()
    OUT.mkdir(parents=True, exist_ok=True)
    flows, places = series()
    ind = {k: indicators(s) for k, s in flows.items()}
    pd.concat(ind, names=["gauge"]).round(4).to_csv(OUT / "river_flow_yearly.csv")

    rows = []
    for key, (river, gauge, side, src, codes, core, note) in GAUGES.items():
        r = {"key": key, "river": river, "gauge": gauge, "side": side, "source": src,
             "codes": "+".join(map(str, codes)), "core": core, "note": note,
             "catchment_km2": places[key][2], "first_year": int(flows[key].index.year.min()),
             "last_year": int(flows[key].index.year.max())}
        for v in INDICATORS:
            x = ind[key][v].dropna().loc[1961:]
            base = x.loc[REF[0]:REF[1]].mean()
            r[f"{v}_1971_1990_m3s"] = round(base, 3)
            r[f"{v}_change_1991_2020_pct"] = round(100 * (x.loc[1991:2020].mean() / base - 1), 1)
            recent = x.loc[2016:2025]
            r[f"{v}_change_2016_last_pct"] = round(100 * (recent.mean() / base - 1), 1) if len(recent) >= 5 else None
            tau, p = stats.kendalltau(x.index, x.values)
            r[f"{v}_trend_tau"], r[f"{v}_trend_p"] = round(tau, 3), round(p, 5)
            r[f"{v}_sen_pct_decade"] = round(1000 * stats.theilslopes(x.values, x.index)[0] / x.mean(), 2)
        others = [k for k in GAUGES if k != key and GAUGES[k][2] == side]
        ratio = (100 * ind[key]["annual"] / ind[key]["annual"].loc[1971:2020].mean() / pooled(ind, others, "annual")).dropna()
        t, p = pettitt(ratio.values)
        r["break_year"], r["break_p"] = int(ratio.index[t]), round(p, 4)
        rows.append(r)
    t = pd.DataFrame(rows)
    gauges = gpd.GeoDataFrame(t, geometry=gpd.points_from_xy([places[k][0] for k in t.key], [places[k][1] for k in t.key]),
                              crs=4326)
    gauges.to_file(OUT / "river_gauges.gpkg", layer="river_gauges", driver="GPKG")
    sheds = catchments(gauges)
    sheds = sheds.merge(t[["key", "river", "gauge", "core", "catchment_km2", "jas_change_1991_2020_pct",
                           "annual_change_1991_2020_pct"]], on="key")
    sheds.to_file(OUT / "river_gauges.gpkg", layer="catchments", driver="GPKG")
    print(sheds[["river", "gauge", "catchment_km2", "traced_km2"]].to_string(index=False))

    core = [k for k in GAUGES if GAUGES[k][5]]
    groups = {"core": core, "core_biscay": [k for k in core if GAUGES[k][2] == "biscay"],
              "core_mediterranean": [k for k in core if GAUGES[k][2] == "mediterranean"],
              "all": list(GAUGES)}
    pooled_rows = [pd.DataFrame({"group": g, "indicator": v, "pct_of_1971_2020": pooled(ind, keys, v).round(2)})
                   for g, keys in groups.items() for v in INDICATORS]
    pd.concat(pooled_rows).rename_axis("year").reset_index().to_csv(OUT / "river_flow_pooled.csv", index=False)

    pd.set_option("display.width", 220)
    cols = ["river", "gauge", "core", "annual_change_1991_2020_pct", "jas_change_1991_2020_pct",
            "jas_change_2016_last_pct", "q7min_change_1991_2020_pct", "annual_trend_p", "break_year", "break_p"]
    print(t[cols].to_string(index=False))
    for g, keys in groups.items():
        for v in ("annual", "jas", "q7min"):
            x = pooled(ind, keys, v)
            print(f"{g:20} {v:7} 1991-2020 {100 * (x.loc[1991:2020].mean() / x.loc[1971:1990].mean() - 1):+6.1f}%"
                  f"  2016- {100 * (x.loc[2016:].mean() / x.loc[1971:1990].mean() - 1):+6.1f}%"
                  f"  tau {stats.kendalltau(x.index, x.values)[0]:+.2f} p {stats.kendalltau(x.index, x.values)[1]:.4f}")


if __name__ == "__main__":
    main()
