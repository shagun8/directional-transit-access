/* City page: map of small areas, layer switch, area panel, city summary. */
(function () {
  'use strict';
  var S = window.Site;
  var el = S.el;
  var fact = S.fact;
  var C = S.COLOURS;

  var cityId = document.body.getAttribute('data-city') || '';
  var city = null;
  var map = null;
  var beforeId;
  var unit = 'hex';        /* 'hex' or 'tract' */
  var layer = 'blocked';   /* 'blocked', 'coverage' or 'class' */
  var loaded = {};         /* unit -> { byId, bounds } */
  var selected = { hex: null, tract: null };

  var UNITS = {
    hex: {
      path: function () { return S.root() + 'data/cells/' + cityId + '.geojson'; },
      idField: 'cell_id',
      coverageField: 'coverage_un_pct',
      coverageLabel: 'Coverage (UN rule)',
      one: 'hexagon',
      many: 'hexagons'
    },
    tract: {
      path: function () { return S.root() + 'data/tracts/' + cityId + '.geojson'; },
      idField: 'geoid',
      coverageField: 'coverage_pct',
      coverageLabel: 'Coverage (US agency rule)',
      one: 'census tract',
      many: 'census tracts'
    }
  };

  var WHY = {
    missing: 'no route leaves in that direction',
    dead: 'a route points that way but reaches nothing within 30 minutes',
    thin: 'transit reaches something, but less than is typical for Full Service areas in the same city'
  };

  function byId(id) { return document.getElementById(id); }

  /* ---------- colours ---------- */
  function numberOr(field, expr) {
    return ['case', ['==', ['typeof', ['get', field]], 'number'], expr, C.notAssessed];
  }
  function fillColour() {
    var u = UNITS[unit];
    if (layer === 'blocked') {
      return numberOr('blocked_share', ['step', ['get', 'blocked_share'],
        C.blocked[0], 0.000001, C.blocked[1], 0.25, C.blocked[2], 0.5, C.blocked[3], 0.75, C.blocked[4]]);
    }
    if (layer === 'coverage') {
      return numberOr(u.coverageField, ['step', ['get', u.coverageField],
        C.coverage[0], 0.000001, C.coverage[1], 25, C.coverage[2], 50, C.coverage[3], 75, C.coverage[4]]);
    }
    return ['match', ['to-string', ['get', 'class']],
      'Full Service', C.classes['Full Service'],
      'Stranded Infrastructure', C.classes['Stranded Infrastructure'],
      'Efficient Network', C.classes['Efficient Network'],
      'Transit Desert', C.classes['Transit Desert'],
      C.notAssessed];
  }

  function renderLegend() {
    var node = byId('legend');
    if (!node) return;
    var u = UNITS[unit];
    var grey = { colour: C.notAssessed, label: 'Not assessed' };
    if (layer === 'blocked') {
      S.renderLegend(node, 'Blocked share: blocked directions divided by the directions a car can reach', [
        { colour: C.blocked[0], label: 'None blocked' },
        { colour: C.blocked[1], label: 'Under 25%' },
        { colour: C.blocked[2], label: '25% to under 50%' },
        { colour: C.blocked[3], label: '50% to under 75%' },
        { colour: C.blocked[4], label: '75% or more' },
        grey
      ], unit === 'hex'
        ? 'The two dark colours mark areas where at least half of the directions are blocked. Grey hexagons have fewer than 100 residents, or no direction that counts.'
        : 'The two dark colours mark areas where at least half of the directions are blocked. Grey tracts have no direction that counts.');
    } else if (layer === 'coverage') {
      S.renderLegend(node, u.coverageLabel + ': share of residents near a stop', [
        { colour: C.coverage[0], label: '0%' },
        { colour: C.coverage[1], label: 'Under 25%' },
        { colour: C.coverage[2], label: '25% to under 50%' },
        { colour: C.coverage[3], label: '50% to under 75%' },
        { colour: C.coverage[4], label: '75% or more' },
        { colour: C.notAssessed, label: 'No value' }
      ], null);
    } else {
      S.renderLegend(node, 'Class: coverage and access, each split at the city\u2019s own median', [
        { colour: C.classes['Full Service'], label: 'Full Service (high coverage, high access)' },
        { colour: C.classes['Stranded Infrastructure'], label: 'Stranded Infrastructure (high coverage, low access)' },
        { colour: C.classes['Efficient Network'], label: 'Efficient Network (low coverage, high access)' },
        { colour: C.classes['Transit Desert'], label: 'Transit Desert (low coverage, low access)' },
        grey
      ], unit === 'hex' ? 'Grey hexagons have fewer than 100 residents.' : 'Grey tracts have no class.');
    }
  }

  /* ---------- selected area panel ---------- */
  function classValue(name) {
    if (!name) return 'Not assessed';
    var chip = el('span', { 'class': 'class-chip' }, [S.swatch(C.classes[name] || C.notAssessed), name]);
    return chip;
  }

  function renderArea(p) {
    var body = byId('cell-body');
    if (!body) return;
    S.clear(body);
    if (!p) {
      body.appendChild(el('p', { 'class': 'muted', text: 'Click or tap an area on the map to see its numbers.' }));
      return;
    }
    var u = UNITS[unit];
    var dl = el('dl', { 'class': 'facts' });
    dl.appendChild(fact(unit === 'hex' ? 'Hexagon' : 'Census tract', String(p[u.idField])));
    dl.appendChild(fact('Residents', S.fmtResidents(p.residents)));
    dl.appendChild(fact(u.coverageLabel, S.fmtPct(p[u.coverageField]), 'Share of residents near a stop.'));
    dl.appendChild(fact('Class', classValue(p['class']), p['class'] ? S.CLASS_MEANING[p['class']] + ', relative to this city.' : null));

    if (unit === 'hex' && p.is_origin === false) {
      body.appendChild(dl);
      body.appendChild(el('p', { 'class': 'note plain', text: 'Not assessed. This hexagon has fewer than 100 residents, so its directions were not measured.' }));
      return;
    }
    if (!S.isNum(p.n_car_directions)) {
      body.appendChild(dl);
      body.appendChild(el('p', { 'class': 'note plain', text: 'Not assessed. Directions were not measured here.' }));
      return;
    }
    dl.appendChild(fact('Directions a car reaches', p.n_car_directions + ' of 8'));
    if (!S.isNum(p.blocked_share)) {
      body.appendChild(dl);
      body.appendChild(el('p', { 'class': 'note plain', text: 'No direction counts here, so there is no blocked share.' }));
      return;
    }
    dl.appendChild(fact('Blocked directions', p.n_blocked + ' of ' + p.n_car_directions,
      'Blocked share: ' + S.fmtShareShort(p.blocked_share) + '.'));
    dl.appendChild(fact('Why blocked: missing', String(p.n_missing), 'Missing: ' + WHY.missing + '.'));
    dl.appendChild(fact('Why blocked: dead', String(p.n_dead), 'Dead: ' + WHY.dead + '.'));
    dl.appendChild(fact('Thin directions', String(p.n_thin), 'Thin: ' + WHY.thin + '.'));
    dl.appendChild(fact('s', S.fmtRatio(p.s), 'Share of car-reachable directions that transit serves.'));
    dl.appendChild(fact('q', S.isNum(p.q) ? S.fmtRatio(p.q) : 'No value',
      S.isNum(p.q)
        ? 'In the served directions, the places transit reaches divided by the places a car reaches.'
        : 'Transit serves no direction here, so q has no value.'));
    body.appendChild(dl);
  }

  /* ---------- city summary ---------- */
  function caveatBox() {
    if (!city.data_caveat) return null;
    return el('div', { 'class': 'caveat', id: 'data-caveat' }, [
      el('span', { 'class': 'caveat-label', text: 'Data caveat' }),
      String(city.data_caveat)
    ]);
  }

  function renderSummary() {
    var body = byId('summary-body');
    S.clear(body);
    var dl = el('dl', { 'class': 'facts' });
    if (unit === 'tract' && city.tract) {
      var t = city.tract;
      body.appendChild(el('p', { 'class': 'small muted', text: 'Measured on census tracts.' }));
      dl.appendChild(fact('Census tracts', S.fmtInt(t.n_tracts)));
      dl.appendChild(fact('Stranded Infrastructure tracts', S.fmtInt(t.n_SI)));
      dl.appendChild(fact('Full Service tracts', S.fmtInt(t.n_FS)));
      dl.appendChild(fact('Median blocked share', 'Stranded Infrastructure ' + S.fmtShareShort(t.median_blocked_SI),
        'Full Service ' + S.fmtShareShort(t.median_blocked_FS)));
      dl.appendChild(fact('Residents in Stranded Infrastructure tracts', S.fmtInt(t.residents_SI)));
      dl.appendChild(fact('Stranded Infrastructure tracts with at least half of directions blocked', S.fmtInt(t.n_SI_half_blocked),
        S.fmtInt(t.residents_SI_half_blocked) + ' residents live in them.'));
      dl.appendChild(fact('Schedule date', S.fmtDate(city.run_date)));
    } else {
      body.appendChild(el('p', { 'class': 'small muted', text: 'Measured on hexagons.' }));
      dl.appendChild(fact('Headline', S.fmtShare(city.headline_share_un),
        S.fmtInt(city.headline_served_blocked_half_un) + ' of ' + S.fmtInt(city.headline_served_denominator_un) +
        ' residents counted as served live where at least half of the directions a car can reach are blocked for transit.'));
      dl.appendChild(fact('UN coverage', S.fmtShare(city.un_coverage_share),
        'Share of residents the UN transit indicator counts as served.'));
      dl.appendChild(fact('Residents', S.fmtInt(city.residents)));
      dl.appendChild(fact('Hexagons', S.fmtInt(city.n_cells),
        S.fmtInt(city.n_origins) + ' have 100 or more residents and were assessed. ' +
        S.fmtInt(city.headline_cells_blocked_half) + ' have at least half of directions blocked.'));
      dl.appendChild(fact('Stranded Infrastructure hexagons', S.fmtInt(city.n_SI)));
      dl.appendChild(fact('Full Service hexagons', S.fmtInt(city.n_FS)));
      dl.appendChild(fact('Median blocked share', 'Stranded Infrastructure ' + S.fmtShareShort(city.median_blocked_SI),
        'Full Service ' + S.fmtShareShort(city.median_blocked_FS)));
      dl.appendChild(fact('Schedule date', S.fmtDate(city.run_date)));
      dl.appendChild(fact('Population source', String(city.population_source)));
    }
    body.appendChild(dl);
    var cav = caveatBox();
    if (cav) body.appendChild(cav);
  }

  /* ---------- map ---------- */
  function boundsOf(fc) {
    var w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
    function ring(r) {
      for (var i = 0; i < r.length; i++) {
        var x = r[i][0], y = r[i][1];
        if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y;
      }
    }
    fc.features.forEach(function (f) {
      var g = f.geometry;
      if (!g) return;
      if (g.type === 'Polygon') g.coordinates.forEach(ring);
      else if (g.type === 'MultiPolygon') g.coordinates.forEach(function (poly) { poly.forEach(ring); });
    });
    return (w === Infinity) ? null : [[w, s], [e, n]];
  }

  function layerIds(u) { return [u + '-fill', u + '-line', u + '-selected']; }

  function addUnitLayers(u, fc) {
    var idField = UNITS[u].idField;
    map.addSource(u, { type: 'geojson', data: fc });
    map.addLayer({ id: u + '-fill', type: 'fill', source: u,
      paint: { 'fill-color': C.notAssessed, 'fill-opacity': 0.78 } }, beforeId);
    map.addLayer({ id: u + '-line', type: 'line', source: u,
      paint: { 'line-color': '#4a4a4a', 'line-opacity': 0.35,
        'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.15, 11, 0.6, 14, 1.2] } }, beforeId);
    map.addLayer({ id: u + '-selected', type: 'line', source: u,
      filter: ['==', ['get', idField], '__none__'],
      paint: { 'line-color': '#000000', 'line-width': 3 } }, beforeId);
    map.on('click', u + '-fill', function (ev) {
      if (unit !== u || !ev.features || !ev.features.length) return;
      select(String(ev.features[0].properties[idField]));
    });
    map.on('mouseenter', u + '-fill', function () { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', u + '-fill', function () { map.getCanvas().style.cursor = ''; });
  }

  function select(id) {
    selected[unit] = id;
    var rec = loaded[unit] && loaded[unit].byId[id];
    if (map && map.getLayer(unit + '-selected')) {
      map.setFilter(unit + '-selected', ['==', ['get', UNITS[unit].idField], id === null ? '__none__' : id]);
    }
    renderArea(rec || null);
  }

  function loadUnit(u) {
    if (loaded[u]) return Promise.resolve(loaded[u]);
    return S.fetchJSON(UNITS[u].path()).then(function (fc) {
      var index = {};
      var idField = UNITS[u].idField;
      fc.features.forEach(function (f) { index[String(f.properties[idField])] = f.properties; });
      loaded[u] = { byId: index, bounds: boundsOf(fc), count: fc.features.length };
      addUnitLayers(u, fc);
      return loaded[u];
    });
  }

  function refresh() {
    var msg = byId('map-msg');
    var label = byId('coverage-label');
    if (label) label.textContent = UNITS[unit].coverageLabel;
    renderLegend();
    renderSummary();
    if (!map) return;
    msg.textContent = 'Loading the ' + UNITS[unit].many + '\u2026';
    var wanted = unit;
    loadUnit(unit).then(function (info) {
      if (wanted !== unit) return;
      ['hex', 'tract'].forEach(function (u) {
        if (!loaded[u]) return;
        layerIds(u).forEach(function (id) {
          map.setLayoutProperty(id, 'visibility', u === unit ? 'visible' : 'none');
        });
      });
      map.setPaintProperty(unit + '-fill', 'fill-color', fillColour());
      if (!refresh.fitted && info.bounds) {
        map.fitBounds(info.bounds, { padding: 24, animate: false });
        refresh.fitted = true;
      }
      var rec = selected[unit] && info.byId[selected[unit]];
      renderArea(rec || null);
      msg.textContent = S.fmtInt(info.count) + ' ' + UNITS[unit].many + '. Click or tap one to see its numbers.';
      document.body.setAttribute('data-ready', unit + ':' + layer);
    }).catch(function () {
      msg.textContent = 'The ' + UNITS[unit].many + ' could not be loaded. Please reload the page.';
      document.body.setAttribute('data-ready', 'failed');
    });
  }

  function setupControls() {
    var form = byId('controls');
    if (!form) return;
    form.addEventListener('change', function (ev) {
      var t = ev.target;
      if (t.name === 'unit') unit = t.value === 'tract' ? 'tract' : 'hex';
      if (t.name === 'layer') layer = t.value;
      refresh();
    });
  }

  function setupMap() {
    var msg = byId('map-msg');
    msg.textContent = 'Loading the map\u2026';
    return S.createMap('map', { center: [city.centre_lon, city.centre_lat], zoom: 9 }).then(function (m) {
      map = m.map;
      S.map = map;   /* handle for the browser checks */
      beforeId = m.beforeId;
      document.body.setAttribute('data-map', m.remote ? 'remote' : 'local');
    }).catch(function () {
      map = null;
      msg.textContent = 'This browser cannot draw the map. You can still read the city summary and download the data.';
      ['map', 'controls', 'legend', 'cell-panel'].forEach(function (id) {
        var node = byId(id);
        if (node) node.hidden = true;
      });
      document.body.setAttribute('data-map', 'none');
    });
  }

  function start() {
    S.fetchJSON(S.root() + 'data/cities.json').then(function (d) {
      city = (d.cities || []).filter(function (c) { return c.city === cityId; })[0];
      if (!city) throw new Error('Unknown city');
      renderSummary();
      document.body.setAttribute('data-summary', 'ready');
      if (!city.cells_public || !byId('map')) return;   /* held city: summary only */
      setupControls();
      renderLegend();
      return setupMap().then(function () { if (map) refresh(); });
    }).catch(function () {
      var body = byId('summary-body');
      S.clear(body);
      body.appendChild(el('p', { 'class': 'note', text: 'The city data could not be loaded. Please reload the page.' }));
      document.body.setAttribute('data-summary', 'failed');
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
