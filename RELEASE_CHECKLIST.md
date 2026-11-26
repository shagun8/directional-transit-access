# Release checklist

State on 2026-11-26: repository private; website public; cell layers of five cities held back on the website.

## Before the repository goes public
1. **Confirm the five earlier cities.** Bamako, Chennai, Delhi, Maputo and Nouakchott use schedule files whose source and licence are not recorded (`data/feeds.csv`).
   - If confirmed open: remove the city from `site/held_cities.json`, set `cells_public` to true in `data/cities.json`, fill `data/feeds.csv`, push.
   - If not: delete `data/cells/<city>.*` for that city **before** making the repository public. The files are in the git history; rewrite the history or start the public repository from a fresh commit.
2. **Complete `CITATION.cff`.** It lists one author, taken from the GitHub profile. Add co-authors and ORCID iDs.
3. **Check the copyright line** in `LICENSE` ("The directional-transit-access authors").
4. **Add formal citations** for WorldPop, Meta HRSL and GHSL to `data/ATTRIBUTION.md` (data set names and licences are there; DOIs are not).
5. **Run** `python scripts/scan_release.py .` It must print `RESULT: clean`.

## At submission
6. Make the repository public: Settings, General, Danger Zone, Change visibility.
7. Connect Zenodo: log in at zenodo.org with GitHub, switch the repository on, then publish a GitHub release (`v1.0.0`). Zenodo mints a DOI.
8. Put the DOI in: the paper's code availability and data availability statements, `README.md`, `CITATION.cff`, `site/about.html` ("How to cite").

## Open research items that touch the release (operator decisions)
- US hexagon population is the 2020 Decennial Census (blocks), not the American Community Survey. US tract population is ACS 2024.
- At 45 minutes the headline falls to about 1% in the median city. The map shows 30 minutes only.
- The direction share exceeds 1 in 13 cities and is not defined in 6. The website does not show it.
- Radiality columns in `city_summary.csv` depend on the centre point chosen.

## Not yet verified on the website
- The real OpenFreeMap background (the test machine could not reach it).
- Phones, Chrome, Safari, screen readers.
- Most city pages were checked for loading and valid data, not viewed in a browser.
