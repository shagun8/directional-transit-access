/* Shared helpers for all pages.
   The only request that leaves this site is the optional background map
   (style, tiles, fonts) from OpenFreeMap. Data layers never depend on it. */
(function (global) {
  'use strict';

  var BASEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
  var BASEMAP_TIMEOUT_MS = 4000;
  var STYLE_READY_TIMEOUT_MS = 8000;

  var COLOURS = {
    classes: {
      'Full Service': '#0072B2',
      'Stranded Infrastructure': '#D55E00',
      'Efficient Network': '#009E73',
      'Transit Desert': '#999999'
    },
    notAssessed: '#E6E6E6',
    /* light to dark; the two darkest steps start at the headline cut (one half) */
    blocked: ['#FFFBD6', '#FDDC9E', '#F9A87C', '#B5367A', '#4A1070'],
    coverage: ['#EFF3FF', '#BDD7E7', '#6BAED6', '#3182BD', '#08519C']
  };

  var CLASS_MEANING = {
    'Full Service': 'high coverage, high access',
    'Stranded Infrastructure': 'high coverage, low access',
    'Efficient Network': 'low coverage, high access',
    'Transit Desert': 'low coverage, low access'
  };

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'];

  function isNum(x) { return typeof x === 'number' && isFinite(x); }

  function root() { return document.body.getAttribute('data-root') || ''; }

  /* ---------- number formatting (display only; data files are not changed) ---------- */
  function fmtInt(x) {
    if (!isNum(x)) return 'No value';
    return Math.round(x).toLocaleString('en-US');
  }
  /* residents of one small area: keep one decimal below 10 so 0.2 does not read as 0 */
  function fmtResidents(x) {
    if (!isNum(x)) return 'No value';
    if (x > 0 && x < 10 && Math.round(x) !== x) return x.toFixed(1);
    return fmtInt(x);
  }
  /* share between 0 and 1 -> "14.5%" */
  function fmtShare(x) {
    if (!isNum(x)) return 'No value';
    return (x * 100).toFixed(1) + '%';
  }
  /* percent value between 0 and 100 -> "42.9%", "50%" */
  function fmtPct(x) {
    if (!isNum(x)) return 'No value';
    return x.toFixed(1).replace(/\.0$/, '') + '%';
  }
  function fmtShareShort(x) { return isNum(x) ? fmtPct(x * 100) : 'No value'; }
  function fmtRatio(x) {
    if (!isNum(x)) return 'No value';
    if (x === 0) return '0';
    return String(Number(x.toPrecision(3)));
  }
  function fmtDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return iso || 'No value';
    return Number(m[3]) + ' ' + MONTHS[Number(m[2]) - 1] + ' ' + m[1];
  }

  /* ---------- small DOM helpers ---------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'text') node.textContent = attrs[k];
        else if (k === 'class') node.className = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* one row of a facts list: label, value, optional plain-words line */
  function fact(label, value, sub) {
    var dd = el('dd', null, [typeof value === 'string' ? value : value]);
    if (sub) dd.appendChild(el('span', { 'class': 'sub', text: sub }));
    return el('div', null, [el('dt', { text: label }), dd]);
  }

  function swatch(colour, round) {
    var s = el('span', { 'class': 'swatch' + (round ? ' dot' : ''), 'aria-hidden': 'true' });
    s.style.backgroundColor = colour;
    return s;
  }

  function renderLegend(node, title, items, noteText, round) {
    clear(node);
    node.appendChild(el('p', { 'class': 'legend-title', text: title }));
    var ul = el('ul');
    items.forEach(function (it) {
      ul.appendChild(el('li', null, [swatch(it.colour, round), it.label]));
    });
    node.appendChild(ul);
    if (noteText) node.appendChild(el('p', { 'class': 'legend-note', text: noteText }));
  }

  /* ---------- fetching ---------- */
  function fetchJSON(url, timeoutMs) {
    var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
    var timer = null;
    var req = fetch(url, ctrl ? { signal: ctrl.signal, credentials: 'omit' } : { credentials: 'omit' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
        return r.json();
      });
    if (!timeoutMs) return req;
    var timeout = new Promise(function (resolve, reject) {
      timer = setTimeout(function () {
        if (ctrl) ctrl.abort();
        reject(new Error('Timed out: ' + url));
      }, timeoutMs);
    });
    return Promise.race([req, timeout]).then(
      function (v) { clearTimeout(timer); return v; },
      function (e) { clearTimeout(timer); throw e; }
    );
  }

  /* ---------- background map, fail soft ---------- */
  function localStyle() {
    return {
      version: 8,
      name: 'local-plain',
      sources: {},
      layers: [{ id: 'plain-background', type: 'background', paint: { 'background-color': '#F2F2EE' } }]
    };
  }

  function looksLikeStyle(s) {
    return !!s && s.version === 8 && Array.isArray(s.layers) && s.layers.length > 0 &&
      s.sources && typeof s.sources === 'object';
  }

  /* Resolves to { style, remote }. Never rejects. */
  function loadBaseStyle() {
    return fetchJSON(BASEMAP_STYLE_URL, BASEMAP_TIMEOUT_MS).then(function (s) {
      if (!looksLikeStyle(s)) throw new Error('Unexpected background style');
      return { style: s, remote: true };
    }).catch(function () {
      return { style: localStyle(), remote: false };
    });
  }

  function firstSymbolLayerId(style) {
    var layers = (style && style.layers) || [];
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].type === 'symbol') return layers[i].id;
    }
    return undefined;
  }

  function setAttribution(container, remote) {
    var old = container.querySelector('.map-attrib');
    if (old) old.parentNode.removeChild(old);
    var box = el('div', { 'class': 'map-attrib' });
    if (remote) {
      box.appendChild(el('a', { href: 'https://openfreemap.org', rel: 'noopener', text: '\u00A9 OpenFreeMap' }));
      box.appendChild(document.createTextNode(' '));
      box.appendChild(el('a', { href: 'https://www.openmaptiles.org/', rel: 'noopener', text: '\u00A9 OpenMapTiles' }));
      box.appendChild(document.createTextNode(' Data from '));
      box.appendChild(el('a', { href: 'https://www.openstreetmap.org/copyright', rel: 'noopener', text: 'OpenStreetMap' }));
    } else {
      box.textContent = 'Background map not loaded. Showing the data only.';
    }
    container.appendChild(box);
  }

  /* Builds a map. Resolves to { map, remote, beforeId } once layers can be added.
     Rejects if the browser cannot draw the map (for example, no WebGL). */
  function createMap(containerId, options) {
    var container = document.getElementById(containerId);
    return loadBaseStyle().then(function (base) {
      return new Promise(function (resolve, reject) {
        if (!global.maplibregl) { reject(new Error('Map library missing')); return; }
        var map;
        try {
          map = new global.maplibregl.Map({
            container: container,
            style: base.style,
            center: options.center || [0, 20],
            zoom: isNum(options.zoom) ? options.zoom : 1,
            attributionControl: false,
            dragRotate: false,
            pitchWithRotate: false,
            touchPitch: false,
            maxPitch: 0
          });
        } catch (e) {
          reject(e);
          return;
        }
        if (map.touchZoomRotate && map.touchZoomRotate.disableRotation) map.touchZoomRotate.disableRotation();
        if (map.keyboard && map.keyboard.disableRotation) map.keyboard.disableRotation();
        map.addControl(new global.maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        /* background tile problems are warnings, never fatal */
        map.on('error', function (ev) {
          var msg = ev && ev.error && ev.error.message ? ev.error.message : 'unknown';
          if (global.console && console.warn) console.warn('Map warning: ' + msg);
        });

        var remote = base.remote;
        var done = false;
        var timer = null;
        function ready() {
          if (done) return;
          done = true;
          if (timer) clearTimeout(timer);
          setAttribution(container, remote);
          resolve({ map: map, remote: remote, beforeId: remote ? firstSymbolLayerId(base.style) : undefined });
        }
        map.once('style.load', ready);
        if (remote) {
          /* the remote style arrived but did not become usable: fall back to the local one */
          timer = setTimeout(function () {
            if (done) return;
            remote = false;
            map.off('style.load', ready);
            map.once('style.load', ready);
            try { map.setStyle(localStyle(), { diff: false }); } catch (e) { reject(e); }
          }, STYLE_READY_TIMEOUT_MS);
        }
      });
    });
  }

  global.Site = {
    COLOURS: COLOURS,
    CLASS_MEANING: CLASS_MEANING,
    isNum: isNum,
    root: root,
    fmtInt: fmtInt,
    fmtResidents: fmtResidents,
    fmtShare: fmtShare,
    fmtPct: fmtPct,
    fmtShareShort: fmtShareShort,
    fmtRatio: fmtRatio,
    fmtDate: fmtDate,
    el: el,
    clear: clear,
    fact: fact,
    swatch: swatch,
    renderLegend: renderLegend,
    fetchJSON: fetchJSON,
    createMap: createMap
  };
})(window);
