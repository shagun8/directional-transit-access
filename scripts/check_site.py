#!/usr/bin/env python3
"""Check a built site, from a folder or over HTTP.

    python scripts/check_site.py _site
    python scripts/check_site.py http://localhost:8000/
    python scripts/check_site.py https://<owner>.github.io/directional-transit-access/

Checks
  - index, about and every city page load (HTTP 200, or the file exists)
  - every local script, stylesheet and link on those pages loads
  - no page loads a script, stylesheet or image from another host
  - every data file a page needs exists and parses (JSON, GeoJSON, CSV)
  - held cities expose no cell file, and their page says so
  - the fixed notes and the footer are on the pages

Exit code is non-zero on any failure. Prints a one-line summary.
Options: --strict (a missing data/ATTRIBUTION.md is a failure, not a warning),
         --expect-cities N (fail unless exactly N cities).
Standard library only.
"""
import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

TIMEOUT = 60
NOTE_CLASSES = "Classes and ranks are relative to each city. Do not compare them between cities."
NOTE_UNITS = "Hexagon and tract values are not comparable. The unit changes the numbers."
NOTE_HELD = ("Cell-level data for this city are not yet published. "
             "The source and licence of its schedule files are being confirmed.")
FOOTER = ("Code: MIT. Data: ODbL 1.0. Built from OpenStreetMap, public transit schedules (GTFS), "
          "WorldPop, Meta HRSL and US Census data. No cookies, no tracking.")
OPTIONAL = ("data/ATTRIBUTION.md",)   # added by the release, not by the site build

CELL_FIELDS = ["city", "cell_id", "residents", "is_origin", "coverage_un_pct", "class",
               "n_car_directions", "n_blocked", "blocked_share", "n_missing", "n_dead",
               "n_thin", "s", "q", "half_blocked"]
TRACT_FIELDS = ["city", "geoid", "residents", "coverage_pct", "class", "n_car_directions",
                "n_blocked", "blocked_share", "n_missing", "n_dead", "n_thin", "s", "q",
                "half_blocked"]
CITY_FIELDS = ["city", "city_name", "country", "relaxed", "relaxations", "data_caveat", "run_date", "centre_lat",
               "centre_lon", "residents", "n_cells", "n_origins", "population_source",
               "un_coverage_share", "headline_share_un", "headline_served_blocked_half_un",
               "headline_served_denominator_un", "headline_cells_blocked_half", "n_SI", "n_FS",
               "median_blocked_SI", "median_blocked_FS", "cells_public", "has_tracts"]


class Target(object):
    """Reads files from a folder or a base URL. read() returns bytes, or None if absent."""

    def __init__(self, base):
        self.is_http = base.startswith("http://") or base.startswith("https://")
        self.base = (base.rstrip("/") + "/") if self.is_http else base

    def read(self, rel):
        if self.is_http:
            url = self.base + urllib.parse.quote(rel)
            try:
                with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
                    if resp.status != 200:
                        return None
                    return resp.read()
            except urllib.error.HTTPError:
                return None
        path = os.path.join(self.base, *rel.split("/"))
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()


class Refs(HTMLParser):
    """Collects what a page loads (scripts, styles, images) and where it links."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.loads = []
        self.links = []
        self.text = []
        self.body_attrs = {}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self.body_attrs = a
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "script" and a.get("src"):
            self.loads.append(a["src"])
        elif tag == "link" and a.get("href"):
            self.loads.append(a["href"])
        elif tag in ("img", "iframe", "source", "audio", "video", "embed") and a.get("src"):
            self.loads.append(a["src"])
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)

    def plain_text(self):
        return " ".join(" ".join(self.text).split())


def resolve(page_rel, ref):
    """Path of ref relative to the site root, or None if there is nothing to fetch."""
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref:
        return None
    joined = os.path.normpath(os.path.join(os.path.dirname(page_rel), ref)).replace(os.sep, "/")
    if ref.endswith("/"):
        joined += "/index.html"
    return joined


def is_external(ref):
    return urllib.parse.urlparse(ref).scheme in ("http", "https") or ref.startswith("//")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a built site.")
    ap.add_argument("base", help="base URL or local folder of the built site")
    ap.add_argument("--strict", action="store_true", help="treat a missing data/ATTRIBUTION.md as a failure")
    ap.add_argument("--expect-cities", type=int, default=None, help="fail unless exactly this many cities")
    args = ap.parse_args(argv)

    t = Target(args.base)
    if not t.is_http and not os.path.isdir(args.base):
        sys.stderr.write("check_site: FAIL: not a folder: %s\n" % args.base)
        print("check_site: FAILED - 0 pages, 1 failures")
        return 1
    failures, warnings = [], []
    counts = {"pages": 0, "data": 0, "assets": 0, "held": 0}

    def bad(msg):
        failures.append(msg)

    def get_text(rel, what):
        try:
            raw = t.read(rel)
        except (urllib.error.URLError, OSError) as exc:
            bad("%s cannot be read: %s (%s)" % (what, rel, exc))
            return None
        if raw is None:
            bad("%s does not load: %s" % (what, rel))
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            bad("%s is not UTF-8: %s" % (what, rel))
            return None

    def exists(rel):
        try:
            return t.read(rel) is not None
        except (urllib.error.URLError, OSError):
            return False

    def get_json(rel):
        text = get_text(rel, "data file")
        if text is None:
            return None
        try:
            obj = json.loads(text)
        except ValueError as exc:
            bad("data file does not parse as JSON: %s (%s)" % (rel, exc))
            return None
        counts["data"] += 1
        return obj

    def get_csv(rel, fields, min_rows=1):
        text = get_text(rel, "data file")
        if text is None:
            return None
        try:
            rows = list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error as exc:
            bad("data file does not parse as CSV: %s (%s)" % (rel, exc))
            return None
        if not rows:
            bad("CSV is empty: %s" % rel)
            return None
        header, body = rows[0], rows[1:]
        missing = [f for f in fields if f not in header]
        if missing:
            bad("CSV %s lacks columns: %s" % (rel, missing))
        if any(len(r) != len(header) for r in body):
            bad("CSV %s has rows with a different number of columns" % rel)
        if len(body) < min_rows:
            bad("CSV %s has %d rows, expected at least %d" % (rel, len(body), min_rows))
        counts["data"] += 1
        return [dict(zip(header, r)) for r in body]

    def get_features(rel, fields, city_id):
        obj = get_json(rel)
        if obj is None:
            return None
        feats = obj.get("features") if isinstance(obj, dict) else None
        if not isinstance(obj, dict) or obj.get("type") != "FeatureCollection" \
                or not isinstance(feats, list) or not feats:
            bad("GeoJSON has no features: %s" % rel)
            return None
        for f in feats:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            if geom.get("type") not in ("Polygon", "MultiPolygon") or not geom.get("coordinates"):
                bad("GeoJSON %s has a feature without a polygon" % rel)
                break
            lack = [k for k in fields if k not in props]
            if lack:
                bad("GeoJSON %s has a feature without: %s" % (rel, lack))
                break
            if props.get("city") != city_id:
                bad("GeoJSON %s has a feature of another city: %r" % (rel, props.get("city")))
                break
        return feats

    checked_refs = {}

    def check_ref(page_rel, ref):
        target = resolve(page_rel, ref)
        if target is None:
            return
        if target.startswith(".."):
            bad("page %s points outside the site: %s" % (page_rel, ref))
            return
        if target not in checked_refs:
            if target.startswith("data/cells/") or target.startswith("data/tracts/"):
                checked_refs[target] = True      # parsed in the data checks below
            else:
                checked_refs[target] = exists(target)
                if checked_refs[target]:
                    counts["assets"] += 1
                elif target in OPTIONAL and not args.strict:
                    warnings.append("%s is not there yet (linked from the footer)" % target)
                else:
                    bad("file does not load: %s (first linked from %s)" % (target, page_rel))

    def check_page(rel, must_contain=(), must_not_contain=(), city_id=None):
        text = get_text(rel, "page")
        if text is None:
            return
        counts["pages"] += 1
        p = Refs()
        p.feed(text)
        p.close()
        plain = p.plain_text()
        for s in (FOOTER,) + tuple(must_contain):
            if s not in plain:
                bad("page %s lacks the text: %s" % (rel, s[:70]))
        for s in must_not_contain:
            if s in text:
                bad("page %s must not contain: %s" % (rel, s))
        if "__ROOT__" in text or "__CITY" in text or "<!--IF_" in text:
            bad("page %s has unfilled template tokens" % rel)
        if city_id is not None and p.body_attrs.get("data-city") != city_id:
            bad("page %s does not carry city id %s" % (rel, city_id))
        for ref in p.loads:
            if ref.startswith("data:"):
                continue
            if is_external(ref):
                bad("page %s loads a file from another host: %s" % (rel, ref))
            elif ref.startswith("/"):
                bad("page %s uses an absolute path: %s" % (rel, ref))
            else:
                check_ref(rel, ref)
        for ref in p.links:
            if is_external(ref) or ref.startswith(("mailto:", "#")):
                continue
            if ref.startswith("/"):
                bad("page %s uses an absolute path: %s" % (rel, ref))
            else:
                check_ref(rel, ref)

    # ---- data index ----
    meta = get_json("data/cities.json")
    cities = meta.get("cities") if isinstance(meta, dict) else None
    if not isinstance(cities, list) or not cities:
        bad("data/cities.json has no cities")
        cities = []
    held = set(meta.get("held_cities") or []) if isinstance(meta, dict) else set()
    for c in cities:
        lack = [k for k in CITY_FIELDS if k not in c]
        if lack:
            bad("cities.json entry %r lacks: %s" % (c.get("city"), lack))
        if c.get("has_tracts") and not isinstance(c.get("tract"), dict):
            bad("cities.json entry %r has tracts but no tract numbers" % c.get("city"))
    ids = [c.get("city") for c in cities]
    if args.expect_cities is not None and len(cities) != args.expect_cities:
        bad("expected %d cities, found %d" % (args.expect_cities, len(cities)))
    site_held = get_json("held_cities.json")
    if not isinstance(site_held, list) or set(site_held) != held:
        bad("held_cities.json does not match held_cities in data/cities.json")
    not_public = set(c.get("city") for c in cities if not c.get("cells_public", True))
    if not_public != held:
        bad("cities with cells_public=false %s differ from held_cities %s" % (sorted(not_public), sorted(held)))

    # ---- pages ----
    check_page("index.html")
    check_page("about.html")
    for c in cities:
        cid = c.get("city")
        rel = "city/%s/index.html" % cid
        if cid in held:
            check_page(rel, must_contain=(NOTE_CLASSES, NOTE_HELD),
                       must_not_contain=["data/cells/", "note-units"], city_id=cid)
        elif c.get("has_tracts"):
            check_page(rel, must_contain=(NOTE_CLASSES, NOTE_UNITS),
                       must_not_contain=["note-held"], city_id=cid)
        else:
            check_page(rel, must_contain=(NOTE_CLASSES,),
                       must_not_contain=["note-held", "note-units"], city_id=cid)

    # ---- data files ----
    rows = get_csv("data/city_summary.csv", ["city", "headline_share_un"])
    if rows is not None and sorted(r.get("city") for r in rows) != sorted(ids):
        bad("data/city_summary.csv cities differ from data/cities.json")
    us = [c.get("city") for c in cities if c.get("has_tracts")]
    rows = get_csv("data/tract_city_summary.csv", ["city"], min_rows=0)
    if rows is not None and not set(us) <= set(r.get("city") for r in rows):
        bad("data/tract_city_summary.csv lacks some cities that have tracts")

    for c in cities:
        cid = c.get("city")
        if cid in held:
            counts["held"] += 1
            for ext in ("geojson", "csv"):
                rel = "data/cells/%s.%s" % (cid, ext)
                try:
                    present = t.read(rel) is not None
                except (urllib.error.URLError, OSError) as exc:
                    bad("could not confirm that %s is absent (%s)" % (rel, exc))
                    continue
                if present:
                    bad("held city exposes a cell file: %s" % rel)
        else:
            feats = get_features("data/cells/%s.geojson" % cid, CELL_FIELDS, cid)
            rows = get_csv("data/cells/%s.csv" % cid, CELL_FIELDS)
            if feats is not None and rows is not None and len(feats) != len(rows):
                bad("cells of %s: GeoJSON has %d features, CSV has %d rows" % (cid, len(feats), len(rows)))
            if feats is not None and c.get("n_cells") is not None and len(feats) != c["n_cells"]:
                bad("cells of %s: %d features, cities.json says n_cells=%s" % (cid, len(feats), c["n_cells"]))
        if c.get("has_tracts"):
            feats = get_features("data/tracts/%s.geojson" % cid, TRACT_FIELDS, cid)
            rows = get_csv("data/tracts/%s.csv" % cid, TRACT_FIELDS)
            if feats is not None and rows is not None and len(feats) != len(rows):
                bad("tracts of %s: GeoJSON has %d features, CSV has %d rows" % (cid, len(feats), len(rows)))

    for msg in warnings:
        sys.stderr.write("check_site: warning: %s\n" % msg)
    for msg in failures:
        sys.stderr.write("check_site: FAIL: %s\n" % msg)
    print("check_site: %s - %d pages, %d page files and links, %d data files parsed, "
          "%d held cities with no cell file, %d failures, %d warnings"
          % ("FAILED" if failures else "OK", counts["pages"], counts["assets"], counts["data"],
             counts["held"], len(failures), len(warnings)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
