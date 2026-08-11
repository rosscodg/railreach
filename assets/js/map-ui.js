/* RailReach shared map interaction layer.
 *
 * Everything here is deliberately dependency-free and exposed on window.RR so
 * that the homepage and the generated spoke pages share one implementation.
 *
 * Keep exported names stable: a visitor carrying an older service-worker cache
 * can be served a stale copy of this file against fresh HTML.
 */
window.RR = (function () {
  'use strict';

  /* Journey-time palette.
   *
   * The previous green/amber/red scale collapsed under deuteranopia: green
   * against red measured an RGB distance of 244 in normal vision but 44
   * simulated, so the two ends of the scale - "great commute" and "poor
   * commute" - were near identical for roughly 8% of men. This is the
   * Okabe-Ito set, which tested at a worst case of 69 across deuteranopia,
   * protanopia and tritanopia. */
  var COLOURS = {
    fast: '#0072B2',      // under 30 min  - blue
    mid: '#E69F00',       // 30-60 min     - orange
    slow: '#D55E00',      // 60-90 min     - vermillion
    terminal: '#111827',  // London terminal
    focus: '#7c3aed'      // the station a page is about
  };

  var BANDS = [
    { max: 30, key: 'fast', label: 'Under 30 min' },
    { max: 60, key: 'mid', label: '30 to 60 min' },
    { max: Infinity, key: 'slow', label: '60 to 90 min' }
  ];

  function colour(mins) {
    for (var i = 0; i < BANDS.length; i++) {
      if (mins < BANDS[i].max) return COLOURS[BANDS[i].key];
    }
    return COLOURS.slow;
  }

  function bandLabel(mins) {
    for (var i = 0; i < BANDS.length; i++) {
      if (mins < BANDS[i].max) return BANDS[i].label;
    }
    return BANDS[BANDS.length - 1].label;
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  var isTouch = window.matchMedia &&
    window.matchMedia('(hover: none) and (pointer: coarse)').matches;

  /* Marker radius. The old r=7 rendered a 20x20 target, below the WCAG 2.2 AA
   * minimum of 24x24 - and worst on touch, where markers also overlap most.
   * Rendered size is roughly 2r + 2*weight + 2, so r=10 gives 26px. */
  function stationRadius() { return isTouch ? 12 : 10; }

  /* ---- Gesture handling -------------------------------------------------
   * The map sits in a long scrolling page. Left at Leaflet's defaults it traps
   * the page: the wheel handler calls preventDefault, and on touch a one-finger
   * drag pans the map instead of scrolling. Both now require an explicit
   * intent, following the convention people already know from embedded maps. */
  function addGestureHandling(map, container) {
    var hint = document.createElement('div');
    hint.className = 'map-hint';
    hint.setAttribute('aria-hidden', 'true');
    hint.textContent = isTouch
      ? 'Use two fingers to move the map'
      : (navigator.platform.indexOf('Mac') === 0 ? 'Use ⌘ + scroll to zoom the map'
                                                 : 'Use ctrl + scroll to zoom the map');
    container.appendChild(hint);

    var hideTimer;
    function show() {
      hint.classList.add('visible');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(function () { hint.classList.remove('visible'); }, 1400);
    }
    function hide() {
      hint.classList.remove('visible');
      clearTimeout(hideTimer);
    }

    map.scrollWheelZoom.disable();

    container.addEventListener('wheel', function (e) {
      if (e.ctrlKey || e.metaKey) {
        // Stop the browser zooming the whole page, and let Leaflet take it.
        e.preventDefault();
        if (!map.scrollWheelZoom.enabled()) map.scrollWheelZoom.enable();
        hide();
      } else {
        if (map.scrollWheelZoom.enabled()) map.scrollWheelZoom.disable();
        show();
      }
    }, { passive: false });

    if (isTouch) {
      map.dragging.disable();
      container.addEventListener('touchstart', function (e) {
        if (e.touches.length >= 2) {
          map.dragging.enable();
          hide();
        }
      }, { passive: true });
      container.addEventListener('touchmove', function (e) {
        if (e.touches.length < 2 && !map.dragging.enabled()) show();
      }, { passive: true });
      container.addEventListener('touchend', function (e) {
        if (e.touches.length < 2) map.dragging.disable();
      }, { passive: true });
    }

    // Keyboard users can still pan/zoom once the map has focus.
    container.addEventListener('focusin', function () { hide(); });
  }

  function createMap(id, opts) {
    opts = opts || {};
    var map = L.map(id, {
      scrollWheelZoom: false,
      zoomControl: true,
      // Leaflet's default is fine for pinch; dragging is gated below on touch.
      touchZoom: true
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 18
    }).addTo(map);
    // Always establish a view: layers added before fitBounds runs would
    // otherwise be projected against an undefined zoom.
    map.setView(opts.center || [52.0, -0.7], opts.zoom || 7, { animate: false });
    addGestureHandling(map, map.getContainer());
    return map;
  }

  /* ---- Framing ----------------------------------------------------------
   * The map previously opened at a fixed zoom and never recentred, so markers
   * occupied 1-3% of the viewport for every terminal, and on station pages
   * 182 of 357 routes put the destination off-screen on a 375px display.
   * Padding keeps markers clear of the legend and promo overlays. */
  function fit(map, latlngs, opts) {
    opts = opts || {};
    var pts = (latlngs || []).filter(function (p) {
      return p && isFinite(p[0]) && isFinite(p[1]);
    });
    if (!pts.length) return;
    var narrow = window.innerWidth <= 768;
    // Keep markers clear of the control panel above and the legend/promo below.
    var controls = document.querySelector('.controls');
    var top = opts.topPadding != null ? opts.topPadding
      : (controls ? Math.round(controls.getBoundingClientRect().height) + 18 : (narrow ? 24 : 70));
    var bottom = opts.bottomPadding != null ? opts.bottomPadding : (narrow ? 155 : 120);
    var side = narrow ? 22 : 50;
    // Never let padding eat the whole map on a short viewport.
    var h = map.getSize().y;
    if (top + bottom > h * 0.7) {
      var scale = (h * 0.7) / (top + bottom);
      top = Math.round(top * scale); bottom = Math.round(bottom * scale);
    }
    map.fitBounds(L.latLngBounds(pts), {
      paddingTopLeft: [side, top],
      paddingBottomRight: [side, bottom],
      maxZoom: opts.maxZoom || 11,
      animate: opts.animate !== false
    });
  }

  /* ---- Markers and popups ----------------------------------------------- */
  function stationPopup(station, terminalName, journey) {
    var html = '<strong>' + esc(station.name) + '</strong><br>' +
      'To ' + esc(terminalName) + ': <strong>' + journey.mins + ' min</strong><br>' +
      (journey.direct ? 'Direct train' : 'Requires a change');
    // The map used to dead-end here, with no route through to the station page.
    if (station.slug) {
      html += '<br><a class="popup-link" href="/stations/' + station.slug + '/">' +
        'Journey guide &rarr;</a>';
    }
    return html;
  }

  function stationMarker(map, station, mins, popupHtml) {
    var m = L.circleMarker([station.lat, station.lng], {
      radius: stationRadius(),
      fillColor: colour(mins),
      color: '#fff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    });
    m.bindPopup(popupHtml);
    m.addTo(map);
    return m;
  }

  function terminalMarker(map, lat, lng, popupHtml) {
    var m = L.circleMarker([lat, lng], {
      radius: isTouch ? 13 : 12,
      fillColor: COLOURS.terminal,
      color: '#fff',
      weight: 3,
      opacity: 1,
      fillOpacity: 0.95
    });
    m.bindPopup(popupHtml);
    m.addTo(map);
    return m;
  }

  return {
    COLOURS: COLOURS,
    BANDS: BANDS,
    colour: colour,
    bandLabel: bandLabel,
    esc: esc,
    isTouch: isTouch,
    stationRadius: stationRadius,
    createMap: createMap,
    fit: fit,
    stationPopup: stationPopup,
    stationMarker: stationMarker,
    terminalMarker: terminalMarker
  };
})();
