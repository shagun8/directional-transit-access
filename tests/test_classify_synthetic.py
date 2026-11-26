"""Hand-built city: one origin looking east, north and west. Every number below can be checked by hand."""
import numpy as np
import pandas as pd

from dtaccess import Settings, classify
from dtaccess.classify import compact


def _city():
    # origin O at (0, 0); a second origin P far south with no stop nearby; three groups of five empty cells
    cells = [("O", 0.0, 0.0, 1000.0, 1000.0), ("P", -0.5, 0.0, 500.0, 0.0)]
    cells += [(f"E{k}", 0.0, 0.01 * k, 0.0, 0.0) for k in range(1, 6)]      # east  -> sector 2
    cells += [(f"N{k}", 0.01 * k, 0.0, 0.0, 0.0) for k in range(1, 6)]      # north -> sector 0
    cells += [(f"W{k}", 0.0, -0.01 * k, 0.0, 0.0) for k in range(1, 6)]     # west  -> sector 6
    U = pd.DataFrame(cells, columns=["uid", "lat", "lon", "pop", "cov"])
    U["cov_un"] = U["cov"]; U["cov_ag"] = U["cov"]
    U["is_origin"] = U["pop"] >= 100
    U["coverage_pct"] = np.where(U["pop"] > 0, 100 * U["cov"] / U["pop"].replace(0, np.nan), np.nan)
    U["coverage_pct_un"] = U["coverage_pct"]
    U["n_poi"] = 10
    car = [("O", u, 10.0) for u in U.uid if u not in ("O", "P")] + [("O", "O", 0.0), ("P", "P", 0.0)]
    tr = [("O", "O", 0.0), ("O", "E1", 12.0), ("O", "E2", 25.0), ("O", "E3", 31.0),      # east: 2 of 5 within 30 min
          ("O", "N1", 45.0),                                                                # north: a route, but nothing within 30
          ("P", "P", 0.0)]
    f = lambda rows: compact(pd.DataFrame(rows, columns=["from_id", "to_id", "travel_time"]), U.uid.values)
    pres = pd.DataFrame({"uid": ["O", "O"], "sector": [2, 0], "n_route_dirs": [1, 1]})
    return U, pres, f(tr), f(car)


def test_blocked_directions_and_failure_types():
    U, pres, tr, car = _city()
    res = classify(U, pres, tr, car, centre=None, settings=Settings(boot=0))
    o = res["cells"].set_index("uid").loc["O"]
    assert (o.n_feasible, o.n_blocked) == (3, 2)
    assert o.blocked_share == 2 / 3
    assert (o.n_dead, o.n_missing, o.n_thin) == (1, 1, 0)     # north: route but no reach; west: no route
    assert o.s == 1 / 3 and abs(o.q - 2 / 5) < 1e-12 and abs(o.a - 2 / 15) < 1e-12
    assert bool(o.half_blocked) is True
    sec = res["sectors"].set_index(["uid", "sector"])
    assert sec.loc[("O", 2), "ftype"] == "served" and sec.loc[("O", 0), "ftype"] == "dead" and sec.loc[("O", 6), "ftype"] == "missing"
    assert sec.loc[("O", 1), "ftype"] == "infeasible"


def test_headline_counts_served_residents_only():
    U, pres, tr, car = _city()
    s = classify(U, pres, tr, car, settings=Settings(boot=0))["summary"]
    h = s["headline"]["un"]
    # P has no car-reachable direction and no served resident; O carries the whole denominator
    assert h["served_residents_denominator"] == 1000.0 and h["served_residents_blocked_half"] == 1000.0 and h["share"] == 1.0
    assert s["coverage"]["un_share"] == 1000.0 / 1500.0


def test_zero_is_never_high():
    U, pres, tr, car = _city()
    q = classify(U, pres, tr, car, settings=Settings(boot=0))["cells"].set_index("uid").quadrant
    assert q["O"] == "Full Service"        # coverage and access above zero and at the median
    assert q["P"] != "Full Service" and q["P"] != "Stranded Infrastructure"   # zero coverage is never high


def test_unreachable_is_absent_not_zero():
    U, pres, tr, car = _city()
    tr2 = pd.concat([tr, compact(pd.DataFrame({"from_id": ["O"], "to_id": ["W1"], "travel_time": [np.nan]}), U.uid.values)], ignore_index=True)
    a = classify(U, pres, tr, car, settings=Settings(boot=0))["cells"]; b = classify(U, pres, tr2, car, settings=Settings(boot=0))["cells"]
    assert a.n_blocked.equals(b.n_blocked)
