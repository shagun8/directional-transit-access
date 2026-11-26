"""Full run from raw inputs (cells, feeds, places, routing with R5, indicators) against the published Jerusalem results.

Not run in CI: it needs Java 21, r5py 1.1.7, the R5 7.5.1 jar and about 300 MB of inputs.
    python scripts/download_regression_inputs.py --out inputs/jerusalem
    DTACCESS_E2E_DIR=inputs/jerusalem pytest -m e2e
Travel times only match pair for pair with the same OpenStreetMap snapshot and schedule file (checksums in
tests/data/jerusalem/inputs.json).
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

D = os.environ.get("DTACCESS_E2E_DIR")
HERE = os.path.join(os.path.dirname(__file__), "data", "jerusalem")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not D, reason="set DTACCESS_E2E_DIR to the folder with the downloaded inputs")]


def test_full_run_reproduces_published_city(tmp_path):
    from dtaccess import run_city
    meta = json.load(open(os.path.join(HERE, "inputs.json")))
    out = str(tmp_path / "jerusalem")
    run_city([os.path.join(D, meta["gtfs"]["file"])], os.path.join(D, meta["osm"]["file"]), os.path.join(HERE, "inputs", "boundary.geojson"), out,
             population=os.path.join(D, meta["population"]["file"]), date=meta["run_date"], centre_names=meta["centre_names"],
             r5_jar=os.path.join(D, meta["r5_jar"]["file"]) if os.path.exists(os.path.join(D, meta["r5_jar"]["file"])) else None)
    T = pd.read_parquet(f"{out}/cells.parquet"); E = pd.read_csv(os.path.join(HERE, "expected", "sa103_cells_jerusalem_res8.csv"))
    assert list(T.cell_id) == list(E.cell_id)
    assert (T["class"].fillna("NA").values == E["class"].fillna("NA").values).all()
    for a, b in [("residents", "population"), ("coverage_un_pct", "coverage_pct_un"), ("access_pct", "accessibility_pct"), ("blocked_share", "blocked_share"),
                 ("n_missing", "n_missing"), ("n_dead", "n_dead"), ("n_thin", "n_thin"), ("places_in_cell", "n_poi")]:
        assert np.allclose(T[a].astype(float), E[b].astype(float), atol=1e-9, equal_nan=True), a
    for nm in ["transit", "car"]:
        new = pd.read_parquet(f"{out}/cache/ttm_{nm}.parquet").astype({"from_id": str, "to_id": str})
        old = pd.read_parquet(os.path.join(HERE, "cache", f"ttm_{nm}.parquet")).astype({"from_id": str, "to_id": str})
        m = new.merge(old, on=["from_id", "to_id"], how="outer", suffixes=("_new", "_old"))
        assert len(m) == len(new) == len(old) and (m.travel_time_new == m.travel_time_old).all(), nm
    row = json.load(open(os.path.join(HERE, "expected", "sa103_city_row.json"))); s = json.load(open(f"{out}/summary.json"))
    assert s["headline"]["un"]["share"] == pytest.approx(row["headline_share_un"], abs=1e-12)
