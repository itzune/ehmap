#!/usr/bin/env bash
# Build the RustGIS project (ehmap.rgis) and the README preview maps from dist/.
# Paths are relative to the repository root so the project works on any machine.
set -euo pipefail
cd "$(dirname "$0")/.."

GPKG=dist/euskal_herria.gpkg
mkdir -p docs

# Layers, top to bottom:
#   Lurralde mugak  territory borders + names (until 1:250,000)
#   Udalerriak      municipality outlines + Basque names (from 1:400,000 in)
#   Dentsitatea     population density per municipality (hidden by default)
#   Lurraldeak      translucent territory colours
# The density view is also saved as a print layout (Dentsitatea) with its legend.
# The OSM basemap is added after the exports, so the previews hold only our own (CC BY) data.
rustgis-cli run \
  --cmd 'map.basemap={"name":"blank"}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"territories\",\"name\":\"Lurraldeak\"}" \
  --cmd 'layer.symbology={"layer":"Lurraldeak","type":"unique","field":"name_eu"}' \
  --cmd 'layer.transparency={"layer":"Lurraldeak","value":40}' \
  --cmd 'layer.outline={"layer":"Lurraldeak","color":"#33333300","width":0}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"municipalities\",\"name\":\"Dentsitatea\"}" \
  --cmd 'layer.symbology={"layer":"Dentsitatea","type":"graduated","field":"density_km2","method":"manual","breaks":[10,25,50,100,250,500,1000,2500,5000],"ramp":"Ember"}' \
  --cmd 'layer.outline={"layer":"Dentsitatea","color":"#FFFFFF66","width":0.3}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":0,"label":"< 10"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":1,"label":"10 – 25"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":2,"label":"25 – 50"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":3,"label":"50 – 100"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":4,"label":"100 – 250"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":5,"label":"250 – 500"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":6,"label":"500 – 1.000"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":7,"label":"1.000 – 2.500"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":8,"label":"2.500 – 5.000"}' \
  --cmd 'layer.classStyle={"layer":"Dentsitatea","index":9,"label":"> 5.000"}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"municipalities\",\"name\":\"Udalerriak\"}" \
  --cmd 'layer.symbology={"layer":"Udalerriak","type":"single"}' \
  --cmd 'layer.noFill={"layer":"Udalerriak"}' \
  --cmd 'layer.outline={"layer":"Udalerriak","color":"#555555","width":0.4}' \
  --cmd 'labels.field={"layer":"Udalerriak","field":"name_eu"}' \
  --cmd 'labels.enable={"layer":"Udalerriak","on":true}' \
  --cmd 'labels.scaleRange={"layer":"Udalerriak","min":400000}' \
  --cmd "layer.addData={\"path\":\"$GPKG\",\"layer\":\"territories\",\"name\":\"Lurralde mugak\"}" \
  --cmd 'layer.symbology={"layer":"Lurralde mugak","type":"single"}' \
  --cmd 'layer.noFill={"layer":"Lurralde mugak"}' \
  --cmd 'layer.outline={"layer":"Lurralde mugak","color":"#333333","width":1.8}' \
  --cmd 'labels.field={"layer":"Lurralde mugak","field":"name_eu"}' \
  --cmd 'labels.enable={"layer":"Lurralde mugak","on":true}' \
  --cmd 'labels.scaleRange={"layer":"Lurralde mugak","max":250000}' \
  --cmd 'layer.zoomTo={"layer":"Lurraldeak"}' \
  --cmd 'layer.visibility={"layer":"Dentsitatea","visible":false}' \
  --cmd 'share.exportMap={"path":"docs/euskal_herria_territories.png","dpi":150}' \
  --cmd 'layer.visibility={"layer":["Lurraldeak","Udalerriak"],"visible":false}' \
  --cmd 'layer.visibility={"layer":"Dentsitatea","visible":true}' \
  --cmd 'layout.publication={"profile":"a4-landscape","style":"panel","extent":[-3.47,41.9,-0.7,43.6],"name":"Dentsitatea","title":"Biztanleria dentsitatea","subtitle":"Euskal Herria, udalerriz udalerri (biztanle/km²)","sources":["Biztanleria: INE Padrón 2025, INSEE 2023","Mugak: IGN España, IGN France","Grisez: udalerri arteko lur partekatuak (biztanlerik gabe)","github.com/itzune/ehmap · CC BY 4.0"],"locator":"none","author":""}' \
  --cmd 'layout.export={"layout":"Dentsitatea","path":"docs/population_density.png","dpi":120}' \
  --cmd 'layer.visibility={"layer":"Dentsitatea","visible":false}' \
  --cmd 'layer.visibility={"layer":["Lurraldeak","Udalerriak"],"visible":true}' \
  --cmd 'map.addTiles={"url":"https://tile.openstreetmap.org/{z}/{x}/{y}.png","name":"OpenStreetMap","attribution":"© OpenStreetMap contributors","maxZoom":19,"replace":true}' \
  --save ehmap.rgis
