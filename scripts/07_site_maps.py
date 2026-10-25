"""Render the atlas maps for the website (site/maps/*.webp).

One cartographic style for every map: warm paper, soft multi-directional relief shading,
the territory borders, and labels in the site's typefaces (Fraunces, Source Sans 3).
Colour scales come from site/palette.json, validated with the dataviz palette checks.

Inputs: dist/ (boundaries, population grid, elevation, rivers, forest, climate), data/raw/copdem
(context relief around Euskal Herria) and fonts/.
"""
import json
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from matplotlib import font_manager
from matplotlib import patheffects as pe
from matplotlib.colors import BoundaryNorm, ListedColormap, to_rgb
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = ROOT / "site" / "maps"
PAL = json.loads((ROOT / "site" / "palette.json").read_text())
CRS = "EPSG:25830"
RES = 100          # m per cell of the shaded relief
WIDTH_PX = 2400    # rendered width; a 1200 px version is made for small screens
DPI = 200

# --- fonts --------------------------------------------------------------------------------

def load_fonts(tmp: Path) -> dict[str, str]:
    """Static instances of the variable fonts, registered with matplotlib."""
    specs = {
        "sans": ("SourceSans3.ttf", {"wght": 400}),
        "sans-semi": ("SourceSans3.ttf", {"wght": 600}),
        "sans-italic": ("SourceSans3-Italic.ttf", {"wght": 400}),
        "serif-italic": ("Fraunces-Italic.ttf", {"wght": 400, "opsz": 36, "SOFT": 50, "WONK": 0}),
        "serif": ("Fraunces.ttf", {"wght": 560, "opsz": 72, "SOFT": 50, "WONK": 0}),
    }
    names = {}
    for key, (file, axes) in specs.items():
        font = TTFont(ROOT / "fonts" / file)
        inst = instantiateVariableFont(font, axes)
        # give each instance its own family name so matplotlib can tell them apart
        for rec in inst["name"].names:
            if rec.nameID in (1, 4, 6, 16):
                rec.string = f"ehmap {key}"
        path = tmp / f"{key}.ttf"
        inst.save(path)
        font_manager.fontManager.addfont(str(path))
        names[key] = f"ehmap {key}"
    return names


# --- relief -------------------------------------------------------------------------------

def frame(outline: gpd.GeoDataFrame, margin: float = 0.05) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = outline.total_bounds
    dx, dy = (x1 - x0) * margin, (y1 - y0) * margin
    return x0 - dx, y0 - dy, x1 + dx, y1 + dy


def regional_dem(bounds) -> tuple[np.ndarray, rasterio.Affine]:
    """The DEM over the whole frame (context included) at RES, EPSG:25830; sea = NaN."""
    tiles = [rasterio.open(p) for p in sorted((ROOT / "data/raw/copdem").glob("*.tif"))]
    src, src_t = merge(tiles, res=1 / 1200, resampling=Resampling.average)
    crs = tiles[0].crs
    for t in tiles:
        t.close()
    x0, y0, x1, y1 = bounds
    transform = rasterio.Affine(RES, 0, x0, 0, -RES, y1)
    dem = np.full((int((y1 - y0) / RES), int((x1 - x0) / RES)), np.nan, "float32")
    reproject(src[0].astype("float32"), dem, src_transform=src_t, src_crs=crs,
              dst_transform=transform, dst_crs=CRS, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    dem[dem <= 0.5] = np.nan
    return dem, transform


def hillshade(dem: np.ndarray, z: float = 2.2) -> np.ndarray:
    """Soft multi-directional hillshade in 0..1 (1 = lit), flat areas ~0.8."""
    d = np.nan_to_num(dem, nan=0.0)
    gy, gx = np.gradient(d, RES)
    slope = np.arctan(z * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    alt = np.radians(45)
    shade = np.zeros_like(d)
    # light mostly from the north-west, as on classic relief maps, softened by other azimuths
    for az, w in ((315, 0.5), (270, 0.2), (360, 0.2), (225, 0.1)):
        a = np.radians(az)
        shade += w * (np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(a - aspect))
    return np.clip(shade, 0, 1)


def ramp(colors: list[str], values: np.ndarray, bounds: list[float]) -> np.ndarray:
    """Interpolate a colour ramp (hex list) over values between bounds[0] and bounds[1]."""
    c = np.array([to_rgb(h) for h in colors])
    v = np.nan_to_num(values, nan=bounds[0])
    t = np.clip((v - bounds[0]) / (bounds[1] - bounds[0]), 0, 1) * (len(c) - 1)
    i = np.clip(np.floor(t).astype(int), 0, len(c) - 2)
    f = (t - i)[..., None]
    return c[i] * (1 - f) + c[i + 1] * f


class Base:
    """Shared layers of every map: frame, relief, sea, territory and municipality borders."""

    def __init__(self, fonts: dict[str, str]):
        self.fonts = fonts
        self.ter = gpd.read_file(DIST / "euskal_herria.gpkg", layer="territories").to_crs(CRS)
        self.mun = gpd.read_file(DIST / "euskal_herria.gpkg", layer="municipalities").to_crs(CRS)
        self.outline = gpd.read_file(DIST / "euskal_herria.gpkg", layer="euskal_herria").to_crs(CRS)
        self.bounds = frame(self.outline)
        self.dem, self.t = regional_dem(self.bounds)
        self.shade = hillshade(self.dem)
        self.inside = ~geometry_mask(self.outline.geometry, self.dem.shape, self.t)
        self.sea = np.isnan(self.dem)
        x0, y0, x1, y1 = self.bounds
        self.extent = (x0, x0 + self.dem.shape[1] * RES, y1 - self.dem.shape[0] * RES, y1)

    def figure(self):
        x0, x1, y0, y1 = self.extent
        w_in = WIDTH_PX / DPI
        fig = plt.figure(figsize=(w_in, w_in * (y1 - y0) / (x1 - x0)), dpi=DPI)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_axis_off()
        return fig, ax

    def background(self, ax, inside_rgb: np.ndarray | None = None, relief: float = 1.0):
        """Paper, faint relief outside, pale sea; inside_rgb (H,W,3) is shaded and drawn inside."""
        paper = np.array(to_rgb(PAL["paper"]))
        sh = self.shade[..., None]
        outside = paper * (0.84 + 0.16 * sh)                      # faint context relief
        rgb = np.where(self.sea[..., None], np.array(to_rgb(PAL["sea"])), outside)
        if inside_rgb is not None:
            k = 0.36 * relief
            lit = inside_rgb * ((1 - k) + k * sh) + 0.05 * relief * (sh - 0.5)
            land = (self.inside & ~self.sea)[..., None]          # estuaries keep the sea colour
            rgb = np.where(land, np.clip(lit, 0, 1), rgb)
        ax.imshow(rgb, extent=self.extent, interpolation="bilinear", zorder=0)

    def borders(self, ax, municipalities: bool = True):
        if municipalities:
            self.mun.boundary.plot(ax=ax, color=PAL["ink"], linewidth=0.15, alpha=0.35, zorder=3)
        self.ter.boundary.plot(ax=ax, color=PAL["ink"], linewidth=0.7, alpha=0.75, zorder=4)
        self.outline.boundary.plot(ax=ax, color=PAL["ink"], linewidth=1.0, alpha=0.9, zorder=4)

    def halo(self, w: float = 2.2):
        return [pe.withStroke(linewidth=w, foreground=PAL["paper"], alpha=0.85)]

    def territory_labels(self, ax, size: float = 9.5):
        spots = {"araba": (-2.72, 42.80), "bizkaia": (-2.86, 43.24), "gipuzkoa": (-2.17, 43.12),
                 "nafarroa_garaia": (-1.62, 42.62), "lapurdi": (-1.45, 43.40),
                 "nafarroa_beherea": (-1.18, 43.24), "zuberoa": (-0.92, 43.13)}
        pts = gpd.GeoSeries(gpd.points_from_xy([p[0] for p in spots.values()],
                                               [p[1] for p in spots.values()]), crs=4326).to_crs(CRS)
        names = dict(zip(self.ter.id, self.ter.name_eu))
        for tid, p in zip(spots, pts):
            ax.text(p.x, p.y, " ".join(names[tid].upper()), ha="center", va="center",
                    fontsize=size, fontfamily=self.fonts["sans-semi"], color=PAL["ink"],
                    path_effects=self.halo(2.6), zorder=10)

    def context_labels(self, ax):
        """Sea and neighbouring regions, quietly."""
        pts = {"Bizkaiko golkoa": ((-2.35, 43.52), "sea"), "Kantabria": ((-3.42, 43.20), "land"),
               "Burgos": ((-3.30, 42.55), "land"), "Errioxa": ((-2.45, 42.30), "land"),
               "Aragoi": ((-1.05, 42.15), "land"), "Biarno": ((-0.68, 43.38), "land"),
               "Landak": ((-1.20, 43.66), "land")}
        g = gpd.GeoSeries(gpd.points_from_xy([v[0][0] for v in pts.values()],
                                             [v[0][1] for v in pts.values()]), crs=4326).to_crs(CRS)
        x0, x1, y0, y1 = self.extent
        for (name, (_, kind)), p in zip(pts.items(), g):
            if not (x0 < p.x < x1 and y0 < p.y < y1):
                continue
            if kind == "sea":
                ax.text(p.x, p.y, name, ha="center", va="center", fontsize=12,
                        fontfamily=self.fonts["serif-italic"], color=PAL["water"], zorder=10)
            else:
                ax.text(p.x, p.y, " ".join(name.upper()), ha="center", va="center",
                        fontsize=6.5, fontfamily=self.fonts["sans"], color=PAL["muted"],
                        path_effects=self.halo(2), zorder=10)

    def town_labels(self, ax, names: list[str], size: float = 6.5):
        m = self.mun.set_index("name_eu")
        for n in names:
            p = m.loc[n].geometry.representative_point()
            ax.plot(p.x, p.y, "o", ms=2.4, color=PAL["ink"], zorder=11)
            ax.text(p.x + 1500, p.y + 900, n, fontsize=size, fontfamily=self.fonts["sans-semi"],
                    color=PAL["ink"], path_effects=self.halo(2.2), zorder=11)

    def save(self, fig, name: str, credit: str):
        """credit: the sources of this map, printed in its corner so the image stands alone."""
        fig.text(0.006, 0.006, f"{credit} · {COPDEM_NOTICE} · ehmap, github.com/itzune/ehmap",
                 fontsize=3.6, fontfamily=self.fonts["sans"], color=PAL["muted"], ha="left",
                 va="bottom", wrap=True)
        OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            fig.savefig(tmp.name, dpi=DPI, transparent=False, facecolor=PAL["paper"])
            plt.close(fig)
            img = Image.open(tmp.name).convert("RGB")
            img.save(OUT / f"{name}.webp", quality=88, method=6)
            small = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            small.save(OUT / f"{name}-1200.webp", quality=85, method=6)
        print(f"site/maps/{name}.webp")


# --- the maps -----------------------------------------------------------------------------

COPDEM_NOTICE = ("Erliebea: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus "
                 "Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union "
                 "and ESA; all rights reserved")
BOUNDS_CREDIT = "Mugak: IGN España, IGN France, Wikidata (CC BY 4.0)"
CITIES = ["Bilbo", "Gasteiz", "Donostia", "Iruñea", "Baiona", "Tutera"]


def map_cover(b: Base):
    """The home page cover: relief only, no labels."""
    fig, ax = b.figure()
    hypso = [PAL["card"], "#E3D5B3"] + PAL["earth"]
    b.background(ax, ramp(hypso, b.dem, [0, 2300]), relief=1.25)
    b.outline.boundary.plot(ax=ax, color=PAL["ink"], linewidth=0.8, alpha=0.7, zorder=4)
    b.save(fig, "azala", BOUNDS_CREDIT)


def map_territories(b: Base):
    fig, ax = b.figure()
    card = np.array(to_rgb(PAL["card"]))
    b.background(ax, card * 0.74 + ramp(PAL["earth"], b.dem, [0, 1800]) * 0.26, relief=0.8)
    b.borders(ax)
    b.territory_labels(ax)
    b.context_labels(ax)
    b.save(fig, "lurraldeak", BOUNDS_CREDIT)


def map_relief(b: Base):
    fig, ax = b.figure()
    hypso = [PAL["card"], "#E3D5B3"] + PAL["earth"]   # sea level ~ paper, summits dark earth
    b.background(ax, ramp(hypso, b.dem, [0, 2300]), relief=1.15)
    b.borders(ax, municipalities=False)
    peaks = gpd.read_file(DIST / "osm" / "peaks.gpkg").to_crs(CRS)
    top = peaks[peaks["rank"] == 1]
    for _, p in top.iterrows():
        x, y = p.geometry.x, p.geometry.y
        ax.plot(x, y, marker="^", ms=5.5, color=PAL["ink"], mec=PAL["paper"], mew=0.7, zorder=12)
        # near the right edge, put the label below-left of the marker
        near_edge = x > b.extent[1] - 30000
        ha, dx, dy = ("right", 1500, -7000) if near_edge else ("center", 0, 0)
        ax.text(x + dx, y + 2600 + dy, p["name"], ha=ha, fontsize=6.6,
                fontfamily=b.fonts["sans-semi"], color=PAL["ink"], path_effects=b.halo(2.2), zorder=12)
        ax.text(x + dx, y - 4200 + dy, f"{p['ele']:.0f} m", ha=ha, fontsize=5.8,
                fontfamily=b.fonts["sans"], color=PAL["ink2"], path_effects=b.halo(2), zorder=12)
    b.context_labels(ax)
    b.save(fig, "erliebea", f"{BOUNDS_CREDIT} · Gailurrak: © OpenStreetMap contributors (ODbL)")


def map_rivers(b: Base):
    fig, ax = b.figure()
    sides = gpd.read_file(DIST / "elevation" / "drainage_basins.gpkg", layer="basins").to_crs(CRS)
    paper = np.array(to_rgb(PAL["paper"]))
    med = ~geometry_mask(sides[sides.side == "mediterranean"].geometry, b.dem.shape, b.t)
    tint = np.where(med[..., None], np.array(to_rgb(PAL["med"])), np.array(to_rgb(PAL["biscay"])))
    b.background(ax, paper * 0.80 + tint * 0.20, relief=0.9)
    streams = gpd.read_file(DIST / "elevation" / "streams_dem.gpkg").to_crs(CRS)
    for order, w in ((1, 0.25), (2, 0.4), (3, 0.6), (4, 0.9), (5, 1.3), (6, 1.8)):
        s = streams[streams.strahler == order]
        if len(s):
            s.plot(ax=ax, color=PAL["water"], linewidth=w, alpha=0.9, zorder=5)
    divide = gpd.read_file(DIST / "elevation" / "drainage_basins.gpkg", layer="divide").to_crs(CRS)
    divide.plot(ax=ax, color=PAL["divide"], linewidth=1.6, linestyle=(0, (4, 2)), zorder=6)
    b.ter.boundary.plot(ax=ax, color=PAL["ink"], linewidth=0.5, alpha=0.45, zorder=4)
    b.outline.boundary.plot(ax=ax, color=PAL["ink"], linewidth=0.9, alpha=0.8, zorder=4)
    rivers = gpd.read_file(DIST / "osm" / "rivers.gpkg").to_crs(CRS).head(14)
    for _, r in rivers.iterrows():
        line = max(getattr(r.geometry, "geoms", [r.geometry]), key=lambda g: g.length)
        p = line.interpolate(0.45, normalized=True)
        q = line.interpolate(0.47, normalized=True)
        angle = np.degrees(np.arctan2(q.y - p.y, q.x - p.x))
        if angle > 90:
            angle -= 180
        if angle < -90:
            angle += 180
        ax.text(p.x, p.y, r["label"].replace(" ibaia", "").replace(" Ibaia", ""), rotation=angle,
                rotation_mode="anchor", ha="center", va="bottom", fontsize=6.6,
                fontfamily=b.fonts["serif-italic"], color=PAL["water"],
                path_effects=b.halo(2.2), zorder=12)
    for text, (lon, lat), col in (("Bizkaiko golkora", (-1.95, 43.22), PAL["water"]),
                                  ("Mediterraneora", (-1.55, 42.45), PAL["med"])):
        p = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=4326).to_crs(CRS)[0]
        ax.text(p.x, p.y, text, ha="center", fontsize=13, fontfamily=b.fonts["serif-italic"],
                color=col, path_effects=b.halo(3), zorder=12)
    b.save(fig, "ibaiak", f"{BOUNDS_CREDIT} · Ibai-izenak: © OpenStreetMap contributors (ODbL)")


def map_forest(b: Base):
    fig, ax = b.figure()
    with rasterio.open(DIST / "forest" / "forest_cover_100m.tif") as src:
        pct = np.full(b.dem.shape, np.nan, "float32")
        reproject(rasterio.band(src, 1), pct, dst_transform=b.t, dst_crs=CRS, dst_nodata=np.nan,
                  src_nodata=255, resampling=Resampling.average)
    paper = np.array(to_rgb(PAL["paper"]))
    classes = np.digitize(np.nan_to_num(pct, nan=0), [10, 30, 50, 70, 90])   # 0 = under 10%
    colors = np.vstack([paper, [to_rgb(c) for c in PAL["forest"]]])
    b.background(ax, colors[classes], relief=0.55)
    b.borders(ax, municipalities=False)
    b.territory_labels(ax, size=8.5)
    b.save(fig, "basoa", f"{BOUNDS_CREDIT} · Basoa: © ESA WorldCover project 2021 / Contains "
           "modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium")


def map_people(b: Base):
    fig, ax = b.figure()
    b.background(ax, np.broadcast_to(np.array(to_rgb(PAL["paper"])), b.dem.shape + (3,)), relief=0.6)
    grid = gpd.read_file(DIST / "population_grid" / "ghs_pop_2020_1km.gpkg").to_crs(CRS)
    bins = [25, 100, 500, 2500, 10000]
    grid = grid[grid.population >= bins[0]]
    cmap = ListedColormap(PAL["people"])
    norm = BoundaryNorm(bins + [1e9], cmap.N)
    grid.plot(ax=ax, column="population", cmap=cmap, norm=norm, linewidth=0, zorder=2)
    b.borders(ax, municipalities=False)
    b.town_labels(ax, CITIES)
    b.save(fig, "jendea", f"{BOUNDS_CREDIT} · Biztanleria: GHSL GHS-POP R2023A, 2020, © European Union (CC BY 4.0)")


def map_heat(b: Base):
    """Warming between the climate normals 1961-1990 and 1991-2020 (ERA5-Land)."""
    fig, ax = b.figure()
    with rasterio.open(DIST / "climate" / "temperature_change.tif") as src:
        dt = np.full(b.dem.shape, np.nan, "float32")
        reproject(rasterio.band(src, 1), dt, dst_transform=b.t, dst_crs=CRS, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
    classes = np.digitize(np.nan_to_num(dt, nan=0), HEAT_BINS[1:-1])
    colors = np.array([to_rgb(c) for c in PAL["heat"]])
    b.background(ax, colors[classes], relief=1.0)
    b.borders(ax, municipalities=False)
    b.territory_labels(ax, size=8.5)
    b.town_labels(ax, CITIES)
    b.save(fig, "beroa", f"{BOUNDS_CREDIT} · Tenperatura: Copernicus Climate Change Service, "
           "ERA5-Land (doi:10.24381/cds.68d2bb30, CC BY 4.0)")


HEAT_BINS = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1]   # °C; the site legend uses the same classes


def stripes():
    """site/data/stripes.json: yearly temperature anomalies vs 1961-1990 for the stripes chart."""
    import pandas as pd
    a = pd.read_csv(DIST / "climate" / "climate_annual.csv")
    a = a[a.variable == "temperature_c"]
    ter = gpd.read_file(DIST / "euskal_herria.gpkg", layer="territories", ignore_geometry=True)
    rows = [("EH", "Euskal Herria")] + list(zip(ter.id, ter.name_eu))
    years = sorted(a.year.unique())
    out = {"years": [int(y) for y in years], "reference": "1961-1990",
           "rows": [{"id": i, "name": n,
                     "anomaly": a[a.area == i].set_index("year").anomaly.reindex(years).round(2).tolist()}
                    for i, n in rows]}
    path = ROOT / "site" / "data" / "stripes.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(path.relative_to(ROOT))

    # rain and evaporative demand: 10-year means of a typical station, for the "Ur gutxiago" chart
    wb = pd.read_csv(DIST / "climate" / "water_balance.csv").set_index("year")
    ref = wb.loc[1961:1990, ["rain_mm", "et0_mm"]].mean()
    tens = wb.dropna(subset=["rain_10y_mm", "et0_10y_mm"])
    water = {"reference": "1961–1990", "window": 10, "stations": int(wb.stations.max()),
             "ref_rain_mm": round(ref.rain_mm), "ref_et0_mm": round(ref.et0_mm),
             "end": tens.index.tolist(),
             "rain_mm": tens.rain_10y_mm.round().astype(int).tolist(),
             "et0_mm": tens.et0_10y_mm.round().astype(int).tolist()}
    path = ROOT / "site" / "data" / "water.json"
    path.write_text(json.dumps(water, separators=(",", ":")))
    print(path.relative_to(ROOT))



def main():
    with tempfile.TemporaryDirectory() as tmp:
        fonts = load_fonts(Path(tmp))
        b = Base(fonts)
        maps = (map_cover, map_territories, map_relief, map_rivers, map_forest, map_people, map_heat)
        only = sys.argv[1:]  # e.g. "heat people" renders only those
        for f in maps:
            if not only or f.__name__.removeprefix("map_") in only:
                f(b)
    if not only or "stripes" in only:
        stripes()


if __name__ == "__main__":
    main()
