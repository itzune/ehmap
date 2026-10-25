"""Rivers of Euskal Herria: named rivers from OpenStreetMap, and the drainage network and the
Mediterranean / Bay of Biscay watershed divide computed from the Copernicus DEM with the
GeoLibre (Whitebox) tools that RustGIS uses.

Inputs (from scripts/00_download.py):
  data/raw/osm/rivers.json   waterway=river ways (with geometry) and their waterway relations
  data/raw/copdem/*.tif      Copernicus DEM GLO-30 tiles (41-44°N, 4-0°W)
  dist/euskal_herria.gpkg    territories and outline

Outputs:
  dist/osm/rivers.gpkg, .geojson              named rivers clipped to Euskal Herria (ODbL)
  dist/elevation/streams_dem.gpkg             DEM-derived streams (> 10 km² upstream), Strahler order
  dist/elevation/drainage_basins.gpkg         Mediterranean (Ebro) and Bay of Biscay sides, and the divide
Needs the GeoLibre runner (RustGIS: Tools pane › Install, or `rustgis-cli run --cmd gp.installGeolibre={}`).
"""
import json
import os
import re
import unicodedata
import shutil
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from shapely import LineString, MultiLineString, line_merge, union_all
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
GPKG = ROOT / "dist" / "euskal_herria.gpkg"
OUT_OSM = ROOT / "dist" / "osm"
OUT_DEM = ROOT / "dist" / "elevation"
CRS = "EPSG:25830"


# --- A. OpenStreetMap rivers -------------------------------------------------------------

def osm_rivers() -> gpd.GeoDataFrame:
    """One feature per river: a waterway relation, or same-named connected ways without one."""
    elements = json.loads((RAW / "osm" / "rivers.json").read_text())["elements"]
    ways = {e["id"]: e for e in elements if e["type"] == "way"}
    rels = [e for e in elements if e["type"] == "relation"]
    line = lambda w: LineString([(p["lon"], p["lat"]) for p in w["geometry"]])

    rows, used = [], set()
    for r in rels:
        ids = [m["ref"] for m in r["members"] if m["type"] == "way" and m["ref"] in ways]
        if not ids:
            continue
        used.update(ids)
        rows.append({"osm_type": "relation", "osm_id": r["id"], "tags": r["tags"],
                     "geometry": line_merge(MultiLineString([line(ways[i]) for i in ids]))})
    loose = gpd.GeoDataFrame([{"id": i, "name": w["tags"].get("name"), "tags": w["tags"],
                               "geometry": line(w)} for i, w in ways.items() if i not in used],
                             crs=4326)
    for name, grp in loose.dropna(subset=["name"]).groupby("name"):
        merged = line_merge(MultiLineString(list(grp.geometry)))
        # same name, different rivers: split into connected parts
        parts = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        groups = gpd.GeoSeries(parts).buffer(1e-6).union_all()
        for comp in getattr(groups, "geoms", [groups]):
            members = grp[grp.geometry.intersects(comp)]
            rows.append({"osm_type": "way", "osm_id": int(members.id.min()),
                         "tags": members.tags.iloc[0],
                         "geometry": line_merge(MultiLineString(list(members.geometry)))})

    g = gpd.GeoDataFrame(rows, crs=4326)
    for k, tag in (("name", "name"), ("name_eu", "name:eu"), ("wikidata", "wikidata")):
        g[k] = g.tags.apply(lambda t: t.get(tag))
    return g.drop(columns="tags")


def river_key(name: str | None) -> str | None:
    """'Zadorra ibaia/Río Zadorra', 'Río Zadorra', 'Zadorra' -> 'zadorra'."""
    if not isinstance(name, str) or not name:
        return None
    first = re.split(r"\s*/\s*", name)[0]
    s = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.split(r"[\s']+", s) if w not in {"rio", "ibaia", "river", "le", "la", "el", "l"}]
    return " ".join(words) or None


def merge_same_river(g: gpd.GeoDataFrame, gap_m: float = 2500,
                     gap_rel_m: float = 10000) -> gpd.GeoDataFrame:
    """Merge pieces whose names match after normalising and that lie within gap_m of each other,
    or gap_rel_m when one of them is a waterway relation (major rivers are often cut by
    reservoirs, e.g. the Zadorra by Ullíbarri-Gamboa). Attributes come from the longest piece,
    preferring relations (they usually carry the wikidata)."""
    g = g.to_crs(CRS).reset_index(drop=True)
    g = g.assign(key=g.name.map(river_key), _len=g.length)
    g["_rank"] = list(zip(g.osm_type.eq("relation"), g._len))
    rows = [r for _, r in g[g.key.isna()].iterrows()]
    for _, grp in g.dropna(subset=["key"]).groupby("key"):
        # connected components of "within gap_m" (union-find)
        idx = list(grp.index)
        parent = {i: i for i in idx}
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        left, right = grp.sindex.query(grp.geometry, predicate="dwithin", distance=gap_rel_m)
        pairs = [(idx[a], idx[b], grp.geometry[idx[a]].distance(grp.geometry[idx[b]]))
                 for a, b in zip(left, right) if a < b]
        for ia, ib, d in pairs:  # pass 1: pieces close to each other
            if d <= gap_m:
                parent[find(ia)] = find(ib)
        has_rel = {}
        for i in idx:
            has_rel[find(i)] = has_rel.get(find(i), False) or grp.osm_type[i] == "relation"
        for ia, ib, d in pairs:  # pass 2: wider gaps, if either group holds a relation
            if has_rel[find(ia)] or has_rel[find(ib)]:
                parent[find(ia)] = find(ib)
        comps = {}
        for i in idx:
            comps.setdefault(find(i), []).append(i)
        for members in comps.values():
            m = grp.loc[members]
            best = m.loc[max(members, key=lambda i: m._rank[i])].copy()
            best["geometry"] = line_merge(union_all(list(m.geometry)))
            rows.append(best)
    return gpd.GeoDataFrame(rows, crs=CRS).drop(columns=["key", "_len", "_rank"])


def clip_rivers(g: gpd.GeoDataFrame, ter: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    outline = ter.union_all()
    g = g.to_crs(CRS)
    g = g[g.intersects(outline)].copy()
    g["geometry"] = g.intersection(outline)
    g["length_km"] = (g.length / 1000).round(2)
    g = g[g.length_km >= 0.5]
    inter = g[["geometry"]].sjoin(ter[["id", "geometry"]], predicate="intersects")
    g["territories"] = inter.groupby(level=0)["id"].agg(lambda s: ";".join(sorted(set(s))))
    return g.sort_values("length_km", ascending=False).reset_index(drop=True)


# --- B. Drainage computed from the DEM with GeoLibre ---------------------------------------

GEOLIBRE = Path(os.environ.get("RUSTGIS_GEOLIBRE",
                               Path.home() / ".local/share/rustgis/geolibre/geolibre"))
HYDRO_RES = 100            # m; the whole 41-44°N, 4-0°W box, so water reaches its real outlets
STREAM_KM2 = 10            # minimum upstream area of a stream
EBRO_OUTLET = (-0.74, 41.57)  # a point on the Ebro below Zaragoza: upstream of it = Ebro basin


def geolibre(tool: str, **params) -> None:
    args = [str(GEOLIBRE), tool] + [f"--{k}={v}" for k, v in params.items()]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"geolibre {tool} failed:\n{r.stdout}\n{r.stderr}")


def regional_dem(path: Path) -> None:
    """All DEM tiles at ~3 arc-seconds, reprojected to EPSG:25830 at HYDRO_RES; sea = nodata."""
    tiles = [rasterio.open(p) for p in sorted((RAW / "copdem").glob("*.tif"))]
    src, src_t = merge(tiles, res=1 / 1200, resampling=Resampling.average)
    src_crs = tiles[0].crs
    for t in tiles:
        t.close()
    left, top = src_t.c, src_t.f
    bounds = rasterio.warp.transform_bounds(src_crs, CRS, left, top - src.shape[1] / 1200,
                                            left + src.shape[2] / 1200, top)
    x0, y0, x1, y1 = (np.floor(b / HYDRO_RES) * HYDRO_RES for b in bounds)
    transform = rasterio.Affine(HYDRO_RES, 0, x0, 0, -HYDRO_RES, y1)
    dem = np.full((int((y1 - y0) / HYDRO_RES), int((x1 - x0) / HYDRO_RES)), -9999, "float32")
    reproject(src[0], dem, src_transform=src_t, src_crs=src_crs, dst_transform=transform,
              dst_crs=CRS, dst_nodata=-9999, resampling=Resampling.bilinear)
    dem[dem <= 0] = -9999  # sea (and the odd negative artefact) becomes an outlet
    with rasterio.open(path, "w", driver="GTiff", width=dem.shape[1], height=dem.shape[0],
                       count=1, dtype="float32", crs=CRS, transform=transform, nodata=-9999,
                       compress="DEFLATE") as dst:
        dst.write(dem, 1)


def drainage(ter: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    outline = ter.union_all()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        regional_dem(t / "dem.tif")
        geolibre("breach_depressions_least_cost", dem=t / "dem.tif", output=t / "breached.tif",
                 fill_deps="true")
        geolibre("d8_pointer", dem=t / "breached.tif", output=t / "pntr.tif")
        geolibre("d8_flow_accum", input=t / "breached.tif", output=t / "accum.tif", out_type="cells")
        cells = STREAM_KM2 * 1e6 / HYDRO_RES ** 2
        geolibre("extract_streams", flow_accumulation=t / "accum.tif", output=t / "streams.tif",
                 threshold=cells)
        geolibre("strahler_stream_order", d8_pntr=t / "pntr.tif", streams=t / "streams.tif",
                 output=t / "strahler.tif")
        geolibre("raster_streams_to_vector", d8_pntr=t / "pntr.tif",
                 streams_raster=t / "strahler.tif", output=t / "streams.shp")

        outlet = gpd.GeoDataFrame(geometry=gpd.points_from_xy([EBRO_OUTLET[0]], [EBRO_OUTLET[1]]),
                                  crs=4326).to_crs(CRS)
        outlet.to_file(t / "outlet.shp")
        geolibre("jenson_snap_pour_points", pour_pts=t / "outlet.shp", streams=t / "streams.tif",
                 snap_dist=3000, output=t / "outlet_snapped.shp")
        geolibre("watershed", d8_pntr=t / "pntr.tif", pour_pts=t / "outlet_snapped.shp",
                 output=t / "ebro.tif")

        streams = gpd.read_file(t / "streams.shp").set_crs(CRS, allow_override=True)
        with rasterio.open(t / "ebro.tif") as r:
            ebro = r.read(1)
            polys = [shape(geom) for geom, v in shapes(ebro.astype("int32"),
                     mask=(ebro > 0) & (ebro != r.nodata), transform=r.transform)]
    ebro_poly = union_all(polys)

    streams = streams.rename(columns={"STRM_VAL": "strahler"})[["strahler", "geometry"]]
    streams = streams[streams.intersects(outline)].copy()
    streams["geometry"] = streams.intersection(outline)
    streams = streams[~streams.is_empty].explode(index_parts=False)
    streams["strahler"] = streams.strahler.astype(int)
    streams["side"] = np.where(streams.geometry.representative_point().within(ebro_poly),
                               "mediterranean", "biscay")

    med = outline.intersection(ebro_poly)
    bis = outline.difference(ebro_poly)
    basins = gpd.GeoDataFrame({"side": ["mediterranean", "biscay"],
                               "sea_eu": ["Mediterraneoa (Ebro)", "Bizkaiko golkoa"],
                               "sea_en": ["Mediterranean (Ebro)", "Bay of Biscay"]},
                              geometry=[med, bis], crs=CRS)
    basins["area_km2"] = (basins.area / 1e6).round(1)
    divide = med.boundary.intersection(bis.boundary)
    divide_g = gpd.GeoDataFrame({"name_eu": ["Isurialdeen banalerroa"],
                                 "length_km": [round(divide.length / 1000, 1)]},
                                geometry=[line_merge(divide)], crs=CRS)
    return streams, basins, divide_g


def main() -> None:
    ter = gpd.read_file(GPKG, layer="territories").to_crs(CRS)
    rivers = clip_rivers(merge_same_river(osm_rivers()), ter)
    OUT_OSM.mkdir(parents=True, exist_ok=True)
    rivers["label"] = rivers.name_eu.fillna(rivers.name.str.split(r"\s*/\s*").str[0])
    out = rivers[["osm_type", "osm_id", "name", "name_eu", "label", "wikidata", "length_km",
                  "territories", "geometry"]].to_crs(4326)
    for path, driver in ((OUT_OSM / "rivers.gpkg", "GPKG"), (OUT_OSM / "rivers.geojson", "GeoJSON")):
        path.unlink(missing_ok=True)
        out.to_file(path, driver=driver, layer="rivers")
    print(f"OSM rivers: {len(out)} features, {out.length_km.sum():,.0f} km inside Euskal Herria")
    print(out.head(15)[["name", "name_eu", "length_km", "territories"]].to_string(index=False))

    streams, basins, divide = drainage(ter)
    OUT_DEM.mkdir(parents=True, exist_ok=True)
    p = OUT_DEM / "streams_dem.gpkg"
    p.unlink(missing_ok=True)
    streams.to_crs(4326).to_file(p, layer="streams")
    p = OUT_DEM / "drainage_basins.gpkg"
    p.unlink(missing_ok=True)
    basins.to_crs(4326).to_file(p, layer="basins")
    divide.to_crs(4326).to_file(p, layer="divide")
    print(f"\nDEM streams: {len(streams)} segments, {streams.length.sum() / 1000:,.0f} km, "
          f"max Strahler order {streams.strahler.max()}")
    print(basins.drop(columns="geometry").to_string(index=False))
    print(f"Divide: {divide.length_km[0]} km")
    share = gpd.overlay(ter[["id", "geometry"]], basins[["side", "geometry"]], how="intersection")
    share["km2"] = share.area / 1e6
    print(share.pivot_table(index="id", columns="side", values="km2", aggfunc="sum").round(0))


if __name__ == "__main__":
    main()
