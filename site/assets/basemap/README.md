# Local land outline

`world_land.geojson` is a coarse outline of land (Natural Earth 1:110m, public domain),
taken from the npm package `world-atlas` 2.0.2 (`land-110m.json`, ISC licence, see
`LICENSE-world-atlas.txt`) and converted from TopoJSON to GeoJSON. Rings that cross the
180 degree meridian were shifted by 360 degrees so they draw as one piece.

It is drawn on the world map only when the OpenFreeMap background does not load.
It holds no study data.
