"""Stages 1 and 2b-2d: cells from the boundary, residents and coverage per cell, street-network clip, places, city centre."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import mapping


def finite(g):
    assert np.isfinite(g.total_bounds).all(), "reprojection failed (non-finite bounds); check PROJ_DATA"
    return g


def osmium_bin():
    p = os.path.join(os.path.dirname(sys.executable), "osmium")
    return p if os.path.exists(p) else shutil.which("osmium")


def build_cells(boundary_path: str, res: int = 8):
    """H3 cells whose centre lies inside the boundary. Returns (cells GeoDataFrame, boundary polygon, UTM crs, area km2, notes)."""
    bz = gpd.read_file(boundary_path)
    bz = bz.set_crs(4326) if bz.crs is None else bz.to_crs(4326)
    notes = {}
    n_invalid = int((~bz.geometry.is_valid).sum())
    if n_invalid:
        bz["geometry"] = bz.geometry.make_valid(); notes["boundary_invalid_polygons_repaired"] = n_invalid
    utm = finite(bz).estimate_utm_crs()
    bound = bz.union_all()
    if bound.geom_type == "GeometryCollection":   # make_valid can leave lines or points; keep polygon parts only
        bound = shapely.union_all([g_ for g_ in shapely.get_parts(bound) if g_.geom_type in ("Polygon", "MultiPolygon")])
    area = finite(gpd.GeoSeries([bound], crs=4326).to_crs(utm)).area.iloc[0] / 1e6
    cells = sorted(h3.geo_to_cells(bound, res))
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    U = gpd.GeoDataFrame({"uid": cells, "lat": ll[:, 0], "lon": ll[:, 1]},
                         geometry=[shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)]) for c in cells], crs=4326)
    U = U.reset_index(drop=True)
    U["area_km2"] = finite(U.to_crs(utm)).area.values / 1e6
    return U, bz, bound, utm, float(area), notes


def _union_buffers(stops_gdf, utm, fixed=None):
    su = finite(stops_gdf.to_crs(utm))
    if fixed is not None:
        g = shapely.union_all(su.geometry.buffer(fixed).values)
    else:
        g = shapely.union_all([p.buffer(b) for p, b in zip(su.geometry, su.buf)])
    shapely.prepare(g)
    return g


def population_and_coverage(U, bz, utm, population, stop_sets: dict, settings, population_column=None):
    """Residents per cell and residents inside each stop-buffer set.

    population: path to a raster (people per pixel; pixel centre decides the cell), a polygon file with a population
      column (areal weighting), or None (cell area in km2 stands in for residents; not the published method).
    stop_sets: {"cov": stops for the label rule, "cov_un": UN rule, "cov_ag": per-agency rule or None}; each a
      GeoDataFrame with a `buf` column in metres. "cov500" (bus buffer on every label-rule stop) is added.
    Returns (U with pop and cov columns, source label, notes).
    """
    res = settings.res; notes = {}
    bufs = {k: _union_buffers(v, utm) for k, v in stop_sets.items() if v is not None}
    bufs["cov500"] = _union_buffers(stop_sets["cov"], utm, fixed=settings.buf_bus_m)
    keys = list(bufs)
    Uu = finite(U.to_crs(utm))
    kind = "none" if population is None else ("raster" if str(population).lower().endswith((".tif", ".tiff", ".vrt")) else "vector")
    if kind == "raster":
        import rasterio
        from rasterio.windows import from_bounds
        with rasterio.open(population) as r:
            b = bz.to_crs(r.crs).total_bounds; pad = 0.02
            w = from_bounds(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad, r.transform).round_offsets().round_lengths()
            arr = r.read(1, window=w, masked=True).filled(np.nan).astype("float64"); tf = r.window_transform(w)
        ii, jj = np.where(np.isfinite(arr) & (arr > 0)); vals = arr[ii, jj]
        xs, ys = rasterio.transform.xy(tf, ii, jj); xs, ys = np.asarray(xs), np.asarray(ys)
        pc = np.array([h3.latlng_to_cell(y, x, res) for x, y in zip(xs, ys)])
        keep = np.isin(pc, U.uid.values)
        pg = gpd.GeoSeries(gpd.points_from_xy(xs[keep], ys[keep]), crs=4326).to_crs(utm)
        px, py = pg.x.values, pg.y.values
        df = pd.DataFrame({"uid": pc[keep], "pop": vals[keep]})
        for k in keys: df[k] = vals[keep] * shapely.contains_xy(bufs[k], px, py)
        agg = df.groupby("uid")[["pop"] + keys].sum()
        notes["raster_pop_outside_cells"] = float(vals[~keep].sum()); notes["raster_pop_in_cells"] = float(vals[keep].sum())
        src = f"{os.path.basename(str(population))} (raster; pixel centre -> cell)"
    elif kind == "vector":
        bl = gpd.read_file(population); bl = bl.set_crs(4326) if bl.crs is None else bl
        col = population_column or next(c for c in ["total_population", "population", "pop", "POP"] if c in bl.columns)
        bl = finite(bl.to_crs(utm)); bl = bl[bl[col] > 0].copy(); bl["barea"] = bl.area
        pieces = gpd.overlay(bl[[col, "barea", "geometry"]], Uu[["uid", "geometry"]], how="intersection", keep_geom_type=True)
        pieces["pop"] = pieces[col] * pieces.area / pieces.barea
        def per_unit(bufg):   # clip each buffer to each cell first, then intersect the block pieces with their cell's clip
            out = {}
            for uid_, ug in zip(U.uid.values, Uu.geometry.values):
                x0, y0, x1, y1 = ug.bounds
                out[uid_] = shapely.intersection(ug, shapely.clip_by_rect(bufg, x0, y0, x1, y1))
            return out
        for k in keys:
            hb = per_unit(bufs[k])
            pieces[k] = pieces[col] * shapely.area(shapely.intersection(pieces.geometry.values, np.array([hb[u] for u in pieces.uid]))) / pieces.barea
        agg = pieces.groupby("uid")[["pop"] + keys].sum()
        notes["vector_pop_total"] = float(bl[col].sum())
        src = f"{os.path.basename(str(population))} (polygons, column {col}; areal weighting)"
    else:
        agg = pd.DataFrame({"pop": U.area_km2.values}, index=U.uid.values)
        for k in keys: agg[k] = shapely.area(shapely.intersection(Uu.geometry.values, bufs[k])) / 1e6
        src = "none: cell area (km2) used in place of residents; every cell is an origin (not the published method)"
    U = U.merge(agg, left_on="uid", right_index=True, how="left").fillna({k: 0 for k in ["pop"] + keys})
    if "cov_ag" not in U.columns: U["cov_ag"] = U["cov"]   # label rule already is the per-agency rule on served stops
    den = U["pop"].replace(0, np.nan)
    U["coverage_pct_un"] = np.where(U["pop"] > 0, 100 * U["cov_un"] / den, np.nan)
    U["coverage_pct"] = np.where(U["pop"] > 0, 100 * U["cov"] / den, np.nan)
    U["coverage_pct_500"] = np.where(U["pop"] > 0, 100 * U["cov500"] / den, np.nan)
    U["is_origin"] = (U["pop"] >= settings.min_pop_origin) if kind != "none" else (U["pop"] > 0)
    return U, src, notes


def clip_osm(osm_full: str, bound, utm, out_pbf: str, buffer_m: float = 10000):
    """Street network clip: boundary plus a margin, whole ways kept (osmium extract -s complete_ways)."""
    poly = gpd.GeoSeries([bound], crs=4326).to_crs(utm).buffer(buffer_m).to_crs(4326).iloc[0]
    pj = out_pbf.replace(".osm.pbf", ".geojson")
    json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": mapping(poly)}]}, open(pj, "w"))
    exe = osmium_bin()
    if not exe: raise RuntimeError("osmium (osmium-tool) not found; install it or pass --no-clip with a ready clip")
    subprocess.run([exe, "extract", "-p", pj, "-s", "complete_ways", osm_full, "-o", out_pbf, "--overwrite"], check=True)
    return out_pbf


def osm_places(osm_pbf: str, utm, cache: str = None) -> pd.DataFrame:
    """Places = every tagged OpenStreetMap point plus the centroid of every valid polygon (buildings and land use
    included), not de-duplicated. Read with the GDAL OSM driver ('points' and 'multipolygons' layers)."""
    if cache and os.path.exists(cache):
        return pd.read_parquet(cache)[["lon", "lat"]]
    import pyogrio
    pt = pyogrio.read_dataframe(osm_pbf, layer="points", columns=["osm_id"])
    pl = pyogrio.read_dataframe(osm_pbf, layer="multipolygons", columns=["osm_id"]); pl = pl[pl.is_valid]
    plc = finite(pl.to_crs(utm)); plc["geometry"] = plc.geometry.centroid; pl = finite(plc.to_crs(4326))
    a_ = pd.DataFrame({"lon": np.r_[pt.geometry.x.values, pl.geometry.x.values], "lat": np.r_[pt.geometry.y.values, pl.geometry.y.values],
                       "layer": ["points"] * len(pt) + ["multipolygons"] * len(pl)})
    if cache: a_.to_parquet(cache)
    return a_[["lon", "lat"]]


def count_in_cells(lat, lon, uids, res: int) -> pd.Series:
    pid = np.array([h3.latlng_to_cell(la, lo, res) for la, lo in zip(lat, lon)])
    pid = pid[np.isin(pid, uids)]
    return pd.Series(uids).map(pd.Series(pid).value_counts()).fillna(0).astype(int)


def _opl(pbf, expr):
    with tempfile.TemporaryDirectory() as td:
        f = f"{td}/x.opl"
        subprocess.run([osmium_bin(), "tags-filter", "-R", pbf, *expr, "-o", f, "-f", "opl", "--overwrite"], check=True, capture_output=True)
        return open(f, encoding="utf-8").read().splitlines()


def _parse_opl(lines):
    dec = lambda s: re.sub(r"%([0-9a-fA-F]+)%", lambda m: chr(int(m.group(1), 16)), s)
    def tags(t):
        return dict(dec(kv).split("=", 1) for kv in re.findall(r"(?:[^,%]|%[0-9a-fA-F]+%)+", t) if "=" in dec(kv)) if t else {}
    out = []
    for L in lines:
        F = {p[0]: p[1:] for p in L.split(" ") if p}
        out.append(dict(id=L.split(" ")[0], tags=tags(F.get("T", "")), x=float(F["x"]) if F.get("x") else None,
                        y=float(F["y"]) if F.get("y") else None, members=F.get("M", "")))
    return out


def centre_by_name(osm_pbf: str, bound, names) -> dict:
    """City centre = the OpenStreetMap place=city node carrying the city name, inside the boundary. If several match,
    the one that is the admin_centre of the city's boundary relation. Fall-backs, in order: a place=town node of that
    name inside the boundary; the admin_centre node of the boundary relation of that name; none."""
    nodes = _parse_opl(_opl(osm_pbf, ["n/place=city,town"])); rels = _parse_opl(_opl(osm_pbf, ["r/boundary=administrative"]))
    names = set(names)
    nm = lambda t: bool({t.get("name"), t.get("name:en")} & names)
    cand = [n for n in nodes if nm(n["tags"]) and n["x"] is not None and shapely.contains_xy(bound, n["x"], n["y"])]
    adm = {m.split("@")[0][1:] for r in rels if nm(r["tags"]) for m in r["members"].split(",") if m.endswith("@admin_centre") and m.startswith("n")}
    city = [n for n in cand if n["tags"].get("place") == "city"]; town = [n for n in cand if n["tags"].get("place") == "town"]
    def pick(lst, rule):
        if len(lst) > 1:
            a = [n for n in lst if n["id"][1:] in adm]
            if len(a) == 1: return a[0], rule + "; several matched, admin_centre member of the city boundary relation"
            return None, rule + f"; {len(lst)} matched, admin_centre did not resolve ({len(a)})"
        return lst[0], rule
    n, rule = None, None
    if city: n, rule = pick(city, "place=city node of the city name inside the boundary")
    elif town: n, rule = pick(town, "fall-back: place=town node of the city name inside the boundary")
    else:
        a = [x for x in nodes if x["id"][1:] in adm and x["x"] is not None]
        if a: n, rule = a[0], "fall-back: admin_centre node of the boundary relation of that name"
    if n is None:
        return {"lat": None, "lon": None, "rule": rule or "none found", "osm_node": None}
    return {"lat": round(n["y"], 6), "lon": round(n["x"], 6), "rule": rule, "osm_node": n["id"], "node_name": n["tags"].get("name")}


def centre_by_place_density(U) -> dict:
    """Fall-back centre: place-density-weighted centroid of the cells in the top quarter of place density."""
    den = U.n_poi / U.area_km2; top = U[den >= den.quantile(0.75)]; wts = den[top.index]
    return {"lat": float(np.average(top.lat, weights=wts)), "lon": float(np.average(top.lon, weights=wts)),
            "rule": f"place-density-weighted centroid of cells at or above the 75th percentile of place density (n={len(top)})", "osm_node": None}
