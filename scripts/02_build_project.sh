#!/usr/bin/env bash
# Build the RustGIS project (ehmap.rgis) and preview map from dist/.
# Paths are relative to the repository root so the project works on any machine.
set -euo pipefail
cd "$(dirname "$0")/.."

GPKG=dist/euskal_herria.gpkg
mkdir -p docs

rustgis-cli run \
  --cmd 'map.basemap={"name":"blank"}' \
  --cmd 'map.addTiles={"url":"https://tile.openstreetmap.org/{z}/{x}/{y}.png","name":"OpenStreetMap","attribution":"© OpenStreetMap contributors","maxZoom":19,"replace":true}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"municipalities\",\"name\":\"Udalerriak\"}" \
  --cmd 'layer.symbology={"layer":"Udalerriak","type":"single"}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"territories\",\"name\":\"Lurraldeak\"}" \
  --cmd 'layer.symbology={"layer":"Lurraldeak","type":"unique","field":"name_eu"}' \
  --cmd 'labels.field={"layer":"Lurraldeak","field":"name_eu"}' \
  --cmd 'labels.enable={"layer":"Lurraldeak","on":true}' \
  --cmd 'layer.zoomTo={"layer":"Lurraldeak"}' \
  --cmd 'share.exportMap={"path":"docs/euskal_herria_territories.png","dpi":150}' \
  --save ehmap.rgis
