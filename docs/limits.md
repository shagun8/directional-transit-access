# Limits

Read these before using a number.

## Car times are free-flow
- Car speeds come from OpenStreetMap speed tags. Congestion is not modelled.
- A car therefore reaches more than it would in traffic, and more directions count.
- Speed tagging differs between countries.

## Travel runs from centre to centre
- Every trip starts and ends at a hexagon centre (or a tract centroid in the US tract layers).
- Walking from a real front door to a stop can be shorter or longer than from the centre.

## One threshold, one hour
- The threshold is 30 minutes. With 45 minutes far fewer directions are blocked.
- The window is one weekday hour, 08:00 to 09:00. Evenings, weekends and off-peak service are not measured.

## Schedules have gaps
- Schedule files miss informal transit in many cities.
- Some cities use older, unofficial or partial files. `data_caveat` in `data/city_summary.csv` says which and why.
- Route types are used as coded. Rail coded as tram gets the 500 m buffer.
- Feed repairs change what the routing engine reads (see `docs/method.md`). Each one is logged.

## Classes are relative
- Full Service, Stranded Infrastructure, Efficient Network and Transit Desert are split at each city's own median.
- A Full Service hexagon in one city can have less service than a Transit Desert hexagon in another.
- Stranded Infrastructure and Full Service are both above the coverage median, but not at the same coverage level.

## Units are not comparable
- Hexagon and census-tract values differ for the same city. Do not put them side by side.
- City outlines differ: urban centres outside the US, city tract sets in the US.

## Places follow the map
- Places are all mapped OpenStreetMap features, buildings included. Where the map is thin, access rests on few places.

## Population
- Sources differ by country and year (WorldPop 2020, Meta HRSL 2020, US Census 2020, American Community Survey 2024). Schedules are mostly from 2026.
- Hexagons with fewer than 100 residents are not assessed.

## Small cities
- With few hexagons, within-city statistics are noisy. Jerusalem has 96.

## The direction share
- It is unstable where the access gap between the two classes is small. It is not defined in 6 of the 71 cities and exceeds 1 in 13. Use medians and ranks across cities, not means.
