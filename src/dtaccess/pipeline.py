"""The full run for one city: boundary -> cells -> feeds -> coverage -> places -> routing -> indicators."""
import hashlib
import json
import os
import time
from datetime import datetime

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from . import gtfs as G_
from . import inputs as I_
from .classify import classify, write_outputs
from .geo import hav
from .settings import Settings


def _md5(path, chunk=1 << 20):
    if os.path.isdir(path): return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""): h.update(b)
    return h.hexdigest()


def run_city(gtfs, osm, boundary, out, population=None, date=None, centre=None, centre_names=None, un_brt=None,
             route_type_override=None, timezone=None, label_stops=None, population_column=None, feed_copy="active",
             clip=True, r5_jar=None, name=None, settings: Settings = None, log=print) -> dict:
    """Compute the directional indicators for one city.

    gtfs: list of GTFS zips (or folders).           osm: OpenStreetMap .osm.pbf covering the city and a 10 km margin.
    boundary: polygon file (any CRS).               population: raster (people per pixel, WGS84), polygon file, or None.
    date: service day, 'YYYY-MM-DD' (a weekday on which the feeds run).   out: output folder.
    centre: (lat, lon); or centre_names: names to look up as an OSM place=city node; else a place-density centre.
    un_brt: {routes column: [values]} marking rapid-bus routes for the UN rule.
    route_type_override: {feed file name: route_type} for feeds that code rail as bus.
    label_stops: optional stop file with a `mode` column ('bus' or other) used for the class labels instead of the
      stops served on the run day (the US runs in the paper used such a stored file).
    Returns the summary dict; writes cells.geojson/csv/parquet, sectors.parquet, summary.json and a cache/ folder.
    """
    S = settings or Settings()
    if date is None: raise ValueError("date is required (a weekday on which the feeds run, e.g. a Tuesday)")
    run = (date if isinstance(date, datetime) else datetime.fromisoformat(str(date))).replace(hour=S.peak_start_hour, minute=0, second=0, microsecond=0)
    tag = name or os.path.basename(os.path.abspath(out))
    cache = f"{out}/cache"; work = f"{out}/work"; os.makedirs(cache, exist_ok=True); os.makedirs(work, exist_ok=True)
    t_start = time.time()
    log(f"dtaccess {tag}: service day {run.date()} ({run.strftime('%A')}), H3 resolution {S.res}")

    # ---- 1 cells
    U, bz, bound, utm, area, n1 = I_.build_cells(boundary, S.res)
    log(f"boundary area {area:.1f} km2; cells {len(U)}")

    # ---- 2a feeds
    G = G_.load_feeds(list(gtfs), run, work, tag, S, feed_copy=feed_copy, route_type_override=route_type_override, timezone=timezone, log=log)

    # ---- 2b coverage and residents
    sg_ag = G_.agency_rule_buffers(G, S.buf_bus_m, S.buf_rail_m)
    sg_un, un_counts = G_.un_rule_buffers(G, un_brt, S.buf_bus_m, S.buf_rail_m)
    if label_stops:
        sg = gpd.read_file(label_stops).to_crs(4326); sg["buf"] = np.where(sg["mode"] == "bus", S.buf_bus_m, S.buf_rail_m)
        stop_sets = {"cov": sg, "cov_un": sg_un, "cov_ag": sg_ag}
    else:
        sg = sg_ag; stop_sets = {"cov": sg, "cov_un": sg_un, "cov_ag": None}
    U, pop_src, n2 = I_.population_and_coverage(U, bz, utm, population, stop_sets, S, population_column)
    log(f"residents {U['pop'].sum():,.0f} in {len(U)} cells; origins {int(U.is_origin.sum())}")

    # ---- 2c street network and places
    if clip:
        osm_clip = f"{work}/{tag}_clip10km.osm.pbf"
        if not os.path.exists(osm_clip): I_.clip_osm(osm, bound, utm, osm_clip, S.osm_buffer_m)
    else:
        osm_clip = osm
    poi = I_.osm_places(osm_clip, utm, cache=f"{cache}/places.parquet")
    U["n_poi"] = I_.count_in_cells(poi.lat.values, poi.lon.values, U.uid.values, S.res).values
    log(f"places in cells {int(U.n_poi.sum()):,} of {len(poi):,}")

    # ---- centre
    if centre is not None:
        cen = {"lat": float(centre[0]), "lon": float(centre[1]), "rule": "given", "osm_node": None}
    else:
        cen = I_.centre_by_name(osm_clip, bound, centre_names) if centre_names else {"lat": None}
        if cen.get("lat") is None: cen = I_.centre_by_place_density(U)
    U["dist_cbd_km"] = hav(U.lat.values, U.lon.values, cen["lat"], cen["lon"])

    # ---- route presence (does not use travel times)
    idx = set(U.uid.values)
    def cell_of_stop(lat, lon):
        c = [h3.latlng_to_cell(a, b, S.res) for a, b in zip(lat, lon)]
        return np.array([x if x in idx else None for x in c], dtype=object)
    pres = G_.route_presence(G, cell_of_stop, S)

    # ---- stage files (enough to re-run the indicators without routing)
    keep = ["uid", "lat", "lon", "area_km2", "pop", "is_origin", "cov", "cov500", "cov_un", "cov_ag", "coverage_pct", "coverage_pct_un",
            "coverage_pct_500", "n_poi", "dist_cbd_km"]
    pd.DataFrame(U[keep]).to_parquet(f"{cache}/cell_inputs.parquet", index=False)
    pres.to_parquet(f"{cache}/route_presence.parquet", index=False)
    meta = {"name": tag, "run_date": run.date().isoformat(), "weekday": run.strftime("%A"), "boundary": os.path.basename(str(boundary)),
            "boundary_area_km2": round(area, 2), "osm": os.path.basename(str(osm)), "population_source": pop_src, "centre": cen,
            "gtfs": [{"file": os.path.basename(str(g).rstrip("/")), "md5": _md5(g)} for g in gtfs], "feed_copy": feed_copy,
            "feed_notes": G["notes"], "un_routes": un_counts, "un_brt": un_brt or {},
            "stops_by_buffer_m": {"label_rule": {str(k): int(v) for k, v in sg.buf.value_counts().items()},
                                  "un_rule": {str(k): int(v) for k, v in sg_un.buf.value_counts().items()}},
            "places_in_cells": int(U.n_poi.sum()), "notes": {**n1, **n2}}
    json.dump(meta, open(f"{cache}/stage_meta.json", "w"), indent=1, default=str)

    # ---- 3 routing
    from .routing import route
    tr_m, car_m, wk_m, RT = route(U, osm_clip, G["zips"], run, cache, S, r5_jar=r5_jar, log=log)
    T = S.threshold_min
    for nm, m in [("transit", tr_m), ("car", car_m)]:
        log(f"{nm}: reachable pairs {len(m):,}; within {T:g} min {(m.travel_time <= T).sum():,}")

    # ---- 4 indicators
    res = classify(pd.DataFrame(U.drop(columns="geometry")), pres, tr_m, car_m, centre=(cen["lat"], cen["lon"]), settings=S)
    RT["total_s"] = round(time.time() - t_start, 1)
    summary = write_outputs(res, out, {"inputs": meta, "runtime_seconds": RT})
    h = summary["headline"]["un"]
    log(f"headline: {h['share']:.4f} of UN-served residents live where at least half the car-reachable directions are blocked "
        f"({h['served_residents_blocked_half']:,.0f} of {h['served_residents_denominator']:,.0f})")
    return summary
