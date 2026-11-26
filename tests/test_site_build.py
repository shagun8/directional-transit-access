"""Build the site from a small fixture and check it.

    python -m pytest tests/test_site_build.py

The fixture holds real files for Jerusalem, Kigali and Santa Ana, and the summary entry
of one held city (Chennai). No cell data of a held city is stored in the repository.
"""
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from html.parser import HTMLParser

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SITE = os.path.join(REPO, "site")
BUILD = os.path.join(REPO, "scripts", "build_site.py")
CHECK = os.path.join(REPO, "scripts", "check_site.py")
FIXTURE = os.path.join(HERE, "fixtures", "site_data")
ABOUT_TEXT = os.path.join(HERE, "fixtures", "about_text.md")

HELD_NOTE = ("Cell-level data for this city are not yet published. "
             "The source and licence of its schedule files are being confirmed.")
# other hosts the site may name: the background map, and credit links for it
ALLOWED_HOSTS = {"tiles.openfreemap.org", "openfreemap.org", "www.openmaptiles.org", "www.openstreetmap.org"}


def run(script, *args):
    return subprocess.run([sys.executable, script] + list(args), capture_output=True, text=True)


def fixture_cities():
    with open(os.path.join(FIXTURE, "cities.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def inputs(tmp_path):
    """Copies of site/ and the fixture data. The held list is taken from the fixture."""
    site = tmp_path / "site"
    data = tmp_path / "data"
    shutil.copytree(SITE, str(site))
    shutil.copytree(FIXTURE, str(data))
    held = fixture_cities()["held_cities"]
    (site / "held_cities.json").write_text(json.dumps(held) + "\n", encoding="utf-8")
    # a placeholder cell file for the held city, so the test can see it being left out
    for ext in ("geojson", "csv"):
        (data / "cells" / ("%s.%s" % (held[0], ext))).write_text("PLACEHOLDER\n", encoding="utf-8")
    return site, data, held


@pytest.fixture()
def built(inputs, tmp_path):
    site, data, held = inputs
    out = tmp_path / "_site"
    res = run(BUILD, "--data", str(data), "--site", str(site), "--out", str(out))
    assert res.returncode == 0, res.stderr
    return out, data, held


def test_build_writes_one_page_per_city(built):
    out, _, held = built
    cities = fixture_cities()["cities"]
    for name in ("index.html", "about.html", "held_cities.json", ".nojekyll",
                 "assets/css/site.css", "assets/js/common.js", "assets/js/index.js", "assets/js/city.js",
                 "vendor/maplibre-gl/maplibre-gl.js", "vendor/maplibre-gl/maplibre-gl.css",
                 "vendor/maplibre-gl/LICENSE.txt", "data/cities.json", "data/city_summary.csv"):
        assert (out / name).is_file(), name
    assert not (out / "city.html").exists()
    assert sorted(p.name for p in (out / "city").iterdir()) == sorted(c["city"] for c in cities)
    for c in cities:
        page = (out / "city" / c["city"] / "index.html").read_text(encoding="utf-8")
        assert 'data-city="%s"' % c["city"] in page
        assert 'data-root="../../"' in page
        assert "__ROOT__" not in page and "__CITY" not in page and "<!--IF_" not in page
        assert "Classes and ranks are relative to each city. Do not compare them between cities." in page
        if c["city"] in held:
            assert HELD_NOTE in page
            assert "data/cells/" not in page
            assert 'id="map"' not in page
        else:
            assert HELD_NOTE not in page
            assert "data/cells/%s.geojson" % c["city"] in page
            assert "data/cells/%s.csv" % c["city"] in page
        has_note = "Hexagon and tract values are not comparable. The unit changes the numbers." in page
        assert has_note == bool(c["has_tracts"])
        assert ("data/tracts/%s.geojson" % c["city"] in page) == bool(c["has_tracts"])


def test_held_city_cell_files_are_left_out(built):
    out, data, held = built
    for ext in ("geojson", "csv"):
        assert (data / "cells" / ("%s.%s" % (held[0], ext))).is_file()        # it was in the input
        assert not (out / "data" / "cells" / ("%s.%s" % (held[0], ext))).exists()
    copied = sorted(p.name for p in (out / "data" / "cells").iterdir())
    assert copied == ["jerusalem.csv", "jerusalem.geojson", "kigali.csv", "kigali.geojson",
                      "santaana.csv", "santaana.geojson"]


def test_data_files_are_copied_unchanged(built):
    out, data, held = built
    for folder, _, names in os.walk(str(data)):
        for name in names:
            src = os.path.join(folder, name)
            rel = os.path.relpath(src, str(data))
            if rel.startswith("cells") and name.split(".")[0] in held:
                continue
            with open(src, "rb") as a, open(os.path.join(str(out), "data", rel), "rb") as b:
                assert a.read() == b.read(), rel


def test_check_site_passes_on_folder(built):
    out, _, _ = built
    res = run(CHECK, str(out), "--expect-cities", "4")
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip().startswith("check_site: OK")
    assert len(res.stdout.strip().splitlines()) == 1


def test_check_site_passes_over_http(built):
    out, _, _ = built
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        res = run(CHECK, "http://127.0.0.1:%d/" % server.server_address[1], "--expect-cities", "4")
    finally:
        server.shutdown()
        server.server_close()
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip().startswith("check_site: OK")


def test_check_site_fails_when_held_cell_file_is_exposed(built):
    out, _, held = built
    (out / "data" / "cells" / (held[0] + ".geojson")).write_text("PLACEHOLDER\n", encoding="utf-8")
    res = run(CHECK, str(out))
    assert res.returncode != 0
    assert "held city exposes a cell file" in res.stderr


def test_check_site_fails_when_a_page_is_missing(built):
    out, _, _ = built
    os.remove(str(out / "city" / "kigali" / "index.html"))
    res = run(CHECK, str(out))
    assert res.returncode != 0
    assert "city/kigali/index.html" in res.stderr


def test_check_site_fails_when_a_data_file_is_broken(built):
    out, _, _ = built
    (out / "data" / "cells" / "jerusalem.geojson").write_text("{not json", encoding="utf-8")
    res = run(CHECK, str(out))
    assert res.returncode != 0
    assert "jerusalem.geojson" in res.stderr


def test_check_site_strict_needs_attribution_file(built):
    out, _, _ = built
    assert run(CHECK, str(out), "--strict").returncode != 0
    (out / "data" / "ATTRIBUTION.md").write_text("placeholder\n", encoding="utf-8")
    assert run(CHECK, str(out), "--strict").returncode == 0


def test_build_refuses_when_held_lists_disagree(inputs, tmp_path):
    site, data, _ = inputs
    (site / "held_cities.json").write_text("[]\n", encoding="utf-8")
    out = tmp_path / "_site"
    res = run(BUILD, "--data", str(data), "--site", str(site), "--out", str(out))
    assert res.returncode != 0
    assert "held cities disagree" in res.stderr
    assert not (out / "data").exists()


def test_build_refuses_to_replace_a_foreign_folder(inputs, tmp_path):
    site, data, _ = inputs
    out = tmp_path / "keep_me"
    out.mkdir()
    (out / "notes.txt").write_text("mine\n", encoding="utf-8")
    res = run(BUILD, "--data", str(data), "--site", str(site), "--out", str(out))
    assert res.returncode != 0
    assert (out / "notes.txt").is_file()


def test_site_held_list_is_a_list_of_ids():
    with open(os.path.join(SITE, "held_cities.json"), encoding="utf-8") as fh:
        held = json.load(fh)
    assert isinstance(held, list) and held and all(isinstance(x, str) for x in held)


def site_text_files():
    for folder, dirs, names in os.walk(SITE):
        dirs[:] = [d for d in dirs if d != "vendor"]
        for name in names:
            if name.endswith((".html", ".js", ".css")):
                yield os.path.join(folder, name)


def test_no_other_hosts_no_absolute_paths_no_tracking():
    for path in site_text_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", text):
            assert host in ALLOWED_HOSTS, "%s names another host: %s" % (path, host)
        assert not re.search(r"""(?:src|href)\s*=\s*["']/""", text), "%s uses an absolute path" % path
        assert not re.search(r"""url\(\s*["']?(?:/|https?:)""", text), "%s loads a remote or absolute url()" % path
        for word in ("document.cookie", "localStorage", "sessionStorage", "sendBeacon", "@import",
                     "@font-face", "googletagmanager", "google-analytics", "gtag("):
            assert word not in text, "%s contains %s" % (path, word)
    # only anchors may point to another host; nothing is loaded from one
    for path in site_text_files():
        if not path.endswith(".html"):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        assert not re.search(r"""<(?:script|link|img|iframe)[^>]+(?:src|href)\s*=\s*["']https?:""", text), path


class _Text(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.items = []
        self._tag = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "li"):
            self._tag = tag
            self.items.append([tag, ""])

    def handle_endtag(self, tag):
        if tag == self._tag:
            self._tag = None

    def handle_data(self, data):
        if self._tag:
            self.items[-1][1] += data


def test_about_page_carries_the_agreed_text_and_nothing_else():
    with open(ABOUT_TEXT, encoding="utf-8") as fh:
        wanted = [line.rstrip("\n") for line in fh if line.strip()]
    wanted = [("h" if line.startswith("# ") else "li", line[2:]) for line in wanted]
    parser = _Text()
    with open(os.path.join(SITE, "about.html"), encoding="utf-8") as fh:
        main = fh.read().split("<main", 1)[1].split("</main>", 1)[0]
    parser.feed(main)
    got = [("h" if tag in ("h1", "h2") else "li", " ".join(text.split())) for tag, text in parser.items]
    assert got == wanted
