#!/usr/bin/env python3
"""Open the built site in a real Firefox and check what a reader would see.

    python tests/browser_render.py --site _site --out screenshots --xvfb

Optional. Not run by pytest. Standard library only: it talks to Firefox over its
Marionette port, so it needs no Selenium and no geckodriver.

  --xvfb      run Firefox on a virtual display (Xvfb over TCP) so WebGL works with
              software rendering. Without it Firefox runs headless (often no WebGL).
  --firefox   path of the Firefox program (default: firefox)

What it does: serves the site on 127.0.0.1, opens index, about and a few city pages at
1280x800 and inside a 390x800 and a 360x800 frame, clicks markers, areas and switches,
compares the area panel with the data file, collects console messages and saves PNGs.
It also swaps the background-map address for a local stand-in (one that answers, one
that never answers) to exercise both branches of the fail-soft code.
Writes <out>/render_report.json. Exit code 1 if any check fails.
"""
import argparse
import base64
import functools
import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
REAL_STYLE = "https://tiles.openfreemap.org/styles/positron"

FRAME_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>frame</title>
<style>html,body{margin:0;background:#888}iframe{border:0;display:block;background:#fff}</style></head>
<body><iframe id="frame" src="%s" width="%d" height="%d"></iframe></body></html>"""

MOCK_STYLE = {
    "version": 8, "name": "stand-in",
    "glyphs": "__BASE__/__mock__/fonts/{fontstack}/{range}.pbf",
    "sources": {"stand_in": {"type": "vector", "tiles": ["__BASE__/__mock__/tiles/{z}/{x}/{y}.pbf"], "maxzoom": 14}},
    "layers": [
        {"id": "background", "type": "background", "paint": {"background-color": "#eef3f5"}},
        {"id": "water", "type": "fill", "source": "stand_in", "source-layer": "water", "paint": {"fill-color": "#c8d7e0"}},
        {"id": "place-labels", "type": "symbol", "source": "stand_in", "source-layer": "place",
         "layout": {"text-field": ["get", "name"], "text-font": ["Noto Sans Regular"]}},
    ],
}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Handler(http.server.SimpleHTTPRequestHandler):
    mode = {"style": "real"}   # real | answers | hangs

    def log_message(self, *a, **k):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")   # the stand-in script must not be cached
        http.server.SimpleHTTPRequestHandler.end_headers(self)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        base = "http://%s:%d" % self.server.server_address
        if url.path == "/__frame__.html":
            q = urllib.parse.parse_qs(url.query)
            body = FRAME_PAGE % (q["u"][0], int(q["w"][0]), int(q["h"][0]))
            return self._send(body.encode(), "text/html; charset=utf-8")
        if url.path == "/__mock__/style.json":
            if self.mode["style"] == "hangs":
                time.sleep(20)
            return self._send(json.dumps(MOCK_STYLE).replace("__BASE__", base).encode(), "application/json")
        if url.path.startswith("/__mock__/"):
            self.send_error(404)
            return
        if url.path == "/assets/js/common.js" and self.mode["style"] != "real":
            with open(os.path.join(self.directory, "assets", "js", "common.js"), encoding="utf-8") as fh:
                text = fh.read()
            assert REAL_STYLE in text
            return self._send(text.replace(REAL_STYLE, base + "/__mock__/style.json").encode(), "text/javascript")
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Marionette(object):
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.settimeout(180)
        self.buf = b""
        self.mid = 0
        self._recv()

    def _recv(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        n, _, rest = self.buf.partition(b":")
        n = int(n)
        while len(rest) < n:
            rest += self.sock.recv(1 << 20)
        self.buf = rest[n:]
        return json.loads(rest[:n].decode("utf-8"))

    def cmd(self, name, **params):
        self.mid += 1
        payload = json.dumps([0, self.mid, name, params]).encode("utf-8")
        self.sock.sendall(str(len(payload)).encode() + b":" + payload)
        while True:
            r = self._recv()
            if r[0] == 1 and r[1] == self.mid:
                if r[2]:
                    raise RuntimeError("%s: %s" % (name, json.dumps(r[2])[:500]))
                return r[3]

    def js(self, script, args=(), chrome=False):
        if chrome:
            self.cmd("Marionette:SetContext", value="chrome")
        try:
            r = self.cmd("WebDriver:ExecuteScript", script=script, args=list(args))
        finally:
            if chrome:
                self.cmd("Marionette:SetContext", value="content")
        return r.get("value") if isinstance(r, dict) else r


class Browser(object):
    def __init__(self, firefox, use_xvfb, workdir):
        self.workdir = workdir
        self.procs = []
        self.log_path = os.path.join(workdir, "firefox.log")
        self.log_pos = 0
        profile = os.path.join(workdir, "profile")
        home = os.path.join(workdir, "home")
        os.makedirs(profile)
        os.makedirs(home)
        port = free_port()
        prefs = {
            "marionette.port": port, "webgl.force-enabled": True, "webgl.disabled": False,
            "browser.shell.checkDefaultBrowser": False, "app.update.auto": False,
            "datareporting.policy.dataSubmissionEnabled": False, "datareporting.healthreport.uploadEnabled": False,
            "toolkit.telemetry.enabled": False, "toolkit.telemetry.unified": False,
            "browser.aboutwelcome.enabled": False, "browser.startup.homepage": "about:blank",
            "startup.homepage_welcome_url": "about:blank", "startup.homepage_welcome_url.additional": "",
            "browser.newtabpage.enabled": False, "network.captive-portal-service.enabled": False,
            "network.connectivity-service.enabled": False, "extensions.update.enabled": False,
            "browser.safebrowsing.malware.enabled": False, "browser.safebrowsing.phishing.enabled": False,
            "services.settings.server": "http://127.0.0.1:9/", "devtools.console.stdout.content": True,
            "browser.sessionstore.resume_from_crash": False, "browser.cache.disk.enable": False,
            "ui.useOverlayScrollbars": 1, "browser.cache.memory.enable": False,
        }
        with open(os.path.join(profile, "user.js"), "w") as fh:
            for k, v in prefs.items():
                fh.write("user_pref(%s, %s);\n" % (json.dumps(k), json.dumps(v)))
        env = dict(os.environ, HOME=home, TMPDIR=workdir, MOZ_REMOTE_ALLOW_SYSTEM_ACCESS="1")
        args = [firefox, "--marionette", "--no-remote", "--remote-allow-system-access", "--profile", profile]
        if use_xvfb:
            disp = 90 + os.getpid() % 400
            xauth = os.path.join(workdir, "xauth")
            open(xauth, "w").close()
            cookie = subprocess.run(["mcookie"], capture_output=True, text=True).stdout.strip()
            subprocess.run(["xauth", "-f", xauth, "add", "127.0.0.1:%d" % disp, "MIT-MAGIC-COOKIE-1", cookie],
                           capture_output=True)
            xlog = open(os.path.join(workdir, "xvfb.log"), "w")
            self.procs.append(subprocess.Popen(
                ["Xvfb", ":%d" % disp, "-screen", "0", "1500x1100x24", "+extension", "GLX", "-listen", "tcp",
                 "-nolisten", "unix", "-nolisten", "local", "-auth", xauth, "-noreset"],
                stdout=xlog, stderr=subprocess.STDOUT, start_new_session=True))
            time.sleep(2)
            if self.procs[-1].poll() is not None:
                raise RuntimeError("Xvfb did not start; see %s" % xlog.name)
            env.update(DISPLAY="127.0.0.1:%d" % disp, XAUTHORITY=xauth, LIBGL_ALWAYS_SOFTWARE="1",
                       GDK_BACKEND="x11", MOZ_ENABLE_WAYLAND="0")
            env.pop("MOZ_HEADLESS", None)
            env.pop("WAYLAND_DISPLAY", None)
            self.display = "Xvfb virtual display"
        else:
            env["MOZ_HEADLESS"] = "1"
            args.insert(1, "--headless")
            self.display = "headless"
        log = open(self.log_path, "w")
        self.procs.append(subprocess.Popen(args + ["about:blank"], env=env, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True))
        self.m = None
        for _ in range(120):
            time.sleep(0.5)
            if self.procs[-1].poll() is not None:
                raise RuntimeError("Firefox exited; see %s" % self.log_path)
            try:
                self.m = Marionette(port)
                break
            except OSError:
                pass
        if self.m is None:
            raise RuntimeError("Firefox did not open its Marionette port")
        caps = self.m.cmd("WebDriver:NewSession", capabilities={"alwaysMatch": {"pageLoadStrategy": "normal"}})
        self.version = caps["capabilities"].get("browserVersion")

    def close(self):
        for p in reversed(self.procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(10)
            except Exception:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    pass

    def set_viewport(self, w, h):
        self.m.cmd("WebDriver:SetWindowRect", x=0, y=0, width=w, height=h + 100)
        time.sleep(0.3)
        inner = self.m.js("return [window.innerWidth, window.innerHeight, window.outerHeight]")
        self.m.cmd("WebDriver:SetWindowRect", x=0, y=0, width=w, height=h + (inner[2] - inner[1]))
        time.sleep(0.3)
        return self.m.js("return [window.innerWidth, window.innerHeight]")

    def reset_console(self):
        self.m.js("Services.console.reset(); return true;", chrome=True)
        with open(self.log_path, "rb") as fh:
            fh.seek(0, 2)
            self.log_pos = fh.tell()

    def console(self, base):
        """Errors and warnings since reset_console(), limited to this site and the background map."""
        msgs = self.m.js("""
            return Services.console.getMessageArray().map(function (m) {
              try { var e = m.QueryInterface(Ci.nsIScriptError);
                    return {msg: e.errorMessage, src: e.sourceName || '', line: e.lineNumber, flags: e.flags}; }
              catch (x) { return {msg: String(m.message), src: '', line: 0, flags: -1}; }
            });""", chrome=True)
        errors, warnings = [], []
        host = urllib.parse.urlparse(base).netloc
        for m in msgs:
            text = "%s (%s:%s)" % (m["msg"], m["src"].replace(base, ""), m["line"])
            if host not in m["src"] and host not in m["msg"] and "openfreemap" not in m["msg"]:
                continue
            if m["flags"] >= 0 and not (m["flags"] & 1) and not (m["flags"] & 8):
                errors.append(text)
            else:
                warnings.append(text)
        with open(self.log_path, "rb") as fh:
            fh.seek(self.log_pos)
            tail = fh.read().decode("utf-8", "replace")
        for line in tail.splitlines():
            if line.startswith("console.error: RSLoader"):
                continue   # Firefox's own settings service, switched off for this run
            if line.startswith("console.error:"):
                errors.append(line.strip())
            elif line.startswith("console.warn:"):
                warnings.append(line.strip())
        return sorted(set(errors)), sorted(set(warnings))

    def wait(self, script, timeout=40):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = self.m.js(script)
            except RuntimeError as exc:
                last = "error: %s" % exc
            if last and not str(last).startswith("error:"):
                return last
            time.sleep(0.3)
        return None

    def click(self, x, y):
        self.m.cmd("WebDriver:PerformActions", actions=[{
            "type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
            "actions": [{"type": "pointerMove", "x": int(round(x)), "y": int(round(y)), "duration": 0, "origin": "viewport"},
                        {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 60},
                        {"type": "pointerUp", "button": 0}]}])
        self.m.cmd("WebDriver:ReleaseActions")
        time.sleep(0.5)

    def shot(self, path, element=None):
        params = {"full": False, "hash": False}
        if element:
            params["id"] = element
        r = self.m.cmd("WebDriver:TakeScreenshot", **params)
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(r["value"]))


JS_LAYOUT = """
  var de = document.documentElement;
  var small = [];
  var nodes = document.querySelectorAll('a, button, select, .radio-row label');
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i], r = n.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (n.closest('noscript')) continue;
    if (r.height < 40) small.push((n.textContent || n.getAttribute('aria-label') || n.className || n.tagName).trim().slice(0, 40) + ' [' + Math.round(r.height) + 'px]');
  }
  var hosts = {};
  performance.getEntriesByType('resource').forEach(function (e) { try { hosts[new URL(e.name).host] = (hosts[new URL(e.name).host] || 0) + 1; } catch (x) {} });
  return {scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, small: small, hosts: hosts,
          cellRequests: performance.getEntriesByType('resource').filter(function (e) { return e.name.indexOf('/data/cells/') >= 0; }).length,
          cookies: document.cookie, storage: (function () { try { return localStorage.length + sessionStorage.length; } catch (x) { return -1; } })()};
"""

JS_MAP_STATE = """
  var S = window.Site, map = S && S.map;
  if (!map) return {map: false, mode: document.body.getAttribute('data-map')};
  var layers = map.getStyle().layers.map(function (l) { return l.id; });
  var out = {map: true, mode: document.body.getAttribute('data-map'), layers: layers, loaded: map.loaded(),
             attrib: (document.querySelector('.map-attrib') || {}).textContent || '',
             canvas: [map.getCanvas().clientWidth, map.getCanvas().clientHeight]};
  var want = arguments[0];
  out.rendered = want && map.getLayer(want) ? map.queryRenderedFeatures({layers: [want]}).length : null;
  return out;
"""


def run(args):
    site = os.path.abspath(args.site)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    handler = functools.partial(Handler, directory=site)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    workdir = tempfile.mkdtemp(prefix="render_", dir=args.workdir)
    report = {"pages": [], "failures": [], "console_errors": [], "console_warnings": []}
    with open(os.path.join(site, "data", "cities.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    cities = {c["city"]: c for c in meta["cities"]}
    b = Browser(args.firefox, args.xvfb, workdir)
    report["browser"] = "Firefox %s, %s" % (b.version, b.display)

    def fail(msg):
        report["failures"].append(msg)

    def expect(cond, msg):
        if not cond:
            fail(msg)
        return cond

    def open_page(rel, size, label, framed):
        """Returns the element id of the frame (or None) once the page is loaded."""
        b.reset_console()
        frame = None
        if framed:
            b.set_viewport(max(size[0], 500), size[1])
            b.m.cmd("WebDriver:Navigate", url="%s/__frame__.html?u=%s&w=%d&h=%d" % (
                base, urllib.parse.quote("/" + rel, safe="/"), size[0], size[1]))
            frame = b.m.cmd("WebDriver:FindElement", using="css selector", value="#frame")["value"][ELEMENT_KEY]
            b.m.cmd("WebDriver:SwitchToFrame", element=frame)
        else:
            got = b.set_viewport(*size)
            expect(got == list(size), "%s: window is %s, wanted %s" % (label, got, list(size)))
            b.m.cmd("WebDriver:Navigate", url=base + "/" + rel)
        return frame

    def shoot(name, frame):
        path = os.path.join(out, name + ".png")
        if frame:
            b.m.cmd("WebDriver:SwitchToParentFrame")
            b.shot(path, frame)
            b.m.cmd("WebDriver:SwitchToFrame", element=frame)
        else:
            b.shot(path)
        return os.path.basename(path)

    def finish(entry, label, frame, width, held=False):
        lay = b.m.js(JS_LAYOUT)
        entry["hosts"] = lay["hosts"]
        entry["small_targets"] = lay["small"]
        expect(lay["scrollWidth"] <= lay["clientWidth"], "%s: page scrolls sideways (%d > %d)" % (label, lay["scrollWidth"], lay["clientWidth"]))
        expect(lay["clientWidth"] == width, "%s: layout width is %d, wanted %d" % (label, lay["clientWidth"], width))
        expect(not lay["small"], "%s: tap targets under 40 px: %s" % (label, lay["small"]))
        expect(lay["cookies"] == "" and lay["storage"] == 0, "%s: cookies or storage in use" % label)
        other = [h for h in lay["hosts"] if h not in (urllib.parse.urlparse(base).netloc, "tiles.openfreemap.org")]
        expect(not other, "%s: requests to other hosts: %s" % (label, other))
        if held:
            expect(lay["cellRequests"] == 0, "%s: a held city page asked for a cell file" % label)
        errors, warnings = b.console(base)
        entry["console_errors"] = errors
        entry["console_warnings"] = warnings
        for e in errors:
            if e not in report["console_errors"]:
                report["console_errors"].append(e)
        for w in warnings:
            if w not in report["console_warnings"]:
                report["console_warnings"].append(w)
        if frame:
            b.m.cmd("WebDriver:SwitchToParentFrame")
        report["pages"].append(entry)

    def index_page(size, tag, framed, want_mode=None):
        label = "index@%s" % tag
        frame = open_page("index.html", size, label, framed)
        entry = {"page": "index.html", "view": tag, "shots": []}
        ok = b.wait("return document.body.getAttribute('data-table') === 'ready' && !!document.body.getAttribute('data-map');")
        expect(ok, "%s: table or map did not get ready" % label)
        rows = b.m.js("return document.querySelectorAll('#city-table tbody tr').length;")
        entry["table_rows"] = rows
        expect(rows == len(cities), "%s: table has %s rows, data has %d cities" % (label, rows, len(cities)))
        state = b.m.js(JS_MAP_STATE, ["cities-circle"])
        if state["map"]:
            b.wait("return window.Site.map.loaded() && window.Site.map.queryRenderedFeatures({layers:['cities-circle']}).length > 0;", 30)
            if state["mode"] == "local":
                b.wait("return !!window.Site.map.getLayer('land-fill') && window.Site.map.loaded();", 15)
            time.sleep(1.0)
            state = b.m.js(JS_MAP_STATE, ["cities-circle"])
        entry["map"] = state
        expect(state["map"], "%s: no map was drawn (mode %s)" % (label, state.get("mode")))
        if want_mode:
            expect(state.get("mode") == want_mode, "%s: background mode is %s, wanted %s" % (label, state.get("mode"), want_mode))
        legend = b.m.js("return Array.prototype.map.call(document.querySelectorAll('#legend li'), function (li) { return li.textContent; });")
        entry["legend"] = legend
        expect(len(legend) == 5 and all("%" in t for t in legend), "%s: legend is %s" % (label, legend))
        entry["shots"].append(shoot("%s_index" % tag, frame))
        if state["map"]:
            expect(state["rendered"] and state["rendered"] > 0, "%s: no city markers drawn" % label)
            c = cities["phoenix"] if "phoenix" in cities else list(cities.values())[0]
            pt = b.m.js("document.getElementById('map').scrollIntoView({block: 'center'}); var m = window.Site.map, p = m.project([arguments[0], arguments[1]]), r = m.getCanvas().getBoundingClientRect(); return [r.left + p.x, r.top + p.y];",
                        [c["centre_lon"], c["centre_lat"]])
            b.click(pt[0], pt[1])
            card = b.wait("var p = document.querySelector('.maplibregl-popup-content, #city-card:not([hidden])'); return p ? p.innerText : '';", 5)
            entry["card"] = card
            href = b.m.js("var a = document.querySelector('.maplibregl-popup-content a.card-link, #city-card:not([hidden]) a.card-link'); return a ? a.getAttribute('href') : '';")
            cut = b.m.js("""var p = document.querySelector('.maplibregl-popup-content');
                if (!p) return false;
                var a = p.getBoundingClientRect(), m = document.getElementById('map').getBoundingClientRect();
                return a.top < m.top - 1 || a.bottom > m.bottom + 1 || a.left < m.left - 1 || a.right > m.right + 1;""")
            expect(not cut, "%s: the marker card is cut off by the map edge" % label)
            entry["card_link"] = href
            want_head = "%.1f%%" % (c["headline_share_un"] * 100)
            want_cov = "%.1f%%" % (c["un_coverage_share"] * 100)
            expect(card and c["city_name"] in card and c["country"] in card and want_head in card and want_cov in card
                   and format(int(round(c["residents"])), ",") in card,
                   "%s: marker card is wrong or missing: %r" % (label, card))
            expect(href == "city/%s/" % c["city"], "%s: card link is %r" % (label, href))
            entry["shots"].append(shoot("%s_index_card" % tag, frame))
        # sorting: residents, high to low
        b.m.js("var s = document.getElementById('sort-key'); s.value = 'residents'; s.dispatchEvent(new Event('change', {bubbles: true})); return true;")
        first = b.m.js("return document.querySelector('#city-table tbody tr td').textContent;")
        biggest = max(cities.values(), key=lambda c: c["residents"])["city_name"]
        entry["first_row_by_residents"] = first
        expect(first == biggest, "%s: sort by residents puts %r first, data says %r" % (label, first, biggest))
        b.m.js("document.getElementById('table-title').scrollIntoView(); return true;")
        time.sleep(0.4)
        entry["shots"].append(shoot("%s_index_table" % tag, frame))
        finish(entry, label, frame, size[0])

    def about_page(size, tag, framed):
        label = "about@%s" % tag
        frame = open_page("about.html", size, label, framed)
        entry = {"page": "about.html", "view": tag, "shots": []}
        n = b.wait("return document.querySelectorAll('main h1, main h2').length;")
        entry["headings"] = n
        expect(n == 9, "%s: %s headings, wanted 9" % (label, n))
        entry["shots"].append(shoot("%s_about" % tag, frame))
        finish(entry, label, frame, size[0])

    def area_check(label, entry, unit, city_id, frame, tag):
        """Click one assessed area and compare the panel with the data file."""
        folder, idf = ("cells", "cell_id") if unit == "hex" else ("tracts", "geoid")
        with open(os.path.join(site, "data", folder, city_id + ".geojson"), encoding="utf-8") as fh:
            feats = {str(f["properties"][idf]): f["properties"] for f in json.load(fh)["features"]}
        pick = b.m.js("""
            var m = window.Site.map, layer = arguments[0], idf = arguments[1];
            document.getElementById('map').scrollIntoView({block: 'center'});
            var c = m.getCanvas(), r = c.getBoundingClientRect();
            var vh = window.innerHeight;
            var fs = m.queryRenderedFeatures([[c.clientWidth * 0.3, c.clientHeight * 0.3], [c.clientWidth * 0.7, c.clientHeight * 0.7]], {layers: [layer]});
            for (var i = 0; i < fs.length; i++) {
              var p = fs[i].properties;
              if (typeof p.blocked_share !== 'number' || !(p.n_blocked > 0) || !(p.n_blocked < p.n_car_directions)) continue;
              var ring = fs[i].geometry.type === 'Polygon' ? fs[i].geometry.coordinates[0] : fs[i].geometry.coordinates[0][0];
              var x = 0, y = 0;
              for (var k = 0; k < ring.length - 1; k++) { var q = m.project(ring[k]); x += q.x; y += q.y; }
              x /= (ring.length - 1); y /= (ring.length - 1);
              var hit = m.queryRenderedFeatures([x, y], {layers: [layer]});
              if (!hit.length || String(hit[0].properties[idf]) !== String(p[idf])) continue;
              if (x < 20 || y < 20 || x > c.clientWidth - 60 || y > c.clientHeight - 20) continue;
              if (r.top + y < 5 || r.top + y > vh - 5) continue;
              return {id: String(p[idf]), x: r.left + x, y: r.top + y};
            }
            return null;""", [unit + "-fill", idf])
        if not expect(pick, "%s: found no assessed %s to click" % (label, unit)):
            return
        b.click(pick["x"], pick["y"])
        text = b.wait("var t = document.getElementById('cell-body').innerText; return t.indexOf(arguments[0]) >= 0 ? t : '';".replace("arguments[0]", json.dumps(pick["id"])), 5)
        entry["area_panel_%s" % unit] = text
        p = feats[pick["id"]]
        cov = p["coverage_un_pct"] if unit == "hex" else p["coverage_pct"]

        def pct(v):
            s = "%.1f" % v
            return (s[:-2] if s.endswith(".0") else s) + "%"
        wanted = [pick["id"], p["class"], "%d of 8" % p["n_car_directions"],
                  "%d of %d" % (p["n_blocked"], p["n_car_directions"]),
                  "Blocked share: " + pct(p["blocked_share"] * 100),
                  "Coverage (UN rule)" if unit == "hex" else "Coverage (US agency rule)",
                  "no route leaves in that direction",
                  "a route points that way but reaches nothing within 30 minutes",
                  "transit reaches something, but less than is typical for Full Service areas in the same city"]
        if cov is not None:
            wanted.append(pct(cov))
        for w in wanted:
            expect(text and str(w) in text, "%s: %s panel lacks %r" % (label, unit, w))
        if text:
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            def after(head):
                return lines[lines.index(head) + 1] if head in lines and lines.index(head) + 1 < len(lines) else None
            expect(after("Why blocked: missing") == str(p["n_missing"]), "%s: missing count shown %r, data %r" % (label, after("Why blocked: missing"), p["n_missing"]))
            expect(after("Why blocked: dead") == str(p["n_dead"]), "%s: dead count shown %r, data %r" % (label, after("Why blocked: dead"), p["n_dead"]))
            expect(after("Thin directions") == str(p["n_thin"]), "%s: thin count shown %r, data %r" % (label, after("Thin directions"), p["n_thin"]))
            res = after("Residents")
            expect(res is not None and abs(float(res.replace(",", "")) - p["residents"]) <= 0.5, "%s: residents shown %r, data %r" % (label, res, p["residents"]))
        entry["shots"].append(shoot("%s_%s_%s_selected" % (tag, city_id, unit), frame))

    def city_page(city_id, size, tag, framed, want_mode=None, light=False):
        c = cities[city_id]
        label = "%s@%s" % (city_id, tag)
        frame = open_page("city/%s/" % city_id, size, label, framed)
        entry = {"page": "city/%s/" % city_id, "view": tag, "shots": []}
        expect(b.wait("return document.body.getAttribute('data-summary') === 'ready';"), "%s: summary did not load" % label)
        summary = b.m.js("return document.getElementById('summary-body').innerText;")
        entry["summary"] = summary
        for w in ["%.1f%%" % (c["headline_share_un"] * 100), "%.1f%%" % (c["un_coverage_share"] * 100),
                  format(int(round(c["residents"])), ","), format(c["n_cells"], ","), c["population_source"]]:
            expect(w in summary, "%s: summary lacks %r" % (label, w))
        if c.get("data_caveat"):
            expect("Data caveat" in summary and c["data_caveat"] in summary, "%s: data caveat is not shown" % label)
        else:
            expect("Data caveat" not in summary, "%s: shows a data caveat it should not" % label)
        body = b.m.js("return document.querySelector('main').innerText;")
        expect("Classes and ranks are relative to each city. Do not compare them between cities." in body, "%s: classes note missing" % label)
        unit_note = "Hexagon and tract values are not comparable. The unit changes the numbers."
        expect((unit_note in body) == bool(c["has_tracts"]), "%s: unit note shown=%s" % (label, unit_note in body))
        if not c["cells_public"]:
            expect("Cell-level data for this city are not yet published. The source and licence of its schedule files are being confirmed." in body,
                   "%s: held note missing" % label)
            expect(b.m.js("return !document.getElementById('map') && !document.querySelector('a[href*=\"data/cells\"]') && !document.querySelector('canvas');"),
                   "%s: held page has a map or a cell download" % label)
            time.sleep(1.0)
            entry["shots"].append(shoot("%s_%s" % (tag, city_id), frame))
            finish(entry, label, frame, size[0], held=True)
            return
        ready = b.wait("var r = document.body.getAttribute('data-ready'); return r === 'hex:blocked' || document.body.getAttribute('data-map') === 'none';", 60)
        state = b.m.js(JS_MAP_STATE, ["hex-fill"])
        if expect(ready and state["map"], "%s: map did not get ready (mode %s)" % (label, state.get("mode"))):
            b.wait("return window.Site.map.loaded() && window.Site.map.queryRenderedFeatures({layers:['hex-fill']}).length > 0;", 60)
            time.sleep(1.0)
            state = b.m.js(JS_MAP_STATE, ["hex-fill"])
            entry["map"] = state
            expect(state["rendered"] and state["rendered"] > 0, "%s: no hexagons drawn" % label)
            if want_mode:
                expect(state["mode"] == want_mode, "%s: background mode is %s, wanted %s" % (label, state["mode"], want_mode))
            msg = b.m.js("return document.getElementById('map-msg').textContent;")
            expect(format(c["n_cells"], ",") + " hexagons" in msg, "%s: map message is %r" % (label, msg))
            legend = b.m.js("return document.getElementById('legend').innerText;")
            expect("Blocked share" in legend and "75% or more" in legend and "Not assessed" in legend, "%s: blocked legend is %r" % (label, legend))
            entry["shots"].append(shoot("%s_%s_hex_blocked" % (tag, city_id), frame))
            area_check(label, entry, "hex", city_id, frame, tag)
            if not light:
                for value, name, want in (("coverage", "hex_coverage", "Coverage (UN rule)"), ("class", "hex_class", "Stranded Infrastructure (high coverage, low access)")):
                    b.m.js("var r = document.querySelector('input[name=layer][value=%s]'); r.click(); return true;" % value)
                    expect(b.wait("return document.body.getAttribute('data-ready') === 'hex:%s' && window.Site.map.loaded();" % value, 20), "%s: layer %s did not switch" % (label, value))
                    time.sleep(0.8)
                    legend = b.m.js("return document.getElementById('legend').innerText;")
                    expect(want in legend, "%s: legend for %s is %r" % (label, value, legend))
                    entry["shots"].append(shoot("%s_%s_%s" % (tag, city_id, name), frame))
                if c["has_tracts"]:
                    b.m.js("document.querySelector('input[name=layer][value=blocked]').click(); document.querySelector('input[name=unit][value=tract]').click(); return true;")
                    expect(b.wait("return document.body.getAttribute('data-ready') === 'tract:blocked' && window.Site.map.loaded() && window.Site.map.queryRenderedFeatures({layers:['tract-fill']}).length > 0;", 60),
                           "%s: tract view did not get ready" % label)
                    time.sleep(1.0)
                    t = c["tract"]
                    tsum = b.m.js("return document.getElementById('summary-body').innerText;")
                    entry["tract_summary"] = tsum
                    for w in ["Measured on census tracts.", format(t["n_tracts"], ","), format(t["residents_SI"], ","),
                              format(t["residents_SI_half_blocked"], ",")]:
                        expect(w in tsum, "%s: tract summary lacks %r" % (label, w))
                    expect(b.m.js("return document.getElementById('coverage-label').textContent;") == "Coverage (US agency rule)", "%s: tract coverage label wrong" % label)
                    vis = b.m.js("var m = window.Site.map; return [m.getLayoutProperty('hex-fill','visibility'), m.getLayoutProperty('tract-fill','visibility')];")
                    expect(vis == ["none", "visible"], "%s: layer visibility in tract view is %s" % (label, vis))
                    entry["shots"].append(shoot("%s_%s_tract_blocked" % (tag, city_id), frame))
                    area_check(label, entry, "tract", city_id, frame, tag)
                    b.m.js("document.querySelector('input[name=layer][value=coverage]').click(); return true;")
                    b.wait("return document.body.getAttribute('data-ready') === 'tract:coverage' && window.Site.map.loaded();", 20)
                    time.sleep(0.8)
                    legend = b.m.js("return document.getElementById('legend').innerText;")
                    expect("Coverage (US agency rule)" in legend, "%s: tract coverage legend is %r" % (label, legend))
                    entry["shots"].append(shoot("%s_%s_tract_coverage" % (tag, city_id), frame))
            if framed:
                b.m.js("document.getElementById('side').scrollIntoView(); return true;")
                time.sleep(0.5)
                entry["shots"].append(shoot("%s_%s_panel" % (tag, city_id), frame))
        finish(entry, label, frame, size[0])

    try:
        probe = b.m.js("var c = document.createElement('canvas'); var g = c.getContext('webgl2') || c.getContext('webgl'); return g ? String(g.getParameter(g.RENDERER)) : null;")
        report["webgl"] = probe or "not available"
        wanted = [c for c in args.cities.split(",") if c in cities]
        desktop, mobile, narrow = (1280, 800), (390, 800), (360, 800)

        Handler.mode["style"] = "real"       # the real address: reachable or not, both must work
        index_page(desktop, "desktop", False)
        about_page(desktop, "desktop", False)
        for cid in wanted:
            city_page(cid, desktop, "desktop", False)
        index_page(mobile, "mobile", True)
        about_page(mobile, "mobile", True)
        for cid in wanted:
            city_page(cid, mobile, "mobile", True)
        index_page(narrow, "narrow360", True)
        about_page(narrow, "narrow360", True)
        for cid in wanted:
            city_page(cid, narrow, "narrow360", True, light=True)

        first_public = [c for c in wanted if cities[c]["cells_public"]][:1]
        Handler.mode["style"] = "answers"    # stand-in style arrives; its tiles and fonts fail
        index_page(desktop, "standin_ok", False, want_mode="remote")
        for cid in first_public:
            city_page(cid, desktop, "standin_ok", False, want_mode="remote", light=True)
        Handler.mode["style"] = "hangs"      # stand-in style never answers in time
        t0 = time.time()
        index_page(desktop, "standin_hangs", False, want_mode="local")
        report["hang_fallback_seconds"] = round(time.time() - t0, 1)
        Handler.mode["style"] = "real"
    finally:
        b.close()
        server.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)

    report["ok"] = not report["failures"]
    with open(os.path.join(out, "render_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    for f in report["failures"]:
        sys.stderr.write("browser_render: FAIL: %s\n" % f)
    print("browser_render: %s - %s, WebGL %s, %d page views, %d failures, %d console errors, %d console warnings"
          % ("OK" if report["ok"] else "FAILED", report["browser"], report["webgl"], len(report["pages"]),
             len(report["failures"]), len(report["console_errors"]), len(report["console_warnings"])))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Open the built site in Firefox and check it.")
    ap.add_argument("--site", required=True, help="built site folder")
    ap.add_argument("--out", required=True, help="folder for PNG files and render_report.json")
    ap.add_argument("--firefox", default="firefox")
    ap.add_argument("--xvfb", action="store_true")
    ap.add_argument("--cities", default="phoenix,jerusalem,bangkok,chennai")
    ap.add_argument("--workdir", default=None, help="folder for temporary files")
    sys.exit(run(ap.parse_args()))
