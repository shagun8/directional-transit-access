# What this map shows
- Most transit scores ask one question: is a stop near where people live?
- This map asks a second question: from that stop, which directions can you travel?
- For each small area we look in eight compass directions.
- A direction counts if a car reaches at least five other areas that way within 30 minutes.
- A direction is blocked if transit, leaving between 08:00 and 09:00 on a weekday, reaches none of them within 30 minutes.
- Blocked share = blocked directions divided by the directions a car can reach.
# The headline number for a city
- Start with the residents the UN transit indicator (SDG 11.2.1) counts as served: within 500 m of a bus or tram stop, or 1,000 m of a rail, metro, ferry or marked rapid-bus stop.
- The headline is the share of those residents who live in areas where at least half of the directions a car can reach are blocked.
# The four classes
- Coverage is the share of an area's residents near a stop. Access is the share of the city's mapped places that transit reaches within 30 minutes.
- Each is split at the city's own median. That gives four classes: Full Service (high coverage, high access), Stranded Infrastructure (high coverage, low access), Efficient Network (low coverage, high access) and Transit Desert (low coverage, low access).
- Classes are relative to each city. Do not compare classes or ranks between cities.
# Why a direction fails
- Missing: no route leaves the area in that direction.
- Dead: a route points that way but reaches nothing within 30 minutes.
- Thin: transit reaches something, but less than is typical for Full Service areas in the same city.
# Direction or distance
- s is the share of car-reachable directions that transit serves.
- q is, in the served directions, the places transit reaches divided by the places a car reaches.
- s times q is transit reach relative to car reach.
# Units
- 71 cities are mapped on hexagons (H3 resolution 8, under 1 square kilometre each).
- 32 US cities are also mapped on census tracts.
- Hexagon and tract values are not comparable. The unit changes the numbers.
# Limits
- Car times are free-flow. Congestion is not modelled, so a car reaches more than it would in traffic.
- Travel times run from the centre of one area to the centre of another.
- One threshold is used: 30 minutes. With 45 minutes far fewer directions are blocked.
- One time window is used: a weekday, 08:00 to 09:00, median travel time.
- Schedule files miss informal transit in many cities. Some cities use older or unofficial files; their pages carry a data caveat.
- Places are all mapped OpenStreetMap features, so they follow how complete the map is in each city.
- City boundaries differ: urban centres outside the US, city tract sets in the US.
- Population comes from WorldPop 2020 in most cities, Meta HRSL 2020 in Chennai and Delhi, the 2020 US Census for US hexagons and the 2024 American Community Survey for US tracts.
# Data, code and licence
- Code is released under the MIT licence. Data are released under the Open Database License (ODbL) 1.0.
- Sources and their licences are listed in the attribution file.
- This site sets no cookies and runs no analytics. Background map tiles come from OpenFreeMap.
# How to cite
- The paper is in preparation. Until it is published, please cite the code and data repository.
