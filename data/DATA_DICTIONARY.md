# Data dictionary

Licence: ODbL 1.0 (`LICENSE.md`). Sources: `ATTRIBUTION.md`. Method: `../docs/method.md`. Limits: `../docs/limits.md`.

Three rules for every file:
- **Classes and ranks are relative to each city.** Do not compare them between cities.
- **Hexagon and tract values are not comparable.** The unit changes the numbers.
- An empty value means "not assessed" or "not defined". It never means zero.

## `cells/<city>.geojson`, `cells/<city>.csv` (71 cities, H3 resolution-8 hexagons)

Source: the paper's 71-city run (project run SA-103), per-city cell and sector tables. `s`, `q`, `a` are computed from the sector table.
Values are rounded for file size (shares to 4 decimals, residents to 3); counts are exact.

| Column | Meaning |
|---|---|
| `city` | City key (lower case, no spaces) |
| `cell_id` | H3 index, resolution 8 |
| `lat`, `lon` | Hexagon centre, WGS84 |
| `residents` | Residents in the hexagon (source per city: `population_source` in `city_summary.csv`) |
| `is_origin` | True if the hexagon has at least 100 residents. Only origins are assessed. |
| `residents_un_served` | Residents inside the UN-rule stop buffers |
| `coverage_un_pct` | `residents_un_served` as a percentage of `residents` |
| `coverage_label_pct` | Percentage of residents inside the label-rule buffers (per agency; in US cities, the project's stored stop file). Sets the class. |
| `access_pct` | Percentage of the city's mapped places that transit reaches within 30 minutes |
| `coverage_rank`, `access_rank` | Within-city percentile rank (0 to 100) of `coverage_label_pct` and `access_pct` among origins |
| `class` | Full Service, Stranded Infrastructure, Efficient Network or Transit Desert. Empty for hexagons that are not origins. |
| `places_in_cell` | Mapped OpenStreetMap places in the hexagon |
| `dist_centre_km` | Great-circle distance to the city centre point |
| `n_car_directions` | Compass directions (of 8) in which a car reaches at least 5 hexagons within 30 minutes |
| `n_blocked` | Of those, directions in which transit reaches no hexagon within 30 minutes |
| `blocked_share` | `n_blocked / n_car_directions`. Empty if `n_car_directions` is 0. |
| `half_blocked` | True if `blocked_share` is 0.5 or more |
| `n_missing` | Blocked directions that no route leaves towards |
| `n_dead` | Blocked directions that a route leaves towards |
| `n_thin` | Served directions where transit reaches a smaller share of the car's hexagons than the city's Full Service median |
| `s` | Served directions divided by car-reachable directions (`1 − blocked_share`) |
| `q` | In served directions, hexagons transit reaches divided by hexagons a car reaches, averaged. Empty if `s` is 0. |
| `a` | `s × q` |

To recompute a city's headline: among rows with `is_origin` and `n_car_directions > 0`, sum `residents_un_served` where
`blocked_share >= 0.5` and divide by the sum over all those rows. Rounding moves the result by less than 0.000001.

## `tracts/<city>.geojson`, `tracts/<city>.csv` (32 US cities, census tracts)

Source: the paper's US tract analysis (project runs SA-7 for directions and SA-97 for labels). Geometry is simplified (15 m).

| Column | Meaning |
|---|---|
| `city`, `geoid` | City key; 11-digit census tract code. 17 tracts belong to two cities, so join on both. |
| `residents` | American Community Survey 2024 tract population |
| `coverage_pct` | Percentage of residents inside the label-rule buffers (US agency rule: 500 m bus, 1,000 m rail). Not the UN per-stop rule. |
| `access_pct` | Percentage of the city's mapped places that transit reaches within 30 minutes |
| `coverage_rank`, `access_rank` | Within-city percentile ranks |
| `class` | As for hexagons. Empty for 70 tracts without a class. |
| `n_car_directions`, `n_blocked`, `blocked_share`, `half_blocked`, `n_missing`, `n_dead`, `n_thin`, `s`, `q`, `a` | As for hexagons, with tracts in place of hexagons |

## `city_summary.csv` (71 rows, hexagons)

Source: project run SA-103, `results_by_city.csv`. File paths are replaced by plain source labels; `city_name` and `data_caveat` are added.

| Column | Meaning |
|---|---|
| `city`, `city_name`, `country`, `region` | City key, display name, country, world region |
| `group` | `us` (32), `world` (24), `pilot` (10) or `earlier` (5): the batch in which the city was added |
| `us` | True for US cities |
| `relaxed`, `relaxations` | True if the city's schedule files miss one of the selection rules (official, recent, complete, one file); the project's own note |
| `data_caveat` | The same note in plain words, plus feed warnings for four other cities |
| `run_date` | Service day |
| `residents`, `boundary_area_km2`, `n_cells`, `n_origins` | Residents inside the outline; its area; hexagons; hexagons with at least 100 residents |
| `population_source` | Population data set and how it was assigned to hexagons |
| `un_coverage_share` | Share of residents inside the UN-rule buffers |
| `agency_rule_coverage_share` | Share inside the per-agency buffers on stops served on the service day |
| `stored_stops_coverage_share` | US only: share inside the per-agency buffers on the project's stored stop file (the label rule) |
| `headline_share_un` | **Headline.** Share of UN-served residents who live where at least half of the car-reachable directions are blocked |
| `headline_served_blocked_half_un`, `headline_served_denominator_un` | Numerator and denominator of the headline, in residents |
| `headline_served_outside_denominator_un` | Share of UN-served residents left out of the denominator (hexagons under 100 residents, or with no car-reachable direction) |
| `headline_cells_blocked_half` | Origins with a blocked share of 0.5 or more |
| `headline_share_agency_rule`, `headline_share_stored_stops` | The headline under the two other coverage rules |
| `n_SI`, `n_FS`, `residents_SI` | Stranded Infrastructure and Full Service hexagons; residents in Stranded Infrastructure hexagons |
| `median_blocked_SI`, `median_blocked_FS`, `mean_blocked_SI`, `mean_blocked_FS` | Blocked share by class |
| `r`, `p` | Rank-biserial r (above 0: Stranded Infrastructure is more blocked) and the two-sided Mann-Whitney p. Hexagons are not independent; read p with care. |
| `beta_dist`, `beta_dist_ci_lo`, `beta_dist_ci_hi`, `beta_dist_p` | Difference in blocked share, Stranded Infrastructure minus Full Service, at equal distance from the centre (OLS, B-spline of distance, HC1), with 95% interval |
| `beta_dist_cluster_ci_lo`, `beta_dist_cluster_ci_hi` | The same interval with errors clustered on H3 resolution-6 parents |
| `S_SI`, `S_FS`, `Q_SI`, `Q_FS`, `dlnA` | Group means of `s`; `mean(a) / mean(s)`; log gap in mean `a` between the classes |
| `direction_share`, `direction_share_raw` | Part of the log gap in `a` that comes from `s` (missing directions). `direction_share` is empty where not defined; `_raw` keeps the computed value. |
| `direction_share_defined`, `direction_share_note` | False in 6 cities where Stranded Infrastructure has the higher mean `a` |
| `direction_share_ci_lo`, `direction_share_ci_hi` | 95% percentile bootstrap (1,000 resamples within class, seed 103) |
| `direction_share_geometric` | The same share from geometric means over hexagons with `s > 0` (a check) |
| `radial_routekm_share_30deg`, `routes_within_2km_share`, `n_routes_radiality` | Share of route length that points within 30° of the centre; share of routes passing within 2 km of it; routes counted. These depend on the centre point chosen. |
| `centre_lat`, `centre_lon`, `centre_osm_node`, `centre_rule` | City centre: the OpenStreetMap `place=city` point of the city name |
| `routing_source` | Whether travel times were computed in the 71-city run or reused from an earlier project run |
| `si_failure_share_missing`, `_dead`, `_thin` | Among failing directions of Stranded Infrastructure hexagons, the share of each type |

## `tract_city_summary.csv` (32 rows, census tracts)

Source: project run SA-97 (labels rebuilt on the current travel times) and its stored tables.

| Column | Meaning |
|---|---|
| `n_tracts`, `n_SI`, `n_FS`, `n_EN`, `n_desert` | Tracts in the city and by class |
| `n_SI_with_car_directions`, `n_FS_with_car_directions` | Tracts of each class with at least one car-reachable direction |
| `median_blocked_SI`, `median_blocked_FS` | Median blocked share by class |
| `residents_SI`, `share_city_residents_SI` | Residents in Stranded Infrastructure tracts, and as a share of the city |
| `n_SI_half_blocked`, `residents_SI_half_blocked` | Stranded Infrastructure tracts with a blocked share of 0.5 or more, and their residents |
| `S_SI`, `S_FS`, `Q_SI`, `Q_FS`, `direction_share` | As in `city_summary.csv`, on tracts |
| `direction_share_eligible`, `direction_share_small_gap`, `direction_share_reversed` | Flags from the stored split table |
| `labels_old_input_known` | False in 13 cities where the travel times behind the project's earlier labels could not be recovered. The labels here use the current travel times in all 32. |

## `feeds.csv`
One row per schedule file used: `city`, `feed_file`, `catalogue`, `feed_id`, `catalogue_url`, `publisher`, `official_feed_flag`, `licence_url`, `licence_note`.

## `cities.json`
The website's index: a subset of `city_summary.csv` and `tract_city_summary.csv`, plus `cells_public` (false for the five cities whose cell layers are held back on the website) and `has_tracts`.
