/* Global page: world map of the cities and a sortable table. */
(function () {
  'use strict';
  var S = window.Site;
  var el = S.el;

  /* headline share classes: lower bound included, upper bound excluded */
  var BREAKS = [0.05, 0.10, 0.20, 0.40];
  var RAMP = S.COLOURS.blocked;
  var BREAK_LABELS = ['Under 5%', '5% to under 10%', '10% to under 20%', '20% to under 40%', '40% or more'];

  var COLUMNS = [
    { key: 'city_name', label: 'City', type: 'text' },
    { key: 'country', label: 'Country', type: 'text' },
    { key: 'headline_share_un', label: 'Headline', type: 'num' },
    { key: 'un_coverage_share', label: 'UN coverage', type: 'num' },
    { key: 'residents', label: 'Residents', type: 'num' },
    { key: 'data_caveat', label: 'Data caveat', type: 'flag' }
  ];

  var cities = [];
  var sortKey = 'headline_share_un';
  var sortDir = 'desc';

  function cityUrl(c) { return S.root() + 'city/' + encodeURIComponent(c.city) + '/'; }

  function compare(a, b) {
    var col = COLUMNS.filter(function (c) { return c.key === sortKey; })[0];
    var x = a[sortKey], y = b[sortKey], r;
    if (col.type === 'text') r = String(x).localeCompare(String(y), 'en');
    else if (col.type === 'flag') r = (x ? 1 : 0) - (y ? 1 : 0);
    else r = (S.isNum(x) ? x : -Infinity) - (S.isNum(y) ? y : -Infinity);
    if (r === 0) r = String(a.city_name).localeCompare(String(b.city_name), 'en');
    else if (sortDir === 'desc') r = -r;
    return r;
  }

  function cellText(c, col) {
    if (col.key === 'headline_share_un' || col.key === 'un_coverage_share') return S.fmtShare(c[col.key]);
    if (col.key === 'residents') return S.fmtInt(c.residents);
    if (col.key === 'data_caveat') return c.data_caveat ? 'Yes' : 'No';
    return String(c[col.key]);
  }

  function renderTable() {
    var table = document.getElementById('city-table');
    S.clear(table);
    table.appendChild(el('caption', { text: cities.length + ' cities. Sort with the list above or a column heading.' }));
    var headRow = el('tr');
    COLUMNS.forEach(function (col) {
      var active = col.key === sortKey;
      var th = el('th', { scope: 'col', 'class': col.type === 'num' ? 'num' : '' });
      if (active) th.setAttribute('aria-sort', sortDir === 'asc' ? 'ascending' : 'descending');
      var btn = el('button', { type: 'button', text: col.label + (active ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : '') });
      btn.addEventListener('click', function () {
        if (sortKey === col.key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        else { sortKey = col.key; sortDir = col.type === 'text' ? 'asc' : 'desc'; }
        syncTools();
        renderTable();
      });
      th.appendChild(btn);
      headRow.appendChild(th);
    });
    table.appendChild(el('thead', null, [headRow]));
    var body = el('tbody');
    cities.slice().sort(compare).forEach(function (c) {
      var tr = el('tr');
      COLUMNS.forEach(function (col) {
        var td = el('td', { 'data-label': col.label, 'class': col.type === 'num' ? 'num' : (col.key === 'city_name' ? 'name' : '') });
        if (col.key === 'city_name') td.appendChild(el('a', { href: cityUrl(c), text: c.city_name }));
        else td.textContent = cellText(c, col);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
  }

  function syncTools() {
    document.getElementById('sort-key').value = sortKey;
    document.getElementById('sort-dir').textContent = sortDir === 'asc' ? 'Low to high' : 'High to low';
  }

  function setupTools() {
    var sel = document.getElementById('sort-key');
    COLUMNS.forEach(function (col) { sel.appendChild(el('option', { value: col.key, text: col.label })); });
    sel.addEventListener('change', function () {
      sortKey = sel.value;
      var col = COLUMNS.filter(function (c) { return c.key === sortKey; })[0];
      sortDir = col.type === 'text' ? 'asc' : 'desc';
      syncTools();
      renderTable();
    });
    document.getElementById('sort-dir').addEventListener('click', function () {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      syncTools();
      renderTable();
    });
    syncTools();
  }

  function renderLegend() {
    var items = RAMP.map(function (colour, i) { return { colour: colour, label: BREAK_LABELS[i] }; });
    S.renderLegend(document.getElementById('legend'), 'Headline share', items, null, true);
  }

  function card(c) {
    return el('div', { 'class': 'card' }, [
      el('p', { 'class': 'card-title', text: c.city_name }),
      el('p', { 'class': 'card-sub', text: c.country }),
      el('dl', { 'class': 'facts' }, [
        S.fact('Headline', S.fmtShare(c.headline_share_un)),
        S.fact('UN coverage', S.fmtShare(c.un_coverage_share)),
        S.fact('Residents', S.fmtInt(c.residents))
      ]),
      el('a', { 'class': 'card-link', href: cityUrl(c), text: 'Open the city page' })
    ]);
  }

  function addLand(map) {
    /* local outline of land, used only when the background map did not load */
    return S.fetchJSON(S.root() + 'assets/basemap/world_land.geojson').then(function (land) {
      map.addSource('land', { type: 'geojson', data: land });
      map.addLayer({ id: 'land-fill', type: 'fill', source: 'land', paint: { 'fill-color': '#DEDED6' } }, 'cities-circle');
      map.addLayer({ id: 'land-line', type: 'line', source: 'land', paint: { 'line-color': '#9A9A92', 'line-width': 0.6 } }, 'cities-circle');
    }).catch(function () { /* a plain background is enough */ });
  }

  function setupMap() {
    var msg = document.getElementById('map-msg');
    msg.textContent = 'Loading the map\u2026';
    S.createMap('map', { center: [10, 20], zoom: 1 }).then(function (m) {
      var map = m.map;
      S.map = map;   /* handle for the browser checks */
      var byId = {};
      var features = cities.map(function (c) {
        byId[c.city] = c;
        return {
          type: 'Feature',
          properties: { city: c.city, headline_share_un: c.headline_share_un },
          geometry: { type: 'Point', coordinates: [c.centre_lon, c.centre_lat] }
        };
      });
      map.addSource('cities', { type: 'geojson', data: { type: 'FeatureCollection', features: features } });
      map.addLayer({
        id: 'cities-circle',
        type: 'circle',
        source: 'cities',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, 6, 4, 9, 8, 12],
          'circle-color': ['step', ['get', 'headline_share_un'],
            RAMP[0], BREAKS[0], RAMP[1], BREAKS[1], RAMP[2], BREAKS[2], RAMP[3], BREAKS[3], RAMP[4]],
          'circle-stroke-color': '#1a1a1a',
          'circle-stroke-width': 1.2
        }
      });
      map.addLayer({
        id: 'cities-selected',
        type: 'circle',
        source: 'cities',
        filter: ['==', ['get', 'city'], ''],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, 9, 4, 12, 8, 15],
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': '#000000',
          'circle-stroke-width': 3
        }
      });
      if (!m.remote) addLand(map);
      map.fitBounds([[-128, -42], [178, 58]], { padding: 24, animate: false });

      var popup = null;
      map.on('click', function (ev) {
        var pad = 12;
        var hits = map.queryRenderedFeatures(
          [[ev.point.x - pad, ev.point.y - pad], [ev.point.x + pad, ev.point.y + pad]],
          { layers: ['cities-circle'] });
        if (!hits.length) return;
        /* nearest marker to the click */
        var best = null, bestD = Infinity;
        hits.forEach(function (f) {
          var p = map.project(f.geometry.coordinates);
          var d = Math.pow(p.x - ev.point.x, 2) + Math.pow(p.y - ev.point.y, 2);
          if (d < bestD) { bestD = d; best = f; }
        });
        var c = byId[best.properties.city];
        if (!c) return;
        if (popup) popup.remove();
        popup = null;
        map.setFilter('cities-selected', ['==', ['get', 'city'], c.city]);
        var box = document.getElementById('city-card');
        if (map.getContainer().clientWidth < 520) {
          /* narrow screens: the card goes under the map so it is never cut off */
          S.clear(box);
          box.appendChild(card(c));
          box.hidden = false;
        } else {
          box.hidden = true;
          popup = new window.maplibregl.Popup({ maxWidth: '280px', focusAfterOpen: false })
            .setLngLat([c.centre_lon, c.centre_lat])
            .setDOMContent(card(c))
            .addTo(map);
          popup.on('close', function () {
            if (map.getLayer('cities-selected')) map.setFilter('cities-selected', ['==', ['get', 'city'], '']);
          });
        }
      });
      map.on('mouseenter', 'cities-circle', function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'cities-circle', function () { map.getCanvas().style.cursor = ''; });
      msg.textContent = 'Click or tap a city marker to see its numbers.';
      document.body.setAttribute('data-map', m.remote ? 'remote' : 'local');
    }).catch(function () {
      msg.textContent = 'This browser cannot draw the map. The table below has the same numbers.';
      document.getElementById('map').hidden = true;
      document.getElementById('legend').hidden = true;
      document.body.setAttribute('data-map', 'none');
    });
  }

  function start() {
    setupTools();
    renderLegend();
    S.fetchJSON(S.root() + 'data/cities.json').then(function (d) {
      cities = d.cities || [];
      renderTable();
      document.body.setAttribute('data-table', 'ready');
      setupMap();
    }).catch(function () {
      document.getElementById('map-msg').textContent = 'The city data could not be loaded. Please reload the page.';
      document.body.setAttribute('data-table', 'failed');
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
