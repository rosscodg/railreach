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
    keepPopupClear(map);
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
    var h = map.getSize().y;
    var shell = map.getContainer().getBoundingClientRect();

    /* Measure what actually covers the map rather than guessing. A hardcoded
     * 155px bottom was under-reading the legend (179px) while the control
     * panel pushed the top padding to 188, leaving a 217px usable band on a
     * 560px map - so fitBounds zoomed out to show most of western Europe. */
    function obstructionTop(sel) {
      var el = document.querySelector(sel);
      if (!el) return 0;
      var r = el.getBoundingClientRect();
      if (!r.height) return 0;
      return Math.max(0, r.bottom - shell.top);
    }
    function obstructionBottom(sel) {
      var el = document.querySelector(sel);
      if (!el) return 0;
      var r = el.getBoundingClientRect();
      if (!r.height) return 0;
      return Math.max(0, shell.bottom - r.top);
    }

    var top = opts.topPadding != null ? opts.topPadding
      : Math.max(obstructionTop('.controls'), narrow ? 16 : 60) + 10;
    var bottom = opts.bottomPadding != null ? opts.bottomPadding
      : Math.max(obstructionBottom('.legend'), obstructionBottom('#promo-banner'),
                 narrow ? 70 : 90) + 10;
    var side = narrow ? 22 : 50;

    /* Padding must never dominate: below about half the map the fit degrades
     * into a uselessly wide view. Prefer a slightly obscured marker to that. */
    var maxPadding = h * 0.5;
    if (top + bottom > maxPadding) {
      var scale = maxPadding / (top + bottom);
      top = Math.round(top * scale);
      bottom = Math.round(bottom * scale);
    }
    map.fitBounds(L.latLngBounds(pts), {
      paddingTopLeft: [side, top],
      paddingBottomRight: [side, bottom],
      maxZoom: opts.maxZoom || 11,
      animate: opts.animate !== false
    });
  }


  /* Centre a point so that it, and the popup above it, sit clear of the
   * control panel. Relying on Leaflet's auto-pan here was not reliable: it
   * pans correctly, then the in-flight setView animation settles and puts the
   * marker back under the panel. Positioning deliberately is deterministic. */
  function focusPoint(map, latlng, zoom) {
    zoom = zoom || map.getZoom();
    var size = map.getSize();
    var mapTop = map.getContainer().getBoundingClientRect().top;

    /* Use the panel's BOTTOM EDGE relative to the map, not its height: the
     * panel starts below the site header, so its height under-counts by the
     * header and the popup still lands underneath it.
     *
     * Raising the popup's z-index cannot fix this. The popup lives inside
     * #map, which is its own stacking context, so it can never paint above a
     * sibling of #map however high its z-index. The only reliable fix is to
     * move the map so the popup has somewhere clear to open. */
    var obstructedTo = 0;
    var panel = document.querySelector('.controls');
    if (panel) {
      var pr = panel.getBoundingClientRect();
      if (pr.height) obstructedTo = Math.max(0, pr.bottom - mapTop);
    }

    // Popups open above their marker, so the marker needs to sit a popup's
    // height below the obstruction. 210 covers the tallest popup plus its tip.
    var targetY = obstructedTo + 210;
    // ...but never so low that the marker leaves the map.
    targetY = Math.min(targetY, size.y - 60);

    var centre = map.project(L.latLng(latlng), zoom)
                    .add([0, size.y / 2 - targetY]);
    map.setView(map.unproject(centre, zoom), zoom, { animate: true });
  }

  /* Move an open popup clear of the panels floating over the map.
   *
   * This runs after the popup is in the DOM, so it measures the real thing
   * rather than guessing its height, and it is bound once in createMap so
   * every route in behaves the same: search, marker tap, deep link, and the
   * terminal and station pages. Guessing per-path is what let a direct marker
   * tap open a popup 83px underneath the control panel while the search path
   * looked fine. */
  function keepPopupClear(map) {
    map.on('popupopen', function (e) {
      var popup = e.popup;
      var tries = 0;

      /* Returns true if it had to move the map. */
      function correct() {
        var el = popup.getElement();
        if (!el) return false;
        var shell = map.getContainer().getBoundingClientRect();
        var r = el.getBoundingClientRect();

        function bottomOf(sel) {
          var o = document.querySelector(sel);
          if (!o) return shell.top;
          var b = o.getBoundingClientRect();
          return b.height ? b.bottom : shell.top;
        }
        function topOf(sel) {
          var o = document.querySelector(sel);
          if (!o) return shell.bottom;
          var b = o.getBoundingClientRect();
          return b.height ? b.top : shell.bottom;
        }

        var clearTop = Math.max(shell.top, bottomOf('.controls')) + 8;
        var clearBottom = Math.min(shell.bottom, topOf('.legend'),
                                   topOf('#promo-banner')) - 8;

        var dy = 0;
        if (r.top < clearTop) {
          dy = clearTop - r.top;
        } else if (r.bottom > clearBottom) {
          // If the popup is taller than the clear band, show its top: the
          // station name and the fastest time matter more than the link.
          dy = Math.max(clearBottom - r.bottom, clearTop - r.top);
        }

        var dx = 0;
        if (r.left < shell.left + 8) dx = shell.left + 8 - r.left;
        else if (r.right > shell.right - 8) dx = shell.right - 8 - r.right;

        if (!dx && !dy) return false;

        /* animate:false deliberately. An animated pan is applied and then
         * cancelled by whatever map animation is still in flight, which is why
         * one tap landed 176px under the panel while the next was fine. An
         * instant pan is synchronous and cannot be cancelled. */
        map.panBy([-dx, -dy], { animate: false });
        return true;
      }

      /* Correcting once is not enough for the first popup after page load: the
       * opening fitBounds animation is still in flight and its final view
       * discards the pan. Re-assert when the map settles, a bounded number of
       * times so this can never loop. */
      function settle() {
        if (tries++ >= 3 || !map.hasLayer(popup)) {
          stop();
          return;
        }
        correct();
      }
      function stop() {
        map.off('moveend', settle);
        map.off('zoomend', settle);
        map.off('popupclose', stop);
      }

      correct();
      map.on('moveend', settle);
      map.on('zoomend', settle);
      map.on('popupclose', stop);
    });
  }


  /* ---- Markers and popups ----------------------------------------------- */
  function stationPopup(station, terminalName, journey) {
    /* Four measures, and they answer different questions. "Fastest" is the
     * quickest way there and may involve a change, so it names where; "fastest
     * direct" is what you can do without changing, shown only when the two
     * differ, since repeating the same number twice tells the reader nothing.
     * The peak figures describe direct services, and say so. */
    var html = '<strong>' + esc(station.name) + '</strong>' +
      '<div class="pop-sub">to ' + esc(terminalName) + '</div>' +
      '<dl class="pop-stats">' +
      '<div><dt>Fastest</dt><dd>' + journey.mins + ' min' +
      (journey.direct ? '' : '<span class="pop-via">change at ' +
                             esc(journey.at || 'one station') + '</span>') +
      '</dd></div>';

    if (!journey.direct && journey.dm) {
      html += '<div><dt>Fastest direct</dt><dd>' + journey.dm + ' min</dd></div>';
    }

    if (journey.typical) {
      var gap = journey.typical - journey.mins;
      html += '<div' + (gap >= 10 ? ' class="pop-gap"' : '') +
        '><dt>Typical peak</dt><dd>' + journey.typical + ' min</dd></div>';
    } else {
      html += '<div><dt>Typical peak</dt><dd class="pop-none">no peak service</dd></div>';
    }

    if (journey.tph) html += '<div><dt>Peak trains</dt><dd>' + journey.tph + '/hr</dd></div>';
    html += '</dl>';

    if (station.slug) {
      html += '<a class="popup-link" href="/stations/' + station.slug + '/">' +
        'Journey guide &rarr;</a>';
    }
    return html;
  }

  function popupOptions() {
    /* autoPan off: it pans against padding guessed from panel heights, which
     * got a direct marker tap wrong by 83px. keepPopupClear corrects after the
     * popup exists, measuring it rather than estimating it. */
    return { autoPan: false };
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
    m.bindPopup(popupHtml, popupOptions());
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
    m.bindPopup(popupHtml, popupOptions());
    m.addTo(map);
    return m;
  }


  /* ---- Discovery -------------------------------------------------------
   * The product's point is showing people places they would never have
   * thought to look at. Ranking is by absolute journey time, not by minutes
   * per kilometre: that metric just rewards being on a fast line, and a
   * brilliant minutes-per-km score is no use if the trip still takes 70
   * minutes. What decides whether you could live somewhere is the clock.
   *
   * "Unfamiliar" is an editorial judgement, so it is an explicit list rather
   * than a clever formula. FEATURED are the towns the site already promotes
   * everywhere; MAJOR are cities and airports nobody discovers on a map. */
  /* Deliberately no "well known" exclusion list.
   *
   * An earlier version filtered out the towns the site promotes plus a set of
   * major cities, on the theory that nobody discovers Reading on a map. That
   * assumed knowledge we have no basis for: plenty of people have no idea
   * where Reading is, still less that it is 23 minutes from Paddington. The
   * only exclusions left are places you cannot actually live - airports and
   * a golf-course halt - which is a category judgement, not a guess about
   * what the reader already knows. */
  var NOT_A_PLACE_TO_LIVE = {};
  ['Gatwick Airport', 'Stansted Airport', 'Luton Airport Parkway',
   'Birmingham International', 'Denham Golf Club'].forEach(function (n) {
    NOT_A_PLACE_TO_LIVE[n] = true;
  });

  var CENTRAL = [51.5074, -0.1278];        // Charing Cross
  var MIN_KM_FROM_LONDON = 20;             // inside this ring it is London, not a move
  var MIN_KM_APART = 8;                    // spread results instead of one line's stops

  function kmBetween(a, b) {
    var R = 6371, p = Math.PI / 180;
    var dLat = (b[0] - a[0]) * p, dLng = (b[1] - a[1]) * p;
    var x = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a[0] * p) * Math.cos(b[0] * p) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return R * 2 * Math.asin(Math.sqrt(x));
  }

  function discoveries(stations, code, maxMins, limit) {
    var out = [], chosen = [];
    stations.filter(function (s) {
      var j = s.journeys[code];
      if (!j || j.mins > maxMins) return false;
      if (NOT_A_PLACE_TO_LIVE[s.name]) return false;
      return kmBetween(CENTRAL, [s.lat, s.lng]) >= MIN_KM_FROM_LONDON;
    }).sort(function (a, b) {
      return a.journeys[code].mins - b.journeys[code].mins;
    }).forEach(function (s) {
      if (out.length >= (limit || 6)) return;
      var tooClose = chosen.some(function (c) {
        return kmBetween(c, [s.lat, s.lng]) < MIN_KM_APART;
      });
      if (tooClose) return;
      chosen.push([s.lat, s.lng]);
      out.push(s);
    });
    return out;
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
    focusPoint: focusPoint,
    popupOptions: popupOptions,
    stationPopup: stationPopup,
    stationMarker: stationMarker,
    terminalMarker: terminalMarker,
    discoveries: discoveries,
    kmBetween: kmBetween
  };
})();
