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
   dist/population_grid/ghs_pop_2020_100m.tif dist/population_grid/ghs_pop_2020_1km.gpkg "$ASSETS/"
(cd dist && zip -qr "$ASSETS/euskal_herria_geojson.zip" geojson)
(cd "$ASSETS" && sha256sum -- * > SHA256SUMS)

printf '%s\n\nData: CC BY 4.0 (see ATTRIBUTION.md). Code: MIT.\n' "$NOTES" > "$ASSETS/notes.md"
gh release create "$VERSION" --repo "$REPO" --target main --title "$VERSION" \
  --notes-file "$ASSETS/notes.md" \
  "$ASSETS"/ehmap.rgis "$ASSETS"/euskal_herria.gpkg "$ASSETS"/euskal_herria_geojson.zip \
  "$ASSETS"/ghs_pop_2020_100m.tif "$ASSETS"/ghs_pop_2020_1km.gpkg "$ASSETS"/SHA256SUMS
