#!/usr/bin/env python3
"""Download the raw inputs of the Jerusalem regression city (about 300 MB) and check their checksums.

    python scripts/download_regression_inputs.py --out inputs/jerusalem

Large inputs are never stored in the repository. Sources and checksums: tests/data/jerusalem/inputs.json.
A checksum mismatch is reported, not hidden: the OpenStreetMap extract is replaced daily at the source, and a
later file gives slightly different travel times. Standard library only.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", default=os.path.join(HERE, "..", "tests", "data", "jerusalem", "inputs.json"))
    a = ap.parse_args()
    meta = json.load(open(a.meta, encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    bad = 0
    for key in ["gtfs", "osm", "population", "r5_jar"]:
        rec = meta[key]; dst = os.path.join(a.out, rec["file"])
        if not os.path.exists(dst):
            print("downloading", rec["url"])
            urllib.request.urlretrieve(rec["url"], dst + ".part"); os.replace(dst + ".part", dst)
        got = md5(dst); ok = got == rec["md5"]
        print(("OK      " if ok else "DIFFERS ") + rec["file"], got)
        bad += not ok
    if bad:
        print(f"{bad} file(s) differ from the recorded checksum; results will not match the stored ones exactly.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
