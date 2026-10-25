#!/usr/bin/env bash
# Build the RustGIS project (ehmap.rgis) and the README preview map from dist/.
# Paths are relative to the repository root so the project works on any machine.
set -euo pipefail
cd "$(dirname "$0")/.."

GPKG=dist/euskal_herria.gpkg
mkdir -p docs

# Territories at the bottom (translucent fill, strong borders), municipalities on top
# (outline only). Municipality names show from 1:400,000 in, territory names until 1:250,000.
# The OSM basemap is added after the export, so the preview holds only our own (CC BY) data.
rustgis-cli run \
  --cmd 'map.basemap={"name":"blank"}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"territories\",\"name\":\"Lurraldeak\"}" \
  --cmd 'layer.symbology={"layer":"Lurraldeak","type":"unique","field":"name_eu"}' \
  --cmd 'layer.transparency={"layer":"Lurraldeak","value":40}' \
  --cmd 'layer.outline={"layer":"Lurraldeak","color":"#333333","width":1.8}' \
  --cmd 'labels.field={"layer":"Lurraldeak","field":"name_eu"}' \
  --cmd 'labels.enable={"layer":"Lurraldeak","on":true}' \
  --cmd 'labels.scaleRange={"layer":"Lurraldeak","max":250000}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"municipalities\",\"name\":\"Udalerriak\"}" \
  --cmd 'layer.symbology={"layer":"Udalerriak","type":"single"}' \
  --cmd 'layer.noFill={"layer":"Udalerriak"}' \
  --cmd 'layer.outline={"layer":"Udalerriak","color":"#555555","width":0.4}' \
  --cmd 'labels.field={"layer":"Udalerriak","field":"name_eu"}' \
  --cmd 'labels.enable={"layer":"Udalerriak","on":true}' \
  --cmd 'labels.scaleRange={"layer":"Udalerriak","min":400000}' \
  --cmd 'layer.zoomTo={"layer":"Lurraldeak"}' \
  --cmd 'share.exportMap={"path":"docs/euskal_herria_territories.png","dpi":150}' \
  --cmd 'map.addTiles={"url":"https://tile.openstreetmap.org/{z}/{x}/{y}.png","name":"OpenStreetMap","attribution":"© OpenStreetMap contributors","maxZoom":19,"replace":true}' \
  --save ehmap.rgis
