# Method

All settings below are fixed in `src/dtaccess/settings.py`. They are the ones used for the published results.

## 1. Areas
- The city outline is filled with H3 hexagons at resolution 8 (under 1 km² each). A hexagon belongs to the city if its centre lies inside the outline.
- A hexagon is an **origin** if it has at least 100 residents. Every hexagon is a destination.

## 2. Schedules
- We keep the service that runs on one weekday (the service day). Trips listed twice with the same stops and times are counted once.
- Some schedule files break rules that the routing engine enforces. Each repair is a switch in `Repairs` and is on by default. Every repair applied is written to `summary.json`.

| Repair | What it does |
|---|---|
| `drop_exact_twin_trips` | Removes a trip that repeats another trip's route, direction, stops and times |
| `drop_trips_ge_72h` | Removes trips with a stop time of 72 hours or more |
| `flex_empty_times` | Demand-responsive feeds without stop times: times are left empty, so they never count in the 08:00 hour |
| `zero_window_frequency_as_one_departure` | A frequency entry with zero headway and start equal to end is read as one departure at the start time |
| `fill_blank_agency_id`, `fill_agency_timezone`, `placeholder_agency_url`, `fill_stop_name` | Fill required fields that routing does not use |
| `drop_duplicate_agency_id`, `drop_duplicate_frequency_rows`, `drop_empty_tables` | Remove records the routing engine rejects |
| `remap_unknown_route_types` | Route types above 1500, or unknown basic codes, are routed as bus. Coverage still uses the code in the file. |
| `drop_duplicate_keys_and_orphans`, `drop_feed_info_missing_required`, `skip_feeds_without_active_trips` | Only with `--feed-copy original` (route on the publisher's zip) |

## 3. Residents and coverage
- Residents per hexagon come from a population raster (the pixel centre decides the hexagon) or from census polygons (areal weighting).
- **UN rule** (SDG 11.2.1), per stop: 500 m around a stop served by bus or tram; 1,000 m around a stop served by rail, metro, ferry, cable car, funicular or a route the feed marks as rapid bus. Only stops served on the service day count. The route type coded in the file is used as it is.
- **Label rule**: per agency. Every stop of an agency that runs any bus route gets 500 m; stops of rail-only agencies get 1,000 m. This rule sets the class labels.
- Coverage of a hexagon is the share of its residents inside the buffers.

## 4. Places and access
- Places are every tagged OpenStreetMap point plus the centroid of every valid polygon (buildings and land use included), read with the GDAL OSM driver. They are not de-duplicated.
- **Access** of an origin is the share of the city's places in the hexagons transit reaches within 30 minutes, the origin's own hexagon included.

## 5. Travel times
- Engine: R5 7.5.1 through r5py 1.1.7. Hexagon centre to hexagon centre, snapped to the street network.
- Transit with walking: departures from 08:00 for 60 minutes, median travel time, 150-minute cap.
- Car: free-flow on the OpenStreetMap network. 60-minute cap; only times up to 30 minutes are used.
- The street network is the OpenStreetMap extract clipped to the outline plus 10 km.
- A pair with no route is absent. It is never treated as zero.

## 6. Classes
- Coverage (label rule) and access are each ranked within the city.
- A hexagon is **high** on a measure only if its value is above zero and its rank is at or above the city median.

| | High access | Low access |
|---|---|---|
| **High coverage** | Full Service | Stranded Infrastructure |
| **Low coverage** | Efficient Network | Transit Desert |

## 7. Directions
- Eight compass sectors of 45°. Sector 0 runs from north to north-east; numbering is clockwise.
- For each origin and sector we count the hexagons reached within 30 minutes, by car and by transit.
- A sector **counts** if a car reaches at least five hexagons there.
- A counting sector is **blocked** if transit reaches none.
- **Blocked share** = blocked sectors divided by counting sectors.

## 8. Why a direction fails
- A route **leaves** a hexagon in a sector if, between 08:00 and 08:59, a trip stops in the hexagon and the mean position of its later stops lies in that sector.
- **Missing**: blocked, and no route leaves in that sector.
- **Dead**: blocked, although a route leaves in that sector.
- **Thin**: served, but transit reaches a smaller share of the car's hexagons than the median served sector of the city's Full Service hexagons.

## 9. The headline
- Denominator: UN-served residents in origins that have at least one counting sector.
- Numerator: those of them in origins with a blocked share of 0.5 or more.

## 10. Direction or distance
Per origin, over counting sectors:
- `s` = served sectors divided by counting sectors.
- `q` = mean, over served sectors, of hexagons transit reaches divided by hexagons a car reaches.
- `a = s × q`.

Per group (Stranded Infrastructure, Full Service): `S = mean(s)`, `Q = mean(a) / mean(s)`, so `mean(a) = S × Q` exactly and

    ln A_FS − ln A_SI = (ln S_FS − ln S_SI) + (ln Q_FS − ln Q_SI).

The **direction share** is the first term divided by the left side. It is not defined when Stranded Infrastructure has the higher mean `a`. It can exceed 1 when `Q` is higher in Stranded Infrastructure. The interval is a percentile bootstrap (1,000 resamples within group, seed 103).

## 11. City statistics
- Stranded Infrastructure vs Full Service blocked share: medians, means, rank-biserial r and the Mann-Whitney p.
- The same contrast at equal distance from the centre: OLS of blocked share on a Stranded Infrastructure indicator and a cubic B-spline of distance to the centre (knots at the 20th, 40th, 60th and 80th percentiles), HC1 errors; also with errors clustered on H3 resolution-6 parents.
- Neighbouring hexagons share roads and routes, so the p-values overstate independence. Lead with medians and r.

## Census tracts (US, data release only)
The tract layers in `data/tracts/` come from the paper's main US analysis, not from this tool. The rules are the
same (eight sectors, 30 minutes, car gate of five, 08:00 to 08:59), with tract centroids as points, the label rule
for coverage, and American Community Survey 2024 population.
