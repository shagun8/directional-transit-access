"""Regression: the indicator stage reproduces the published Jerusalem results exactly.

Inputs: the stage files of a full dtaccess run on Jerusalem (cells with residents, coverage and places; route
presence; transit and car travel times from r5py 1.1.7 / R5 7.5.1). No Java is needed here.
Expected: the stored outputs of the paper's 71-city run for Jerusalem (cell table, sector table, city row).
The same full run, started from the raw inputs, is covered by tests/test_e2e_routing.py.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from dtaccess import classify_from_cache

HERE = os.path.join(os.path.dirname(__file__), "data", "jerusalem")
SRC = {"uid": "cell_id", "pop": "population", "quadrant": "class"}   # tool name -> name in the stored file


@pytest.fixture(scope="module")
def res():
    return classify_from_cache(os.path.join(HERE, "cache"))


@pytest.fixture(scope="module")
def expected_cells():
    return pd.read_csv(os.path.join(HERE, "expected", "sa103_cells_jerusalem_res8.csv"))


@pytest.fixture(scope="module")
def row():
    return json.load(open(os.path.join(HERE, "expected", "sa103_city_row.json")))


def test_cells_identical(res, expected_cells):
    T, E = res["cells"], expected_cells
    assert list(T.uid) == list(E.cell_id)
    assert (T.quadrant.fillna("NA").values == E["class"].fillna("NA").values).all()
    assert (T.is_origin.values == E.is_origin.values).all()
    for col in ["pop", "cov_un", "coverage_pct_un", "coverage_pct", "accessibility_pct", "coverage_percentile", "accessibility_percentile",
                "n_poi", "dist_cbd_km", "n_feasible", "n_blocked", "blocked_share", "n_missing", "n_dead", "n_thin"]:
        a = T[col].astype(float).values; b = E[SRC.get(col, col)].astype(float).values
        assert np.array_equal(np.isnan(a), np.isnan(b)), col
        assert np.allclose(a, b, rtol=0, atol=1e-9, equal_nan=True), col


def test_sectors_identical(res):
    E = pd.read_csv(os.path.join(HERE, "expected", "sa103_sectors_main.csv")).sort_values(["uid", "sector"]).reset_index(drop=True)
    T = res["sectors"].sort_values(["uid", "sector"]).reset_index(drop=True)
    assert len(T) == len(E)
    for col in ["car_reach", "transit_reach", "n_route_dirs"]:
        assert (T[col].values == E[col].values).all(), col
    assert (T.ftype.values == E.ftype.values).all()


def test_headline_and_coverage(res, row):
    s = res["summary"]; h = s["headline"]["un"]
    assert h["share"] == pytest.approx(row["headline_share_un"], abs=1e-12)
    assert h["served_residents_blocked_half"] == pytest.approx(row["headline_served_blocked_half_un"], abs=1e-6)
    assert h["served_residents_denominator"] == pytest.approx(row["headline_served_denominator_un"], abs=1e-6)
    assert s["headline"]["cells_blocked_half"] == row["headline_cells_blocked_half"]
    assert s["coverage"]["un_share"] == pytest.approx(row["un_coverage_share"], abs=1e-12)
    assert s["city"]["n_cells"] == row["n_cells"] and s["city"]["n_origins"] == row["n_origins"]


def test_si_vs_fs(res, row):
    v = res["summary"]["si_vs_fs"]
    assert (v["n_SI"], v["n_FS"]) == (row["n_SI"], row["n_FS"])
    for a, b in [("median_blocked_SI", "median_blocked_SI"), ("median_blocked_FS", "median_blocked_FS"), ("mean_blocked_SI", "mean_blocked_SI"),
                 ("mean_blocked_FS", "mean_blocked_FS"), ("rank_biserial_r", "r")]:
        assert v[a] == pytest.approx(row[b], abs=1e-12), a
    b = v["si_effect_at_equal_distance"]
    assert b["beta"] == pytest.approx(row["beta_dist"], abs=1e-9)
    assert b["ci_lo"] == pytest.approx(row["beta_dist_ci_lo"], abs=1e-9) and b["ci_hi"] == pytest.approx(row["beta_dist_ci_hi"], abs=1e-9)
    assert b["cluster_ci_lo"] == pytest.approx(row["beta_dist_cluster_ci_lo"], abs=1e-9)
    assert v["failure_shares_SI"] == {k: row[f"si_failure_share_{k}"] for k in ["missing", "dead", "thin"]}


def test_exact_split(res, row):
    x = res["summary"]["split"]
    for k in ["S_SI", "S_FS", "Q_SI", "Q_FS", "dlnA", "direction_share", "direction_share_geometric"]:
        assert x[k] == pytest.approx(row[k], abs=1e-12), k
    assert x["direction_share_defined"] is True
    # seeded bootstrap (1,000 resamples, seed 103)
    assert x["direction_share_ci_lo"] == pytest.approx(row["direction_share_ci_lo"], abs=1e-9)
    assert x["direction_share_ci_hi"] == pytest.approx(row["direction_share_ci_hi"], abs=1e-9)


def test_identity_s_times_q(res):
    U = res["cells"].dropna(subset=["s"])
    assert np.allclose(U.a, U.s * U.q.fillna(0), atol=1e-12)
    assert np.allclose(1 - U.s, U.blocked_share, atol=1e-12)
