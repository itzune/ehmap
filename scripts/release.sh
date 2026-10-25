#!/usr/bin/env bash
# Publish a GitHub Release with the large outputs that are not versioned in git.
# Usage: scripts/release.sh v0.2.0   (needs a "## v0.2.0" section in CHANGELOG.md)
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${1:?usage: scripts/release.sh vX.Y.Z}
REPO=itzune/ehmap

[[ -z "$(git status --porcelain)" ]] || { echo "working tree not clean: commit first" >&2; exit 1; }
git fetch -q origin
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { echo "push main first" >&2; exit 1; }

# release notes: the version's section of CHANGELOG.md
NOTES=$(awk -v v="## $VERSION" '$0 ~ "^"v {on=1; next} /^## / && on {exit} on' CHANGELOG.md)
[[ -n "$NOTES" ]] || { echo "no '## $VERSION' section in CHANGELOG.md" >&2; exit 1; }

ASSETS=$(mktemp -d)
trap 'rm -rf "$ASSETS"' EXIT
cp ehmap.rgis dist/euskal_herria.gpkg \
   dist/population_grid/ghs_pop_2020_100m.tif dist/population_grid/ghs_pop_2020_1km.gpkg \
   dist/elevation/copernicus_dem_25m.tif dist/elevation/copernicus_dem_50m.tif \
   dist/osm/peaks.gpkg dist/osm/rivers.gpkg dist/elevation/drainage_basins.gpkg \
   dist/forest/forest_cover_100m.tif dist/forest/landcover_2021_10m.tif \
   dist/climate/temperature_change.tif dist/climate/rain_stations.gpkg dist/climate/station_check.csv \
   dist/climate/station_quality.csv dist/climate/rain_timeline.csv dist/climate/rain_timeline_stations.csv \
   dist/climate/water_balance.csv dist/climate/heat_stations.gpkg \
   dist/rivers/river_gauges.gpkg dist/rivers/river_flow_yearly.csv \
   dist/sea/sea_annual.csv dist/sea/marine_heatwaves.csv dist/sea/tide_gauges.gpkg \
   dist/climate/climate_annual.csv dist/climate/climate_by_municipality.csv "$ASSETS/"
(cd dist && zip -qr "$ASSETS/euskal_herria_geojson.zip" geojson)
(cd "$ASSETS" && sha256sum -- * > SHA256SUMS)

printf '%s\n\nData: CC BY 4.0 (climate stations: © AEMET, © Météo-France, © Gobierno de Navarra; rivers: Hub’Eau, © MITECO; sea: NOAA, PSMSL), except elevation (Copernicus WorldDEM-30 licence) and peaks (ODbL, © OpenStreetMap contributors); see ATTRIBUTION.md. Code: MIT.\n' "$NOTES" > "$ASSETS/notes.md"
gh release create "$VERSION" --repo "$REPO" --target main --title "$VERSION" \
  --notes-file "$ASSETS/notes.md" \
  "$ASSETS"/ehmap.rgis "$ASSETS"/euskal_herria.gpkg "$ASSETS"/euskal_herria_geojson.zip \
  "$ASSETS"/ghs_pop_2020_100m.tif "$ASSETS"/ghs_pop_2020_1km.gpkg \
  "$ASSETS"/copernicus_dem_25m.tif "$ASSETS"/copernicus_dem_50m.tif "$ASSETS"/peaks.gpkg \
  "$ASSETS"/rivers.gpkg "$ASSETS"/drainage_basins.gpkg \
  "$ASSETS"/forest_cover_100m.tif "$ASSETS"/landcover_2021_10m.tif \
  "$ASSETS"/temperature_change.tif "$ASSETS"/rain_stations.gpkg "$ASSETS"/station_check.csv \
  "$ASSETS"/station_quality.csv "$ASSETS"/rain_timeline.csv "$ASSETS"/rain_timeline_stations.csv \
  "$ASSETS"/water_balance.csv "$ASSETS"/heat_stations.gpkg \
  "$ASSETS"/river_gauges.gpkg "$ASSETS"/river_flow_yearly.csv \
  "$ASSETS"/sea_annual.csv "$ASSETS"/marine_heatwaves.csv "$ASSETS"/tide_gauges.gpkg \
  "$ASSETS"/climate_annual.csv "$ASSETS"/climate_by_municipality.csv \
  "$ASSETS"/SHA256SUMS
