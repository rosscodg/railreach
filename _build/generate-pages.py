#!/usr/bin/env python3
"""Generate every RailReach page other than the homepage.

Outputs:
  /terminals/<slug>/   9 terminal pages
  /stations/<slug>/    one page per station
  /terminals/          terminal hub
  /stations/           station hub
  /about/              methodology + provenance
  /sitemap.xml         regenerated with a real lastmod
  /assets/js/*.js

Reads the canonical dataset at _build/data/stations.json and rewrites the
generated regions of index.html from it, so the homepage and the spoke pages
can no longer drift apart.

Run from anywhere:  python3 _build/generate-pages.py
"""

import os
import re
import json
import math
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://railreach.co.uk"
BUILD_DATE = datetime.date.today().isoformat()

# ── Terminal metadata ──────────────────────────────────────────────────────
TERMINAL_META = {
    'KGX': {'slug': 'kings-cross', 'name': 'Kings Cross', 'operators': 'Great Northern, Thameslink, LNER',
            'region': 'the north and east of England'},
    'WAT': {'slug': 'waterloo', 'name': 'Waterloo', 'operators': 'South Western Railway',
            'region': 'Surrey, Hampshire and the South West'},
    'PAD': {'slug': 'paddington', 'name': 'Paddington', 'operators': 'Great Western Railway, Elizabeth line',
            'region': 'the Thames Valley and the West'},
    'LBG': {'slug': 'london-bridge', 'name': 'London Bridge', 'operators': 'Southeastern, Southern, Thameslink',
            'region': 'South East London, Kent and Surrey'},
    'VIC': {'slug': 'victoria', 'name': 'Victoria', 'operators': 'Southeastern, Southern',
            'region': 'Kent, Sussex and the South Coast'},
    'LST': {'slug': 'liverpool-street', 'name': 'Liverpool Street', 'operators': 'Greater Anglia',
            'region': 'Essex, Hertfordshire and East Anglia'},
    'EUS': {'slug': 'euston', 'name': 'Euston', 'operators': 'Avanti West Coast, London Northwestern',
            'region': 'the West Coast Main Line, Buckinghamshire and the Midlands'},
    'MYB': {'slug': 'marylebone', 'name': 'Marylebone', 'operators': 'Chiltern Railways',
            'region': 'the Chilterns, Buckinghamshire and Oxfordshire'},
    'FST': {'slug': 'fenchurch-street', 'name': 'Fenchurch Street', 'operators': 'c2c',
            'region': 'East London and South Essex'},
}

# The 27 towns that had hand-built pages first. They keep prominent placement
# on the homepage and station hub; slugs for all stations come from the data.
FEATURED = [
    'Cambridge', 'Reading', 'Oxford', 'Brighton', 'Guildford', 'Woking',
    'St Albans City', 'Stevenage', 'Milton Keynes Central', 'Chelmsford',
    'Sevenoaks', 'Basingstoke', 'Winchester', 'Watford Junction', 'Swindon',
    'Colchester', 'Ipswich', 'Peterborough', 'Bedford', 'High Wycombe',
    'Tonbridge', 'Tunbridge Wells', 'Crawley', 'Bromley South', 'Richmond',
    'Slough', 'Maidenhead',
]

# Populated from the dataset in main(); every station gets a page.
STATION_SLUGS = {}


# ── Helpers ────────────────────────────────────────────────────────────────
def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;').replace("'", '&#39;'))


def json_esc(s):
    return json.dumps(s)[1:-1]


def band(mins):
    return 't-fast' if mins < 30 else 't-mid' if mins < 60 else 't-slow'


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


def badge(mins):
    return f'<span class="t-badge {band(mins)}">{mins} min</span>'


def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def faq_ld_from_html(faqs_html):
    items = []
    for m in re.finditer(r'<h3>(.*?)</h3>\s*<p>(.*?)</p>', faqs_html, re.DOTALL):
        items.append({
            "@type": "Question",
            "name": re.sub(r'<[^>]+>', '', m.group(1)),
            "acceptedAnswer": {"@type": "Answer", "text": re.sub(r'<[^>]+>', '', m.group(2))},
        })
    return json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items}, indent=0)


def breadcrumb_ld(trail):
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE + path}
            for i, (name, path) in enumerate(trail)
        ],
    }, indent=0)


# ── Shared chrome ──────────────────────────────────────────────────────────
def head(title, desc, canonical, og_title, og_desc, map_h=None, leaflet=True):
    mapvar = f'\n<style>:root {{ --map-h: {map_h}; }}</style>' if map_h else ''
    leaflet_tags = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">\n'
                    '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n') if leaflet else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:site_name" content="RailReach">
<meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE}/og-image.png">
<meta name="theme-color" content="#1e293b">
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.json">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HKGQBJT0D3"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag('js',new Date());gtag('config','G-HKGQBJT0D3');</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
{leaflet_tags}<link rel="stylesheet" href="/assets/css/shared.css">{mapvar}
</head>'''


def site_header(active=''):
    def cur(key):
        return ' aria-current="page"' if key == active else ''
    return f'''<a class="skip-link" href="#content">Skip to content</a>
<header class="site-header">
<a class="brand" href="/">Rail<span>Reach</span></a>
<nav class="site-nav" aria-label="Primary">
<a href="/terminals/"{cur('terminals')}>Terminals</a>
<a href="/stations/"{cur('stations')}>Stations</a>
<a href="/about/"{cur('about')}>About the data</a>
</nav>
</header>'''


def crumbs(trail):
    """trail: list of (name, href-or-None); the last item is the current page."""
    parts = [f'<li><a href="{href}">{name}</a></li>' if href else f'<li>{name}</li>'
             for name, href in trail]
    return ('<nav class="crumb-bar" aria-label="Breadcrumb"><ol class="breadcrumb">'
            + ''.join(parts) + '</ol></nav>')


def legend(extra=''):
    return f'''<div class="legend">
<p class="legend-title">Journey Time</p>
<div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div> Under 30 min</div>
<div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> 30–60 min</div>
<div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div> 60–90 min</div>
{extra}<div class="legend-item"><div class="legend-dot" style="background:#7c3aed"></div> London Terminal</div>
</div>'''


PROMO = '''<div id="promo-banner">
<a id="promo-slot-1" href="https://www.connells.co.uk/" target="_blank" rel="noopener sponsored">
<div class="promo-connells">
<div class="promo-logo">Connells<span>Est. 1936</span></div>
<div class="promo-body">
<div class="promo-headline">Found your perfect commute? Now find your perfect home.</div>
<div class="promo-sub">Over 150 branches nationwide &bull; Free online valuations &bull; Expert local knowledge</div>
</div>
<div class="promo-cta">Search Now</div>
</div>
</a>
</div>'''

DATA_NOTE = ('<div class="data-note"><strong>Data:</strong> journey times are the fastest typical weekday '
             'service on each route, compiled from published National Rail operator timetables for 2026. '
             'They exclude engineering works and disruption, and are not live departure times. '
             f'Last reviewed {BUILD_DATE}. <a href="/about/">Read the full methodology &rarr;</a></div>')


def site_footer(total):
    return f'''<footer class="site-footer">
<div class="wrap">
<div>
<p><strong>RailReach</strong> — free UK train commute time data.</p>
<p>Journey times from {total} stations to 9 London main line terminals, sourced from National Rail operator timetables for 2026.</p>
</div>
<div class="footer-links">
<a href="/">Map</a>
<a href="/terminals/">Terminals</a>
<a href="/stations/">Stations</a>
<a href="/about/">About the data</a>
</div>
</div>
</footer>
<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');</script>
</body></html>'''


# ── Data source ────────────────────────────────────────────────────────────
DATA_PATH = os.path.join(BASE, '_build', 'data', 'stations.json')


def load_data():
    """Load the canonical dataset.

    This replaces the old approach of regex-scraping index.html by hardcoded
    line numbers, which silently produced a stations-data.js full of HTML.
    """
    with open(DATA_PATH) as f:
        data = json.load(f)
    terminals = data['terminals']
    stations = data['stations']
    for s in stations:
        assert s['journeys'], f"{s['name']} has no journeys"
    return terminals, stations


def js_data_block(terminals, stations):
    """Render the dataset as the JS both index.html and spoke pages consume."""
    tlines = ',\n'.join(
        f'  {code}: {{ name: "{t["name"]}", lat: {t["lat"]}, lng: {t["lng"]} }}'
        for code, t in terminals.items())

    slines = []
    for s in stations:
        j = ', '.join(f'{c}: {{ mins: {v["mins"]}, direct: {str(v["direct"]).lower()} }}'
                      for c, v in sorted(s['journeys'].items(), key=lambda kv: kv[1]['mins']))
        slines.append(f'  {{ name: "{s["name"]}", lat: {s["lat"]}, lng: {s["lng"]}, '
                      f'slug: "{s["slug"]}", journeys: {{ {j} }} }}')

    return ('const TERMINALS = {\n' + tlines + '\n};\n\nconst STATIONS = [\n'
            + ',\n'.join(slines) + '\n];')


def replace_marked(html, tag, replacement, comment='html'):
    open_m, close_m = (f'<!-- GEN:{tag} -->', f'<!-- /GEN:{tag} -->') if comment == 'html' \
        else (f'/* GEN:{tag} */', f'/* /GEN:{tag} */')
    pattern = re.escape(open_m) + r'.*?' + re.escape(close_m)
    out, n = re.subn(pattern, open_m + '\n' + replacement + '\n' + close_m, html, count=1, flags=re.DOTALL)
    assert n == 1, f"marker '{tag}' not found in index.html"
    return out


MAP_CORE_JS = '''// Shared map utilities for RailReach spoke pages
function getColor(mins) {
  if (mins < 30) return '#22c55e';
  if (mins < 60) return '#f59e0b';
  return '#ef4444';
}

function initMap(lat, lng, zoom) {
  const map = L.map('map').setView([lat, lng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
  }).addTo(map);
  return map;
}

// NOTE: keep these names stable. Visitors carrying an older service-worker
// cache may be served a stale copy of this file against fresh HTML; renaming
// an exported function would break every map on the site for them.
function createTerminalMarker(map, lat, lng, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 12, fillColor: '#7c3aed', color: '#fff',
    weight: 3, opacity: 1, fillOpacity: 0.9
  }).bindPopup(popupHtml).addTo(map);
}

function createStationMarker(map, lat, lng, mins, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 7, fillColor: getColor(mins), color: '#fff',
    weight: 2, opacity: 1, fillOpacity: 0.85
  }).bindPopup(popupHtml).addTo(map);
}
'''


def write_shared_js(data_js):
    os.makedirs(os.path.join(BASE, 'assets', 'js'), exist_ok=True)
    for name, content in (('stations-data.js', data_js + '\n'), ('map-core.js', MAP_CORE_JS)):
        path = os.path.join(BASE, 'assets', 'js', name)
        with open(path, 'w') as f:
            f.write(content)
        print(f"  wrote assets/js/{name}")


# ── Terminal pages ─────────────────────────────────────────────────────────
def generate_terminal_page(code, terminals, stations, total):
    meta = TERMINAL_META[code]
    slug, name, operators = meta['slug'], meta['name'], meta['operators']
    t = terminals[code]

    serving = sorted(
        ((s['name'], s['journeys'][code]['mins'], s['journeys'][code]['direct'])
         for s in stations if code in s['journeys'] and s['journeys'][code]['mins'] <= 90),
        key=lambda x: x[1])
    count = len(serving)
    top3 = ', '.join(f"{n} ({m} min)" for n, m, _ in serving[:3])
    top5 = ', '.join(n for n, _, _ in serving[:5])
    under30 = [n for n, m, _ in serving if m < 30]
    under30_names = ', '.join(under30[:6]) if under30 else 'none within 30 minutes'
    fastest = serving[0]
    direct_count = sum(1 for _, _, d in serving if d)

    row_parts = []
    for st_name, st_mins, st_direct in serving:
        # NOTE: do not name these `slug`/`m` — `slug` is this terminal's own
        # slug and is used below to pick the output directory.
        st_slug = STATION_SLUGS.get(st_name)
        cell = (f'<a href="/stations/{st_slug}/">{esc(st_name)}</a>'
                if st_slug else esc(st_name))
        row_parts.append(f'<tr><td>{cell}</td><td>{badge(st_mins)}</td>'
                         f'<td>{"Direct" if st_direct else "Change required"}</td></tr>')
    rows = '\n'.join(row_parts)

    terminal_nav = '\n'.join(
        f'<a class="current" href="/terminals/{m2["slug"]}/">{m2["name"]}</a>' if c2 == code
        else f'<a href="/terminals/{m2["slug"]}/">{m2["name"]}</a>'
        for c2, m2 in TERMINAL_META.items())

    breadth = ("offers unusually broad commuter coverage" if count >= 45
               else "serves a focused commuter corridor")

    faqs_html = f"""<h3>What is the fastest train to London {name}?</h3>
<p>The fastest connection is from {fastest[0]}, at {fastest[1]} minutes{" on a direct service" if fastest[2] else ", with one change"}. Services into {name} are operated by {operators}.</p>
<h3>Which commuter towns are within 30 minutes of {name}?</h3>
<p>{len(under30)} stations reach {name} in under 30 minutes, including {under30_names}. These are the shortest commutes available into this terminal.</p>
<h3>How many stations connect to {name}?</h3>
<p>{count} stations have a service to London {name} within 90 minutes, and {direct_count} of those are direct trains with no change required.</p>
<h3>What areas does {name} serve?</h3>
<p>London {name} primarily serves {meta['region']}. Key commuter destinations on this network include {top5}.</p>
<h3>Is {name} a good terminal to commute into?</h3>
<p>With {count} stations inside 90 minutes and {direct_count} direct services, {name} {breadth}. The quickest option is {fastest[0]} at {fastest[1]} minutes.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Terminals", "/terminals/"),
                                  (f"{name} train times", f"/terminals/{slug}/")])),
        json.loads(faq_ld_from_html(faqs_html)),
    ], indent=0)

    body = f'''<body>
{site_header('terminals')}
{crumbs([("RailReach", "/"), ("Terminals", "/terminals/"), (f"{name} train times", None)])}
<div class="map-shell">
<div id="map" role="application" aria-label="Map of train journey times to London {name}"></div>
{legend()}
<div class="station-count" id="station-count"></div>
{PROMO}
</div><!-- /.map-shell -->

<main id="content" class="page-content">
<div class="wrap">
<h1>Train journey times to London {name}</h1>
<p class="lede">{count} stations reach London {name} within 90 minutes, {direct_count} of them on a direct train. Services are operated by {operators}. The fastest commute is from {fastest[0]} at {fastest[1]} minutes.</p>

<h2>Every station to {name}</h2>
<p class="section-note">Sorted fastest first. Times are the quickest typical weekday service.</p>
<div class="table-scroll">
<table>
<caption>Journey times from {count} stations to London {name}</caption>
<thead><tr><th>Station</th><th>Journey time</th><th>Service</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>

<h2>Frequently asked questions</h2>
{faqs_html}

<h2>Other London terminals</h2>
<p>Compare journey times into each of the nine London main line termini.</p>
<div class="terminal-nav">{terminal_nav}</div>

{DATA_NOTE}
</div>
</main>

<script type="application/ld+json">{ld}</script>

<script src="/assets/js/stations-data.js"></script>
<script src="/assets/js/map-core.js"></script>
<script>
const code='{code}';
const t=TERMINALS[code];
const map=initMap(t.lat,t.lng,8);
createTerminalMarker(map,t.lat,t.lng,'<strong>'+t.name+'</strong><br>London terminal');
let count=0;
STATIONS.forEach(s=>{{
  const j=s.journeys[code];
  if(j&&j.mins<=90){{
    createStationMarker(map,s.lat,s.lng,j.mins,'<strong>'+s.name+'</strong><br>To '+t.name+': <strong>'+j.mins+' min</strong><br>'+(j.direct?'Direct train':'Requires a change'));
    count++;
  }}
}});
document.getElementById('station-count').textContent=count+' stations within 90 min of '+t.name;
</script>
{site_footer(total)}'''

    html = head(
        title=f"London {name} Train Times &amp; Journey Map | RailReach",
        desc=f"Train journey times to London {name} from {count} stations — {top3}. Interactive map, direct and indirect routes, 2026 timetable data.",
        canonical=f"{SITE}/terminals/{slug}/",
        og_title=f"{name} Train Times | RailReach",
        og_desc=f"Journey times to London {name} from {count} stations, mapped and ranked.",
        map_h="56vh",
    ) + '\n' + body

    outdir = os.path.join(BASE, 'terminals', slug)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.html'), 'w') as f:
        f.write(html)
    return count


# ── Station pages ──────────────────────────────────────────────────────────
def generate_station_page(station_name, slug, terminals, stations, total):
    sdata = next((s for s in stations if s['name'] == station_name), None)
    if not sdata:
        print(f"  WARNING: station '{station_name}' not in data")
        return None

    sorted_journeys = sorted(sdata['journeys'].items(), key=lambda x: x[1]['mins'])
    fastest_code, fastest_j = sorted_journeys[0]
    fastest_name = TERMINAL_META[fastest_code]['name']
    n_terms = len(sorted_journeys)
    plural = 's' if n_terms > 1 else ''
    times_desc = ', '.join(f"{TERMINAL_META[c]['name']} ({j['mins']} min)" for c, j in sorted_journeys[:3])
    terminal_list = ', '.join(TERMINAL_META[c]['name'] for c, _ in sorted_journeys)
    direct_terminals = [TERMINAL_META[c]['name'] for c, j in sorted_journeys if j['direct']]
    direct_text = ', '.join(direct_terminals) if direct_terminals else 'none — all routes require a change'

    dists = sorted(
        ((s2['name'], haversine(sdata['lat'], sdata['lng'], s2['lat'], s2['lng']), s2)
         for s2 in stations if s2['name'] != station_name),
        key=lambda x: x[1])[:6]

    nearby_cards = []
    for nb_name, nb_dist, nb_data in dists:
        nb_slug = STATION_SLUGS.get(nb_name)
        meta = f'{nb_dist:.0f} km away'
        if nb_data['journeys']:
            nb_fast = min(nb_data['journeys'].values(), key=lambda j: j['mins'])
            meta = f'{badge(nb_fast["mins"])} fastest to London &middot; {nb_dist:.0f} km away'
        if nb_slug:
            nearby_cards.append(f'<li><a class="card" href="/stations/{nb_slug}/">'
                                f'<span class="card-title">{esc(nb_name)}</span>'
                                f'<span class="card-meta">{meta}</span></a></li>')
        else:
            nearby_cards.append(f'<li><span class="card"><span class="card-title">{esc(nb_name)}</span>'
                                f'<span class="card-meta">{meta}</span></span></li>')
    nearby_html = '\n'.join(nearby_cards)

    table_rows = '\n'.join(
        f'<tr><td><a href="/terminals/{TERMINAL_META[c]["slug"]}/">{TERMINAL_META[c]["name"]}</a></td>'
        f'<td>{badge(j["mins"])}</td><td>{"Direct" if j["direct"] else "Change required"}</td>'
        f'<td>{TERMINAL_META[c]["operators"]}</td></tr>'
        for c, j in sorted_journeys)

    terminal_nav = '\n'.join(f'<a href="/terminals/{m["slug"]}/">{m["name"]}</a>'
                             for m in TERMINAL_META.values())

    verdict = ("an excellent commuter base, with a sub-30-minute journey into central London"
               if fastest_j['mins'] < 30 else
               "a practical commuter choice, with the fastest journey under an hour"
               if fastest_j['mins'] < 60 else
               "a longer commute, typically traded off against more space and lower housing costs")
    simplicity = ("Direct trains keep the journey simple." if fastest_j['direct']
                  else "Most services require one change.")
    direct_answer = (f"Yes — direct services run to {direct_text}." if direct_terminals
                     else f"No direct service is recorded from {station_name}; all routes into London require one change.")

    faqs_html = f"""<h3>How long does the train from {station_name} to London take?</h3>
<p>The fastest train from {station_name} reaches London {fastest_name} in {fastest_j['mins']} minutes. {station_name} connects to {n_terms} London terminal{plural}: {terminal_list}.</p>
<h3>Which London station should I travel to from {station_name}?</h3>
<p>{fastest_name} is the quickest at {fastest_j['mins']} minutes{", on a direct service" if fastest_j['direct'] else ", though it requires a change"}. Direct trains run to {direct_text}.</p>
<h3>Is {station_name} a good commuter town for London?</h3>
<p>At {fastest_j['mins']} minutes to London {fastest_name}, {station_name} is {verdict}. {simplicity}</p>
<h3>Are there direct trains from {station_name} to London?</h3>
<p>{direct_answer}</p>
<h3>What are the nearest stations to {station_name}?</h3>
<p>The closest alternatives are {', '.join(n[0] for n in dists[:3])}. These can offer a faster or cheaper route into London depending on where you live.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Stations", "/stations/"),
                                  (f"{station_name} to London", f"/stations/{slug}/")])),
        json.loads(faq_ld_from_html(faqs_html)),
    ], indent=0)

    polylines = '\n'.join(
        "L.polyline([[{},{}],[{},{}]],{{color:getColor({}),weight:3,opacity:0.7,{}}}).addTo(map);".format(
            sdata['lat'], sdata['lng'], terminals[c]['lat'], terminals[c]['lng'], j['mins'],
            "" if j['direct'] else "dashArray:'8,6',")
        for c, j in sorted_journeys)

    term_markers = '\n'.join(
        "createTerminalMarker(map,{},{},'<strong>{}</strong><br>{} min from {}<br>{}');".format(
            terminals[c]['lat'], terminals[c]['lng'], json_esc(TERMINAL_META[c]['name']),
            j['mins'], json_esc(station_name), "Direct" if j['direct'] else "Requires a change")
        for c, j in sorted_journeys)

    # One section per route, so the page answers "<station> to <terminal>"
    # directly. Separate route pages would be near-duplicates: 345 stations
    # share only 357 journeys, so most towns serve a single terminal.
    route_parts = []
    for c, j in sorted_journeys:
        tm = TERMINAL_META[c]
        peers = sorted((s2['journeys'][c]['mins'] for s2 in stations if c in s2['journeys']))
        rank = peers.index(j['mins']) + 1
        service = ('a direct train with no change'
                   if j['direct'] else 'one change of train en route')
        route_parts.append(
            f'<h2>{station_name} to {tm["name"]}</h2>\n'
            f'<p>The fastest train from {station_name} to London {tm["name"]} takes '
            f'<strong>{j["mins"]} minutes</strong> and involves {service}. '
            f'The route is operated by {tm["operators"]}. '
            f'That makes {station_name} the {ordinal(rank)} quickest of the {len(peers)} '
            f'stations with a service into {tm["name"]} inside 90 minutes.</p>')
    route_sections = '\n'.join(route_parts)

    this_station_legend = ('<div class="legend-item"><div class="legend-dot" '
                           'style="background:#3b82f6"></div> This station</div>\n')

    body = f'''<body>
{site_header('stations')}
{crumbs([("RailReach", "/"), ("Stations", "/stations/"), (f"{station_name} to London", None)])}
<div class="map-shell">
<div id="map" role="application" aria-label="Map of train routes from {station_name} to London"></div>
{legend(this_station_legend)}
<div class="station-count" id="station-count"></div>
{PROMO}
</div><!-- /.map-shell -->

<main id="content" class="page-content">
<div class="wrap">
<h1>Train times from {station_name} to London</h1>
<p class="lede">{station_name} connects to {n_terms} London terminal{plural}. The fastest route is {fastest_name} in {fastest_j['mins']} minutes{" on a direct train" if fastest_j['direct'] else ", with one change"}.</p>

<h2>{station_name} to each London terminal</h2>
<div class="table-scroll">
<table>
<caption>Journey times from {station_name} to London terminals</caption>
<thead><tr><th>London terminal</th><th>Journey time</th><th>Service</th><th>Operator</th></tr></thead>
<tbody>
{table_rows}
</tbody>
</table>
</div>

{route_sections}
<h2>Frequently asked questions</h2>
{faqs_html}

<h2>Nearby stations</h2>
<p>Alternative departure points close to {station_name}.</p>
<ul class="link-grid">
{nearby_html}
</ul>

<h2>All London terminals</h2>
<div class="terminal-nav">{terminal_nav}</div>

{DATA_NOTE}
</div>
</main>

<script type="application/ld+json">{ld}</script>

<script src="/assets/js/stations-data.js"></script>
<script src="/assets/js/map-core.js"></script>
<script>
const map=initMap({sdata['lat']},{sdata['lng']},9);
L.circleMarker([{sdata['lat']},{sdata['lng']}],{{radius:12,fillColor:'#3b82f6',color:'#fff',weight:3,opacity:1,fillOpacity:0.9}}).bindPopup('<strong>{json_esc(station_name)}</strong>').addTo(map);
{term_markers}
{polylines}
document.getElementById('station-count').textContent='{json_esc(station_name)} — {n_terms} London terminal{plural}';
</script>
{site_footer(total)}'''

    html = head(
        title=f"{station_name} to London Train Times | RailReach",
        desc=f"Train times from {station_name} to London — {times_desc}. Direct and indirect routes compared on an interactive map. 2026 timetable data.",
        canonical=f"{SITE}/stations/{slug}/",
        og_title=f"{station_name} to London Train Times | RailReach",
        og_desc=f"Journey times from {station_name} to London terminals. {fastest_name} in {fastest_j['mins']} min.",
        map_h="56vh",
    ) + '\n' + body

    outdir = os.path.join(BASE, 'stations', slug)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.html'), 'w') as f:
        f.write(html)
    return fastest_j['mins'], fastest_name


# ── Hub pages ──────────────────────────────────────────────────────────────
def generate_terminal_hub(stations, counts, total):
    cards, rows = [], []
    for code, meta in TERMINAL_META.items():
        serving = sorted(
            ((s['name'], s['journeys'][code]['mins'])
             for s in stations if code in s['journeys'] and s['journeys'][code]['mins'] <= 90),
            key=lambda x: x[1])
        fastest = serving[0] if serving else ('—', 0)
        under30 = sum(1 for _, m in serving if m < 30)
        cards.append(
            f'<li><a class="card" href="/terminals/{meta["slug"]}/">'
            f'<span class="card-title">{meta["name"]}</span>'
            f'<span class="card-meta">{counts[code]} stations within 90 min &middot; {under30} under 30 min<br>'
            f'{meta["operators"]}</span></a></li>')
        rows.append(
            f'<tr><td><a href="/terminals/{meta["slug"]}/">{meta["name"]}</a></td>'
            f'<td>{counts[code]}</td><td>{under30}</td>'
            f'<td>{esc(fastest[0])} {badge(fastest[1])}</td><td>{meta["operators"]}</td></tr>')

    faqs_html = f"""<h3>How many main line terminals does London have?</h3>
<p>London has nine main line railway terminals: {', '.join(m['name'] for m in TERMINAL_META.values())}. Each serves a different part of the country, and most commuter towns are tied to just one or two of them.</p>
<h3>Which London terminal has the most commuter stations?</h3>
<p>Waterloo has the widest commuter catchment, with {counts['WAT']} stations reaching it within 90 minutes, followed by Victoria ({counts['VIC']}) and Kings Cross ({counts['KGX']}).</p>
<h3>Which London terminal should I commute into?</h3>
<p>That is usually decided by where you live rather than by preference — each town sits on a line into one or two specific terminals. The table above shows the catchment of each, and every terminal page lists its stations in full.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Terminals", "/terminals/")])),
        json.loads(faq_ld_from_html(faqs_html)),
        {"@context": "https://schema.org", "@type": "ItemList",
         "name": "London main line rail terminals",
         "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "name": m['name'],
              "url": f"{SITE}/terminals/{m['slug']}/"}
             for i, m in enumerate(TERMINAL_META.values())]},
    ], indent=0)

    html = head(
        title="London Rail Terminals | Train Times to All 9 London Termini | RailReach",
        desc="Compare all 9 London main line terminals — how many stations reach each within 90 minutes, which operators run them, and the fastest commute into every terminus.",
        canonical=f"{SITE}/terminals/",
        og_title="London Rail Terminals | RailReach",
        og_desc="All 9 London main line terminals compared by commuter catchment.",
        leaflet=False,
    ) + f'''
<body>
{site_header('terminals')}
{crumbs([("RailReach", "/"), ("Terminals", None)])}
<main id="content" class="page-content">
<div class="wrap">
<h1>London main line rail terminals</h1>
<p class="lede">London has nine main line terminals, each serving a different slice of the country. Together they connect {total} stations to the capital within 90 minutes.</p>

<h2>All nine terminals</h2>
<ul class="link-grid">
{chr(10).join(cards)}
</ul>

<h2>Commuter catchment compared</h2>
<div class="table-scroll">
<table>
<caption>London terminals ranked by the number of stations within 90 minutes</caption>
<thead><tr><th>Terminal</th><th>Stations within 90 min</th><th>Under 30 min</th><th>Fastest station</th><th>Operators</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>

<h2>Frequently asked questions</h2>
{faqs_html}

{DATA_NOTE}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'terminals')
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.html'), 'w') as f:
        f.write(html)
    print("  wrote terminals/index.html")


def generate_station_hub(page_info, total):
    """page_info: {station_name: (fastest_mins, fastest_terminal)}"""
    ordered = sorted(page_info.items(), key=lambda kv: kv[1][0])
    featured = sorted(((n, v) for n, v in page_info.items() if n in FEATURED),
                      key=lambda kv: kv[1][0])
    cards = '\n'.join(
        f'<li><a class="card" href="/stations/{STATION_SLUGS[name]}/">'
        f'<span class="card-title">{esc(short_name(name))}</span>'
        f'<span class="card-meta">{badge(mins)} to {term}</span></a></li>'
        for name, (mins, term) in featured)

    rows = '\n'.join(
        f'<tr><td><a href="/stations/{STATION_SLUGS[name]}/">{esc(name)}</a></td>'
        f'<td>{badge(mins)}</td><td>{term}</td></tr>'
        for name, (mins, term) in ordered)

    fastest = ordered[0]
    under30 = [n for n, (m, _) in ordered if m < 30]

    faqs_html = f"""<h3>Which commuter towns are closest to London by train?</h3>
<p>Of the towns with a full RailReach guide, {len(under30)} are within 30 minutes of a London terminal: {', '.join(under30)}. The quickest is {fastest[0]} at {fastest[1][0]} minutes into {fastest[1][1]}.</p>
<h3>How do I compare two commuter towns?</h3>
<p>Each station page lists every London terminal that town can reach, the journey time, whether the train is direct, and the operator — so two towns can be compared on identical measures.</p>
<h3>Does RailReach cover every UK station?</h3>
<p>RailReach covers the {total} stations that reach a London main line terminal within 90 minutes — every one has its own journey guide. Stations beyond that threshold are outside a practical daily commute and are not included.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Stations", "/stations/")])),
        json.loads(faq_ld_from_html(faqs_html)),
        {"@context": "https://schema.org", "@type": "ItemList",
         "name": "London commuter station guides",
         "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "name": name,
              "url": f"{SITE}/stations/{STATION_SLUGS[name]}/"}
             for i, (name, _) in enumerate(ordered)]},
    ], indent=0)

    html = head(
        title="Commuter Stations to London | Journey Times by Town | RailReach",
        desc=f"Every one of {len(ordered)} stations within 90 minutes of London, ranked by journey time — fastest terminal, direct services and nearby alternatives.",
        canonical=f"{SITE}/stations/",
        og_title="Commuter Stations to London | RailReach",
        og_desc="London commuter towns ranked by fastest train journey time.",
        leaflet=False,
    ) + f'''
<body>
{site_header('stations')}
{crumbs([("RailReach", "/"), ("Stations", None)])}
<main id="content" class="page-content">
<div class="wrap">
<h1>London commuter stations</h1>
<p class="lede">A journey guide for every one of the {len(ordered)} stations that reach a London terminal within 90 minutes, ranked by fastest route. The <a href="/">interactive map</a> shows the same data geographically.</p>

<h2>Popular commuter towns</h2>
<p>The most searched destinations, ranked by fastest journey into London.</p>
<ul class="link-grid">
{cards}
</ul>

<h2>Every station, ranked</h2>
<p class="section-note">All {len(ordered)} stations with a journey into London under 90 minutes.</p>
<div class="table-scroll">
<table>
<caption>Commuter towns ranked by fastest journey into London</caption>
<thead><tr><th>Station</th><th>Fastest journey</th><th>To terminal</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>

<h2>Frequently asked questions</h2>
{faqs_html}

{DATA_NOTE}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'stations')
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.html'), 'w') as f:
        f.write(html)
    print("  wrote stations/index.html")


def generate_about(stations, counts, total, n_station_pages):
    op_list = sorted({o.strip() for m in TERMINAL_META.values() for o in m['operators'].split(',')})
    pairs = sum(len(s['journeys']) for s in stations)
    direct = sum(1 for s in stations for j in s['journeys'].values() if j['direct'])

    faqs_html = f"""<h3>Where does RailReach get its journey times?</h3>
<p>Times are compiled from published National Rail operator timetables for 2026, covering {', '.join(op_list[:6])} and others. Each figure is the fastest typical weekday service on that route.</p>
<h3>Are these live train times?</h3>
<p>No. RailReach is a planning tool, not a live departure board. Times do not account for engineering works, strikes or day-to-day disruption. Check National Rail or your operator before travelling.</p>
<h3>What does "fastest typical weekday service" mean?</h3>
<p>The quickest journey a commuter could reasonably expect on a normal weekday, rather than a one-off record time or an average across all services. Off-peak and weekend journeys are often slower.</p>
<h3>What counts as a direct train?</h3>
<p>A service running from the origin station to the London terminal without requiring the passenger to change trains. Where a change is needed, the time includes a realistic interchange allowance and the route is marked accordingly.</p>
<h3>Why is the cut-off 90 minutes?</h3>
<p>Ninety minutes each way is the practical outer limit of a daily commute for most people. Stations beyond that threshold are excluded from the dataset.</p>
<h3>Can I reuse this data?</h3>
<p>Yes. The journey time dataset is published under a Creative Commons Attribution 4.0 licence — please credit RailReach and link back to this site.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("About the data", "/about/")])),
        json.loads(faq_ld_from_html(faqs_html)),
        {"@context": "https://schema.org", "@type": "Dataset",
         "name": "UK Train Journey Times to London Terminals 2026",
         "description": f"Journey times from {total} UK stations to 9 London main line terminals, based on published 2026 National Rail operator timetables.",
         "url": f"{SITE}/about/",
         "license": "https://creativecommons.org/licenses/by/4.0/",
         "creator": {"@type": "Organization", "name": "RailReach", "url": SITE + "/"},
         "temporalCoverage": "2026",
         "dateModified": BUILD_DATE,
         "spatialCoverage": {"@type": "Place", "name": "England and Wales"},
         "variableMeasured": [
             {"@type": "PropertyValue", "name": "Journey time", "unitText": "minutes"},
             {"@type": "PropertyValue", "name": "Direct service",
              "description": "Whether the journey is a direct train or requires a change"},
         ]},
    ], indent=0)

    rows = '\n'.join(
        f'<tr><td>{TERMINAL_META[c]["name"]}</td><td>{counts[c]}</td><td>{TERMINAL_META[c]["operators"]}</td></tr>'
        for c in TERMINAL_META)

    html = head(
        title="About the Data | Methodology &amp; Sources | RailReach",
        desc="How RailReach journey times are compiled: sources, the 90-minute threshold, what counts as a direct train, known limitations and licensing.",
        canonical=f"{SITE}/about/",
        og_title="About the RailReach Data | Methodology",
        og_desc="Sources, methodology and limitations behind RailReach journey times.",
        leaflet=False,
    ) + f'''
<body>
{site_header('about')}
{crumbs([("RailReach", "/"), ("About the data", None)])}
<main id="content" class="page-content">
<div class="wrap">
<h1>About the data</h1>
<p class="lede">RailReach publishes train journey times from {total} stations to all 9 London main line terminals — {pairs} station-to-terminal journeys in total, {direct} of them direct. This page explains where those numbers come from, and where they should not be relied on.</p>

<h2>What RailReach is</h2>
<p>RailReach is a free planning tool for anyone weighing up where to live against how long they will spend on a train. It is built for homebuyers, renters, relocators and daily commuters who need to compare towns on a like-for-like basis, rather than check a specific departure.</p>
<p>Every station within 90 minutes of a London terminal is plotted on one interactive map and colour-coded by journey time, so the commuter belt can be read at a glance. There is no registration and no paywall.</p>

<h2>Sources and method</h2>
<p>Journey times are compiled from published National Rail operator timetables for 2026. The operators covered are {', '.join(op_list)}.</p>
<p>Each figure is the <strong>fastest typical weekday service</strong> on that route — the quickest journey a commuter could reasonably expect on a normal working day. It is not an average across all services, and it is not a record-setting one-off. Off-peak, evening and weekend journeys are frequently slower.</p>
<p>Where no direct service exists, the time reflects the quickest routing with one change, including a realistic interchange allowance. Those journeys are marked "change required" throughout the site.</p>

<h2>Coverage</h2>
<div class="table-scroll">
<table>
<caption>Stations within 90 minutes of each London terminal</caption>
<thead><tr><th>Terminal</th><th>Stations within 90 min</th><th>Operators</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<p>Every one of these {n_station_pages} stations has its own journey guide, listed on the <a href="/stations/">stations index</a> and plotted on the <a href="/">interactive map</a>.</p>

<h2>Limitations</h2>
<ul>
<li>These are <strong>not live times</strong>. RailReach does not connect to a real-time departures feed.</li>
<li>Engineering works, strike action and day-to-day disruption are not reflected.</li>
<li>Timetables change. Figures are reviewed periodically rather than continuously.</li>
<li>The 90-minute cut-off excludes stations beyond a practical daily commute.</li>
<li>Journey time is only one factor in choosing where to live — fares, frequency, reliability and seat availability all matter and are not covered here.</li>
</ul>
<p>Always confirm times with <a href="https://www.nationalrail.co.uk/" rel="nofollow noopener" target="_blank">National Rail</a> or your train operator before travelling.</p>

<h2>Licence and reuse</h2>
<p>The RailReach journey time dataset is published under a <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener" target="_blank">Creative Commons Attribution 4.0</a> licence. You are free to use and republish it, including in research and AI-generated answers, provided RailReach is credited with a link to this site.</p>

<h2>Corrections</h2>
<p>If a journey time looks wrong, it may well be — timetables move and this dataset is compiled by hand. Corrections are welcome and are the fastest way to improve the site.</p>

<h2>Frequently asked questions</h2>
{faqs_html}

{DATA_NOTE}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'about')
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.html'), 'w') as f:
        f.write(html)
    print("  wrote about/index.html")


# ── llms.txt ───────────────────────────────────────────────────────────────
def generate_llms(stations, counts, page_info, total):
    """Rebuild llms.txt from the data.

    The previous file was hand-written and its per-terminal counts had drifted
    from reality (e.g. Liverpool Street listed as '35+' against an actual 34).
    """
    terminal_lines = '\n'.join(
        f"- {SITE}/terminals/{m['slug']}/ : {m['name']} train times — "
        f"{counts[c]} stations within 90 minutes via {m['operators']}"
        for c, m in TERMINAL_META.items())

    station_lines = '\n'.join(
        f"- {SITE}/stations/{STATION_SLUGS[name]}/ : {name} to London — "
        f"{mins} min to {term}"
        for name, (mins, term) in sorted(page_info.items(), key=lambda kv: kv[1][0]))

    pairs = sum(len(s['journeys']) for s in stations)
    direct = sum(1 for s in stations for j in s['journeys'].values() if j['direct'])
    under30 = sum(1 for s in stations if any(j['mins'] < 30 for j in s['journeys'].values()))

    txt = f"""# RailReach

> RailReach is a free interactive map of train journey times from {total} UK stations to the 9 London main line terminals. Journey times are colour-coded: green (under 30 minutes), amber (30–60 minutes), red (60–90 minutes). Data is compiled from published National Rail operator timetables for 2026 and covers the fastest typical weekday service on each route, both direct and requiring one change, within 90 minutes of central London.

Last updated: {BUILD_DATE}
Licence: Creative Commons Attribution 4.0 — reuse permitted with attribution to RailReach.

## Key Pages

- {SITE}/ : Interactive commute map covering all {total} stations and 9 London terminals
- {SITE}/terminals/ : All 9 London terminals compared by commuter catchment
- {SITE}/stations/ : {len(page_info)} commuter towns ranked by fastest journey into London
- {SITE}/about/ : Methodology, sources, limitations and licensing

## Terminal Pages

{terminal_lines}

## Station Pages

{station_lines}

## Data Summary

- {total} stations covered, all within 90 minutes of a London terminal
- 9 London main line terminals
- {pairs} station-to-terminal journeys recorded, {direct} of them direct services
- {under30} stations reach a London terminal in under 30 minutes
- Times are the fastest typical weekday service, not live departures, and exclude engineering works and disruption
- Colour coding: green (<30 min), amber (30–60 min), red (60–90 min)

## Citation

When citing RailReach journey times, please attribute to RailReach ({SITE}) and note the 2026 timetable basis and the {BUILD_DATE} review date.
"""
    with open(os.path.join(BASE, 'llms.txt'), 'w') as f:
        f.write(txt)
    print(f"  wrote llms.txt ({len(TERMINAL_META)} terminals, {len(page_info)} stations)")


# ── Service worker ─────────────────────────────────────────────────────────
def generate_sw():
    """Stamp the SW cache name with a content hash.

    The previous worker used a fixed 'railreach-v1' cache and served every
    asset cache-first, so returning visitors kept stale CSS/JS indefinitely.
    Hashing the assets means each build gets its own cache and old ones are
    dropped on activate.
    """
    import hashlib
    h = hashlib.sha256()
    for rel in ('assets/css/shared.css', 'assets/js/stations-data.js', 'assets/js/map-core.js'):
        with open(os.path.join(BASE, rel), 'rb') as f:
            h.update(f.read())
    version = h.hexdigest()[:10]

    sw = f'''// RailReach Service Worker — cache name is stamped per build by _build/generate-pages.py
const CACHE_NAME = 'railreach-{version}';
const PRECACHE = [
  '/',
  '/assets/css/shared.css',
  '/assets/js/stations-data.js',
  '/assets/js/map-core.js',
  '/favicon.svg',
  '/manifest.json'
];

self.addEventListener('install', e => {{
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
}});

self.addEventListener('activate', e => {{
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener('fetch', e => {{
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  // Map tiles: cache-first, they never change
  if (url.hostname.endsWith('tile.openstreetmap.org')) {{
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(resp => {{
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return resp;
      }}))
    );
    return;
  }}

  // Leave third-party requests (fonts, unpkg, analytics) to the browser
  if (url.origin !== self.location.origin) return;

  // HTML: network-first so content updates land immediately
  if (e.request.destination === 'document') {{
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request).then(r => r || caches.match('/')))
    );
    return;
  }}

  // Own assets: stale-while-revalidate — fast, but never stale for more than one visit
  e.respondWith(
    caches.match(e.request).then(cached => {{
      const network = fetch(e.request).then(resp => {{
        if (resp && resp.ok) {{
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }}
        return resp;
      }}).catch(() => cached);
      return cached || network;
    }})
  );
}});
'''
    with open(os.path.join(BASE, 'sw.js'), 'w') as f:
        f.write(sw)
    print(f"  wrote sw.js (cache railreach-{version})")


# ── Sitemap ────────────────────────────────────────────────────────────────
def generate_sitemap():
    urls = [("/", "weekly", "1.0"), ("/terminals/", "monthly", "0.9"),
            ("/stations/", "monthly", "0.9"), ("/about/", "yearly", "0.5")]
    urls += [(f"/terminals/{m['slug']}/", "monthly", "0.8") for m in TERMINAL_META.values()]
    urls += [(f"/stations/{s}/", "monthly", "0.7") for s in STATION_SLUGS.values()]

    body = '\n'.join(
        f'  <url><loc>{SITE}{path}</loc><lastmod>{BUILD_DATE}</lastmod>'
        f'<changefreq>{freq}</changefreq><priority>{pri}</priority></url>'
        for path, freq, pri in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f'{body}\n</urlset>\n')
    with open(os.path.join(BASE, 'sitemap.xml'), 'w') as f:
        f.write(xml)
    print(f"  wrote sitemap.xml ({len(urls)} URLs, lastmod {BUILD_DATE})")


# ── index.html sync ────────────────────────────────────────────────────────
def sync_index(terminals, stations, counts, total, data_js):
    """Rewrite the generated regions of index.html from the dataset."""
    path = os.path.join(BASE, 'index.html')
    with open(path) as f:
        html = f.read()

    lede = (f'<p class="lede">RailReach maps the fastest weekday train journey from '
            f'<strong>{total} stations</strong> to all <strong>9 London main line terminals</strong> '
            f'— every station within 90 minutes of central London, colour-coded by journey time. '
            f'Free to use, no sign-up.</p>')

    terminal_cards = '<ul class="link-grid">\n' + '\n'.join(
        f'<li><a class="card" href="/terminals/{m["slug"]}/">'
        f'<span class="card-title">{m["name"]}</span>'
        f'<span class="card-meta">{counts[c]} stations within 90 min<br>{m["operators"]}</span></a></li>'
        for c, m in TERMINAL_META.items()) + '\n</ul>'

    by_name = {s['name']: s for s in stations}
    featured = []
    for name in FEATURED:
        s = by_name.get(name)
        if not s:
            continue
        code, j = min(s['journeys'].items(), key=lambda kv: kv[1]['mins'])
        featured.append((name, s['slug'], j['mins'], TERMINAL_META[code]['name']))
    featured.sort(key=lambda x: x[2])

    station_cards = '<ul class="link-grid">\n' + '\n'.join(
        f'<li><a class="card" href="/stations/{slug}/">'
        f'<span class="card-title">{esc(short_name(name))}</span>'
        f'<span class="card-meta">{badge(mins)} to {term}</span></a></li>'
        for name, slug, mins, term in featured) + '\n</ul>'

    # Full data table, grouped by terminal, every station linked to its page
    sections = []
    for code, m in TERMINAL_META.items():
        rows = sorted(((s['name'], s['slug'], s['journeys'][code])
                       for s in stations if code in s['journeys']),
                      key=lambda x: x[2]['mins'])
        body = '\n'.join(
            f'<tr><td><a href="/stations/{slug}/">{esc(nm)}</a></td><td>{m["name"]}</td>'
            f'<td>{badge(j["mins"])}</td><td>{"Yes" if j["direct"] else "No"}</td></tr>'
            for nm, slug, j in rows)
        sections.append(
            f'<thead><tr><th colspan="4">{m["name"]}</th></tr></thead>\n'
            f'<thead><tr><th>Station</th><th>Terminal</th><th>Journey time</th><th>Direct</th></tr></thead>\n'
            f'<tbody>\n{body}\n</tbody>')

    table = ('<div class="table-scroll">\n<table>\n'
             '<caption>Train journey times from all stations to London terminals</caption>\n'
             + '\n'.join(sections) + '\n</table>\n</div>')

    html = replace_marked(html, 'lede', lede)
    html = replace_marked(html, 'terminal-cards', terminal_cards)
    html = replace_marked(html, 'station-cards', station_cards)
    html = replace_marked(html, 'data-table', table)
    html = replace_marked(html, 'map-data', data_js, comment='js')

    with open(path, 'w') as f:
        f.write(html)
    print(f"  synced index.html ({len(featured)} featured, {total} rows in data table)")


def short_name(name):
    """Trim station suffixes that add nothing in a card title."""
    for suffix in (' Central', ' City', ' Junction', ' (Main)'):
        if name.endswith(suffix) and name not in ('Milton Keynes Central',):
            return name[: -len(suffix)]
    return name.replace('Milton Keynes Central', 'Milton Keynes')


# ── Dataset exports ────────────────────────────────────────────────────────
def export_dataset(terminals, stations):
    """Publish the dataset as citable CSV and JSON downloads."""
    import csv
    outdir = os.path.join(BASE, 'data')
    os.makedirs(outdir, exist_ok=True)

    rows = []
    for s in stations:
        for code, j in sorted(s['journeys'].items(), key=lambda kv: kv[1]['mins']):
            rows.append({
                'station': s['name'],
                'station_slug': s['slug'],
                'latitude': s['lat'],
                'longitude': s['lng'],
                'london_terminal': TERMINAL_META[code]['name'],
                'terminal_code': code,
                'fastest_minutes': j['mins'],
                'direct': 'yes' if j['direct'] else 'no',
                'operators': TERMINAL_META[code]['operators'],
            })
    rows.sort(key=lambda r: (r['london_terminal'], r['fastest_minutes']))

    csv_path = os.path.join(outdir, 'journey-times.csv')
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    json_path = os.path.join(outdir, 'journey-times.json')
    with open(json_path, 'w') as f:
        json.dump({
            'name': 'UK train journey times to London terminals',
            'source': 'National Rail operator timetables, 2026',
            'basis': 'fastest typical weekday service',
            'maxMinutes': 90,
            'lastReviewed': BUILD_DATE,
            'licence': 'CC BY 4.0',
            'attribution': f'RailReach ({SITE}/)',
            'terminals': {c: {**terminals[c], 'slug': TERMINAL_META[c]['slug'],
                              'operators': TERMINAL_META[c]['operators']}
                          for c in TERMINAL_META},
            'journeys': rows,
        }, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print(f"  wrote data/journey-times.csv and .json ({len(rows)} journeys)")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print("Loading dataset...")
    terminals, stations = load_data()
    STATION_SLUGS.update({s['name']: s['slug'] for s in stations})
    total = len(stations)
    counts = {c: sum(1 for s in stations if c in s['journeys'] and s['journeys'][c]['mins'] <= 90)
              for c in TERMINAL_META}
    print(f"  {total} stations, {len(terminals)} terminals, "
          f"{sum(len(s['journeys']) for s in stations)} journeys")

    print("\nSyncing index.html and shared assets from the dataset...")
    data_js = js_data_block(terminals, stations)
    sync_index(terminals, stations, counts, total, data_js)
    write_shared_js(data_js)

    print("\nTerminal pages...")
    for code in TERMINAL_META:
        n = generate_terminal_page(code, terminals, stations, total)
        print(f"  {TERMINAL_META[code]['name']:<18} {n} stations")

    print("\nStation pages...")
    page_info = {}
    for s in stations:
        res = generate_station_page(s['name'], s['slug'], terminals, stations, total)
        if res:
            page_info[s['name']] = res
    print(f"  {len(page_info)} station pages")

    print("\nHub and about pages...")
    generate_terminal_hub(stations, counts, total)
    generate_station_hub(page_info, total)
    generate_about(stations, counts, total, len(page_info))

    print("\nService worker, sitemap, llms.txt and dataset exports...")
    generate_sw()
    generate_sitemap()
    generate_llms(stations, counts, page_info, total)
    export_dataset(terminals, stations)

    print(f"\nDone — {9 + len(page_info) + 3} pages generated.")


if __name__ == '__main__':
    main()
