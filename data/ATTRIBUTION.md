# Sources and attribution

The data in this folder are derived from the open sources below. They are released under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/) because they contain
information derived from OpenStreetMap.

## OpenStreetMap
- © OpenStreetMap contributors. Licence: ODbL 1.0. <https://www.openstreetmap.org/copyright>
- Used for: the street network (car, walk and transit access routing), mapped places, and city centre points.
- Extracts: Geofabrik country and region files; for US cities, clips stored by the project.

## Transit schedules (GTFS)
- 217 schedule files in 71 cities. One row per file in [`feeds.csv`](feeds.csv): city, file, publisher, catalogue page and licence link.
- 210 files are listed in the [Mobility Database](https://mobilitydatabase.org). 73 of them carry a licence link there. For the others the catalogue records none; check the publisher's terms before reuse.
- 7 files (Bamako, Chennai, Delhi, Maputo, Nouakchott) come from earlier project folders. Their source and licence are not recorded. Cell-level data for these five cities are not published on the website until this is confirmed.
- This release contains no schedule file. It contains only indicators computed from them.

## Population
- WorldPop, University of Southampton: constrained population counts for 2020 at 100 m. Licence: CC BY 4.0. <https://www.worldpop.org> Used for 37 cities outside the US.
- Meta Data for Good and CIESIN: High Resolution Settlement Layer, 2020, about 30 m. Licence: CC BY 4.0. Used for Chennai and Delhi.
- US Census Bureau: 2020 Decennial Census block population (US hexagons) and American Community Survey 2024 tract population (US tracts). Public domain. This product uses Census Bureau data but is not endorsed or certified by the Census Bureau.

## Boundaries
- European Commission, Joint Research Centre: GHSL Urban Centre Database (GHS-UCDB R2024A). Licence: CC BY 4.0. City outline for 34 cities outside the US. In six of them (Belo Horizonte, Fortaleza, Jakarta, Rio de Janeiro, São Paulo, Toronto) the urban centre is cut to the operator's area with an OpenStreetMap administrative boundary.
- US Census Bureau: census tract boundaries (TIGER/Line). Public domain. City tract sets for the 32 US cities.
- Bamako, Chennai, Delhi, Maputo, Nouakchott: administrative or zone outlines from earlier project folders. Only the union outline is used, to choose the hexagons.

## Software
- R5 7.5.1 (Conveyal) through r5py 1.1.7 for routing. H3 (Uber) for the hexagon grid.
- Website: MapLibre GL JS 4.7.1 (BSD 3-Clause, `site/vendor/maplibre-gl/LICENSE.txt`). World land outline: Natural Earth 1:110m (public domain) through the `world-atlas` package (ISC). Background map tiles: OpenFreeMap, © OpenMapTiles, data from OpenStreetMap.

## How to credit this release
"Directional transit access data. Contains information from OpenStreetMap, which is made available under the Open Database License (ODbL), and indicators derived from public transit schedules, WorldPop, Meta HRSL and US Census data."
