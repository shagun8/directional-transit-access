"""Stage 3: travel-time tables with r5py (R5). Transit: departures over one hour, median travel time.
Car: free-flow on the OpenStreetMap network, one departure. Cell centre to cell centre, snapped to the network."""
import json
import os
import sys
import time
from datetime import timedelta

import geopandas as gpd
import pandas as pd

from .classify import compact


def _cache_dir():
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "r5py")


def route(U, osm_pbf, zips, run, cache, settings, r5_jar=None, log=print):
    """Returns (transit table, car table, walk table or None, runtimes). Reads finished tables from `cache` if present."""
    S = settings; uids = U.uid.values
    names = ["transit", "car"] + (["walk"] if S.walk_matrix else [])
    done = all(os.path.exists(f"{cache}/ttm_{nm}.parquet") for nm in names) and os.path.exists(f"{cache}/runtime.json")
    if done:
        out = {nm: compact(pd.read_parquet(f"{cache}/ttm_{nm}.parquet"), uids) for nm in names}
        log("travel times loaded from cache")
        return out["transit"], out["car"], out.get("walk"), json.load(open(f"{cache}/runtime.json"))
    os.environ.setdefault("JAVA_TOOL_OPTIONS", "-XX:-OmitStackTraceInFastThrow")
    argv = sys.argv
    sys.argv = [argv[0]] + (["--r5-classpath", r5_jar] if r5_jar else []) + ["--max-memory", S.heap]
    try:
        import r5py
        from r5py import TransportMode
        for f in [osm_pbf] + list(zips):   # r5py keeps working copies keyed by file name: drop stale ones
            c = os.path.join(_cache_dir(), os.path.basename(f))
            if os.path.exists(c) and os.path.getmtime(c) < os.path.getmtime(f):
                os.remove(c); log(f"removed stale r5py working copy {os.path.basename(c)}")
        orig = U[U.is_origin]
        P_o = gpd.GeoDataFrame({"id": orig.uid.values}, geometry=gpd.points_from_xy(orig.lon, orig.lat), crs=4326)
        P_d = gpd.GeoDataFrame({"id": uids}, geometry=gpd.points_from_xy(U.lon, U.lat), crs=4326)
        RT = {}; t0 = time.time(); net = r5py.TransportNetwork(osm_pbf, list(zips)); RT["network_build_s"] = round(time.time() - t0, 1)
        pdir = f"{cache}/parts"; os.makedirs(pdir, exist_ok=True)
        def ttm(modes, maxt, use_window, tag):
            out = []
            for k in range(0, len(P_o), S.batch):   # origin batches: same per-origin result, bounded memory; one resume file per batch
                pf = f"{pdir}/{tag}_{k:07d}_{S.batch}.parquet"
                if os.path.exists(pf): out.append(compact(pd.read_parquet(pf), uids)); continue
                kw = dict(origins=P_o.iloc[k:k + S.batch], destinations=P_d, departure=run, percentiles=[50], transport_modes=modes,
                          max_time=maxt, snap_to_network=True)
                if use_window: kw["departure_time_window"] = timedelta(minutes=S.window_min)
                m = pd.DataFrame(r5py.TravelTimeMatrix(net, **kw)); m.columns = ["from_id", "to_id", "travel_time"]; m = compact(m, uids)
                m.to_parquet(pf + ".tmp"); os.replace(pf + ".tmp", pf); out.append(m); log(f"  {tag} batch {k}-{k + S.batch} of {len(P_o)} done")
            return pd.concat(out, ignore_index=True)
        t0 = time.time(); tr_m = ttm([TransportMode.TRANSIT, TransportMode.WALK], timedelta(minutes=S.max_transit_min), True, "transit"); RT["transit_s"] = round(time.time() - t0, 1)
        wk_m = None
        if S.walk_matrix:
            t0 = time.time(); wk_m = ttm([TransportMode.WALK], timedelta(minutes=S.max_transit_min), True, "walk"); RT["walk_s"] = round(time.time() - t0, 1)
        t0 = time.time(); car_m = ttm([TransportMode.CAR], timedelta(minutes=S.max_car_min), False, "car"); RT["car_s"] = round(time.time() - t0, 1)
        RT["r5py_version"] = r5py.__version__
    finally:
        sys.argv = argv
    tr_m.to_parquet(f"{cache}/ttm_transit.parquet"); car_m.to_parquet(f"{cache}/ttm_car.parquet")
    if wk_m is not None: wk_m.to_parquet(f"{cache}/ttm_walk.parquet")
    json.dump(RT, open(f"{cache}/runtime.json", "w"))
    return tr_m, car_m, wk_m, RT
