/* RailReach homepage map controller.
 *
 * Expects TERMINALS and STATIONS (inlined in index.html) and window.RR
 * (assets/js/map-ui.js) to already be defined.
 */
(function () {
  'use strict';

  var DEFAULT_TERMINAL = 'KGX';
  var BUDGETS = [30, 45, 60, 90];
  var state = { terminal: DEFAULT_TERMINAL, max: 90 };

  var map = RR.createMap('map');
  var stationLayer = L.layerGroup().addTo(map);
  var terminalLayer = L.layerGroup().addTo(map);
  var markerBySlug = {};

  var els = {
    buttons: document.getElementById('terminal-buttons'),
    select: document.getElementById('terminal-select'),
    budget: document.getElementById('budget-filter'),
    count: document.getElementById('station-count'),
    search: document.getElementById('station-search'),
    results: document.getElementById('station-search-results')
  };

  /* ---- URL state --------------------------------------------------------
   * Previously nothing about the view was in the URL, so no map view could be
   * shared or bookmarked and the back button did nothing. */
  function readUrl() {
    var p = new URLSearchParams(location.search);
    var to = (p.get('to') || '').toUpperCase();
    var max = parseInt(p.get('max'), 10);
    if (TERMINALS[to]) state.terminal = to;
    if (BUDGETS.indexOf(max) !== -1) state.max = max;
  }

  function writeUrl(push) {
    var p = new URLSearchParams();
    if (state.terminal !== DEFAULT_TERMINAL) p.set('to', state.terminal);
    if (state.max !== 90) p.set('max', String(state.max));
    var qs = p.toString();
    var url = location.pathname + (qs ? '?' + qs : '');
    if (push) history.pushState({ t: state.terminal, m: state.max }, '', url);
    else history.replaceState({ t: state.terminal, m: state.max }, '', url);
  }

  /* ---- Data ------------------------------------------------------------- */
  function visibleStations() {
    var code = state.terminal;
    return STATIONS.filter(function (s) {
      var j = s.journeys[code];
      return j && j.mins <= Math.min(state.max, 90);
    }).sort(function (a, b) {
      return a.journeys[code].mins - b.journeys[code].mins;
    });
  }

  /* ---- Rendering -------------------------------------------------------- */
  function render(opts) {
    opts = opts || {};
    var code = state.terminal;
    var terminal = TERMINALS[code];
    var list = visibleStations();

    stationLayer.clearLayers();
    terminalLayer.clearLayers();
    markerBySlug = {};

    var t = RR.terminalMarker(terminalLayer, terminal.lat, terminal.lng,
      '<strong>London ' + RR.esc(terminal.name) + '</strong><br>London terminal' +
      '<br><a class="popup-link" href="/terminals/' + slugFor(code) + '/">Terminal guide &rarr;</a>');

    list.forEach(function (s) {
      var j = s.journeys[code];
      var m = RR.stationMarker(stationLayer, s, j.mins, RR.stationPopup(s, terminal.name, j));
      if (s.slug) markerBySlug[s.slug] = m;
    });

    els.count.textContent = list.length + ' station' + (list.length === 1 ? '' : 's') +
      ' within ' + state.max + ' min of ' + terminal.name;

    document.querySelectorAll('.terminal-btn').forEach(function (b) {
      var on = b.dataset.code === code;
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (els.select.value !== code) els.select.value = code;

    document.querySelectorAll('.budget-btn').forEach(function (b) {
      var on = parseInt(b.dataset.max, 10) === state.max;
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });

    if (opts.fit !== false) {
      var pts = list.map(function (s) { return [s.lat, s.lng]; });
      pts.push([terminal.lat, terminal.lng]);
      RR.fit(map, pts, { animate: opts.animate !== false });
    }
  }

  var TERMINAL_SLUGS = {
    KGX: 'kings-cross', WAT: 'waterloo', PAD: 'paddington', LBG: 'london-bridge',
    VIC: 'victoria', LST: 'liverpool-street', EUS: 'euston', MYB: 'marylebone',
    FST: 'fenchurch-street'
  };
  function slugFor(code) { return TERMINAL_SLUGS[code] || ''; }

  /* ---- Controls --------------------------------------------------------- */
  function buildTerminalControls() {
    var entries = Object.keys(TERMINALS).map(function (c) { return [c, TERMINALS[c]]; })
      .sort(function (a, b) { return a[1].name.localeCompare(b[1].name); });

    entries.forEach(function (pair) {
      var code = pair[0], t = pair[1];

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'terminal-btn';
      btn.dataset.code = code;
      btn.textContent = t.name;
      btn.setAttribute('aria-pressed', 'false');
      btn.addEventListener('click', function () {
        state.terminal = code;
        writeUrl(true);
        render();
      });
      els.buttons.appendChild(btn);

      var opt = document.createElement('option');
      opt.value = code;
      opt.textContent = t.name;
      els.select.appendChild(opt);
    });

    els.select.addEventListener('change', function () {
      state.terminal = els.select.value;
      writeUrl(true);
      render();
    });
  }

  /* Journey-time budget. This is the question a map answers better than a
   * table - "everywhere within 45 minutes of Waterloo" - and it previously
   * could not be asked at all. */
  function buildBudgetControls() {
    BUDGETS.forEach(function (mins) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'budget-btn';
      btn.dataset.max = String(mins);
      // Two labels so the chip can be terse on narrow screens without the
      // control losing meaning. CSS swaps them at the mobile breakpoint.
      btn.innerHTML = mins === 90
        ? '<span class="btn-long">All</span><span class="btn-short">All</span>'
        : '<span class="btn-long">Under ' + mins + '</span>' +
          '<span class="btn-short">&lt;' + mins + '</span>';
      btn.setAttribute('aria-label', mins === 90
        ? 'Any journey time' : 'Journeys under ' + mins + ' minutes');
      btn.setAttribute('aria-pressed', 'false');
      btn.addEventListener('click', function () {
        state.max = mins;
        writeUrl(true);
        render();
      });
      els.budget.appendChild(btn);
    });
  }

  /* ---- Search -----------------------------------------------------------
   * The site's traffic arrives place-first ("Reading to London train times")
   * but the homepage only offered terminal-first navigation. */
  function buildSearch() {
    var input = els.search, listbox = els.results;
    var matches = [], active = -1;

    function close() {
      listbox.hidden = true;
      listbox.innerHTML = '';
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      active = -1;
    }

    function fastestFor(s) {
      var best = null, bestCode = null;
      Object.keys(s.journeys).forEach(function (c) {
        if (!best || s.journeys[c].mins < best.mins) { best = s.journeys[c]; bestCode = c; }
      });
      return { code: bestCode, j: best };
    }

    function choose(s) {
      var f = fastestFor(s);
      state.terminal = f.code;
      if (f.j.mins > state.max) state.max = 90;
      writeUrl(true);
      render({ fit: false });
      map.setView([s.lat, s.lng], Math.max(map.getZoom(), 10), { animate: true });
      var m = markerBySlug[s.slug];
      if (m) m.openPopup();
      input.value = s.name;
      close();
    }

    function draw() {
      listbox.innerHTML = '';
      matches.forEach(function (s, i) {
        var f = fastestFor(s);
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.id = 'rr-opt-' + i;
        li.className = 'search-opt' + (i === active ? ' active' : '');
        li.setAttribute('aria-selected', i === active ? 'true' : 'false');
        li.innerHTML = '<span class="opt-name">' + RR.esc(s.name) + '</span>' +
          '<span class="opt-meta">' + f.j.mins + ' min to ' + RR.esc(TERMINALS[f.code].name) + '</span>';
        li.addEventListener('mousedown', function (e) { e.preventDefault(); choose(s); });
        listbox.appendChild(li);
      });
      listbox.hidden = matches.length === 0;
      input.setAttribute('aria-expanded', matches.length ? 'true' : 'false');
    }

    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) { matches = []; close(); return; }
      var starts = [], contains = [];
      STATIONS.forEach(function (s) {
        var n = s.name.toLowerCase();
        if (n.indexOf(q) === 0) starts.push(s);
        else if (n.indexOf(q) !== -1) contains.push(s);
      });
      matches = starts.concat(contains).slice(0, 8);
      active = -1;
      draw();
    });

    input.addEventListener('keydown', function (e) {
      if (listbox.hidden && e.key !== 'ArrowDown') return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!matches.length) return;
        active = e.key === 'ArrowDown'
          ? (active + 1) % matches.length
          : (active <= 0 ? matches.length - 1 : active - 1);
        draw();
        input.setAttribute('aria-activedescendant', 'rr-opt-' + active);
      } else if (e.key === 'Enter') {
        if (active >= 0 && matches[active]) { e.preventDefault(); choose(matches[active]); }
        else if (matches.length === 1) { e.preventDefault(); choose(matches[0]); }
      } else if (e.key === 'Escape') {
        close();
      }
    });

    input.addEventListener('blur', function () { setTimeout(close, 120); });
  }

  /* ---- Boot ------------------------------------------------------------- */
  readUrl();
  buildTerminalControls();
  buildBudgetControls();
  buildSearch();
  writeUrl(false);
  render({ animate: false });

  window.addEventListener('popstate', function (e) {
    var s = e.state;
    if (s) { state.terminal = s.t; state.max = s.m; }
    else { state.terminal = DEFAULT_TERMINAL; state.max = 90; readUrl(); }
    render();
  });

  // Re-fit if the viewport changes shape enough to matter (rotation).
  var lastW = window.innerWidth;
  window.addEventListener('resize', function () {
    if (Math.abs(window.innerWidth - lastW) < 80) return;
    lastW = window.innerWidth;
    map.invalidateSize();
    render({ animate: false });
  });
})();
