#!/usr/bin/env python3
"""Scan the repository before every push. Stops (exit 1) on any match.

  1. Secrets: token and key patterns, private-key blocks.
  2. Personal paths, user names and machine names.
  3. Columns that come from phone-location data, wealth indices or other sources that must not be released.
  4. Files that should never be in git: schedule zips, OpenStreetMap extracts, rasters, files above 25 MB.

    python scripts/scan_release.py [folder]

Standard library only.
"""
import csv
import json
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SKIP_DIRS = {".git", "_site", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
TEXT_EXT = {".py", ".md", ".json", ".geojson", ".csv", ".yml", ".yaml", ".toml", ".cff", ".txt", ".html", ".js", ".css", ".cfg", ".sh", ""}
SECRETS = [
    ("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer or api key assignment", re.compile(r"(?i)\b(api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*[\"\'][A-Za-z0-9_\-./+]{20,}[\"\']")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
]
PATHS = [
    ("absolute home or scratch path", re.compile(r"(?<![A-Za-z0-9_.-])/(home|scratch|Users|mnt|bridge)/[A-Za-z0-9_.-]+/")),
    ("Windows user path", re.compile(r"[A-Za-z]:\\\\Users\\\\")),
    ("personal or machine name", re.compile(r"(?i)\b(mittal53|umni\d|umnilab|ecnuser)\b")),
]
# column names (CSV headers, GeoJSON property keys, Parquet columns) that mark non-releasable data
BANNED_COLUMNS = re.compile(
    r"(?i)^(.*footfall.*|.*visitor.*|.*device.*|total_devices|avg_demand_pct|demand_generated.*|.*trip_count.*|home_.*|.*caid.*|.*maid.*|"
    r"rwi|rwi_tile_share|.*ridership.*|boardings|alightings|.*ctpp.*|median_household_income|median_hh_income|.*google.*)$")
BANNED_FILES = re.compile(r"(?i)\.(osm\.pbf|pbf|tif|tiff|vrt|jar)$|(^|/)(?!.*fixtures?)(gtfs|feed)[^/]*\.zip$")
MAX_BYTES = 25 * 1024 * 1024
ALLOW = {  # (file suffix, rule) pairs that are known and harmless
    ("scripts/scan_release.py", "*"),
}


def allowed(rel, rule):
    return any(rel.endswith(s) and (r == "*" or r == rule) for s, r in ALLOW)


def columns_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            return next(csv.reader(f), [])
    if ext == ".geojson":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        keys = set()
        for ft in d.get("features", []):
            keys.update((ft.get("properties") or {}).keys())
        return sorted(keys)
    if ext == ".parquet":
        try:
            import pyarrow.parquet as pq
            return pq.ParquetFile(path).schema_arrow.names
        except ImportError:
            return []
    return []


def main():
    hits = []; n_files = 0; n_tables = 0; total = 0
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for fn in files:
            p = os.path.join(d, fn); rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            size = os.path.getsize(p); total += size; n_files += 1
            if BANNED_FILES.search(rel): hits.append((rel, "file type must not be in git"))
            if size > MAX_BYTES: hits.append((rel, f"file larger than 25 MB ({size / 1e6:.1f} MB)"))
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".csv", ".geojson", ".parquet"):
                n_tables += 1
                for c in columns_of(p):
                    if BANNED_COLUMNS.match(str(c)) and not allowed(rel, "column"):
                        hits.append((rel, f"banned column '{c}'"))
            if ext in TEXT_EXT and size < 30 * 1024 * 1024:
                with open(p, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                for name, rx in SECRETS + PATHS:
                    m = rx.search(text)
                    if m and not allowed(rel, name):
                        hits.append((rel, f"{name}: ...{text[max(0, m.start() - 20):m.end() + 20]!r}..."))
    print(f"scanned {n_files} files ({total / 1e6:.1f} MB), {n_tables} tables")
    for rel, what in hits:
        print("MATCH", rel, "|", what)
    print("RESULT:", "clean" if not hits else f"{len(hits)} match(es) - do not push")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
