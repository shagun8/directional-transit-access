# Test fixture

Real files copied from the data release, not made-up values:

- `cities.json`: the entries for Jerusalem, Kigali, Santa Ana and Chennai, unchanged.
- `cells/`: Jerusalem, Kigali and Santa Ana, unchanged.
- `tracts/`: Santa Ana, unchanged (covers the census-tract path).
- `city_summary.csv`, `tract_city_summary.csv`: the rows for these cities, unchanged.

Chennai is a held city. Its cell files are **not** in this fixture and must not be added.
The test writes an empty placeholder file for it at run time to prove the build leaves it out.
