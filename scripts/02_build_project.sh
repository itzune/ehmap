#!/usr/bin/env bash
# Build the RustGIS project (ehmap.rgis) and the README preview maps from dist/.
# Paths are relative to the repository root so the project works on any machine.
set -euo pipefail
cd "$(dirname "$0")/.."

GPKG=dist/euskal_herria.gpkg
GRID=dist/population_grid
mkdir -p docs

# RustGIS stores raster paths as absolute paths, but embeds rasters it downloads from a URL.
# Serve dist/ locally for the duration of the build so rasters end up inside ehmap.rgis.
PORT=8765
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory dist >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER' EXIT
sleep 1

# Layers, top to bottom:
#   Gailur nagusiak the 3 highest peaks of each territory (OSM, hidden by default)
#   Gailurrak       all named peaks, from 1:400,000 in (OSM, hidden by default)
#   Lurralde mugak  territory borders + names (until 1:250,000)
#   Udalerriak      municipality outlines + Basque names (from 1:400,000 in)
#   Biztanleria 100m  GHSL people per 100 m cell, from 1:500,000 in (hidden by default)
#   Biztanleria 1km   GHSL people per km², beyond 1:500,000 (hidden by default)
#   Dentsitatea     population density per municipality (hidden by default)
#   Lurraldeak      translucent territory colours
#   Erliebea        Copernicus DEM, 50 m, shaded relief (hidden by default)
# The density, grid and relief views are also saved as print layouts with their legends.
# The OSM basemap is added after the exports, so the previews hold no OSM tiles.
rustgis-cli run \
  --cmd 'map.basemap={"name":"blank"}' \
  --cmd "layer.addUrl={\"url\":\"http://127.0.0.1:$PORT/elevation/copernicus_dem_50m.tif\",\"name\":\"Erliebea\",\"whole\":true}" \
  --cmd 'raster.symbology={"layer":"Erliebea","type":"shadedRelief"}' \
  --cmd 'raster.stretch={"layer":"Erliebea","type":"custom","min":0,"max":2000}' \
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
  --cmd "layer.addData={\"path\":\"$GRID/ghs_pop_2020_1km.gpkg\",\"name\":\"Biztanleria 1km\"}" \
  --cmd 'layer.symbology={"layer":"Biztanleria 1km","type":"graduated","field":"population","method":"manual","breaks":[5,25,100,250,500,1000,2500,5000,10000],"ramp":"Ember"}' \
  --cmd 'layer.outline={"layer":"Biztanleria 1km","color":"#00000000","width":0}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":0,"label":"< 5"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":1,"label":"5 – 25"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":2,"label":"25 – 100"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":3,"label":"100 – 250"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":4,"label":"250 – 500"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":5,"label":"500 – 1.000"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":6,"label":"1.000 – 2.500"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":7,"label":"2.500 – 5.000"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":8,"label":"5.000 – 10.000"}' \
  --cmd 'layer.classStyle={"layer":"Biztanleria 1km","index":9,"label":"> 10.000"}' \
  --cmd 'layer.scaleRange={"layer":"Biztanleria 1km","max":500000}' \
  --cmd "layer.addUrl={\"url\":\"http://127.0.0.1:$PORT/population_grid/ghs_pop_2020_100m.tif\",\"name\":\"Biztanleria 100m\",\"whole\":true}" \
  --cmd 'raster.symbology={"layer":"Biztanleria 100m","type":"classify","method":"geometricInterval","classes":9,"ramp":"Ember"}' \
  --cmd 'layer.transparency={"layer":"Biztanleria 100m","value":25}' \
  --cmd 'layer.scaleRange={"layer":"Biztanleria 100m","min":500000}' \
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
  --cmd 'layer.addData={"path":"dist/osm/peaks.gpkg","name":"Gailurrak"}' \
  --cmd 'layer.definitionQuery={"layer":"Gailurrak","where":"name IS NOT NULL AND ele IS NOT NULL"}' \
  --cmd 'layer.symbology={"layer":"Gailurrak","type":"single"}' \
  --cmd 'layer.marker={"layer":"Gailurrak","shape":"triangle","size":4}' \
  --cmd 'layer.color={"layer":"Gailurrak","color":"#3A2A1A"}' \
  --cmd 'layer.scaleRange={"layer":"Gailurrak","min":400000}' \
  --cmd 'labels.field={"layer":"Gailurrak","field":"label"}' \
  --cmd 'labels.enable={"layer":"Gailurrak","on":true}' \
  --cmd 'labels.scaleRange={"layer":"Gailurrak","min":150000}' \
  --cmd 'labels.class.add={"layer":"Gailurrak","name":"Mila metrotik gora","where":"ele >= 1000"}' \
  --cmd 'labels.scaleRange={"layer":"Gailurrak","class":"Mila metrotik gora","min":400000}' \
  --cmd 'layer.addData={"path":"dist/osm/peaks.gpkg","name":"Gailur nagusiak"}' \
  --cmd 'layer.definitionQuery={"layer":"Gailur nagusiak","where":"rank <= 3"}' \
  --cmd 'layer.symbology={"layer":"Gailur nagusiak","type":"single"}' \
  --cmd 'layer.marker={"layer":"Gailur nagusiak","shape":"triangle","size":8}' \
  --cmd 'layer.color={"layer":"Gailur nagusiak","color":"#B22222"}' \
  --cmd 'labels.field={"layer":"Gailur nagusiak","field":"label"}' \
  --cmd 'labels.enable={"layer":"Gailur nagusiak","on":true}' \
  --cmd 'layer.zoomTo={"layer":"Lurraldeak"}' \
  --cmd 'layer.visibility={"layer":["Dentsitatea","Biztanleria 1km","Biztanleria 100m","Erliebea","Gailurrak","Gailur nagusiak"],"visible":false}' \
  --cmd 'share.exportMap={"path":"docs/euskal_herria_territories.png","dpi":150}' \
  --cmd 'layer.visibility={"layer":["Lurraldeak","Udalerriak"],"visible":false}' \
  --cmd 'layer.visibility={"layer":"Dentsitatea","visible":true}' \
  --cmd 'layout.publication={"profile":"a4-landscape","style":"panel","extent":[-3.47,41.9,-0.7,43.6],"name":"Dentsitatea","title":"Biztanleria dentsitatea","subtitle":"Euskal Herria, udalerriz udalerri (biztanle/km²)","sources":["Biztanleria: INE Padrón 2025, INSEE 2023","Mugak: IGN España, IGN France","Grisez: udalerri arteko lur partekatuak (biztanlerik gabe)","github.com/itzune/ehmap · CC BY 4.0"],"locator":"none","author":""}' \
  --cmd 'layout.export={"layout":"Dentsitatea","path":"docs/population_density.png","dpi":120}' \
  --cmd 'layer.visibility={"layer":"Dentsitatea","visible":false}' \
  --cmd 'layer.visibility={"layer":"Biztanleria 1km","visible":true}' \
  --cmd 'layout.publication={"profile":"a4-landscape","style":"panel","extent":[-3.47,41.9,-0.7,43.6],"name":"Biztanleria sareta","title":"Non bizi da jendea?","subtitle":"Euskal Herria, 1 km-ko laukietan (biztanle/km², 2020)","sources":["Biztanleria: GHSL GHS-POP R2023A, 2020 (EB, JRC)","Mugak: IGN España, IGN France","github.com/itzune/ehmap · CC BY 4.0"],"locator":"none","author":""}' \
  --cmd 'layout.export={"layout":"Biztanleria sareta","path":"docs/population_grid.png","dpi":120}' \
  --cmd 'layer.visibility={"layer":"Biztanleria 1km","visible":false}' \
  --cmd 'layer.visibility={"layer":["Erliebea","Gailur nagusiak"],"visible":true}' \
  --cmd 'layout.publication={"profile":"a4-landscape","style":"panel","extent":[-3.47,41.9,-0.5,43.6],"name":"Erliebea","title":"Erliebea eta gailurrak","subtitle":"Euskal Herria: lurralde bakoitzeko hiru gailur garaienak","sources":["Erliebea: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved","Gailurrak: © OpenStreetMap contributors (ODbL)","Mugak: IGN España, IGN France","github.com/itzune/ehmap"],"locator":"none","author":""}' \
  --cmd 'layout.export={"layout":"Erliebea","path":"docs/elevation.png","dpi":120}' \
  --cmd 'layer.visibility={"layer":["Erliebea","Gailur nagusiak"],"visible":false}' \
  --cmd 'layer.visibility={"layer":["Lurraldeak","Udalerriak"],"visible":true}' \
  --cmd 'map.addTiles={"url":"https://tile.openstreetmap.org/{z}/{x}/{y}.png","name":"OpenStreetMap","attribution":"© OpenStreetMap contributors","maxZoom":19,"replace":true}' \
  --save ehmap.rgis
