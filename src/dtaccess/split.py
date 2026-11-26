"""Exact split of transit reach into direction and distance.

Per cell, over the directions a car can reach:
  s = served directions / car-reachable directions
  q = mean of (cells transit reaches / cells a car reaches) over served directions
  a = s * q  (the mean reach ratio over all car-reachable directions, blocked ones counting 0)
Per group (SI, FS): S = mean(s), Q = mean(a) / mean(s), so mean(a) = S * Q exactly and
  ln A_FS - ln A_SI = (ln S_FS - ln S_SI) + (ln Q_FS - ln Q_SI).
The direction share is the first term divided by the left-hand side.
"""
import numpy as np
import pandas as pd

SI, FS = "Stranded Infrastructure", "Full Service"


def unit_table(sectors: pd.DataFrame) -> pd.DataFrame:
    """sectors: one row per (uid, sector) with car_reach, transit_reach, feasible. Returns uid, n, n_served, s, q, a."""
    f = sectors[sectors.feasible].copy()
    f["served"] = f.transit_reach > 0
    f["rr"] = f.transit_reach / f.car_reach
    g = f.groupby("uid").agg(W=("sector", "size"), Ws=("served", "sum"), NUM=("rr", "sum"))
    g["s"] = g.Ws / g.W
    g["a"] = g.NUM / g.W
    g["q"] = np.where(g.Ws > 0, g.NUM / g.Ws.where(g.Ws > 0), np.nan)
    chk = float((g.a - g.s * g.q.fillna(0)).abs().max()) if len(g) else 0.0
    assert chk < 1e-12, chk
    return g.rename(columns={"W": "n", "Ws": "n_served"})[["n", "n_served", "s", "q", "a"]]


def decomp(si: pd.DataFrame, fs: pd.DataFrame) -> dict:
    """si, fs: unit tables (s, q, a) of the two groups. Primary split and a geometric-mean check."""
    r = {"n_SI": len(si), "n_FS": len(fs)}
    for k, d in [("SI", si), ("FS", fs)]:
        S = d.s.mean(); MA = d.a.mean()
        r[f"S_{k}"] = S; r[f"meanA_{k}"] = MA; r[f"Q_{k}"] = MA / S if S > 0 else np.nan
        pos = d[d.s > 0]
        r[f"mlog_s_{k}"] = float(np.log(pos.s).mean()) if len(pos) else np.nan
        r[f"mlog_q_{k}"] = float(np.log(pos.q).mean()) if len(pos) else np.nan
        r[f"mlog_A_{k}"] = float(np.log(pos.a).mean()) if len(pos) else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        r["dlnS"] = np.log(r["S_FS"]) - np.log(r["S_SI"]); r["dlnQ"] = np.log(r["Q_FS"]) - np.log(r["Q_SI"])
        r["dlnA"] = np.log(r["meanA_FS"]) - np.log(r["meanA_SI"])
        r["share_s"] = r["dlnS"] / r["dlnA"]; r["share_q"] = r["dlnQ"] / r["dlnA"]
        r["geo_dlnS"] = r["mlog_s_FS"] - r["mlog_s_SI"]; r["geo_dlnA"] = r["mlog_A_FS"] - r["mlog_A_SI"]
        r["geo_share_s"] = r["geo_dlnS"] / r["geo_dlnA"]
    return r


def direction_share(units: pd.DataFrame, labels: pd.Series, boot: int = 0, seed: int = 103) -> dict:
    """units: unit_table output; labels: uid -> class. Returns the split and, if boot > 0, a percentile interval."""
    lab = labels.reindex(units.index)
    g_si = units[lab == SI].reset_index(drop=True); g_fs = units[lab == FS].reset_index(drop=True)
    if not len(g_si) or not len(g_fs):
        return {"direction_share": np.nan, "direction_share_defined": False}
    x = decomp(g_si, g_fs)
    out = {"direction_share": x["share_s"], "direction_share_geometric": x["geo_share_s"], "dlnA": x["dlnA"], "dlnS": x["dlnS"],
           "S_SI": x["S_SI"], "S_FS": x["S_FS"], "Q_SI": x["Q_SI"], "Q_FS": x["Q_FS"], "split_n_SI": x["n_SI"], "split_n_FS": x["n_FS"]}
    out["direction_share_defined"] = bool(np.isfinite(x["share_s"]) and np.isfinite(x["dlnA"]) and x["dlnA"] > 0)
    if boot:
        rng = np.random.default_rng(seed); bs = []
        for _ in range(boot):
            bs.append(decomp(g_si.iloc[rng.integers(0, len(g_si), len(g_si))], g_fs.iloc[rng.integers(0, len(g_fs), len(g_fs))])["share_s"])
        bs = np.array(bs); bs = bs[np.isfinite(bs)]
        lo, hi = (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))) if len(bs) else (np.nan, np.nan)
        out["direction_share_ci_lo"], out["direction_share_ci_hi"] = lo, hi
    return out
