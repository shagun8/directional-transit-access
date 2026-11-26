"""Stage 4: from cell inputs, route presence and travel times to labels, blocked directions and the city summary.

No routing happens here. `classify_from_cache` re-runs this stage from the files a routed run leaves in `<out>/cache/`.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy import stats

from . import __version__
from .geo import bearing, hav
from .settings import Settings
from .split import SI, FS, unit_table, direction_share

CLASSES = [FS, SI, "Efficient Network", "Transit Desert"]

# column names in the written cell table  <-  internal names
CELL_COLUMNS = {
    "uid": "cell_id", "lat": "lat", "lon": "lon", "pop": "residents", "is_origin": "is_origin", "cov_un": "residents_un_served",
    "coverage_pct_un": "coverage_un_pct", "coverage_pct": "coverage_label_pct", "accessibility_pct": "access_pct",
    "coverage_percentile": "coverage_rank", "accessibility_percentile": "access_rank", "quadrant": "class", "n_poi": "places_in_cell",
    "dist_cbd_km": "dist_centre_km", "n_feasible": "n_car_directions", "n_blocked": "n_blocked", "blocked_share": "blocked_share",
    "n_missing": "n_missing", "n_dead": "n_dead", "n_thin": "n_thin", "s": "s", "q": "q", "a": "a", "half_blocked": "half_blocked",
}
ROUND = {"lat": 5, "lon": 5, "residents": 3, "residents_un_served": 3, "coverage_un_pct": 2, "coverage_label_pct": 2, "access_pct": 4,
         "coverage_rank": 2, "access_rank": 2, "dist_centre_km": 2, "blocked_share": 4, "s": 4, "q": 5, "a": 6}


def compact(m: pd.DataFrame, uids) -> pd.DataFrame:
    """Travel-time table with ids as categoricals on the cell list. Unreachable pairs are absent, never zero."""
    m = m.dropna(subset=["travel_time"])
    return pd.DataFrame({"from_id": pd.Categorical(m.from_id.astype(str).values, categories=uids),
                         "to_id": pd.Categorical(m.to_id.astype(str).values, categories=uids),
                         "travel_time": m.travel_time.astype("float32").values})


def rank_biserial(a, b):
    """Rank-biserial r (> 0 means a is larger) and the two-sided Mann-Whitney p."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return np.nan, np.nan
    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    return 2 * u.statistic / (len(a) * len(b)) - 1, u.pvalue


def _ols_si(formula, df, cluster=None):
    import statsmodels.formula.api as smf
    try:
        if cluster:
            m = smf.ols(formula, df).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df[cluster])[0]})
        else:
            m = smf.ols(formula, df).fit(cov_type="HC1")
        ci = m.conf_int().loc["SI"]
        return {"beta": float(m.params["SI"]), "ci": [float(ci[0]), float(ci[1])], "p": float(m.pvalues["SI"]), "n": int(m.nobs)}
    except Exception as e:  # too few cells or a singular design: report, do not hide
        return {"beta": np.nan, "ci": [np.nan, np.nan], "p": np.nan, "n": 0, "error": repr(e)[:150]}


def _sector_counts(m, lat, lon, uids, thr, name, n_sectors):
    r = m[m.travel_time <= thr]
    oi = r.from_id.cat.codes.values; di = r.to_id.cat.codes.values
    k = oi != di; oi, di = oi[k], di[k]
    sec = (bearing(lat[oi], lon[oi], lat[di], lon[di]) / (360.0 / n_sectors)).astype(int) % n_sectors
    return pd.DataFrame({"uid": uids[oi], "sector": sec}).groupby(["uid", "sector"]).size().rename(name).reset_index()


def label_cells(U: pd.DataFrame, tr_m: pd.DataFrame, settings: Settings):
    """Access (share of the city's places transit reaches within the threshold) and the four classes.
    A cell is high on a measure only if its value is above zero and its within-city percentile is at or above the median."""
    T = settings.threshold_min
    reach = tr_m[tr_m.travel_time <= T]
    has_any = tr_m.from_id.astype(str).unique()      # origins with no routed pair at all get no access value
    poi = U.set_index("uid")["n_poi"]
    acc = reach.assign(p=reach.to_id.astype(str).map(poi)).groupby(reach.from_id.astype(str)).p.sum()
    U["accessibility_pct"] = np.where(U.is_origin & U.uid.isin(has_any), 100 * U.uid.map(acc).fillna(0) / U["n_poi"].sum(), np.nan)
    O_ = U.is_origin & U.accessibility_pct.notna() & U.coverage_pct.notna()
    cv_, av_ = U.loc[O_, "coverage_pct"], U.loc[O_, "accessibility_pct"]
    cp = cv_.rank(pct=True, method="average") * 100; apc = av_.rank(pct=True, method="average") * 100
    hc, ha = (cp >= cp.median()) & (cv_ > 0), (apc >= apc.median()) & (av_ > 0)
    moved = {"zero_coverage_at_or_above_median": int(((cv_ == 0) & (cp >= cp.median())).sum()),
             "zero_access_at_or_above_median": int(((av_ == 0) & (apc >= apc.median())).sum()), "n_origins": int(len(hc))}
    q = pd.Series(np.select([hc & ha, hc & ~ha, ~hc & ha], [FS, SI, "Efficient Network"], "Transit Desert"), index=cp.index)
    U["coverage_percentile"], U["accessibility_percentile"], U["quadrant"] = cp, apc, q
    return U, moved


def classify(U: pd.DataFrame, presence: pd.DataFrame, tr_m: pd.DataFrame, car_m: pd.DataFrame, centre=None,
             settings: Settings = None) -> dict:
    """Run stage 4.

    U: one row per cell, in the cell-list order: uid, lat, lon, pop, is_origin, cov, cov_un, cov_ag, coverage_pct,
       coverage_pct_un, n_poi, and optionally dist_cbd_km.
    presence: uid, sector, n_route_dirs (routes leaving the cell in that direction, 08:00-08:59).
    tr_m, car_m: compact travel-time tables (see `compact`).
    centre: (lat, lon) or None. Used only for the distance-controlled SI effect.
    Returns {"cells": DataFrame, "sectors": DataFrame, "summary": dict}.
    """
    S = settings or Settings()
    U = U.copy().reset_index(drop=True); uids = U.uid.values
    assert list(tr_m.from_id.cat.categories) == list(uids) and list(car_m.from_id.cat.categories) == list(uids), "travel times and cells differ"
    T, NS = S.threshold_min, S.n_sectors
    if "dist_cbd_km" not in U.columns:
        U["dist_cbd_km"] = hav(U.lat.values, U.lon.values, centre[0], centre[1]) if centre is not None else np.nan
    if centre is not None:   # the published city table ran the distance control on the centre rounded to five decimals (about 1 m)
        centre = (round(float(centre[0]), 5), round(float(centre[1]), 5))
    U, moved = label_cells(U, tr_m, S)

    # ---- sectors: counts of cells reached within the threshold, by compass sector of the destination
    LAT, LON = U.lat.values, U.lon.values
    orig = U[U.is_origin]
    full = pd.MultiIndex.from_product([orig.uid, range(NS)], names=["uid", "sector"]).to_frame(index=False)
    c = full.merge(_sector_counts(car_m, LAT, LON, uids, T, "car_reach", NS), on=["uid", "sector"], how="left") \
            .merge(_sector_counts(tr_m, LAT, LON, uids, T, "transit_reach", NS), on=["uid", "sector"], how="left") \
            .fillna({"car_reach": 0, "transit_reach": 0})
    c = c.merge(presence, on=["uid", "sector"], how="left").fillna({"n_route_dirs": 0})
    c["feasible"] = c.car_reach >= S.min_car
    c["blocked"] = c.feasible & (c.transit_reach == 0)
    c["ftype"] = np.where(~c.feasible, "infeasible", np.where(c.blocked, np.where(c.n_route_dirs > 0, "dead", "missing"), "served"))
    c["reach_ratio"] = np.where(c.ftype == "served", c.transit_reach / c.car_reach.replace(0, np.nan), np.nan)
    c = c.merge(U[["uid", "quadrant"]].rename(columns={"quadrant": "q"}), on="uid")
    thin_thr = c[(c.ftype == "served") & (c.q == FS)].reach_ratio.median()   # the city's Full Service median
    c.loc[(c.ftype == "served") & (c.reach_ratio < thin_thr), "ftype"] = "thin"
    t = c.groupby("uid").agg(n_feasible=("feasible", "sum"), n_blocked=("blocked", "sum"), car_dest=("car_reach", "sum"),
                             n_missing=("ftype", lambda s: (s == "missing").sum()), n_dead=("ftype", lambda s: (s == "dead").sum()),
                             n_thin=("ftype", lambda s: (s == "thin").sum())).reset_index()
    t["blocked_share"] = t.n_blocked / t.n_feasible.replace(0, np.nan)
    ut = unit_table(c)
    U = U.merge(t, on="uid", how="left").merge(ut[["s", "q", "a"]], left_on="uid", right_index=True, how="left")
    in_den = U.is_origin & (U.n_feasible.fillna(0) > 0)
    U["half_blocked"] = (U.blocked_share >= 0.5).where(in_den).astype("boolean")

    # ---- city summary
    out = {"n_cells": len(U), "n_origins": int(U.is_origin.sum()), "residents": float(U["pop"].sum())}
    if "cov_ag" not in U.columns:
        U["cov_ag"] = U["cov"]
    cov = {"un_share": float(U.cov_un.sum() / U["pop"].sum()), "label_rule_share": float(U["cov"].sum() / U["pop"].sum()),
           "agency_rule_share": float(U.cov_ag.sum() / U["pop"].sum())}
    dc = U[in_den]; head = {}
    for nm, col in [("un", "cov_un"), ("label_rule", "cov"), ("agency_rule", "cov_ag")]:
        tot = float(U[col].sum()); den = float(dc[col].sum()); num = float(dc.loc[dc.blocked_share >= 0.5, col].sum())
        head[nm] = {"share": num / den if den else np.nan, "served_residents_blocked_half": num, "served_residents_denominator": den,
                    "served_share_outside_denominator": 1 - den / tot if tot else np.nan}
    head["cells_blocked_half"] = int((dc.blocked_share >= 0.5).sum())
    sf = U[U.quadrant.isin([SI, FS])]; v = sf.dropna(subset=["blocked_share"])
    si, fs = v[v.quadrant == SI].blocked_share, v[v.quadrant == FS].blocked_share
    r, p = rank_biserial(si, fs)
    sivfs = {"n_SI": int((sf.quadrant == SI).sum()), "n_FS": int((sf.quadrant == FS).sum()),
             "residents_SI": float(sf[sf.quadrant == SI]["pop"].sum()), "residents_FS": float(sf[sf.quadrant == FS]["pop"].sum()),
             "median_blocked_SI": float(si.median()) if len(si) else np.nan, "median_blocked_FS": float(fs.median()) if len(fs) else np.nan,
             "mean_blocked_SI": float(si.mean()) if len(si) else np.nan, "mean_blocked_FS": float(fs.mean()) if len(fs) else np.nan,
             "rank_biserial_r": r, "mann_whitney_p": p, "thin_threshold": float(thin_thr) if pd.notna(thin_thr) else np.nan}
    if centre is not None and len(si) >= 3 and len(fs) >= 3:
        import h3
        vv = v.assign(SI=(v.quadrant == SI).astype(int), dist=hav(v.lat.values, v.lon.values, centre[0], centre[1]),
                      parent6=[h3.cell_to_parent(x, 6) for x in v.uid])
        kn = tuple(np.round(np.percentile(vv.dist, [20, 40, 60, 80]), 4)); spl = f"bs(dist, knots={kn}, degree=3)"
        b = _ols_si(f"blocked_share ~ SI + {spl}", vv); bc = _ols_si(f"blocked_share ~ SI + {spl}", vv, cluster="parent6")
        sivfs["si_effect_at_equal_distance"] = {"beta": b["beta"], "ci_lo": b["ci"][0], "ci_hi": b["ci"][1], "p": b["p"], "n": b["n"],
                                                "cluster_ci_lo": bc["ci"][0], "cluster_ci_hi": bc["ci"][1]}
        if "error" in b: sivfs["si_effect_at_equal_distance"]["error"] = b["error"]
    for lab, qq in [("SI", SI), ("FS", FS)]:
        fc = c[(c.q == qq) & c.ftype.isin(["missing", "dead", "thin"])].ftype.value_counts()
        sivfs[f"failure_cells_{lab}"] = {k: int(fc.get(k, 0)) for k in ["missing", "dead", "thin"]}
        sivfs[f"failure_shares_{lab}"] = {k: round(int(fc.get(k, 0)) / max(int(fc.sum()), 1), 4) for k in ["missing", "dead", "thin"]}
    split = direction_share(ut, U.set_index("uid").quadrant, boot=S.boot, seed=S.seed)
    summary = {"tool": {"name": "dtaccess", "version": __version__}, "settings": S.as_dict(), "city": out, "coverage": cov, "headline": head,
               "classes": {"counts": {k: int(v_) for k, v_ in U.quadrant.value_counts().items()},
                           "residents": {k: float(v_) for k, v_ in U.groupby("quadrant")["pop"].sum().items()},
                           "tie_rule_cells_moved": moved},
               "si_vs_fs": sivfs, "split": split}
    return {"cells": U, "sectors": c, "summary": summary}


def _json(o):
    if isinstance(o, dict): return {str(k): _json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_json(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


def cell_table(U: pd.DataFrame, rounded: bool = True) -> pd.DataFrame:
    """The public cell table (plain column names). Wealth, device or other outside columns are never written."""
    D = U[[k for k in CELL_COLUMNS if k in U.columns]].rename(columns=CELL_COLUMNS).copy()
    for k in ["n_car_directions", "n_blocked", "n_missing", "n_dead", "n_thin"]:
        D[k] = D[k].astype("Int64")
    if rounded:
        for k, p in ROUND.items():
            D[k] = D[k].round(p)
    return D


def write_outputs(res: dict, out_dir: str, extra: dict = None) -> dict:
    """Write cells (GeoJSON, CSV, Parquet), sectors (Parquet) and summary.json into out_dir."""
    import h3
    os.makedirs(out_dir, exist_ok=True)
    D = cell_table(res["cells"])
    D.to_csv(f"{out_dir}/cells.csv", index=False)
    cell_table(res["cells"], rounded=False).to_parquet(f"{out_dir}/cells.parquet", index=False)
    res["sectors"].to_parquet(f"{out_dir}/sectors.parquet", index=False)
    feats = []
    for rec in json.loads(D.to_json(orient="records")):
        ring = [[round(lo, 6), round(la, 6)] for la, lo in h3.cell_to_boundary(rec["cell_id"])]; ring.append(ring[0])
        feats.append({"type": "Feature", "properties": rec, "geometry": {"type": "Polygon", "coordinates": [ring]}})
    json.dump({"type": "FeatureCollection", "features": feats}, open(f"{out_dir}/cells.geojson", "w"), separators=(",", ":"))
    summary = dict(res["summary"])
    if extra: summary.update(extra)
    json.dump(_json(summary), open(f"{out_dir}/summary.json", "w"), indent=1)
    return summary


def classify_from_cache(cache_dir: str, out_dir: str = None, settings: Settings = None) -> dict:
    """Re-run stage 4 from a routed run's cache folder (cell_inputs.parquet, route_presence.parquet, ttm_transit.parquet,
    ttm_car.parquet, stage_meta.json). Writes outputs if out_dir is given."""
    U = pd.read_parquet(f"{cache_dir}/cell_inputs.parquet")
    uids = U.uid.values
    pres = pd.read_parquet(f"{cache_dir}/route_presence.parquet")
    tr = compact(pd.read_parquet(f"{cache_dir}/ttm_transit.parquet"), uids)
    car = compact(pd.read_parquet(f"{cache_dir}/ttm_car.parquet"), uids)
    meta = json.load(open(f"{cache_dir}/stage_meta.json"))
    cen = meta.get("centre") or {}
    centre = (cen["lat"], cen["lon"]) if cen.get("lat") is not None else None
    res = classify(U, pres, tr, car, centre=centre, settings=settings)
    res["summary"]["inputs"] = meta
    if out_dir:
        write_outputs(res, out_dir, {"inputs": meta})
    return res
