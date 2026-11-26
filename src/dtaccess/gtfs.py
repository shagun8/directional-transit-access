"""Stage 2a: read schedule files (GTFS), keep the service of one day, repair what the routing engine rejects,
and derive stop buffers and route presence.

Only eight GTFS tables are read: agency, stops, routes, trips, stop_times, calendar, calendar_dates, frequencies.
"""
import hashlib
import os
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

from .geo import bearing

GTFS_USED = {"agency", "stops", "routes", "trips", "stop_times", "calendar", "calendar_dates", "frequencies"}


def tsec(s: pd.Series) -> pd.Series:
    """'HH:MM:SS' -> seconds (NaN if empty)."""
    a = s.fillna("").str.strip().str.split(":", expand=True)
    if a.shape[1] < 3:
        a = a.reindex(columns=range(3))
    return pd.to_numeric(a[0], errors="coerce") * 3600 + pd.to_numeric(a[1], errors="coerce") * 60 + pd.to_numeric(a[2], errors="coerce")


def read_feed(src: str) -> dict:
    """Read a GTFS zip or folder. Tables keep every value as text."""
    F = {}
    if src.endswith(".zip"):
        zf = zipfile.ZipFile(src)
        for n in zf.namelist():   # exact basename match in any folder; macOS resource files skipped
            b_ = os.path.basename(n)
            if n.startswith("__MACOSX") or "/__MACOSX" in n or b_.startswith("._") or not b_.endswith(".txt"): continue
            if b_[:-4] not in GTFS_USED: continue   # a feed zip can carry licence or readme .txt files
            assert b_[:-4] not in F, f"duplicate table {b_} in {src}"
            F[b_[:-4]] = pd.read_csv(zf.open(n), dtype=str, encoding="utf-8-sig", low_memory=False)
    else:
        for n in os.listdir(src):
            if n.endswith(".txt") and n[:-4] in GTFS_USED:
                F[n[:-4]] = pd.read_csv(os.path.join(src, n), dtype=str, encoding="utf-8-sig")
    for k in F: F[k].columns = [c.strip() for c in F[k].columns]
    return F


def active_services(F: dict, target: str, dow: str) -> set:
    """service_ids running on the day `target` (YYYYMMDD), weekday name `dow`."""
    act = set()
    if "calendar" in F and len(F["calendar"]):
        c = F["calendar"]
        act |= set(c[(c.start_date.str.strip() <= target) & (c.end_date.str.strip() >= target) & (c[dow].str.strip() == "1")].service_id)
    if "calendar_dates" in F and len(F["calendar_dates"]):
        cd = F["calendar_dates"]; cd = cd[cd.date.str.strip() == target]
        act |= set(cd[cd.exception_type.str.strip() == "1"].service_id); act -= set(cd[cd.exception_type.str.strip() == "2"].service_id)
    return act


def load_feeds(srcs, run, work_dir, tag, settings, feed_copy="active", route_type_override=None, timezone=None, log=print):
    """Read all feeds for the run day and write the copies the routing engine reads.

    feed_copy="active": the routing copy holds only the day's service (default).
    feed_copy="original": route on the publisher's zip, changed only where R5 would reject it.
    Returns dict(trips, stop_times, stops, routes, zips, notes).
    """
    R = settings.repairs
    target = run.strftime("%Y%m%d"); dow = run.strftime("%A").lower()
    peak0 = settings.peak_start_hour * 3600; peak1 = peak0 + settings.window_min * 60
    os.makedirs(work_dir, exist_ok=True)
    TRIPS, ST, STOPS, ROUTES, ZIPS, twin_tot, act_tot = [], [], [], [], [], 0, 0
    notes = {}
    def note(k, v): notes[k] = v
    for i, src in enumerate(srcs):
        base = os.path.basename(src.rstrip("/"))
        F = read_feed(src); act = active_services(F, target, dow)
        tr = F["trips"]; tr = tr[tr.service_id.isin(act)].copy()
        if "direction_id" not in tr.columns: tr["direction_id"] = "0"
        tr["direction_id"] = tr.direction_id.fillna("0").astype(str)
        st = F["stop_times"][F["stop_times"].trip_id.isin(tr.trip_id)].copy()
        if R.flex_empty_times:
            for _tc in ["arrival_time", "departure_time"]:   # demand-responsive feeds carry no times; empty = never in the 08:00 hour
                if _tc not in st.columns:
                    st[_tc] = pd.Series("", index=st.index, dtype=object); log(f"  {base}: stop_times has no {_tc} (flex feed); set empty")
        st["stop_sequence"] = pd.to_numeric(st.stop_sequence); st = st.sort_values(["trip_id", "stop_sequence"])
        if R.drop_trips_ge_72h:
            _hmax = pd.concat([tsec(st.arrival_time), tsec(st.departure_time)], axis=1).max(axis=1)
            _drop = set(st.loc[_hmax >= 72 * 3600, "trip_id"])
            if _drop:
                log(f"  {base}: {len(_drop)} trips with a stop time >= 72 h dropped"); note(f"trips_time_ge72h_dropped_{i}", len(_drop))
                tr = tr[~tr.trip_id.isin(_drop)].copy(); st = st[~st.trip_id.isin(_drop)].copy()
        fq = F.get("frequencies")
        if R.drop_exact_twin_trips:
            sig = (st.stop_id + "@" + st.arrival_time.fillna("") + "@" + st.departure_time.fillna("")).groupby(st.trip_id).agg("|".join)
            if fq is not None and len(fq):
                fs = (fq.start_time + "-" + fq.end_time + "/" + fq.headway_secs).groupby(fq.trip_id).agg("|".join)
                sig = sig + "#" + fs.reindex(sig.index).fillna("")
            tr["sig"] = tr.trip_id.map(sig).map(lambda s: hashlib.md5(str(s).encode()).hexdigest())
            tw = tr.duplicated(["route_id", "direction_id", "sig"], keep="first")
            n_act = len(tr); twin_tot += int(tw.sum())
            tr = tr[~tw].drop(columns="sig"); st = st[st.trip_id.isin(tr.trip_id)]
        else:
            n_act = len(tr); tw = pd.Series(False, index=tr.index)
        log(f"feed {base}: active services {len(act)}, active trips {n_act:,}, exact twins {int(tw.sum())}")
        act_tot += n_act
        tr["fid"] = i; st = st.assign(fid=i)
        rt = F["routes"].copy(); rt["fid"] = i
        _ov = (route_type_override or {}).get(base)
        if _ov: rt["route_type"] = str(_ov); log(f"  route_type set to {_ov} for coverage: {base}"); note(f"route_type_override_{base}", str(_ov))
        if "agency_id" not in rt.columns: rt["agency_id"] = F["agency"].agency_id.iloc[0] if "agency_id" in F["agency"].columns else "A"
        if R.fill_blank_agency_id and len(F["agency"]) == 1 and rt.agency_id.isna().any():   # blank agency_id is valid for a one-agency feed
            _a = F["agency"].agency_id.iloc[0] if "agency_id" in F["agency"].columns else "A"
            log(f"  {int(rt.agency_id.isna().sum())} routes with blank agency_id set to the feed's only agency {_a}")
            note(f"agency_id_filled_{base}", {"routes": int(rt.agency_id.isna().sum()), "agency": _a})
            rt["agency_id"] = rt.agency_id.fillna(_a)
        _ag = F["agency"][[c_ for c_ in ["agency_id", "agency_name"] if c_ in F["agency"].columns]].drop_duplicates("agency_id") \
            if "agency_id" in F["agency"].columns else pd.DataFrame(columns=["agency_id"])
        rt = rt.merge(_ag, on="agency_id", how="left")   # agency_name is used only for the rapid-bus flag
        assert len(rt) == len(F["routes"]), "agency join changed the routes row count"
        sp = F["stops"].copy(); sp["fid"] = i
        fqa = fq[fq.trip_id.isin(tr.trip_id)].copy() if fq is not None and len(fq) else None
        if fqa is not None and R.zero_window_frequency_as_one_departure:   # headway < 1 s is invalid and R5 rejects it
            _hw = pd.to_numeric(fqa.headway_secs, errors="coerce"); _bad = ~(_hw >= 1)
            if _bad.any():
                _z = fqa[_bad & (tsec(fqa.start_time) == tsec(fqa.end_time))]   # zero-length window = one departure at start_time
                _one = _z.drop_duplicates("trip_id").set_index("trip_id").start_time
                _one = _one[~_one.index.isin(fqa[~_bad].trip_id)]   # only trips with no valid frequency row
                if len(_one):
                    _m = st.trip_id.isin(_one.index); _first = st[_m].groupby("trip_id").departure_time.first().pipe(tsec)
                    _off = tsec(_one) - _first.reindex(_one.index)
                    def _fmt(x): x = int(round(x)); return f"{x // 3600:02d}:{(x % 3600) // 60:02d}:{x % 60:02d}"
                    for _tc in ["arrival_time", "departure_time"]:
                        _v = tsec(st.loc[_m, _tc]) + st.loc[_m, "trip_id"].map(_off).values
                        st.loc[_m, _tc] = [_fmt(x) if pd.notna(x) else "" for x in _v]
                log(f"  {base}: {int(_bad.sum())} frequency rows with headway < 1 s; {len(_one)} zero-length windows turned into one departure; rows dropped")
                note(f"frequency_headway_lt1_{i}", {"rows": int(_bad.sum()), "single_departures": int(len(_one))})
                fqa = fqa[~_bad].copy()
                if not len(fqa): fqa = None
        tr["is_freq"] = tr.trip_id.isin(fqa.trip_id) if fqa is not None else False
        if fqa is not None:
            fqa["s0"], fqa["s1"] = tsec(fqa.start_time), tsec(fqa.end_time)
            peak_freq = set(fqa[(fqa.s0 < peak1) & (fqa.s1 > peak0)].trip_id); tr["freq_in_peak"] = tr.trip_id.isin(peak_freq)
        else:
            tr["freq_in_peak"] = False
        TRIPS.append(tr); ST.append(st); STOPS.append(sp); ROUTES.append(rt)

        if feed_copy == "original":
            if not src.endswith(".zip"): raise ValueError("feed_copy='original' needs zip files")
            if R.skip_feeds_without_active_trips and len(tr) == 0:   # adds no service that day
                log(f"  {base}: 0 active trips on the run date; not passed to R5"); note(f"not_routed_no_active_trips_{base}", True)
                continue
            zin = zipfile.ZipFile(src); empty = []
            if R.drop_empty_tables:
                for n in zin.namelist():
                    if n.endswith(".txt"):
                        lines = [l for l in zin.read(n).decode("utf-8-sig", "ignore").splitlines() if l.strip()]
                        if len(lines) <= 1: empty.append(n)
            PK = {"calendar_dates": ["service_id", "date"], "calendar": ["service_id"], "trips": ["trip_id"], "routes": ["route_id"],
                  "stops": ["stop_id"], "stop_times": ["trip_id", "stop_sequence"]}
            fix = {}
            if R.drop_duplicate_keys_and_orphans:
                for t_, k_ in PK.items():
                    if t_ in F and len(F[t_]) and all(x in F[t_].columns for x in k_):
                        nd = int(F[t_].duplicated(k_).sum())
                        if nd: fix[t_] = {"duplicate_keys": nd}
                if "stop_times" in F and "trips" in F:
                    no = int((~F["stop_times"].trip_id.isin(F["trips"].trip_id)).sum())
                    if no: fix.setdefault("stop_times", {})["orphan_trip_rows"] = no
            _fi = [n for n in zin.namelist() if os.path.basename(n) == "feed_info.txt"]
            if _fi and R.drop_feed_info_missing_required:   # feed_info is not used for routing
                _fid = pd.read_csv(zin.open(_fi[0]), dtype=str, encoding="utf-8-sig"); _fid.columns = [x.strip() for x in _fid.columns]
                _req = ["feed_publisher_name", "feed_publisher_url", "feed_lang"]
                if any(c_ not in _fid.columns or _fid[c_].isna().any() or (_fid[c_].astype(str).str.strip() == "").any() for c_ in _req):
                    fix["feed_info"] = {"dropped_empty_required_field": True}
            if empty or fix:
                z = f"{work_dir}/{tag}_{base[:-4]}_r5.zip"
                with zipfile.ZipFile(z + ".tmp", "w", zipfile.ZIP_DEFLATED) as zo:
                    for n in zin.namelist():
                        b_ = os.path.basename(n)[:-4] if n.endswith(".txt") else None
                        if n in empty or (b_ == "feed_info" and "feed_info" in fix): continue
                        if b_ in fix:
                            d_ = F[b_]
                            if fix[b_].get("duplicate_keys"): d_ = d_.drop_duplicates(PK[b_], keep="first")
                            if fix[b_].get("orphan_trip_rows"): d_ = d_[d_.trip_id.isin(F["trips"].trip_id)]
                            zo.writestr(n, d_.to_csv(index=False))
                        else:
                            zo.writestr(n, zin.read(n))
                os.replace(z + ".tmp", z)
                log(f"  {base}: routing copy: empty tables {empty}; repairs {fix}")
                note(f"routing_copy_{base}", {"empty_tables_dropped": empty, "repairs": fix})
                ZIPS.append(z)
            else:
                ZIPS.append(src)
            continue

        # ---- feed_copy == "active": write the day's service as a clean routing copy
        z = f"{work_dir}/{tag}_gtfs_{i}_{target}.zip"
        stops_out = F["stops"].copy()
        if "stop_name" not in stops_out.columns: stops_out["stop_name"] = pd.Series([None] * len(stops_out), index=stops_out.index, dtype=object)
        n_noname = int(stops_out.stop_name.isna().sum())
        if n_noname and R.fill_stop_name:   # R5 fails on a null stop_name; routing does not use names
            stops_out["stop_name"] = stops_out.stop_name.fillna(stops_out.stop_id); log(f"  {n_noname} stops without stop_name filled with stop_id")
            note(f"stop_name_filled_{i}", n_noname)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            cal = F["calendar"][F["calendar"].service_id.isin(act)] if "calendar" in F else None
            ag_out = F["agency"].copy()
            if R.drop_duplicate_agency_id and "agency_id" in ag_out.columns and ag_out.agency_id.duplicated().any():
                log(f"  {int(ag_out.agency_id.duplicated().sum())} duplicate agency_id rows dropped (first kept)")
                note(f"agency_dup_dropped_{i}", int(ag_out.agency_id.duplicated().sum())); ag_out = ag_out.drop_duplicates("agency_id")
            if "agency_url" not in ag_out.columns: ag_out["agency_url"] = np.nan
            if "agency_timezone" not in ag_out.columns: ag_out["agency_timezone"] = np.nan
            if R.fill_agency_timezone and ag_out.agency_timezone.isna().any():   # R5 needs it; only fixes how local clock times are read
                _tz = ag_out.agency_timezone.dropna().mode().iloc[0] if ag_out.agency_timezone.notna().any() else timezone
                if _tz:
                    log(f"  {int(ag_out.agency_timezone.isna().sum())} agencies without agency_timezone set to {_tz}"); note(f"agency_timezone_filled_{i}", _tz)
                    ag_out["agency_timezone"] = ag_out.agency_timezone.fillna(_tz)
            if R.placeholder_agency_url:
                ag_out.loc[~ag_out.agency_url.fillna("").astype(str).str.strip().str.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+$"), "agency_url"] = np.nan
                n_nourl = int(ag_out.agency_url.isna().sum())
                if n_nourl:   # required by R5's reader; not used in routing
                    ag_out["agency_url"] = ag_out.agency_url.fillna("http://unknown.invalid"); log(f"  {n_nourl} agencies without agency_url filled with placeholder")
                    note(f"agency_url_filled_{i}", n_nourl)
            rt_out = F["routes"][F["routes"].route_id.isin(tr.route_id)].copy()
            if R.remap_unknown_route_types:
                _rtn = pd.to_numeric(rt_out.route_type, errors="coerce")
                _bad = _rtn.isna() | (_rtn > 1500) | ((_rtn < 100) & ~_rtn.isin([0, 1, 2, 3, 4, 5, 6, 7, 11, 12]))
                if _bad.any():   # R5 accepts 0-1500; informal road vehicles and unknown basic codes -> 3 for routing only
                    log(f"  route_type remapped to 3 for routing: {rt_out.route_type[_bad].value_counts().to_dict()}")
                    note(f"route_type_remapped_{i}", rt_out.route_type[_bad].value_counts().to_dict())
                    rt_out.loc[_bad, "route_type"] = "3"
            parts = [("agency", ag_out), ("routes", rt_out), ("trips", tr.drop(columns=["fid", "is_freq", "freq_in_peak"])),
                     ("stop_times", st.drop(columns="fid").astype({"stop_sequence": int})), ("stops", stops_out)]
            if cal is not None: parts.append(("calendar", cal))
            if "calendar_dates" in F: parts.append(("calendar_dates", F["calendar_dates"][F["calendar_dates"].service_id.isin(act)]))
            if fqa is not None:
                fq_out = fqa.drop(columns=["s0", "s1"])
                if R.drop_duplicate_frequency_rows: fq_out = fq_out.drop_duplicates(["trip_id", "start_time"])
                parts.append(("frequencies", fq_out))
            for n_, df_ in parts:
                if len(df_) or not R.drop_empty_tables: zf.writestr(n_ + ".txt", df_.to_csv(index=False))
                else: log(f"  empty table {n_} not written")
        ZIPS.append(z)
    trips = pd.concat(TRIPS, ignore_index=True); stt = pd.concat(ST, ignore_index=True)
    stops = pd.concat(STOPS, ignore_index=True); routes = pd.concat(ROUTES, ignore_index=True)
    for c in ["stop_lat", "stop_lon"]: stops[c] = pd.to_numeric(stops[c], errors="coerce")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"])
    notes["feeds"] = [os.path.basename(s.rstrip("/")) for s in srcs]
    notes["active_trips"] = act_tot; notes["exact_twins_dropped"] = twin_tot
    return {"trips": trips, "stop_times": stt, "stops": stops, "routes": routes, "zips": ZIPS, "notes": notes}


def _served(G):
    return G["stop_times"][["fid", "trip_id", "stop_id"]].drop_duplicates(["fid", "stop_id", "trip_id"]).merge(
        G["trips"][["fid", "trip_id", "route_id"]], on=["fid", "trip_id"])


def agency_rule_buffers(G, buf_bus=500, buf_rail=1000) -> gpd.GeoDataFrame:
    """Per-agency rule: every stop of an agency that runs any bus-type route gets the bus buffer, else the rail buffer.
    Only stops served on the run day."""
    def bus_like(t):
        t = str(t).strip()
        return (t.lower() in {"3", "11", "bus", "share_taxi", "minibus"}) or (t.isdigit() and (200 <= int(t) < 300 or 700 <= int(t) < 800 or 1500 <= int(t) < 1600))
    r = G["routes"].copy(); r["bus"] = r.route_type.map(bus_like)
    ag_bus = r.groupby(["fid", "agency_id"]).bus.any()
    served = _served(G).merge(r[["fid", "route_id", "agency_id"]], on=["fid", "route_id"])
    sa = served.drop_duplicates(["fid", "stop_id", "agency_id"]).copy()
    sa["buf"] = np.where([ag_bus.get((f, a), True) for f, a in zip(sa.fid, sa.agency_id)], buf_bus, buf_rail)
    sb = sa.groupby(["fid", "stop_id"]).buf.max().reset_index()     # a stop served by a rail-only agency keeps the rail buffer
    s = G["stops"].merge(sb, on=["fid", "stop_id"]).drop_duplicates(["stop_lat", "stop_lon", "buf"])
    return gpd.GeoDataFrame(s[["stop_id", "buf"]], geometry=gpd.points_from_xy(s.stop_lon, s.stop_lat), crs=4326)


def un_rule_buffers(G, un_brt=None, buf_bus=500, buf_rail=1000):
    """UN rule (SDG 11.2.1), per stop: a stop served by rail, metro, ferry, cable car, funicular or a feed-marked
    rapid-bus route gets the rail buffer; every other stop the bus buffer. Feed-coded route types are used as they are.
    un_brt: {column of routes (or agency_name): [values that mark rapid-bus routes]}.
    Returns (stops GeoDataFrame, route counts)."""
    def high(t):
        t = str(t).strip()
        if not t.lstrip("-").isdigit(): return False
        t = int(t)
        return t in (1, 2, 4, 5, 6, 7, 12) or 100 <= t < 200 or 400 <= t < 500 or 1000 <= t < 1100 or 1300 <= t < 1500
    r = G["routes"].copy(); r["high"] = r.route_type.map(high)
    r["brt"] = False
    for col_, vals_ in (un_brt or {}).items():
        if col_ in r.columns: r["brt"] |= r[col_].astype(str).str.strip().isin(vals_)
    r["high"] = r.high | r.brt
    counts = {"rail_metro_ferry_cable": int((r.high & ~r.brt).sum()), "brt_marked": int(r.brt.sum()), "low": int((~r.high).sum())}
    served = _served(G).merge(r[["fid", "route_id", "high"]], on=["fid", "route_id"])
    sb = served.groupby(["fid", "stop_id"]).high.any().reset_index(); sb["buf"] = np.where(sb.high, buf_rail, buf_bus)
    s_ = G["stops"].merge(sb[["fid", "stop_id", "buf"]], on=["fid", "stop_id"]).drop_duplicates(["stop_lat", "stop_lon", "buf"])
    return gpd.GeoDataFrame(s_[["stop_id", "buf"]], geometry=gpd.points_from_xy(s_.stop_lon, s_.stop_lat), crs=4326), counts


def route_presence(G, cell_of_stop, settings) -> pd.DataFrame:
    """Routes leaving each cell, by compass sector, 08:00-08:59.

    For every stop visit in the hour, the direction is the bearing from the stop to the mean position of all later
    stops of that trip ("if I board here, where does it take me"). Counted as distinct (feed, route, direction) per
    (cell, sector). Frequency-based trips count if a frequency window overlaps the hour.
    cell_of_stop: function (lat array, lon array) -> array of cell ids (None/NaN outside the cell set).
    """
    peak0 = settings.peak_start_hour * 3600; peak1 = peak0 + settings.window_min * 60
    sp = G["stops"][["fid", "stop_id", "stop_lat", "stop_lon"]].drop_duplicates(["fid", "stop_id"]).copy()
    sp["uid"] = cell_of_stop(sp.stop_lat.values, sp.stop_lon.values); sp = sp[sp.uid.notna()]
    s2 = G["stop_times"][["fid", "trip_id", "stop_id", "stop_sequence", "departure_time"]].merge(
        G["trips"][["fid", "trip_id", "route_id", "direction_id", "is_freq", "freq_in_peak"]], on=["fid", "trip_id"])
    s2["dep"] = tsec(s2.departure_time)
    s2 = s2[np.where(s2.is_freq, s2.freq_in_peak, (s2.dep >= peak0) & (s2.dep < peak1))]
    s2 = s2.merge(sp, on=["fid", "stop_id"], how="inner").sort_values(["fid", "trip_id", "stop_sequence"])
    if not len(s2):
        return pd.DataFrame({"uid": pd.Series(dtype=str), "sector": pd.Series(dtype=int), "n_route_dirs": pd.Series(dtype=int)})
    g_ = s2.groupby(["fid", "trip_id"], sort=False)
    s2["n_after"] = g_.cumcount(ascending=False)
    s2["sla"] = g_.stop_lat.transform(lambda v: v[::-1].cumsum()[::-1]) - s2.stop_lat
    s2["slo"] = g_.stop_lon.transform(lambda v: v[::-1].cumsum()[::-1]) - s2.stop_lon
    b2 = s2[s2.n_after > 0].copy(); b2["dla"], b2["dlo"] = b2.sla / b2.n_after, b2.slo / b2.n_after
    b2 = b2[~((abs(b2.dla - b2.stop_lat) < 1e-9) & (abs(b2.dlo - b2.stop_lon) < 1e-9))]
    b2["sector"] = (bearing(b2.stop_lat.values, b2.stop_lon.values, b2.dla.values, b2.dlo.values) / settings.sector_deg).astype(int) % settings.n_sectors
    return b2.drop_duplicates(["uid", "fid", "route_id", "direction_id", "sector"]).groupby(["uid", "sector"]).size().rename("n_route_dirs").reset_index()
