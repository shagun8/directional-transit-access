# Directional transit access

Most transit scores ask one question: is a stop near where people live? This repository asks a second one:
**from that stop, in which directions can you travel?**

For each small area of a city we look in eight compass directions. A direction counts if a car reaches at least
five other areas that way within 30 minutes. The direction is *blocked* if transit, leaving between 08:00 and
09:00 on a weekday, reaches none of them within 30 minutes.

The repository holds three things:

| Part | Where | Licence |
|---|---|---|
| `dtaccess`, a Python tool that computes the indicators for any city from public inputs | `src/dtaccess/` | MIT |
| Results for 71 cities on hexagons and 32 US cities on census tracts | `data/` | ODbL 1.0 |
| A static website with an interactive map | `site/` | MIT (code) |

## The headline number

Take the residents the UN transit indicator (SDG 11.2.1) counts as served: within 500 m of a bus or tram stop,
or 1,000 m of a rail, metro, ferry or marked rapid-bus stop. The headline is the share of those residents who
live in areas where at least half of the car-reachable directions are blocked.

## Install

```bash
conda env create -f environment.yml      # Python 3.12, Java 21, r5py 1.1.7 (which loads R5 7.5.1), osmium
conda activate dtaccess
pip install -e ".[routing,test]"
```

Routing needs Java 21 and several GB of memory. Everything after routing runs without Java.

## Run a city

```bash
dtaccess run \
  --gtfs feed1.zip feed2.zip \
  --osm region-latest.osm.pbf \
  --boundary city.geojson \
  --population worldpop_2020_constrained.tif \
  --date 2026-11-17 \
  --centre-name "Casablanca" \
  --out out/casablanca
```

| Input | What it is |
|---|---|
| `--gtfs` | One or more GTFS schedule zips that run on `--date` |
| `--osm` | An OpenStreetMap `.osm.pbf` that covers the city and 10 km around it. The tool clips it. |
| `--boundary` | The city outline (any polygon file) |
| `--population` | A population raster in WGS84 (people per pixel), or a polygon file with a population column. Optional; without it the tool weights by area and says so. |
| `--date` | The service day. The paper uses a Tuesday. |
| `--centre` or `--centre-name` | City centre as `LAT,LON`, or the city name to look up as an OpenStreetMap `place=city` point. Used only for one distance-controlled statistic. |

Outputs in `--out`:

| File | Content |
|---|---|
| `cells.geojson`, `cells.csv`, `cells.parquet` | One row per hexagon: residents, coverage, class, blocked share, failure types, `s`, `q` |
| `sectors.parquet` | One row per hexagon and compass direction |
| `summary.json` | The headline, coverage, class counts, the Stranded Infrastructure vs Full Service comparison, the direction-or-distance split, feed repairs applied |
| `cache/` | Travel times and stage files. `dtaccess classify --cache out/city/cache --out out/city2` re-runs the indicators without routing. |

Column definitions: [`data/DATA_DICTIONARY.md`](data/DATA_DICTIONARY.md). Method: [`docs/method.md`](docs/method.md). Limits: [`docs/limits.md`](docs/limits.md).

Python:

```python
from dtaccess import run_city, classify_from_cache
summary = run_city(gtfs=["feed.zip"], osm="region.osm.pbf", boundary="city.geojson",
                   population="pop.tif", date="2026-11-17", out="out/city")
print(summary["headline"]["un"]["share"])
```

## Does the tool reproduce the paper?

- The indicator stage reproduces the stored results of the paper's run in **71 of 71 cities**: every class label, blocked share and failure type, the headline, and the city statistics (checked outside this repository, on the stored travel times).
- A full run from raw inputs (schedule file, OpenStreetMap extract, population raster) reproduces **Jerusalem** exactly: travel times pair for pair, and every cell value.
- CI runs unit tests on a small made-up schedule and the Jerusalem regression from stored travel times (`tests/`). The full routing run is `pytest -m e2e` after `python scripts/download_regression_inputs.py`.

## Data

- `data/city_summary.csv`: 71 cities on hexagons. `data/cells/<city>.geojson|csv`: their hexagons.
- `data/tract_city_summary.csv`: 32 US cities on census tracts. `data/tracts/<city>.geojson|csv`: their tracts.
- `data/feeds.csv` and `data/ATTRIBUTION.md`: every schedule file used, its publisher and licence link.
- **Hexagon and tract values are not comparable.** The unit changes the numbers.
- **Classes and ranks are relative to each city.** Do not compare them between cities.
- The release contains no phone-location data and nothing derived from it.

## Website

`python scripts/build_site.py --data data --site site --out _site` assembles the site. GitHub Actions deploys it to
Pages. It sets no cookies and runs no analytics.

## Cite

The paper is in preparation. Until it is published, please cite this repository (`CITATION.cff`).
