# Licence of the files in `dist/osm/`

These files are **not** under CC BY 4.0. They are extracted from OpenStreetMap and are
available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

© OpenStreetMap contributors — https://www.openstreetmap.org/copyright

Files: `peaks.gpkg`, `peaks.geojson` — `natural=peak` nodes inside Euskal Herria, with
`name`, `name:eu`, `ele` (parsed to metres) and `wikidata` from OSM, plus fields computed here:
`territory_id`, `territories` (every territory within 100 m), `rank` (position among the
named peaks of its territory) and `label`.

If you publish a database derived from these files, it must be under the ODbL too
(share-alike). Maps and images made from them need the credit "© OpenStreetMap contributors".
Errors are best fixed in OpenStreetMap itself, so everyone benefits.
