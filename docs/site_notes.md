# Site notes

## Changes made after these notes were written (2026-11-26)
- `data/ATTRIBUTION.md`, `data/feeds.csv` and `data/DATA_DICTIONARY.md` now exist. CI runs `check_site.py --strict`.
- City pages show `data_caveat` (plain wording) instead of the raw `relaxations` text. The table column "Data caveat" follows the same field.
- Residents are stored with three decimals. The page still shows whole numbers, so a hexagon with 99.96 residents reads as 100 and is not assessed.
- The Natural Earth outline is credited in `data/ATTRIBUTION.md`.
- The notes below are the site builder's original record. Where they say something is missing, check this list first.

## What is in this bundle

- `site/` static source. `index.html` (world map and table), `about.html`, `city.html` (template for city pages).
- `site/assets/css/site.css`, `site/assets/js/common.js`, `index.js`, `city.js`.
- `site/vendor/maplibre-gl/` MapLibre GL JS 4.7.1 from the npm registry, with its `LICENSE.txt`.
- `site/assets/basemap/world_land.geojson` coarse land outline for the world map when the background map does not load.
- `site/held_cities.json` the five held cities: chennai, delhi, maputo, bamako, nouakchott.
- `scripts/build_site.py`, `scripts/check_site.py`. Standard library only.
- `tests/test_site_build.py` (pytest) and `tests/fixtures/`.
- `tests/browser_render.py` optional real-browser check. Standard library only. Not run by pytest.
- `screenshots/` 65 PNG files and `render_report.json` from the browser check with WebGL.
- `screenshots/no_webgl/` 3 PNG files and a report from a run in a browser without WebGL.

## How to build and check

    python scripts/build_site.py --data data --site site --out _site
    python scripts/check_site.py _site --expect-cities 71
    python -m http.server 8000 --directory _site
    python scripts/check_site.py http://localhost:8000/ --expect-cities 71
    python -m pytest tests/test_site_build.py
    python tests/browser_render.py --site _site --out screenshots --xvfb     # optional

## What the build does

- Copies `site/` to `_site/`. The template `city.html` is not copied.
- Copies `data/` to `_site/data/` byte for byte.
- Leaves out `data/cells/<city>.*` for every city in `site/held_cities.json`.
- Writes `_site/city/<city>/index.html` for each city, with the city id, name and country filled in.
- Stops with an error if `site/held_cities.json`, `held_cities` in `cities.json` and the `cells_public` flags disagree.
- Writes `.nojekyll` and `.site_build.json` (a marker; the build only replaces a folder that has it).
- Reads no data value except city id, name, country, `has_tracts` and `cells_public`.

## What the pages show

- All numbers are read in the browser from `data/cities.json` and the city GeoJSON files.
- Nothing is recomputed. Numbers are only formatted for display (see "Display rounding").
- World page: 71 markers coloured by `headline_share_un`, a card on click, a sortable table.
- City page: hexagon map with three layers, an area panel, the city summary, download links.
- US city page: unit switch to census tracts, `coverage_pct` labelled "Coverage (US agency rule)", tract summary.
- Held city page: summary only, the fixed sentence, no map, no cell download, no request for a cell file.
- About page: the agreed text, as headings and bullet lists. A test compares it line by line.

## Background map

- The page asks OpenFreeMap for its style once, with a 4 second limit.
- If that fails, the map uses a plain local background. Data layers are added either way.
- If the style arrives but does not become usable in 8 seconds, the map also switches to the local background.
- With the background loaded, the corner shows "© OpenFreeMap © OpenMapTiles Data from OpenStreetMap" with links.
- Without it, the corner says "Background map not loaded. Showing the data only."
- No other host is contacted. No cookies, storage, fonts or analytics.

## Choices I made that you may want to change

- Site title: "Transit access by direction". It is in the three HTML files.
- World map classes: under 5%, 5 to under 10%, 10 to under 20%, 20 to under 40%, 40% or more. City counts per class: 13, 15, 22, 17, 4.
- Blocked share colours: #FFFBD6, #FDDC9E, #F9A87C, #B5367A, #4A1070. Lightness (L*) 98, 89, 76, 44, 20, so the half cut is the largest step.
- Coverage colours: #EFF3FF, #BDD7E7, #6BAED6, #3182BD, #08519C.
- A value of exactly 25%, 50% or 75% goes into the higher class. This matches `half_blocked` (blocked share of 0.5 or more).
- Coverage layer colours every hexagon that has a coverage value, also those with fewer than 100 residents. Grey there means "No value".
- On screens narrower than 520 px the marker card appears under the map, not as a pop-up, so it is never cut off.
- The local land outline is Natural Earth 1:110m (public domain) from npm `world-atlas` 2.0.2 (ISC). Please add it to `data/ATTRIBUTION.md`, or delete `site/assets/basemap/` to drop it (the world map then falls back to a plain background).
- Fields in `cities.json` that the site does not show: `r`, `beta_dist` and its interval, `direction_share`, `si_failure_share_*`, `group`, `region`. I had no agreed plain wording for them.

## Display rounding

- City shares: one decimal, for example 14.5%.
- Area percentages: one decimal, ".0" dropped, for example 50%, 12.5%, 42.9%.
- Residents: whole number with thousands separators. Area residents below 10 keep one decimal.
- s and q: three significant digits.
- Schedule date: "3 March 2026" from `run_date`.

## Things for the lead to act on

- The data archive contains the cell files of the five held cities. The build leaves them out of `_site/`, but they must not be committed to a public repository either.
- `data/ATTRIBUTION.md` does not exist yet. `check_site.py` only warns about it. Use `--strict` once it is added.
- The "Data caveat" text is shown exactly as stored in `relaxations`. Eleven of the nineteen texts carry internal codes such as "R3 no:" or "(R5)". Readers will not know them. Plain rewrites would have to come from you.
- Three hexagons (Corpus Christi, Fort Worth, Houston) show 100 residents but are not assessed (`is_origin` is false). The stored value is rounded; I did not check the unrounded value.
- 150 assessed hexagons and 167 tracts have no direction that counts (`n_car_directions` is 0). They are drawn grey and the panel says so.

## Checks I ran on the data before wiring labels

- `n_blocked` equals `n_missing` plus `n_dead` in all 60,804 hexagons and 10,371 tracts that have a value.
- `half_blocked` equals "blocked share is 0.5 or more" in all of them.
- `q` is empty exactly where `s` is 0 (3,853 areas).
- `headline_cells_blocked_half` and `n_origins` in `cities.json` equal the counts in the cell files for all 71 cities.
- `n_cells` equals the number of features in every cell file (also checked by `check_site.py`).

## How I tested

- `build_site.py` on the full data: 71 city pages written, 10 cell files of 5 held cities left out.
- `check_site.py _site --expect-cities 71`: OK. 73 pages, 200 data files parsed, 0 failures, 1 warning (the missing attribution file).
- Same check over `python -m http.server` on 127.0.0.1: OK, same counts. The five held cell files return 404.
- `pytest tests/test_site_build.py`: 14 passed (Python 3.10.12, pytest 6.2.5).
- Fixture: real files for Jerusalem, Kigali and Santa Ana (hexagons, and tracts for Santa Ana), plus the summary entry of Chennai. No held cell data is in the fixture. The test writes an empty placeholder at run time to prove the build leaves it out.
- Browser check: Firefox 160.0.1 with WebGL (software rendering, llvmpipe). 21 page views, 0 failures.
  - Pages: index, about, Phoenix, Jerusalem, Bangkok, Chennai at 1280x800, 390x800 and 360x800.
  - Clicked a marker and compared the card with `cities.json`. Sorted the table by residents.
  - Clicked one hexagon per city and one Phoenix tract and compared the panel with the data file.
  - Switched all three layers and, for Phoenix, the unit. Checked legends, labels and the tract summary.
  - Checked: no sideways scroll, no tap target under 40 px, no cookies or storage, no host other than the site and OpenFreeMap, no cell request on the held page.
  - Stand-in background that answers (tiles and fonts fail): map reports the background as loaded, data layers drawn under its labels, credit line shown.
  - Stand-in background that never answers: map falls back to the local background after the 4 second limit.
- Second run, headless Firefox without WebGL (index, about, Phoenix, Chennai, three sizes): the map box is hidden, the message "This browser cannot draw the map" shows, the table has 71 rows, the city summary shows. That run reports 11 "no map" failures by design; they are the expected result without WebGL.
- Text contrast: all text and link colours are at least 6.7:1 on their backgrounds (computed, WCAG AA needs 4.5:1).
- Colour ramps: lightness stays in order under simulated protan, deutan and tritan vision (computed).

## Console messages seen

- One error, on every page with a map: Firefox reports that the request to tiles.openfreemap.org did not succeed. The browser writes this itself when the host is unreachable; the page then uses the local background. It was absent in the stand-in runs.
- No JavaScript error from the site's own code or from MapLibre.
- Without WebGL: the same network message, plus one warning "Failed to create WebGL context" from MapLibre. No other error.
- In some runs Firefox warned "Layout was forced before the page was fully loaded" for the test frame page. It did not appear in the final run.

## Not verified

- The real OpenFreeMap background. The sandbox blocks that host, as expected. The "background loaded" branch was tested only with a local stand-in style, never with the real style, tiles, fonts or sprite.
- How the data layers look on top of the real Positron background (colours, label order, opacity).
- GitHub Pages itself. Tested only from a folder and from a local file server. `check_site.py` was not run against a github.io address.
- The requested test setup. The conda environment with Firefox and geckodriver could not be used inside the sandbox and Selenium was not available. I drove the system Firefox 160.0.1 through its Marionette port instead.
- Maps in true headless mode. Headless Firefox had no WebGL here, so the maps were rendered on a virtual display (Xvfb) instead. Headless mode was used only for the no-WebGL run.
- The 390 and 360 px views ran inside a frame of that size in a desktop Firefox (its window cannot be narrower than 500 px). No phone, no touch input, no mobile browser.
- Other browsers (Chrome, Safari, Edge) and screen readers.
- City pages other than Phoenix, Jerusalem, Bangkok and Chennai in a browser (67 of 71 not rendered). They were checked by `check_site.py` only (page loads, files parse).
- A US city other than Phoenix in tract view in a browser.
- The largest file (Corpus Christi, 5.5 MB, 7,873 hexagons) in a browser.
- Keyboard-only use of the map. Cells cannot be reached by keyboard; the table and downloads can.
