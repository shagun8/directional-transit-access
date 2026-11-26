#!/usr/bin/env python3
"""Assemble the static site.

    python scripts/build_site.py --data data --site site --out _site

What it does
  1. Copies site/ into the output folder (the city template city.html is not copied).
  2. Copies data/ into <out>/data/, but leaves out data/cells/<city>.* for every
     city listed in site/held_cities.json.
  3. Writes one page per city at <out>/city/<city>/index.html with the city id baked in.

It does not read, change or round any data value. It only copies files and fills
the city id, name and country into the page template.

Standard library only.
"""
import argparse
import html
import json
import os
import re
import shutil
import sys

MARKER = ".site_build.json"
TEMPLATE = "city.html"
CITY_ID = re.compile(r"^[a-z0-9_-]+$")


def fail(msg):
    sys.stderr.write("build_site: ERROR: %s\n" % msg)
    sys.exit(1)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def keep_block(text, name, keep):
    """Keep or drop everything between <!--IF_NAME--> and <!--END_NAME-->."""
    pattern = re.compile(r"[ \t]*<!--IF_%s-->\n?(.*?)[ \t]*<!--END_%s-->\n?" % (name, name), re.S)
    return pattern.sub((lambda m: m.group(1)) if keep else "", text)


def render_city(template, city, held):
    is_held = city["city"] in held
    page = template
    page = keep_block(page, "US", bool(city.get("has_tracts")) and not is_held)
    page = keep_block(page, "HELD", is_held)
    page = keep_block(page, "PUBLIC", not is_held)
    page = page.replace("__ROOT__", "../../")
    page = page.replace("__CITY_NAME__", html.escape(str(city["city_name"]), quote=True))
    page = page.replace("__COUNTRY__", html.escape(str(city.get("country") or ""), quote=True))
    page = page.replace("__CITY__", city["city"])
    left = re.findall(r"__[A-Z_]+__|<!--(?:IF|END)_[A-Z]+-->", page)
    if left:
        fail("template tokens left in page for %s: %s" % (city["city"], sorted(set(left))))
    return page


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble the static site.")
    ap.add_argument("--data", required=True, help="data folder (contains cities.json, cells/, tracts/)")
    ap.add_argument("--site", required=True, help="site source folder")
    ap.add_argument("--out", required=True, help="output folder (replaced if it is a previous build)")
    args = ap.parse_args(argv)

    data, site, out = args.data, args.site, args.out
    for need in (os.path.join(site, "index.html"), os.path.join(site, "about.html"),
                 os.path.join(site, TEMPLATE), os.path.join(site, "held_cities.json"),
                 os.path.join(data, "cities.json")):
        if not os.path.isfile(need):
            fail("missing input file: %s" % need)

    held = read_json(os.path.join(site, "held_cities.json"))
    if not isinstance(held, list) or not all(isinstance(x, str) for x in held):
        fail("site/held_cities.json must be a JSON list of city ids")
    held = set(held)

    meta = read_json(os.path.join(data, "cities.json"))
    cities = meta.get("cities")
    if not isinstance(cities, list) or not cities:
        fail("data/cities.json has no cities")
    ids = [c.get("city") for c in cities]
    for cid in ids:
        if not isinstance(cid, str) or not CITY_ID.match(cid):
            fail("unsafe or missing city id: %r" % (cid,))
    if len(set(ids)) != len(ids):
        fail("duplicate city ids in data/cities.json")

    # The held list and the data must agree, otherwise a page and its files disagree.
    data_held = set(meta.get("held_cities") or [])
    not_public = set(c["city"] for c in cities if not c.get("cells_public", True))
    if held != data_held or held != not_public:
        fail("held cities disagree: site/held_cities.json=%s, cities.json held_cities=%s, "
             "cities with cells_public=false=%s" % (sorted(held), sorted(data_held), sorted(not_public)))

    out_abs = os.path.abspath(out)
    for src in (site, data):
        src_abs = os.path.abspath(src)
        if out_abs == src_abs or src_abs.startswith(out_abs + os.sep) or out_abs.startswith(src_abs + os.sep):
            fail("output folder must not be, contain or sit inside an input folder: %s" % out)
    if os.path.exists(out):
        if os.path.isdir(out) and (not os.listdir(out) or os.path.isfile(os.path.join(out, MARKER))):
            shutil.rmtree(out)
        else:
            fail("output folder exists and is not a previous build: %s (remove it yourself)" % out)

    # 1. site source (without the template)
    site_abs = os.path.abspath(site)
    shutil.copytree(site, out, ignore=lambda d, names: [TEMPLATE] if os.path.abspath(d) == site_abs else [])

    # 2. data, without the cell files of held cities
    cells_dir = os.path.abspath(os.path.join(data, "cells"))
    skipped = []

    def ignore_held(folder, names):
        if os.path.abspath(folder) != cells_dir:
            return []
        drop = [n for n in names if n.split(".", 1)[0] in held]
        skipped.extend(drop)
        return drop

    shutil.copytree(data, os.path.join(out, "data"), ignore=ignore_held)

    # every city that is not held must have its files
    for c in cities:
        cid = c["city"]
        wanted = []
        if cid not in held:
            wanted += ["cells/%s.geojson" % cid, "cells/%s.csv" % cid]
        if c.get("has_tracts"):
            wanted += ["tracts/%s.geojson" % cid, "tracts/%s.csv" % cid]
        for rel in wanted:
            if not os.path.isfile(os.path.join(out, "data", rel)):
                fail("data file missing for %s: data/%s" % (cid, rel))
    left_in = [n for n in os.listdir(os.path.join(out, "data", "cells"))
               if n.split(".", 1)[0] in held] if os.path.isdir(os.path.join(out, "data", "cells")) else []
    if left_in:
        fail("held city cell files were copied: %s" % sorted(left_in))

    # 3. one page per city
    with open(os.path.join(site, TEMPLATE), encoding="utf-8") as fh:
        template = fh.read()
    for c in cities:
        folder = os.path.join(out, "city", c["city"])
        os.makedirs(folder)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_city(template, c, held))

    # GitHub Pages: serve files as they are
    open(os.path.join(out, ".nojekyll"), "w").close()
    with open(os.path.join(out, MARKER), "w", encoding="utf-8") as fh:
        json.dump({"cities": len(cities), "held_cities": sorted(held),
                   "cell_files_left_out": sorted(skipped)}, fh, indent=1)
        fh.write("\n")

    print("build_site: wrote %d city pages to %s; left out %d cell files of %d held cities"
          % (len(cities), out, len(skipped), len(held)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
