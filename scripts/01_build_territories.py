"""Build municipality and territory layers for the 7 territories of Euskal Herria.

Inputs (from scripts/00_download.py, sources in ATTRIBUTION.md):
  data/raw/es/municipios_01_20_31_48.geojson    Araba, Gipuzkoa, Nafarroa, Bizkaia (IGN)
  data/raw/es/municipios_burgos_trevino.geojson Treviño enclave (Burgos), counted in Araba
  data/raw/fr/communes_64.geojson               Pyrénées-Atlantiques communes (IGN ADMIN EXPRESS)
  data/raw/wikidata/names_eu_es.csv             Basque names of the southern municipalities
  data/reference/iparralde_territories.csv      INSEE code -> Lapurdi / Nafarroa Beherea / Zuberoa

Outputs (EPSG:4326; areas computed in EPSG:25830):
  dist/euskal_herria.gpkg                 layers municipalities, territories, euskal_herria
  dist/geojson/<layer>.geojson            same layers, full detail
  dist/geojson/simplified/<layer>.geojson lighter versions for web maps (shared borders kept)
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import (MultiPolygon, Polygon, coverage_simplify, get_parts, polygonize,
                     set_precision, union_all)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DIST = ROOT / "dist"
SIMPLIFY_M = 50  # coverage simplification tolerance for the web versions

TERRITORIES = pd.DataFrame([
    # id, name_eu, name_es, name_fr, name_en, iso_3166_2
    ("araba", "Araba", "Álava", "Alava", "Álava", "ES-VI"),
    ("bizkaia", "Bizkaia", "Vizcaya", "Biscaye", "Biscay", "ES-BI"),
    ("gipuzkoa", "Gipuzkoa", "Guipúzcoa", "Guipuscoa", "Gipuzkoa", "ES-SS"),
    ("nafarroa_garaia", "Nafarroa Garaia", "Alta Navarra", "Haute-Navarre", "Upper Navarre", "ES-NA"),
    ("lapurdi", "Lapurdi", "Labort", "Labourd", "Labourd", ""),
    ("nafarroa_beherea", "Nafarroa Beherea", "Baja Navarra", "Basse-Navarre", "Lower Navarre", ""),
    ("zuberoa", "Zuberoa", "Sola", "Soule", "Soule", ""),
], columns=["id", "name_eu", "name_es", "name_fr", "name_en", "iso_3166_2"])
EUSKAL_HERRIA = {"name_eu": "Euskal Herria", "name_es": "Euskal Herria",
                 "name_fr": "Pays basque", "name_en": "Basque Country"}

SOUTH = {"01": "araba", "20": "gipuzkoa", "48": "bizkaia", "31": "nafarroa_garaia"}
TREVINO = {"09109", "09276"}  # Condado de Treviño, La Puebla de Arganzón
COLS = ["code", "country", "type", "name", "name_eu", "territory_id", "territory",
        "admin_province", "wikidata", "note", "geometry"]


def south() -> gpd.GeoDataFrame:
    es = gpd.read_file(RAW / "es" / "municipios_01_20_31_48.geojson")
    es["territory_id"] = es.prov_code.map(SOUTH)
    es["note"] = ""
    tr = gpd.read_file(RAW / "es" / "municipios_burgos_trevino.geojson")
    tr = tr[tr.mun_code.isin(TREVINO)].copy()
    assert len(tr) == 2, tr.mun_name.tolist()
    tr["territory_id"] = "araba"
    tr["note"] = "Treviño enclave: administratively Burgos, historically and geographically Araba"
    g = pd.concat([es, tr], ignore_index=True)
    g = g.rename(columns={"mun_code": "code", "mun_name": "name", "prov_name": "admin_province"})
    # INE codes 53xxx are lands shared by several municipalities (facerías, parzonerías…)
    g["type"] = g.code.str.startswith("53").map({True: "shared_land", False: "municipality"})
    names = pd.read_csv(RAW / "wikidata" / "names_eu_es.csv", dtype=str)
    assert names.code.is_unique
    g = g.merge(names, on="code", how="left")
    g["name_eu"] = g.name_eu.fillna(g.name)
    g["wikidata"] = g.wikidata.fillna("").str.replace("http://www.wikidata.org/entity/", "")
    g["country"] = "ES"
    return gpd.GeoDataFrame(g, crs=es.crs)


def north() -> gpd.GeoDataFrame:
    fr = gpd.read_file(RAW / "fr" / "communes_64.geojson")
    ref = pd.read_csv(ROOT / "data" / "reference" / "iparralde_territories.csv",
                      dtype=str, keep_default_na=False)
    g = fr.merge(ref, left_on="code", right_on="insee", how="inner")
    assert len(g) == len(ref), set(ref.insee) - set(g.code)
    ids = dict(zip(TERRITORIES.name_eu, TERRITORIES.id))
    g["territory_id"] = g.territory.map(ids)
    g = g.rename(columns={"nom": "name"})
    g["wikidata"] = g.wikidata.str.replace("http://www.wikidata.org/entity/", "")
    g["admin_province"] = "Pyrénées-Atlantiques"
    g["type"] = "municipality"
    g["country"] = "FR"
    return gpd.GeoDataFrame(g, crs=fr.crs)


def stitch_border(s: gpd.GeoDataFrame, n: gpd.GeoDataFrame, max_gap_m2: float = 1e6) -> gpd.GeoDataFrame:
    """Join the Spanish and French datasets along the state border (in EPSG:25830).

    The two national sources draw the border slightly differently: the Spanish line wins
    where they overlap, and gaps smaller than max_gap_m2 go to the municipality sharing
    the longest edge with them. Larger holes (e.g. Villaverde de Trucios) are kept.
    All overlay operations run on a 1 cm grid so dissolving later leaves no slivers.
    """
    grid = 0.01
    s["geometry"] = set_precision(s.geometry.make_valid().values, grid)
    n["geometry"] = set_precision(n.geometry.make_valid().values, grid)
    n["geometry"] = n.geometry.difference(s.union_all(grid_size=grid), grid_size=grid)
    m = pd.concat([s, n], ignore_index=True)
    outline = m.union_all(grid_size=grid)
    polys = getattr(outline, "geoms", [outline])
    gaps = [Polygon(r) for p in polys for r in p.interiors if Polygon(r).area < max_gap_m2]
    for gap in gaps:  # m has a RangeIndex, so sindex positions are also labels
        near = m.sindex.query(gap.buffer(1))
        shared = m.geometry.iloc[near].intersection(gap.boundary.buffer(1)).length
        best = shared.idxmax()
        m.at[best, "geometry"] = m.geometry[best].union(gap, grid_size=grid)
    print(f"Border stitch: {len(gaps)} gaps filled")
    return rebuild_coverage(gpd.GeoDataFrame(m, crs=s.crs), grid)


def rebuild_coverage(m: gpd.GeoDataFrame, grid: float) -> gpd.GeoDataFrame:
    """Re-node all boundaries and rebuild each polygon from the resulting faces, so that
    neighbours share identical edges (a clean coverage, needed for simplification)."""
    lines = union_all(m.boundary.values, grid_size=grid)
    faces = gpd.GeoDataFrame(geometry=list(get_parts(polygonize(get_parts(lines)))), crs=m.crs)
    pts = faces.representative_point().to_frame("geometry")
    hit = gpd.sjoin(pts, m[["geometry"]], predicate="within").groupby(level=0).index_right.first()
    faces = faces.loc[hit.index].assign(owner=hit.values)
    m = m.copy()
    m["geometry"] = faces.dissolve("owner").geometry.reindex(m.index)
    assert m.geometry.notna().all()
    return m


def polygonal(geoms: gpd.GeoSeries, min_area_m2: float = 1.0) -> gpd.GeoSeries:
    """Always MultiPolygon: drop stray lines/points left by overlays, and slivers that
    would collapse when GeoJSON rounds coordinates to ~10 cm (min_area in CRS units²)."""
    def fix(g):
        parts = [p for p in get_parts(g) for p in get_parts(p)
                 if p.geom_type == "Polygon" and p.area >= min_area_m2]
        return MultiPolygon(parts)
    return geoms.apply(fix)


def aggregate(m: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Territories and the Euskal Herria outline from the municipality layer."""
    m = m.assign(is_mun=m["type"].eq("municipality").astype(int),
                 is_shared=m["type"].eq("shared_land").astype(int))
    t = m.dissolve("territory_id", aggfunc={"is_mun": "sum", "is_shared": "sum", "area_km2": "sum"})
    t = t.rename(columns={"is_mun": "n_municipalities", "is_shared": "n_shared_lands"})
    t = gpd.GeoDataFrame(TERRITORIES.merge(t, left_on="id", right_index=True), crs=m.crs)
    eh = gpd.GeoDataFrame({**{k: [v] for k, v in EUSKAL_HERRIA.items()},
                           "n_municipalities": [t.n_municipalities.sum()],
                           "area_km2": [t.area_km2.sum()]},
                          geometry=[t.union_all()], crs=m.crs)
    return t, eh


def write(layers: dict[str, gpd.GeoDataFrame], gpkg: Path | None, geojson_dir: Path) -> None:
    geojson_dir.mkdir(parents=True, exist_ok=True)
    if gpkg:
        gpkg.unlink(missing_ok=True)
    for name, gdf in layers.items():
        gdf = gdf.assign(geometry=polygonal(gdf.geometry)).to_crs(4326).round({"area_km2": 3})
        # round to 6 decimals (~10 cm) ourselves: GDAL's rounding can leave stray lines
        gdf["geometry"] = polygonal(gpd.GeoSeries(set_precision(gdf.geometry.values, 1e-6)), 0)
        if gpkg:
            gdf.to_file(gpkg, layer=name, driver="GPKG")
        out = geojson_dir / f"{name}.geojson"
        out.unlink(missing_ok=True)
        gdf.to_file(out, driver="GeoJSON", layer_options={"RFC7946": "YES"})


def main() -> None:
    m = stitch_border(south().to_crs(25830), north().to_crs(25830))
    m["territory"] = m.territory_id.map(dict(zip(TERRITORIES.id, TERRITORIES.name_eu)))
    m["area_km2"] = m.area / 1e6
    m = m[COLS[:-1] + ["area_km2", "geometry"]].sort_values(["territory_id", "code"], ignore_index=True)
    t, eh = aggregate(m)
    write({"municipalities": m, "territories": t, "euskal_herria": eh},
          DIST / "euskal_herria.gpkg", DIST / "geojson")

    ms = m.copy()
    ms["geometry"] = coverage_simplify(m.geometry.values, SIMPLIFY_M)
    ts, ehs = aggregate(ms)
    write({"municipalities": ms, "territories": ts, "euskal_herria": ehs},
          None, DIST / "geojson" / "simplified")

    print(t.drop(columns="geometry").round(1).to_string(index=False))
    print(f"Total: {eh.n_municipalities[0]} municipalities + {t.n_shared_lands.sum()} shared lands,"
          f" {eh.area_km2[0]:.0f} km² -> {DIST.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
