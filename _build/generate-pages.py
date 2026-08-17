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
import hashlib
import urllib.parse
import math
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://railreach.co.uk"

# BUILD_DATE is when the pages were last generated. It is the right value for
# sitemap lastmod, which describes when the page changed.
BUILD_DATE = datetime.date.today().isoformat()

# REVIEW_DATE is when the journey times were last checked against timetables.
# It must NOT track the build: a CSS or copy change would otherwise claim a data
# review that never happened. Loaded from stations.json in main(); bump it there
# only when the data has actually been verified.
REVIEW_DATE = BUILD_DATE
GEO_SOURCE = 'unspecified'
GEO_UPDATED = 'unknown'
SOURCE_LABEL = ''
BASIS_LABEL = ''
METHOD_LABEL = ''

# ── Terminal metadata ──────────────────────────────────────────────────────
TERMINAL_META = {
    'KGX': {'slug': 'kings-cross', 'name': 'Kings Cross', 'operators': 'Great Northern, LNER, Hull Trains, Lumo',
            'region': 'Hertfordshire, Cambridgeshire and the East Coast Main Line'},
    'STP': {'slug': 'st-pancras', 'name': 'St Pancras', 'operators': 'Thameslink, East Midlands Railway, Southeastern high speed',
            'region': 'Bedfordshire, the Midlands and, via HS1, the Medway towns'},
    'WAT': {'slug': 'waterloo', 'name': 'Waterloo', 'operators': 'South Western Railway',
            'region': 'Surrey, Hampshire and the South West'},
    'PAD': {'slug': 'paddington', 'name': 'Paddington', 'operators': 'Great Western Railway, Elizabeth line',
            'region': 'the Thames Valley and the West'},
    'LBG': {'slug': 'london-bridge', 'name': 'London Bridge', 'operators': 'Southeastern, Southern, Thameslink',
            'region': 'South East London, Kent and Surrey'},
    'VIC': {'slug': 'victoria', 'name': 'Victoria', 'operators': 'Southeastern, Southern',
            'region': 'Kent, Sussex and the South Coast'},
    'LST': {'slug': 'liverpool-street', 'name': 'Liverpool Street', 'operators': 'Greater Anglia, Elizabeth line',
            'region': 'Essex, Hertfordshire and East Anglia'},
    'EUS': {'slug': 'euston', 'name': 'Euston', 'operators': 'Avanti West Coast, London Northwestern',
            'region': 'the West Coast Main Line, Buckinghamshire and the Midlands'},
    'MYB': {'slug': 'marylebone', 'name': 'Marylebone', 'operators': 'Chiltern Railways',
            'region': 'the Chilterns, Buckinghamshire and Oxfordshire'},
    'FST': {'slug': 'fenchurch-street', 'name': 'Fenchurch Street', 'operators': 'c2c',
            'region': 'East London and South Essex'},
    'MOG': {'slug': 'moorgate', 'name': 'Moorgate', 'operators': 'Great Northern',
            'region': 'the City, and the Hertford loop and Welwyn inner suburbs'},
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



def fastest(j):
    """The fastest time, or None where no direct service exists."""
    return j.get('mins')


def has_time(j):
    return j.get('mins') is not None


def sorted_journeys_fn(journeys):
    """Journeys fastest first, with change-required ones last."""
    return sorted(journeys.items(),
                  key=lambda kv: (kv[1].get('mins') is None, kv[1].get('mins') or 0))


def time_cell(j):
    """A journey time for a table cell, or an honest note when there is none."""
    if not has_time(j):
        return '<span class="t-badge t-change">Change required</span>'
    cell = badge(j['mins'])
    if not j.get('direct') and j.get('changeAt'):
        cell += f'<span class="t-via">change at {esc(j["changeAt"])}</span>'
    return cell


def md_direct(j):
    """The fastest-direct column, in markdown."""
    if j.get('direct') and has_time(j):
        return 'same as fastest'
    d = j.get('directMins')
    return f'{d} min' if d is not None else 'no direct service'


def direct_cell(j):
    """The quickest service that does not require changing.

    Blank rather than repeated when the fastest journey is already direct: the
    same number twice in adjacent columns reads as an error.
    """
    if j.get('direct') and has_time(j):
        return '<span class="muted">same as fastest</span>'
    d = j.get('directMins')
    if d is None:
        return '<span class="muted">no direct service</span>'
    return f'{d} min'


def no_direct(j):
    """Reachable, but only by changing."""
    return has_time(j) and j.get('directMins') is None


def typical_cell(j):
    t = j.get('typicalPeakMins')
    if t is None:
        # Peak figures are measured on direct services. Printing "no peak
        # service" for a station that has no direct service at all reads as
        # "you cannot do this in the peak", which is not what we know: we have
        # not measured connections in the peak.
        if no_direct(j):
            return '<span class="muted">direct trains only</span>'
        return '<span class="muted">no peak service</span>'
    gap = t - j['mins']
    cls = ' class="gap-wide"' if gap >= 10 else ''
    return f'<span{cls}>{t} min</span>'


def frequency_cell(j):
    f = j.get('peakTrainsPerHour')
    if f:
        return f'{f}/hr'
    return ('<span class="muted">direct trains only</span>' if no_direct(j)
            else '<span class="muted">&ndash;</span>')


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



# ── GEO helpers ────────────────────────────────────────────────────────────
def key_facts(pairs):
    """A compact, dated fact block.

    Language models quote short attributable statements far more readily than
    prose, so the headline numbers are stated once, plainly, with a date.
    """
    rows = '\n'.join(f'<div class="fact"><dt>{k}</dt><dd>{v}</dd></div>' for k, v in pairs)
    return (f'<dl class="key-facts">\n{rows}\n'
            f'<div class="fact"><dt>Data reviewed</dt><dd>{REVIEW_DATE}</dd></div>\n</dl>')


def train_station_ld(name, lat, lng, description, url):
    return {
        "@context": "https://schema.org",
        "@type": "TrainStation",
        "name": name,
        "description": description,
        "url": url,
        "geo": {"@type": "GeoCoordinates", "latitude": lat, "longitude": lng},
        "containedInPlace": {"@type": "Country", "name": "United Kingdom"},
    }


def webpage_ld(name, description, url, about_name):
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "description": description,
        "url": url,
        "inLanguage": "en-GB",
        "dateModified": REVIEW_DATE,
        "isPartOf": {"@type": "WebSite", "name": "RailReach", "url": SITE + "/"},
        "about": {"@type": "Thing", "name": about_name},
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "isAccessibleForFree": True,
    }


def write_markdown(rel_dir, text):
    """Plain-text alternate.

    Files without YAML front matter are copied verbatim by Jekyll, so these
    are served as-is rather than rendered into HTML.
    """
    outdir = os.path.join(BASE, rel_dir)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'index.md'), 'w') as f:
        f.write(text)


# ── Shared chrome ──────────────────────────────────────────────────────────
def head(title, desc, canonical, og_title, og_desc, map_h=None, leaflet=True, md=True):
    mapvar = f'\n<style>:root {{ --map-h: {map_h}; }}</style>' if map_h else ''
    md_tag = (f'\n<link rel="alternate" type="text/markdown" href="{canonical}index.md">'
              if md else '')
    leaflet_tags = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">\n'
                    '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n') if leaflet else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">{md_tag}
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
    # Okabe-Ito. The old green/amber/red collapsed under deuteranopia (green vs
    # red: RGB distance 244 normal, 44 simulated). This set tests at 69 worst
    # case across deuteranopia, protanopia and tritanopia.
    return f'''<div class="legend">
<p class="legend-title">Journey Time</p>
<div class="legend-item"><div class="legend-dot" style="background:#0072B2"></div> <span class="legend-long">Under 30 min</span><span class="legend-short">&lt;30</span></div>
<div class="legend-item"><div class="legend-dot" style="background:#E69F00"></div> <span class="legend-long">30 to 60 min</span><span class="legend-short">30–60</span></div>
<div class="legend-item"><div class="legend-dot" style="background:#D55E00"></div> <span class="legend-long">60 to 90 min</span><span class="legend-short">60–90</span></div>
{extra}<div class="legend-item"><div class="legend-dot" style="background:#111827"></div> <span class="legend-long">London Terminal</span><span class="legend-short">Terminal</span></div>
</div>'''


# The banner at the foot of the map is data, not markup buried in this file.
# _build/data/promos.json holds every banner that has run, exactly one marked
# active, so retiring an advertiser preserves their copy and styling and
# reinstating one is a two-boolean change rather than an exercise in reading
# git history.
PROMOS_PATH = os.path.join(BASE, '_build', 'data', 'promos.json')


def build_promo():
    with open(PROMOS_PATH) as f:
        promos = json.load(f)['promos']
    live = [p for p in promos if p.get('active')]
    if len(live) != 1:
        raise SystemExit(
            "ERROR: {} has {} active promos, expected exactly 1. Refusing to "
            "guess which banner should be published.".format(PROMOS_PATH, len(live)))
    p = live[0]

    if p['variant'] == 'promo-jmi':
        r = p['rating']
        inner = (
            '<div class="promo-brand">\n'
            '<img class="promo-mark" src="{}" alt="{}" width="115" height="23" loading="lazy">\n'
            '<div class="promo-trust"><img class="promo-stars" src="{}" alt="" '
            'width="108" height="20" loading="lazy">'
            '<span class="sr-only">{}</span>'
            '<span class="promo-tp-name" aria-hidden="true">{}</span></div>\n'
            '</div>\n'
            '<div class="promo-body">\n'
            '<div class="promo-headline">{}<span>{}</span>{}</div>\n'
            '<div class="promo-sub">{}</div>\n'
            '</div>\n'
            '<div class="promo-cta">{}</div>'
        ).format(p['wordmark'], esc(p['wordmarkAlt']), r['image'], esc(r['spokenAs']),
                 esc(r['source']), esc(p['headline']), esc(p['headlineEmphasis']),
                 esc(p['headlineTail']), esc(p['sub']), esc(p['cta']))
    else:
        inner = (
            '<div class="promo-logo">{}<span>{}</span></div>\n'
            '<div class="promo-body">\n'
            '<div class="promo-headline">{}</div>\n'
            '<div class="promo-sub">{}</div>\n'
            '</div>\n'
            '<div class="promo-cta">{}</div>'
        ).format(esc(p['logoText']), esc(p['logoSub']), esc(p['headline']),
                 p['sub'], esc(p['cta']))

    # A bare & in an attribute is invalid HTML, so escape whatever the data holds.
    href = p['href'].replace('&amp;', '&').replace('&', '&amp;')
    return ('<div id="promo-banner">\n'
            '<a id="promo-slot-1" href="{}" target="_blank" rel="{}"\n'
            '   aria-label="{}">\n'
            '<div class="{}">\n{}\n</div>\n</a>\n</div>').format(
                href, p['rel'], esc(p['ariaLabel']), p['variant'], inner)


PROMO = None   # populated by main(), before any page is written

# Station named in the correction link, set per page while generating.
REPORT_SUBJECT = ''


def data_note():
    """The provenance line shown on every page.

    A function, not a module-level constant. As a constant its f-string was
    evaluated at import time, when REVIEW_DATE still holds its BUILD_DATE
    default, so every page claimed the timetable was reviewed on the day the
    site was last generated. That went unnoticed while the two dates happened
    to coincide. main() sets REVIEW_DATE from the dataset, so this must not be
    read until after that.
    """
    return ('<div class="data-note"><strong>Data:</strong> journey times are the fastest typical weekday '
            'service on each route, computed from Darwin Timetable Files published by the '
            'Rail Delivery Group under the Open Government Licence. '
            'They exclude engineering works and disruption, and are not live departure times. '
            f'Last reviewed {REVIEW_DATE}. <a href="/about/">Read the full methodology &rarr;</a>'
            f'{_report_link()}</div>')


def _report_link():
    """Route to the correction form, carrying the station where we know it.

    Set by generate_station_page so the reader does not have to retype what
    the page is already about.
    """
    if not REPORT_SUBJECT:
        return ''
    return (' <a href="/about/?station=' + urllib.parse.quote(REPORT_SUBJECT) +
            '#corrections">Report a correction &rarr;</a>')


def site_footer(total):
    return f'''<footer class="site-footer">
<div class="wrap">
<div>
<p><strong>RailReach</strong>: free UK train commute time data.</p>
<p>Journey times from {total} stations to {len(TERMINAL_META)} London terminals, computed from Darwin Timetable Files published by the Rail Delivery Group.</p>
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
        pub = {c: v for c, v in s['journeys'].items() if v.get('mins') is not None}
        j = ', '.join(
            f'{c}: {{ mins: {v["mins"]}, direct: {str(v["direct"]).lower()}'
            # Only carried when the quickest way needs a change, so the payload
            # does not repeat the headline for the majority that are direct.
            # The direct time is carried whenever one exists, even when it is
            # the same as the headline, because the direct-only view needs it
            # for every station rather than only the ones a change beats.
            + (f', dm: {v["directMins"]}' if v.get('directMins') is not None
               and v['directMins'] != v['mins'] else '')
            # Explicit, rather than inferred from a missing dm: "no direct
            # service" and "direct exists but is slower" need different words.
            + (', nd: 1' if v.get('directMins') is None else '')
            + (f', at: "{json_esc(v["changeAt"])}"' if not v['direct'] and v.get('changeAt') else '')
            + (f', typical: {v["typicalPeakMins"]}' if v.get('typicalPeakMins') else '')
            + (f', tph: {v["peakTrainsPerHour"]}' if v.get('peakTrainsPerHour') else '')
            + ' }'
            for c, v in sorted(pub.items(), key=lambda kv: kv[1]['mins']))
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


MAP_CORE_JS = """// Deprecated: superseded by map-ui.js. Kept as a thin shim so that any page
// still held in an older service-worker cache continues to work.
function getColor(mins) { return window.RR ? RR.colour(mins) : '#0072B2'; }

function initMap(lat, lng, zoom) {
  if (window.RR) return RR.createMap('map', { center: [lat, lng], zoom: zoom });
  var map = L.map('map').setView([lat, lng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
  }).addTo(map);
  return map;
}

function createTerminalMarker(map, lat, lng, popupHtml) {
  return RR.terminalMarker(map, lat, lng, popupHtml);
}

function createStationMarker(map, lat, lng, mins, popupHtml) {
  return RR.stationMarker(map, { lat: lat, lng: lng, name: '' }, mins, popupHtml);
}
"""


def write_shared_js(data_js):
    os.makedirs(os.path.join(BASE, 'assets', 'js'), exist_ok=True)
    for name, content in (('stations-data.js', data_js + '\n'), ('map-core.js', MAP_CORE_JS)):
        path = os.path.join(BASE, 'assets', 'js', name)
        with open(path, 'w') as f:
            f.write(content)
        print(f"  wrote assets/js/{name}")




# ── Asset versioning ───────────────────────────────────────────────────────
# GitHub Pages serves every file with max-age=600 and gives us no control over
# that header. Without a version in the URL a returning visitor can hold the
# previous JS or CSS for up to ten minutes after a deploy while already having
# the new HTML, so fresh markup runs against stale script. Stamping each URL
# with a hash of that file's own contents makes a changed asset a different
# URL, which is fetched immediately, while an unchanged one keeps its URL and
# stays cached.
#
# A query string rather than a hashed filename, deliberately: the file keeps
# its real name on disk, so HTML cached from an earlier build still requests a
# URL that exists and gets the current file, instead of 404ing on a hashed
# filename that has since been replaced.
ASSET_VERSIONS = {}

# Every asset the pages reference. Two are generated during this run, so they
# are hashed from the exact bytes about to be written rather than from whatever
# the previous build happened to leave on disk.
VERSIONED_ASSETS = ('assets/css/shared.css', 'assets/js/map-ui.js',
                    'assets/js/home-map.js', 'assets/js/stations-data.js',
                    'assets/js/map-core.js', 'assets/img/just-move-in-white.svg', 'assets/img/trustpilot-stars.svg')


def compute_asset_versions(data_js):
    generated = {
        'assets/js/stations-data.js': (data_js + '\n').encode(),
        'assets/js/map-core.js': MAP_CORE_JS.encode(),
    }
    for rel in VERSIONED_ASSETS:
        blob = generated.get(rel)
        if blob is None:
            with open(os.path.join(BASE, rel), 'rb') as f:
                blob = f.read()
        ASSET_VERSIONS['/' + rel] = hashlib.sha256(blob).hexdigest()[:8]


ASSET_REF = re.compile(r'(/assets/(?:js|css|img)/[A-Za-z0-9._-]+)(\?v=[0-9a-f]+)?')


def stamp_assets(html):
    """Rewrite every /assets/ reference to carry its content hash.

    Applied at write time rather than in each template, so a reference added
    later cannot quietly miss out. Matching an existing ?v= makes it
    idempotent: index.html is both source and output, so it gets re-stamped in
    place on every build rather than accumulating versions.
    """
    def sub(m):
        path = m.group(1)
        v = ASSET_VERSIONS.get(path)
        return f'{path}?v={v}' if v else path
    return ASSET_REF.sub(sub, html)


def write_html(path, html):
    """Single writer for every generated page, so stamping is unmissable."""
    with open(path, 'w') as f:
        f.write(stamp_assets(html))


# ── Timetable currency ─────────────────────────────────────────────────────
# National Rail changes its timetable twice a year: conventionally the second
# Sunday of December and the third Sunday of May. Dates are computed rather
# than hardcoded so this does not quietly rot. They are the published pattern,
# not a guarantee - confirm against National Rail before a refresh.
def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)   # first Sunday
    return d + datetime.timedelta(weeks=n - 1)


def timetable_changes(around_year):
    dates = []
    for y in (around_year - 1, around_year, around_year + 1):
        dates.append(_nth_sunday(y, 5, 3))    # May change
        dates.append(_nth_sunday(y, 12, 2))   # December change
    return sorted(dates)


def check_timetable_currency(review_date):
    """Warn if the data predates the timetable currently in force.

    The site stamps 'Data reviewed' and schema dateModified on all 358 pages.
    If the underlying times predate a timetable change, those dates assert a
    currency the data does not have, so say so loudly at build time.
    """
    today = datetime.date.today()
    review = datetime.date.fromisoformat(review_date)
    changes = timetable_changes(today.year)
    in_force = max((d for d in changes if d <= today), default=None)
    upcoming = min((d for d in changes if d > today), default=None)

    if in_force and review < in_force:
        print("")
        print("  " + "!" * 68)
        print(f"  ! TIMETABLE CHANGED on {in_force} - data was last reviewed {review}")
        print("  ! The site will claim a freshness the journey times do not have.")
        print("  ! Re-check the times, then bump lastReviewed in")
        print("  ! _build/data/stations.json. See _build/REFRESH.md")
        print("  " + "!" * 68)
        print("")
    else:
        days = (upcoming - today).days if upcoming else None
        print(f"  data reviewed {review}; timetable in force since {in_force}")
        if upcoming:
            print(f"  next timetable change {upcoming} ({days} days) - refresh due then")



def check_prose_figures(stations):
    """Catch hand-written times that have drifted from the dataset.

    The homepage FAQ and terminal summaries quote specific figures in prose
    the generator does not own - 137 of them. A data refresh silently leaves
    those stale, which is precisely the kind of quiet inaccuracy the review
    date is supposed to rule out. Compare and report.
    """
    path = os.path.join(BASE, 'index.html')
    with open(path) as f:
        html = f.read()

    # Ignore the regions the generator rewrites, and all script blocks.
    for tag in ('lede', 'terminal-cards', 'station-cards', 'data-table'):
        html = re.sub(r'<!-- GEN:%s -->.*?<!-- /GEN:%s -->' % (tag, tag), '', html, flags=re.DOTALL)
    html = re.sub(r'/\* GEN:map-data \*/.*?/\* /GEN:map-data \*/', '', html, flags=re.DOTALL)
    html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)

    # The prose is terminal-specific ("From Victoria: Sevenoaks (30 min)"),
    # so a figure is correct if it matches the time to ANY terminal that
    # station serves. Comparing only against the fastest cries wolf.
    valid = {}
    for s in stations:
        valid[s['name']] = set(j['mins'] for j in s['journeys'].values()
                               if j.get('mins') is not None)

    checked = 0
    mismatches = []
    for m in re.finditer(r'([A-Z][A-Za-z\'\- ]{2,28}?) \((\d+) min\)', html):
        name, mins = m.group(1).strip(), int(m.group(2))
        if name not in valid:
            continue
        checked += 1
        if mins not in valid[name]:
            mismatches.append((name, mins, sorted(valid[name])))

    if mismatches:
        print(f"  WARNING: {len(mismatches)} hand-written figure(s) disagree with the data:")
        for name, quoted, actual in mismatches[:12]:
            print(f"    index.html says {name} ({quoted} min); data has {actual}")
        print("    These sit in prose the generator does not own. Edit index.html by hand.")
    else:
        print(f"  {checked} hand-written figures in prose all agree with the data")


# ── Discovery ──────────────────────────────────────────────────────────────
# Mirrors RR.discoveries in assets/js/map-ui.js. Ranked by absolute journey
# time, not minutes per kilometre: that metric rewards being on a fast line,
# and a good ratio is no comfort if the trip still takes 70 minutes.
# Deliberately no "well known" exclusion list. Filtering out promoted towns
# and major cities assumed knowledge we have no basis for: plenty of people
# have no idea where Reading is, still less that it is 23 minutes from
# Paddington. The only exclusions left are places you cannot live in, which is
# a category judgement rather than a guess about the reader.
NOT_A_PLACE_TO_LIVE = {
    'Gatwick Airport', 'Stansted Airport', 'Luton Airport Parkway',
    'Birmingham International', 'Denham Golf Club',
}

CENTRAL = (51.5074, -0.1278)   # Charing Cross
MIN_KM_FROM_LONDON = 20        # inside this ring it is London, not a relocation
MIN_KM_APART = 8               # spread results rather than list one line's stops


def discoveries(stations, code, max_mins, limit=6, exclude=None):
    candidates = []
    for s in stations:
        if s['name'] == exclude or s['name'] in NOT_A_PLACE_TO_LIVE:
            continue
        j = s['journeys'].get(code)
        if not j or j.get('mins') is None or j['mins'] > max_mins:
            continue
        if haversine(CENTRAL[0], CENTRAL[1], s['lat'], s['lng']) < MIN_KM_FROM_LONDON:
            continue
        candidates.append(s)

    candidates.sort(key=lambda s: s['journeys'][code]['mins'])
    picked, coords = [], []
    for s in candidates:
        if len(picked) >= limit:
            break
        if any(haversine(c[0], c[1], s['lat'], s['lng']) < MIN_KM_APART for c in coords):
            continue
        coords.append((s['lat'], s['lng']))
        picked.append(s)
    return picked


def discovery_band(mins):
    """Round a journey time up to a band that reads naturally in a sentence."""
    import math as _m
    return max(30, int(_m.ceil(mins / 15.0) * 15))


# ── Terminal pages ─────────────────────────────────────────────────────────
def generate_terminal_page(code, terminals, stations, total):
    global REPORT_SUBJECT
    REPORT_SUBJECT = ''
    meta = TERMINAL_META[code]
    slug, name, operators = meta['slug'], meta['name'], meta['operators']
    t = terminals[code]

    serving = sorted(
        ((s['name'], s['journeys'][code]['mins'], s['journeys'][code]['direct'],
          s['journeys'][code])
         for s in stations if code in s['journeys']
         and s['journeys'][code].get('mins') is not None
         and s['journeys'][code]['mins'] <= 90),
        key=lambda x: x[1])
    count = len(serving)
    top3 = ', '.join(f"{n} ({m} min)" for n, m, _, _ in serving[:3])
    top5 = ', '.join(n for n, _, _, _ in serving[:5])
    under30 = [n for n, m, _, _ in serving if m < 30]
    under30_names = ', '.join(under30[:6]) if under30 else 'none within 30 minutes'
    fastest = serving[0]
    direct_count = sum(1 for _, _, d, _ in serving if d)

    row_parts = []
    for st_name, st_mins, st_direct, st_j in serving:
        # NOTE: do not name these `slug`/`m` — `slug` is this terminal's own
        # slug and is used below to pick the output directory.
        st_slug = STATION_SLUGS.get(st_name)
        cell = (f'<a href="/stations/{st_slug}/">{esc(st_name)}</a>'
                if st_slug else esc(st_name))
        row_parts.append(f'<tr><td>{cell}</td><td>{time_cell(st_j)}</td>'
                         f'<td>{direct_cell(st_j)}</td>'
                         f'<td>{typical_cell(st_j)}</td>'
                         f'<td>{frequency_cell(st_j)}</td></tr>')
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

    page_url = f"{SITE}/terminals/{slug}/"
    page_desc = (f"{count} stations reach London {name} within 90 minutes, "
                 f"{direct_count} of them directly. Fastest: {fastest[0]} at {fastest[1]} minutes.")
    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Terminals", "/terminals/"),
                                  (f"{name} train times", f"/terminals/{slug}/")])),
        webpage_ld(f"London {name} train times", page_desc, page_url,
                   f"Train journey times to London {name}"),
        train_station_ld(f"London {name}", t['lat'], t['lng'], page_desc, page_url),
        json.loads(faq_ld_from_html(faqs_html)),
    ], indent=0)

    facts = key_facts([
        ("Stations within 90 minutes", str(count)),
        ("Direct services", f"{direct_count} of {count}"),
        ("Stations under 30 minutes", str(len(under30))),
        ("Fastest station", f"{fastest[0]}, {fastest[1]} minutes"),
        ("Operators", operators),
        ("Source", "Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0"),
    ])

    body = f'''<body>
{site_header('terminals')}
{crumbs([("RailReach", "/"), ("Terminals", "/terminals/"), (f"{name} train times", None)])}
<div class="map-shell" role="region" aria-label="Map of train journey times to London {name}">
<a class="skip-map" href="#all-stations">Skip the map and read the journey times as a table</a>
<div id="map"></div>
{legend()}
<div class="station-count" id="station-count"></div>
{PROMO}
</div><!-- /.map-shell -->

<main id="content" class="page-content">
<div class="wrap">
<h1>Train journey times to London {name}</h1>
<p class="lede">{count} stations reach London {name} within 90 minutes, {direct_count} of them on a direct train. Services are operated by {operators}. The fastest commute is from {fastest[0]} at {fastest[1]} minutes.</p>
{facts}

<h2 id="all-stations">Every station to {name}</h2>
<p class="section-note">Sorted fastest first. Times are the quickest typical weekday service.</p>
<div class="table-scroll">
<table>
<caption>Journey times from {count} stations to London {name}</caption>
<thead><tr><th>Station</th><th>Fastest</th><th>Fastest direct</th><th>Typical peak</th><th>Peak trains</th></tr></thead>
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

{data_note()}
</div>
</main>

<script type="application/ld+json">{ld}</script>

<script src="/assets/js/stations-data.js"></script>
<script src="/assets/js/map-ui.js"></script>
<script>
const code='{code}';
const t=TERMINALS[code];
const map=RR.createMap('map');
const pts=[[t.lat,t.lng]];
RR.terminalMarker(map,t.lat,t.lng,'<strong>London '+RR.esc(t.name)+'</strong><br>London terminal');
let count=0;
STATIONS.forEach(function(s){{
  const j=s.journeys[code];
  if(j&&j.mins<=90){{
    RR.stationMarker(map,s,j.mins,RR.stationPopup(s,t.name,j));
    pts.push([s.lat,s.lng]);
    count++;
  }}
}});
document.getElementById('station-count').textContent=count+' stations within 90 min of '+t.name;
RR.fit(map,pts,{{animate:false}});
</script>
{site_footer(total)}'''

    html = head(
        title=f"London {name} Train Times &amp; Journey Map | RailReach",
        desc=f"Train journey times to London {name} from {count} stations: {top3}. Interactive map, direct and indirect routes, 2026 timetable data.",
        canonical=f"{SITE}/terminals/{slug}/",
        og_title=f"{name} Train Times | RailReach",
        og_desc=f"Journey times to London {name} from {count} stations, mapped and ranked.",
        map_h="56vh",
    ) + '\n' + body

    outdir = os.path.join(BASE, 'terminals', slug)
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)

    md_rows = '\n'.join(
        f"| {n} | {m} min{'' if j.get('direct') else ' (change at ' + str(j.get('changeAt')) + ')'} | "
        f"{md_direct(j)} | {j.get('typicalPeakMins') or '-'} | "
        f"{j.get('peakTrainsPerHour') or '-'} |"
        for n, m, d, j in serving)
    md_faq = re.sub(r'<h3>(.*?)</h3>\s*<p>(.*?)</p>',
                    lambda mm: f"### {re.sub(r'<[^>]+>', '', mm.group(1))}\n\n"
                               f"{re.sub(r'<[^>]+>', '', mm.group(2))}\n",
                    faqs_html, flags=re.DOTALL)
    write_markdown(f'terminals/{slug}', f'''# Train journey times to London {name}

{count} stations reach London {name} within 90 minutes, {direct_count} of them on a
direct train. Services are operated by {operators}.

- Stations within 90 minutes: {count}
- Direct services: {direct_count} of {count}
- Stations under 30 minutes: {len(under30)}
- Fastest station: {fastest[0]} - {fastest[1]} minutes
- Operators: {operators}
- Source: Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0
- Data reviewed: {REVIEW_DATE}

## Every station to {name}

| Station | Fastest | Fastest direct | Typical peak | Peak trains/hr |
| --- | --- | --- | --- |
{md_rows}

## Frequently asked questions

{md_faq}
## About this data

Fastest is the quickest scheduled weekday service; typical peak is the median of
services arriving at the London terminal between 07:00 and 09:30. Computed from
Darwin Timetable Files published by the Rail Delivery Group under the Open
Government Licence. Not live times, and they exclude disruption and engineering
work. Full methodology: {SITE}/about/

Source: RailReach - {page_url}
Licence: CC BY 4.0. Please attribute RailReach and link to {SITE}/
''')
    return count


# ── Station pages ──────────────────────────────────────────────────────────
def generate_station_page(station_name, slug, terminals, stations, total):
    global REPORT_SUBJECT
    REPORT_SUBJECT = station_name
    sdata = next((s for s in stations if s['name'] == station_name), None)
    if not sdata:
        print(f"  WARNING: station '{station_name}' not in data")
        return None

    sorted_journeys = sorted_journeys_list = sorted_journeys_fn(sdata['journeys'])
    timed = [(c, j) for c, j in sorted_journeys if j.get('mins') is not None]
    if not timed:
        # No direct service to any terminal we track. These are real stations
        # with real demand - Henley-on-Thames, Marlow, Windsor - reached by
        # changing at a junction. Say so honestly rather than leaving a stale
        # page on disk, which is what happened the first time this ran.
        return generate_indirect_station_page(station_name, slug, sdata,
                                              sorted_journeys, terminals, stations, total)
    fastest_code, fastest_j = timed[0]

    # Where the quickest terminal runs nothing in the morning peak, say so and
    # name the one a commuter can actually use. Welham Green is 38 minutes to
    # Kings Cross against 39 to Moorgate, but has no peak train to Kings Cross.
    peak_options = [(c, j) for c, j in timed if j.get('peakTrainsPerHour')]
    commuter_code, commuter_j = (peak_options[0] if peak_options else (None, None))
    peak_caveat = ''
    if commuter_code and commuter_code != fastest_code and not fastest_j.get('peakTrainsPerHour'):
        peak_caveat = (' That route runs no train during the morning peak, so the practical '
                       f'commute is {TERMINAL_META[commuter_code]["name"]} in '
                       f'{commuter_j["mins"]} minutes, with '
                       f'{commuter_j["peakTrainsPerHour"]} trains an hour.')
    fastest_name = TERMINAL_META[fastest_code]['name']
    n_terms = len(sorted_journeys)
    plural = 's' if n_terms > 1 else ''
    times_desc = ', '.join(f"{TERMINAL_META[c]['name']} ({j['mins']} min)" for c, j in timed[:3])
    terminal_list = ', '.join(TERMINAL_META[c]['name'] for c, _ in sorted_journeys)
    direct_terminals = [TERMINAL_META[c]['name'] for c, j in timed if j['direct']]
    direct_text = ', '.join(direct_terminals) if direct_terminals else 'none; all routes require a change'

    dists = sorted(
        ((s2['name'], haversine(sdata['lat'], sdata['lng'], s2['lat'], s2['lng']), s2)
         for s2 in stations if s2['name'] != station_name),
        key=lambda x: x[1])[:6]

    nearby_cards = []
    for nb_name, nb_dist, nb_data in dists:
        nb_slug = STATION_SLUGS.get(nb_name)
        meta = f'{nb_dist:.0f} km away'
        if nb_data['journeys']:
            nb_timed = [j for j in nb_data['journeys'].values() if j.get('mins') is not None]
            nb_fast = min(nb_timed, key=lambda j: j['mins']) if nb_timed else None
            if nb_fast:
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
        f'<td>{time_cell(j)}</td><td>{direct_cell(j)}</td>'
        f'<td>{typical_cell(j)}</td><td>{frequency_cell(j)}</td>'
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
    direct_answer = (f"Yes. Direct services run to {direct_text}." if direct_terminals
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

    page_url = f"{SITE}/stations/{slug}/"
    page_desc = (f"{station_name} reaches London {fastest_name} in {fastest_j['mins']} minutes, "
                 f"the fastest of {n_terms} London terminal{plural} it serves.")
    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Stations", "/stations/"),
                                  (f"{station_name} to London", f"/stations/{slug}/")])),
        webpage_ld(f"{station_name} to London train times", page_desc, page_url,
                   f"Train journey times from {station_name} to London"),
        train_station_ld(station_name, sdata['lat'], sdata['lng'], page_desc, page_url),
        json.loads(faq_ld_from_html(faqs_html)),
    ], indent=0)

    facts = key_facts([
        ("Fastest journey to London", f"{fastest_j['mins']} minutes to {fastest_name}"),
        ("Direct service", "Yes" if fastest_j['direct'] else "No, one change required"),
        ("London terminals served", f"{n_terms} ({terminal_list})"),
        ("Operator", TERMINAL_META[fastest_code]['operators']),
        ("Source", "Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0"),
    ])

    polylines = '\n'.join(
        "L.polyline([[{},{}],[{},{}]],{{color:RR.colour({}),weight:3,opacity:0.75,{}}}).addTo(map);".format(
            sdata['lat'], sdata['lng'], terminals[c]['lat'], terminals[c]['lng'], j['mins'],
            "" if j['direct'] else "dashArray:'8,6',")
        for c, j in timed)

    def terminal_popup(c, j):
        """The station page's terminal popups, matching the map's layout.

        Same shape as RR.stationPopup on the homepage: the journey time leads,
        any change it depends on sits directly beneath it, and the peak rows
        are omitted where no direct service exists rather than reporting "no
        peak service" for something we have simply not measured.
        """
        html = ('<strong>London {}</strong>'
                '<div class="pop-sub">from {}</div>'
                '<div class="pop-hero"><b>{}</b> min</div>').format(
                    json_esc(TERMINAL_META[c]['name']), json_esc(station_name), j['mins'])
        if not j['direct'] and j.get('changeAt'):
            html += '<div class="pop-change">change at {}</div>'.format(json_esc(j['changeAt']))

        rows = ''
        if j.get('directMins') is None:
            rows += '<div><dt>Direct train</dt><dd class="pop-none">none</dd></div>'
        elif not j['direct']:
            rows += '<div><dt>Fastest direct</dt><dd>{} min</dd></div>'.format(j['directMins'])

        if j.get('directMins') is not None:
            typical = j.get('typicalPeakMins')
            if typical is None:
                rows += ('<div><dt>Typical peak</dt>'
                         '<dd class="pop-none">no peak service</dd></div>')
            else:
                gap = ' class="pop-gap"' if typical - j['mins'] >= 10 else ''
                rows += ('<div{}><dt>Typical peak</dt>'
                         '<dd>{} min</dd></div>').format(gap, typical)
            tph = j.get('peakTrainsPerHour')
            if tph:
                rows += '<div><dt>Peak trains</dt><dd>{}/hr</dd></div>'.format(tph)

        if rows:
            html += '<dl class="pop-stats">{}</dl>'.format(rows)
        html += ('<a class="popup-link" href="/terminals/{}/">Terminal guide &rarr;</a>'
                 ).format(TERMINAL_META[c]['slug'])
        return html

    term_markers = '\n'.join(
        "RR.terminalMarker(map,{},{},'{}');".format(
            terminals[c]['lat'], terminals[c]['lng'], terminal_popup(c, j))
        for c, j in timed)

    # Every point the map must frame: the station plus each terminal it reaches.
    fit_points = '[[{},{}],{}]'.format(
        sdata['lat'], sdata['lng'],
        ','.join('[{},{}]'.format(terminals[c]['lat'], terminals[c]['lng'])
                 for c, _ in timed))

    # One section per route, so the page answers "<station> to <terminal>"
    # directly. Separate route pages would be near-duplicates: 345 stations
    # share only 357 journeys, so most towns serve a single terminal.
    route_parts = []
    for c, j in timed:
        tm = TERMINAL_META[c]
        peers = sorted(s2['journeys'][c]['mins'] for s2 in stations
                       if c in s2['journeys'] and s2['journeys'][c].get('mins') is not None)
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

    # Acquisition -> discovery. Someone landing here from a search already
    # knows this town; the nearby-stations list only offers its geographic
    # neighbours, which are the places they had already thought of. This
    # surfaces comparable commutes they had not.
    band = discovery_band(fastest_j['mins'])
    finds = discoveries(stations, fastest_code, band, limit=6, exclude=station_name)
    if finds:
        find_cards = '\n'.join(
            '<li><a class="card" href="/stations/{}/">'
            '<span class="card-title">{}</span>'
            '<span class="card-meta">{} to {}{}</span></a></li>'.format(
                f['slug'], esc(f['name']), badge(f['journeys'][fastest_code]['mins']),
                fastest_name,
                ' &middot; direct' if f['journeys'][fastest_code]['direct'] else ' &middot; one change')
            for f in finds)
        discovery_section = f"""<h2 id="discover">Other places within {band} minutes of {fastest_name}</h2>
<p>{station_name} is one of many places you could commute from. These are other options within {band} minutes of London {fastest_name}, ranked by journey time and spread across the network rather than clustered on one stretch of line.</p>
<ul class="link-grid">
{find_cards}
</ul>
<p><a href="/?to={fastest_code}&amp;max={min(band, 90)}">See all of them on the map &rarr;</a></p>"""
    else:
        discovery_section = ''

    this_station_legend = ('<div class="legend-item"><div class="legend-dot" '
                           'style="background:#7c3aed"></div> <span class="legend-long">This station</span><span class="legend-short">This stn</span></div>\n')

    body = f'''<body>
{site_header('stations')}
{crumbs([("RailReach", "/"), ("Stations", "/stations/"), (f"{station_name} to London", None)])}
<div class="map-shell" role="region" aria-label="Map of train routes from {station_name} to London">
<a class="skip-map" href="#journey-comparison">Skip the map and read the journey times as a table</a>
<div id="map"></div>
{legend(this_station_legend)}
<div class="station-count" id="station-count"></div>
{PROMO}
</div><!-- /.map-shell -->

<main id="content" class="page-content">
<div class="wrap">
<h1>Train times from {station_name} to London</h1>
<p class="lede">{station_name} connects to {n_terms} London terminal{plural}. The fastest route is {fastest_name} in {fastest_j['mins']} minutes{" on a direct train" if fastest_j['direct'] else ", with one change"}.{peak_caveat}</p>
{facts}

<h2 id="journey-comparison">{station_name} to each London terminal</h2>
<div class="table-scroll">
<table>
<caption>Journey times from {station_name} to London terminals</caption>
<thead><tr><th>London terminal</th><th>Fastest</th><th>Fastest direct</th><th>Typical peak</th><th>Peak trains</th><th>Operator</th></tr></thead>
<tbody>
{table_rows}
</tbody>
</table>
</div>

{route_sections}
<h2>Frequently asked questions</h2>
{faqs_html}

{discovery_section}
<h2>Nearby stations</h2>
<p>Alternative departure points close to {station_name}, for comparing platforms rather than places.</p>
<ul class="link-grid">
{nearby_html}
</ul>

<h2>All London terminals</h2>
<div class="terminal-nav">{terminal_nav}</div>

{data_note()}
</div>
</main>

<script type="application/ld+json">{ld}</script>

<script src="/assets/js/stations-data.js"></script>
<script src="/assets/js/map-ui.js"></script>
<script>
const map=RR.createMap('map');
L.circleMarker([{sdata['lat']},{sdata['lng']}],{{radius:RR.stationRadius()+2,fillColor:RR.COLOURS.focus,color:'#fff',weight:3,opacity:1,fillOpacity:0.95}}).bindPopup('<strong>{json_esc(station_name)}</strong><br>This station').addTo(map);
{term_markers}
{polylines}
document.getElementById('station-count').textContent='{json_esc(station_name)}: {n_terms} London terminal{plural}';
// Fixes the 182 of 357 routes whose destination fell off a 375px screen.
RR.fit(map,{fit_points},{{animate:false}});
</script>
{site_footer(total)}'''

    html = head(
        title=f"{station_name} to London Train Times | RailReach",
        desc=f"Train times from {station_name} to London: {times_desc}. Direct and indirect routes compared on an interactive map. 2026 timetable data.",
        canonical=f"{SITE}/stations/{slug}/",
        og_title=f"{station_name} to London Train Times | RailReach",
        og_desc=f"Journey times from {station_name} to London terminals. {fastest_name} in {fastest_j['mins']} min.",
        map_h="56vh",
    ) + '\n' + body

    outdir = os.path.join(BASE, 'stations', slug)
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)

    md_rows = '\n'.join(
        f"| {TERMINAL_META[c]['name']} | "
        f"{str(j['mins']) + ' min' if j.get('mins') is not None else 'change required'}"
        f"{'' if j.get('direct') or j.get('mins') is None else ' (change at ' + str(j.get('changeAt')) + ')'} | "
        f"{md_direct(j)} | "
        f"{j.get('typicalPeakMins') or '-'} | {j.get('peakTrainsPerHour') or '-'} | "
        f"{TERMINAL_META[c]['operators']} |"
        for c, j in sorted_journeys)
    md_faq = re.sub(r'<h3>(.*?)</h3>\s*<p>(.*?)</p>',
                    lambda m: f"### {re.sub(r'<[^>]+>', '', m.group(1))}\n\n"
                              f"{re.sub(r'<[^>]+>', '', m.group(2))}\n",
                    faqs_html, flags=re.DOTALL)
    write_markdown(f'stations/{slug}', f'''# Train times from {station_name} to London

{station_name} connects to {n_terms} London terminal{plural}. The fastest route is \
{fastest_name} in {fastest_j['mins']} minutes\
{" on a direct train" if fastest_j['direct'] else ", with one change"}.

- Fastest journey to London: {fastest_j['mins']} minutes to {fastest_name}
- Direct service: {"Yes" if fastest_j['direct'] else "No - one change required"}
- London terminals served: {n_terms} ({terminal_list})
- Operator: {TERMINAL_META[fastest_code]['operators']}
- Source: Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0
- Data reviewed: {REVIEW_DATE}

## {station_name} to each London terminal

| London terminal | Fastest | Fastest direct | Typical peak | Peak trains/hr | Operator |
| --- | --- | --- | --- | --- |
{md_rows}

## Frequently asked questions

{md_faq}
## About this data

Fastest is the quickest scheduled weekday service; typical peak is the median of
services arriving at the London terminal between 07:00 and 09:30. Computed from
Darwin Timetable Files published by the Rail Delivery Group under the Open
Government Licence. Not live times, and they exclude disruption and engineering
work. Full methodology: {SITE}/about/

Source: RailReach - {page_url}
Licence: CC BY 4.0. Please attribute RailReach and link to {SITE}/
''')
    return fastest_j['mins'], fastest_name



def generate_indirect_station_page(station_name, slug, sdata, sorted_journeys,
                                   terminals, stations, total):
    """A station with no direct service to any terminal we cover.

    The timetable can confirm no direct train exists; it cannot compute the
    interchange without a routing engine. So the page says exactly that, and
    names the terminal the station is associated with, rather than publishing
    a number nobody has verified.
    """
    codes = [c for c, _ in sorted_journeys]
    names = ', '.join(TERMINAL_META[c]['name'] for c in codes)
    primary = codes[0] if codes else 'PAD'
    tm = TERMINAL_META[primary]

    dists = sorted(
        ((s2['name'], haversine(sdata['lat'], sdata['lng'], s2['lat'], s2['lng']), s2)
         for s2 in stations if s2['name'] != station_name),
        key=lambda x: x[1])[:6]
    nearby_cards = []
    for nb_name, nb_dist, nb in dists:
        timed_nb = [j for j in nb['journeys'].values() if j.get('mins') is not None]
        meta = f'{nb_dist:.0f} km away'
        if timed_nb:
            meta = (f'{badge(min(j["mins"] for j in timed_nb))} fastest to London '
                    f'&middot; {nb_dist:.0f} km away')
        nearby_cards.append(
            f'<li><a class="card" href="/stations/{nb["slug"]}/">'
            f'<span class="card-title">{esc(nb_name)}</span>'
            f'<span class="card-meta">{meta}</span></a></li>')

    faqs_html = f"""<h3>Is there a direct train from {station_name} to London?</h3>
<p>No. Across three midweek days of timetable data there is no direct service from {station_name} to any London terminal RailReach covers. Reaching London means changing, usually at the nearest junction on the main line.</p>
<h3>Which London terminal does {station_name} connect towards?</h3>
<p>Services from {station_name} feed towards London {names}, operated by {tm['operators']}. The connecting journey time depends on the change and is not published here, because it has not been measured.</p>
<h3>Why does RailReach not give a journey time for {station_name}?</h3>
<p>Every time on this site is computed from published timetables. A journey involving a change requires routing across services, which this dataset does not do, so no figure is given rather than an estimated one.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("Stations", "/stations/"),
                                  (f"{station_name} to London", f"/stations/{slug}/")])),
        webpage_ld(f"{station_name} to London train times",
                   f"{station_name} has no direct service to a London terminal; a change is required.",
                   f"{SITE}/stations/{slug}/", f"Train services from {station_name} to London"),
        train_station_ld(station_name, sdata['lat'], sdata['lng'],
                         f"{station_name} railway station", f"{SITE}/stations/{slug}/"),
        json.loads(faq_ld_from_html(faqs_html)),
    ], indent=0)

    facts = key_facts([
        ("Direct service to London", "None found in the timetable"),
        ("Connects towards", names),
        ("Operator", tm['operators']),
        ("Source", "Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0"),
    ])

    body = f"""<body>
{site_header('stations')}
{crumbs([("RailReach", "/"), ("Stations", "/stations/"), (f"{station_name} to London", None)])}
<div class="map-shell" role="region" aria-label="Map showing {station_name}">
<a class="skip-map" href="#journey-comparison">Skip the map and read the detail as text</a>
<div id="map"></div>
{legend(this_station_legend_html())}
<div class="station-count" id="station-count"></div>
{PROMO}
</div><!-- /.map-shell -->

<main id="content" class="page-content">
<div class="wrap">
<h1>Train times from {station_name} to London</h1>
<p class="lede">{station_name} has no direct train to a London terminal. Reaching London requires a change, and RailReach does not publish a time for journeys it has not measured.</p>
{facts}

<h2 id="journey-comparison">{station_name} to London</h2>
<div class="table-scroll">
<table>
<caption>Services from {station_name} towards London</caption>
<thead><tr><th>London terminal</th><th>Direct service</th><th>Operator</th></tr></thead>
<tbody>
{chr(10).join(f'<tr><td>{TERMINAL_META[c]["name"]}</td><td><span class="t-badge t-change">Change required</span></td><td>{TERMINAL_META[c]["operators"]}</td></tr>' for c in codes)}
</tbody>
</table>
</div>

<h2>Frequently asked questions</h2>
{faqs_html}

<h2>Nearby stations</h2>
<p>Stations near {station_name} with a direct London service.</p>
<ul class="link-grid">
{chr(10).join(nearby_cards)}
</ul>

{data_note()}
</div>
</main>

<script type="application/ld+json">{ld}</script>
<script src="/assets/js/stations-data.js"></script>
<script src="/assets/js/map-ui.js"></script>
<script>
const map=RR.createMap('map');
L.circleMarker([{sdata['lat']},{sdata['lng']}],{{radius:RR.stationRadius()+2,fillColor:RR.COLOURS.focus,color:'#fff',weight:3,opacity:1,fillOpacity:0.95}}).bindPopup('<strong>{json_esc(station_name)}</strong><br>No direct London service').addTo(map);
document.getElementById('station-count').textContent='{json_esc(station_name)}: no direct London service';
RR.fit(map,[[{sdata['lat']},{sdata['lng']}]],{{maxZoom:12,animate:false}});
</script>
{site_footer(total)}"""

    html = head(
        title=f"{station_name} to London Train Times | RailReach",
        desc=f"{station_name} has no direct train to a London terminal. Which terminal it connects towards, the operator, and nearby stations that do have a direct service.",
        canonical=f"{SITE}/stations/{slug}/",
        og_title=f"{station_name} to London | RailReach",
        og_desc=f"No direct London service from {station_name}; a change is required.",
        map_h="56vh",
    ) + '\n' + body

    outdir = os.path.join(BASE, 'stations', slug)
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)

    write_markdown(f'stations/{slug}', f"""# Train times from {station_name} to London

{station_name} has no direct train to a London terminal. Reaching London requires a
change, and no journey time is published because none has been measured.

- Direct service to London: none found in the timetable
- Connects towards: {names}
- Operator: {tm['operators']}
- Source: Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0
- Data reviewed: {REVIEW_DATE}

Source: RailReach - {SITE}/stations/{slug}/
Licence: CC BY 4.0. Please attribute RailReach and link to {SITE}/
""")
    return None


def this_station_legend_html():
    return ('<div class="legend-item"><div class="legend-dot" '
            'style="background:#7c3aed"></div> <span class="legend-long">This station</span>'
            '<span class="legend-short">This stn</span></div>\n')


# ── Hub pages ──────────────────────────────────────────────────────────────
def generate_terminal_hub(stations, counts, total):
    global REPORT_SUBJECT
    REPORT_SUBJECT = ''
    cards, rows = [], []
    for code, meta in TERMINAL_META.items():
        serving = sorted(
            ((s['name'], s['journeys'][code]['mins'])
             for s in stations if code in s['journeys'] and s['journeys'][code].get('mins') is not None
         and s['journeys'][code]['mins'] <= 90),
            key=lambda x: x[1])
        fastest = serving[0] if serving else ('None', 0)
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
<p>London has {len(TERMINAL_META)} main line railway terminals: {', '.join(m['name'] for m in TERMINAL_META.values())}. Each serves a different part of the country, and most commuter towns are tied to just one or two of them.</p>
<h3>Which London terminal has the most commuter stations?</h3>
<p>Waterloo has the widest commuter catchment, with {counts['WAT']} stations reaching it within 90 minutes, followed by Victoria ({counts['VIC']}) and Kings Cross ({counts['KGX']}).</p>
<h3>Which London terminal should I commute into?</h3>
<p>That is usually decided by where you live rather than by preference. Each town sits on a line into one or two specific terminals. The table above shows the catchment of each, and every terminal page lists its stations in full.</p>"""

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
        title=f"London Rail Terminals | Train Times to All {len(TERMINAL_META)} London Termini | RailReach",
        desc=f"Compare all {len(TERMINAL_META)} London terminals: how many stations reach each within 90 minutes, which operators run them, and the fastest commute into every terminus.",
        canonical=f"{SITE}/terminals/",
        og_title="London Rail Terminals | RailReach",
        og_desc=f"All {len(TERMINAL_META)} London terminals compared by commuter catchment.",
        md=False,
        leaflet=False,
    ) + f'''
<body>
{site_header('terminals')}
{crumbs([("RailReach", "/"), ("Terminals", None)])}
<main id="content" class="page-content">
<div class="wrap">
<h1>London main line rail terminals</h1>
<p class="lede">London has {len(TERMINAL_META)} main line terminals, each serving a different slice of the country. Together they connect {total} stations to the capital within 90 minutes.</p>

<h2>All {len(TERMINAL_META)} terminals</h2>
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

{data_note()}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'terminals')
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)
    print("  wrote terminals/index.html")


def generate_station_hub(page_info, total):
    global REPORT_SUBJECT
    REPORT_SUBJECT = ''
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
<p>Each station page lists every London terminal that town can reach, the journey time, whether the train is direct, and the operator, so two towns can be compared on identical measures.</p>
<h3>Does RailReach cover every UK station?</h3>
<p>RailReach covers the {total} stations that reach a London main line terminal within 90 minutes, and every one has its own journey guide. Stations beyond that threshold are outside a practical daily commute and are not included.</p>"""

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
        desc=f"Every one of {len(ordered)} stations within 90 minutes of London, ranked by journey time: fastest terminal, direct services and nearby alternatives.",
        canonical=f"{SITE}/stations/",
        og_title="Commuter Stations to London | RailReach",
        og_desc="London commuter towns ranked by fastest train journey time.",
        md=False,
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

{data_note()}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'stations')
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)
    print("  wrote stations/index.html")


def generate_about(stations, counts, total, n_station_pages):
    global REPORT_SUBJECT
    REPORT_SUBJECT = ''
    op_list = sorted({o.strip() for m in TERMINAL_META.values() for o in m['operators'].split(',')})
    pairs = sum(len(s['journeys']) for s in stations)
    direct = sum(1 for s in stations for j in s['journeys'].values() if j.get('direct'))

    faqs_html = f"""<h3>Where does RailReach get its journey times?</h3>
<p>Times are computed from Darwin Timetable Files, published by the Rail Delivery Group through the Rail Data Marketplace under the Open Government Licence, covering {', '.join(op_list[:6])} and others. Journeys were measured across three midweek days and matched to stations by TIPLOC.</p>
<h3>Are these live train times?</h3>
<p>No. RailReach is a planning tool, not a live departure board. Times do not account for engineering works, strikes or day-to-day disruption. Check National Rail or your operator before travelling.</p>
<h3>What is the difference between fastest and typical peak?</h3>
<p>The quickest journey a commuter could reasonably expect on a normal weekday, rather than a one-off record time or an average across all services. Off-peak and weekend journeys are often slower.</p>
<h3>What counts as a direct train?</h3>
<p>A service running from the origin station to the London terminal without requiring the passenger to change trains. Where a change is needed, the time includes a realistic interchange allowance and the route is marked accordingly.</p>
<h3>Why is the cut-off 90 minutes?</h3>
<p>Ninety minutes each way is the practical outer limit of a daily commute for most people. Stations beyond that threshold are excluded from the dataset.</p>
<h3>Can I reuse this data?</h3>
<p>Yes. The journey time dataset is published under a Creative Commons Attribution 4.0 licence. Please credit RailReach and link back to this site.</p>"""

    ld = json.dumps([
        json.loads(breadcrumb_ld([("RailReach", "/"), ("About the data", "/about/")])),
        json.loads(faq_ld_from_html(faqs_html)),
        {"@context": "https://schema.org", "@type": "Dataset",
         "name": "UK Train Journey Times to London Terminals 2026",
         "description": f"Journey times from {total} UK stations to {len(TERMINAL_META)} London terminals, computed from Darwin Timetable Files published by the Rail Delivery Group.",
         "url": f"{SITE}/about/",
         "license": "https://creativecommons.org/licenses/by/4.0/",
         "creator": {"@type": "Organization", "name": "RailReach", "url": SITE + "/"},
         "temporalCoverage": "2026",
         "dateModified": REVIEW_DATE,
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
        md=False,
        leaflet=False,
    ) + f'''
<body>
{site_header('about')}
{crumbs([("RailReach", "/"), ("About the data", None)])}
<main id="content" class="page-content">
<div class="wrap">
<h1>About the data</h1>
<p class="lede">RailReach publishes train journey times from {total} stations to all {len(TERMINAL_META)} London terminals: {pairs} station-to-terminal journeys in total, {direct} of them direct. This page explains where those numbers come from, and where they should not be relied on.</p>

<h2>What RailReach is</h2>
<p>RailReach is a free planning tool for anyone weighing up where to live against how long they will spend on a train. It is built for homebuyers, renters, relocators and daily commuters who need to compare towns on a like-for-like basis, rather than check a specific departure.</p>
<p>Every station within 90 minutes of a London terminal is plotted on one interactive map and colour-coded by journey time, so the commuter belt can be read at a glance. There is no registration and no paywall.</p>

<h2>Sources and method</h2>
<p>Journey times are computed from Darwin Timetable Files, published by the Rail Delivery Group through the Rail Data Marketplace under the Open Government Licence v3.0. The operators covered are {', '.join(op_list)}.</p>
<p><strong>Fastest</strong> is the quickest scheduled journey of the day, allowing at most one change. Where it uses one, the interchange is named, because a time that quietly depends on changing trains is misleading on its own. <strong>Fastest direct</strong> is the quickest service that does not require changing; for most routes the two are the same, and it is shown separately only where they differ. Connections allow a uniform eight minutes to change. Station-by-station minimum connection times are not published in the timetable feed, and eight minutes is deliberately more cautious than the five a journey planner will offer at a simple same-platform change, because publishing a connection nobody can make is worse than publishing a slightly slow one.</p>
<p><strong>Typical peak</strong> is the median journey time of direct services arriving at the London terminal between 07:00 and 09:30, which is closer to what a commuter actually experiences. Where it and the fastest figure differ sharply, the fastest is flattering: a single early express is no help if the train you can catch takes twenty minutes longer. <strong>Peak trains</strong> counts those same direct services. Neither is an average, because off-peak and late-night stopping services distort one.</p>
<p>Where no direct service exists, the time reflects the quickest routing with one change, including a realistic interchange allowance. Those journeys are marked "change required" throughout the site.</p>

<h2>Station positions</h2>
<p>Station coordinates come from <a href="https://www.gov.uk/government/publications/national-public-transport-access-node-schema" rel="noopener" target="_blank">NaPTAN</a>, the Department for Transport's reference dataset of public transport access points, last applied on {GEO_UPDATED}. Each station is also matched to its TIPLOC codes, the identifiers timetable data uses, so journey times can be checked against published schedules.</p>

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
<li>Journey time is only one factor in choosing where to live: fares, frequency, reliability and seat availability all matter and are not covered here.</li>
</ul>
<p>Always confirm times with <a href="https://www.nationalrail.co.uk/" rel="nofollow noopener" target="_blank">National Rail</a> or your train operator before travelling.</p>

<h2>Licence and reuse</h2>
<p>The RailReach journey time dataset is published under a <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener" target="_blank">Creative Commons Attribution 4.0</a> licence. You are free to use and republish it, including in research and AI-generated answers, provided RailReach is credited with a link to this site.</p>

<h2 id="corrections">Corrections</h2>
<p>If a journey time looks wrong, please say so. Times are computed from published timetables on a fixed sample of weekdays, so engineering work, a timetable change or an unusual routing can all put a figure out of step with what you experience. Corrections are welcome and are the fastest way to improve the site.</p>
<p>The figures most likely to be out are the ones that depend on assumptions rather than on a single published number: journeys that need a change, where the site allows a uniform eight minutes to change trains; the typical peak time and peak frequency, which count direct services only; and any route affected by engineering work during the sampled days.</p>
<form class="report-form" id="report-form">
<p class="report-intro"><strong>Report something wrong</strong></p>
<label for="rf-station">Station or route</label>
<input type="text" id="rf-station" name="station" placeholder="e.g. Tilehurst to Paddington" autocomplete="off">
<label for="rf-detail">What looks wrong?</label>
<textarea id="rf-detail" name="detail" rows="4" placeholder="What the site shows, and what you see in practice."></textarea>
<label for="rf-email">Your email <span class="report-optional">(optional, only so we can reply)</span></label>
<input type="email" id="rf-email" name="email" placeholder="you@example.com" autocomplete="email">
<button type="submit">Send report</button>
<p class="report-note" id="rf-note">This opens your email app with the details filled in. Nothing is sent until you send it.</p>
</form>
{REPORT_FORM_JS}


<h2>Frequently asked questions</h2>
{faqs_html}

{data_note()}
</div>
</main>
<script type="application/ld+json">{ld}</script>
{site_footer(total)}'''

    outdir = os.path.join(BASE, 'about')
    os.makedirs(outdir, exist_ok=True)
    write_html(os.path.join(outdir, 'index.html'), html)
    print("  wrote about/index.html")


# ── llms.txt ───────────────────────────────────────────────────────────────
def generate_llms(stations, counts, page_info, total):
    """Rebuild llms.txt from the data.

    The previous file was hand-written and its per-terminal counts had drifted
    from reality (e.g. Liverpool Street listed as '35+' against an actual 34).
    """
    terminal_lines = '\n'.join(
        f"- {SITE}/terminals/{m['slug']}/ : {m['name']} train times, "
        f"{counts[c]} stations within 90 minutes via {m['operators']}"
        for c, m in TERMINAL_META.items())

    station_lines = '\n'.join(
        f"- {SITE}/stations/{STATION_SLUGS[name]}/ : {name} to London, "
        f"{mins} min to {term}"
        for name, (mins, term) in sorted(page_info.items(), key=lambda kv: kv[1][0]))

    pairs = sum(len(s['journeys']) for s in stations)
    direct = sum(1 for s in stations for j in s['journeys'].values() if j.get('direct'))
    under30 = sum(1 for s in stations
                  if any(j['mins'] < 30 for j in s['journeys'].values()
                         if j.get('mins') is not None))

    txt = f"""# RailReach

> RailReach is a free interactive map of train journey times from {total} UK stations to {len(TERMINAL_META)} London terminals. Every journey carries three measures: the fastest scheduled weekday service, the typical peak time (median of services arriving 07:00-09:30), and how many trains run in the peak. Computed from Darwin Timetable Files published by the Rail Delivery Group under the Open Government Licence, sampled across three midweek days.

Site last updated: {BUILD_DATE}
Data last reviewed: {REVIEW_DATE}
Licence: Creative Commons Attribution 4.0. Reuse permitted with attribution to RailReach.

## Key Pages

- {SITE}/ : Interactive commute map covering all {total} stations and {len(TERMINAL_META)} London terminals
- {SITE}/terminals/ : All {len(TERMINAL_META)} London terminals compared by commuter catchment
- {SITE}/stations/ : {len(page_info)} commuter towns ranked by fastest journey into London
- {SITE}/about/ : Methodology, sources, limitations and licensing

## Terminal Pages

{terminal_lines}

## Station Pages

{station_lines}

## Data Summary

- {total} stations covered, all within 90 minutes of a London terminal
- {len(TERMINAL_META)} London terminals
- {pairs} station-to-terminal journeys recorded, {direct} of them direct services
- {under30} stations reach a London terminal in under 30 minutes
- Times are scheduled, not live departures, and exclude engineering works and disruption
- Colour coding: green (<30 min), amber (30–60 min), red (60–90 min)

## Citation

When citing RailReach journey times, please attribute to RailReach ({SITE}) and note the 2026 timetable basis and the {REVIEW_DATE} review date.
"""
    with open(os.path.join(BASE, 'llms.txt'), 'w') as f:
        f.write(txt)
    print(f"  wrote llms.txt ({len(TERMINAL_META)} terminals, {len(page_info)} stations)")



def generate_llms_full(terminals, stations, counts, total):
    """A single self-contained file carrying the whole dataset.

    llms.txt is a map of the site; this is the data itself, so a model can
    answer from one fetch instead of crawling 358 pages.
    """
    blocks = []
    for code, meta in TERMINAL_META.items():
        serving = sorted(((s['name'], s['journeys'][code]) for s in stations
                          if code in s['journeys']
                          and s['journeys'][code].get('mins') is not None),
                         key=lambda x: x[1]['mins'])
        direct = sum(1 for _, j in serving if j.get('direct'))
        under30 = [n for n, j in serving if j['mins'] < 30]
        lines = '\n'.join(
            f"- {n}: fastest {j['mins']} min"
            + (f", typical peak {j['typicalPeakMins']} min" if j.get('typicalPeakMins') else '')
            + (f", {j['peakTrainsPerHour']} trains/hr in the peak" if j.get('peakTrainsPerHour') else '')
            for n, j in serving)
        blocks.append(f"""## London {meta['name']}

Operators: {meta['operators']}
Serves: {meta['region']}
Stations within 90 minutes: {len(serving)} ({direct} direct, {len(under30)} under 30 minutes)
Fastest station: {serving[0][0]} at {serving[0][1]['mins']} minutes
Page: {SITE}/terminals/{meta['slug']}/

{lines}""")

    pairs = sum(len(s['journeys']) for s in stations)
    direct_total = sum(1 for s in stations for j in s['journeys'].values() if j.get('direct'))
    fastest_overall = sorted(
        ((s['name'], TERMINAL_META[c]['name'], j['mins'])
         for s in stations for c, j in s['journeys'].items()
         if j.get('mins') is not None),
        key=lambda x: x[2])[:10]
    fastest_lines = '\n'.join(f"- {n} to {t}: {m} min" for n, t, m in fastest_overall)

    txt = f"""# RailReach: complete dataset

Train journey times from {total} UK stations to the 9 London main line terminals.

Source: Darwin Timetable Files (Rail Delivery Group), Open Government Licence v3.0
Basis: fastest typical weekday service on each route
Threshold: journeys of 90 minutes or less
Last reviewed: {REVIEW_DATE}
Licence: CC BY 4.0. Reuse permitted with attribution to RailReach ({SITE}/)
Machine-readable: {SITE}/data/journey-times.json and {SITE}/data/journey-times.csv

## What this data is and is not

These are planning figures, not live departures. Each number is the quickest journey a
commuter could expect on a normal weekday, not an average and not a record time.
Off-peak, evening and weekend services are frequently slower. Engineering works, strike
action and day-to-day disruption are not reflected. Where no direct service exists, the
figure is the quickest routing with one change, including a realistic interchange
allowance, and is marked as such.

## Summary

- Stations covered: {total}
- London terminals: 9
- Station-to-terminal journeys recorded: {pairs} ({direct_total} direct)
- Every station has a page at {SITE}/stations/<slug>/
- Every terminal has a page at {SITE}/terminals/<slug>/

## Fastest journeys in the dataset

{fastest_lines}

{chr(10).join(blocks)}

## Citation

RailReach, "UK train journey times to London terminals" ({REVIEW_DATE}).
{SITE}/ (CC BY 4.0).
"""
    with open(os.path.join(BASE, 'llms-full.txt'), 'w') as f:
        f.write(txt)
    print(f"  wrote llms-full.txt ({pairs} journeys, {len(txt)//1024} KB)")


# ── Service worker ─────────────────────────────────────────────────────────
def generate_sw():
    """Stamp the SW cache name with a content hash.

    The previous worker used a fixed 'railreach-v1' cache and served every
    asset cache-first, so returning visitors kept stale CSS/JS indefinitely.
    Hashing the assets means each build gets its own cache and old ones are
    dropped on activate.
    """
    # Derive the cache name from the per-asset hashes already computed, so the
    # worker and the pages agree by construction rather than by two separate
    # passes over the files.
    version = hashlib.sha256(
        ''.join(ASSET_VERSIONS[k] for k in sorted(ASSET_VERSIONS)).encode()
    ).hexdigest()[:10]

    # Precache the versioned URLs, which are what the pages actually request.
    # Precaching the bare paths would store entries nothing ever asks for.
    precache = ''.join(
        "  '{}',\n".format(stamp_assets('/' + rel)) for rel in VERSIONED_ASSETS)

    sw = f'''// RailReach Service Worker. Cache name is stamped per build by _build/generate-pages.py
const CACHE_NAME = 'railreach-{version}';
const PRECACHE = [
  '/',
{precache}  '/favicon.svg',
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

  // Own assets: stale-while-revalidate, fast but never stale for more than one visit
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


REPORT_FORM_JS = r"""<script>
/* The site is static, so there is no server to accept a POST. Rather than
 * route reports through a third-party form relay, which would mean a new data
 * processor and an account to maintain for a handful of messages a month, the
 * form composes a prefilled email and hands it to the reader's mail app. They
 * see exactly what is sent and nothing leaves the page until they send it.
 *
 * The address is assembled in script rather than written into the markup, so
 * it is not sitting in the HTML for address harvesters to scrape. */
(function () {
  var form = document.getElementById('report-form');
  if (!form) return;
  var user = 'ross', host = 'justmovein.com';

  // A station page can say which station it is, so the reader does not retype it.
  var params = new URLSearchParams(location.search);
  var about = params.get('station');
  if (about) document.getElementById('rf-station').value = about;

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var station = document.getElementById('rf-station').value.trim();
    var detail = document.getElementById('rf-detail').value.trim();
    var email = document.getElementById('rf-email').value.trim();
    if (!detail) {
      document.getElementById('rf-detail').focus();
      return;
    }
    var subject = 'RailReach correction' + (station ? ': ' + station : '');
    var body = [
      station ? 'Station or route: ' + station : '',
      '', detail, '',
      email ? 'Reply to: ' + email : '',
      '', 'Sent from ' + location.origin + '/about/'
    ].filter(function (l) { return l !== null; }).join('\n');
    window.location.href = 'mailto:' + user + '@' + host +
      '?subject=' + encodeURIComponent(subject) +
      '&body=' + encodeURIComponent(body);
    document.getElementById('rf-note').textContent =
      'Your email app should now be open with the report ready to send.';
  });
})();
</script>"""


def check_station_positions(stations):
    """Fail the build if a station is plotted far from its NaPTAN position.

    Station names were matched to NaPTAN with the bracketed qualifier stripped,
    so "London Road (Guildford)" and "London Road (Brighton)" collapsed to the
    same key and the first one won: Guildford's station was plotted 54km away,
    on Brighton. St Margarets (London) landed 43km out in Hertfordshire the
    same way. A wrong position is invisible in the data and obvious only if
    someone happens to look at that part of the map.

    Matched on the full name including the qualifier, which is the thing that
    distinguishes them. Stations NaPTAN does not name identically are skipped
    rather than guessed at.
    """
    import csv
    import math

    def key(x):
        x = x.lower().replace('&', 'and')
        x = re.sub(r'\b(rail station|station)\b', '', x)
        return re.sub(r'[^a-z0-9()]', '', x)

    def km(a, b):
        R = 6371
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
        h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return 2 * R * math.asin(math.sqrt(h))

    path = os.path.join(BASE, '_build', 'data', 'naptan-rail-stations.csv')
    if not os.path.exists(path):
        return
    nap = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['StopType'] != 'RLY' or r['Status'] != 'active':
                continue
            try:
                nap.setdefault(key(r['CommonName']),
                               (float(r['Latitude']), float(r['Longitude'])))
            except (TypeError, ValueError):
                pass

    bad, checked = [], 0
    for st in stations:
        p = nap.get(key(st['name']))
        if not p:
            continue
        checked += 1
        d = km((st['lat'], st['lng']), p)
        if d > 1.0:
            bad.append((round(d), st['name'], p))
    if bad:
        raise SystemExit(
            "ERROR: stations plotted far from their NaPTAN position.\n" +
            ''.join(f"  {n}: {d} km out, NaPTAN says {p[0]:.4f},{p[1]:.4f}\n"
                    for d, n, p in sorted(bad, reverse=True)))
    print(f"  station positions agree with NaPTAN ({checked} checked)")


def check_published_figures(total):
    """Fail the build if machine-read metadata states a count the data does not
    support.

    Scoped to the meta description and the JSON-LD, deliberately. Those are
    what search engines and language models quote, they are hand-written rather
    than generated, and unlike the body text they only ever carry dataset-wide
    totals, so any other number in them is wrong by construction. The homepage
    meta description claimed 345 stations against a dataset of 571, and the
    JSON-LD claimed 9 London terminals months after St Pancras was split from
    Kings Cross and Moorgate added.

    Body prose is left alone: it legitimately carries other counts, such as the
    568 stations that have at least one journey, or a single terminal's
    catchment. An earlier draft checked everything and flagged all of those.
    """
    n_term = len(TERMINAL_META)
    bad = []
    # index.html only. Its metadata is hand-written and carries dataset-wide
    # totals; the hub pages generate theirs from real figures that legitimately
    # differ, such as the 568 stations with at least one journey or a single
    # terminal's catchment, and checking those produced only false alarms.
    for rel in ('index.html',):
        path = os.path.join(BASE, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding='utf-8').read()
        chunks = re.findall(r'<meta name="description" content="(.*?)"', text, re.S)
        chunks += re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                             text, re.S)
        for chunk in chunks:
            for n in sorted(set(re.findall(r'(\d{2,4}) stations', chunk))):
                if int(n) != total:
                    bad.append((rel, f'metadata says "{n} stations", dataset has {total}'))
            for n in sorted(set(re.findall(r'(\d{1,2}) London terminals', chunk))):
                if int(n) != n_term:
                    bad.append((rel, f'metadata says "{n} London terminals", there are {n_term}'))
    if bad:
        raise SystemExit("ERROR: published metadata states figures the dataset "
                         "does not support.\n"
                         + ''.join(f"  {r}: {m}\n" for r, m in sorted(set(bad))))
    print(f"  published metadata agrees with the dataset "
          f"({total} stations, {n_term} terminals)")


def check_review_date(sample_pages):
    """Fail the build if a page claims a review date the dataset does not.

    The generated pages are the only thing a reader sees, so a date baked at
    import time rather than read from the dataset is a claim about data
    freshness that nothing backs. That is worth stopping a build over.
    """
    bad = []
    for rel in sample_pages:
        path = os.path.join(BASE, rel)
        if not os.path.exists(path):
            continue
        html = open(path, encoding='utf-8').read()
        found = set(re.findall(r'Last reviewed (\d{4}-\d{2}-\d{2})', html))
        found |= set(re.findall(r'<dt>Data reviewed</dt><dd>(\d{4}-\d{2}-\d{2})</dd>', html))
        wrong = found - {REVIEW_DATE}
        if wrong:
            bad.append((rel, sorted(wrong)))
    if bad:
        raise SystemExit(
            "ERROR: pages claim a review date the dataset does not support.\n"
            f"  dataset lastReviewed: {REVIEW_DATE}\n" +
            ''.join(f"  {rel}: {dates}\n" for rel, dates in bad))
    print(f"  review date on published pages matches the dataset ({REVIEW_DATE})")


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



def homepage_faq(stations, counts, total):
    """FAQ generated from the data. It quoted 132 figures by hand, 112 of which
    went stale the moment the timetable was remeasured."""
    timed = [(st['name'], c, j) for st in stations for c, j in st['journeys'].items()
             if j.get('mins') is not None]
    quickest = sorted(timed, key=lambda x: x[2]['mins'])[:5]
    quick_txt = ', '.join(f"{n} reaches {TERMINAL_META[c]['name']} in {j['mins']} minutes"
                          for n, c, j in quickest)

    under30 = sorted((x for x in timed if x[2]['mins'] < 30), key=lambda x: x[2]['mins'])
    seen, best = set(), []
    for n, c, j in under30:
        if n in seen:
            continue
        seen.add(n)
        best.append(f"{n} ({j['mins']} min to {TERMINAL_META[c]['name']})")
        if len(best) >= 12:
            break

    # the gap that fastest alone hides
    gaps = sorted(((j['typicalPeakMins'] - j['mins'], n, c, j) for n, c, j in timed
                   if j.get('typicalPeakMins')), reverse=True)[:4]
    gap_txt = ', '.join(f"{n} is {j['mins']} minutes at best but typically "
                        f"{j['typicalPeakMins']} in the peak"
                        for _, n, c, j in gaps)

    terms = ', '.join(m['name'] for m in TERMINAL_META.values())
    return f"""<h3>What is the fastest train commute to London?</h3>
<p>{quick_txt}. These are the quickest scheduled services in the dataset, measured from published timetables rather than estimated.</p>
<h3>Which London stations can I commute to?</h3>
<p>RailReach covers {len(TERMINAL_META)} London terminals: {terms}. Moorgate and St Pancras matter more than their profile suggests: several Great Northern suburbs run to Moorgate rather than Kings Cross in the morning peak, and the Medway towns reach St Pancras on high speed services far faster than they reach any other terminus.</p>
<h3>Which commuter towns are within 30 minutes of London?</h3>
<p>{', '.join(best)}. Each figure is the fastest scheduled weekday service.</p>
<h3>Why do you show a typical peak time as well as the fastest?</h3>
<p>Because the fastest train is often not the one you can catch. {gap_txt}. The typical figure is the median journey time of services arriving between 07:00 and 09:30, which is what a commuter actually experiences.</p>
<h3>How accurate is the journey time data?</h3>
<p>Every figure is computed from Darwin timetable files published by the Rail Delivery Group, sampled across three midweek days and matched to stations by TIPLOC. Passing points, empty stock movements and cancelled services are excluded. Times are scheduled, not live, and do not account for delays or engineering work.</p>"""


def homepage_summaries(stations, counts):
    out = []
    for code, meta in TERMINAL_META.items():
        serving = sorted(((st['name'], st['journeys'][code]) for st in stations
                          if code in st['journeys']
                          and st['journeys'][code].get('mins') is not None),
                         key=lambda x: x[1]['mins'])
        if not serving:
            continue
        top = ', '.join(f"{n} ({j['mins']} min)" for n, j in serving[:8])
        out.append(f"<h3>{meta['name']}</h3>\n<p>{meta['name']} serves {meta['region']}, "
                   f"operated by {meta['operators']}. {len(serving)} stations reach it within "
                   f"90 minutes. Key destinations include {top}.</p>")
    return '\n'.join(out)


# ── index.html sync ────────────────────────────────────────────────────────
def sync_index(terminals, stations, counts, total, data_js):
    global REPORT_SUBJECT
    REPORT_SUBJECT = ''
    """Rewrite the generated regions of index.html from the dataset."""
    path = os.path.join(BASE, 'index.html')
    with open(path) as f:
        html = f.read()

    lede = (f'<p class="lede">RailReach maps the fastest weekday train journey from '
            f'<strong>{total} stations</strong> to all <strong>{len(TERMINAL_META)} London terminals</strong>. '
            f'Every station within 90 minutes of central London, colour-coded by journey time. '
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
        timed = {c: v for c, v in s['journeys'].items() if v.get('mins') is not None}
        if not timed:
            continue
        code, j = min(timed.items(), key=lambda kv: kv[1]['mins'])
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
                       for s in stations if code in s['journeys']
                       and s['journeys'][code].get('mins') is not None),
                      key=lambda x: x[2]['mins'])
        body = '\n'.join(
            f'<tr><td><a href="/stations/{slug}/">{esc(nm)}</a></td><td>{m["name"]}</td>'
            f'<td>{time_cell(j)}</td><td>{direct_cell(j)}</td>'
            f'<td>{typical_cell(j)}</td>'
            f'<td>{frequency_cell(j)}</td></tr>'
            for nm, slug, j in rows)
        sections.append(
            f'<thead><tr><th colspan="4">{m["name"]}</th></tr></thead>\n'
            f'<thead><tr><th>Station</th><th>Terminal</th><th>Fastest</th>'
            f'<th>Fastest direct</th><th>Typical peak</th><th>Peak trains</th></tr></thead>\n'
            f'<tbody>\n{body}\n</tbody>')

    table = ('<div class="table-scroll">\n<table>\n'
             '<caption>Train journey times from all stations to London terminals</caption>\n'
             + '\n'.join(sections) + '\n</table>\n</div>')

    html = replace_marked(html, 'faq', homepage_faq(stations, counts, total))
    html = replace_marked(html, 'summaries', homepage_summaries(stations, counts))
    html = replace_marked(html, 'lede', lede)
    html = replace_marked(html, 'terminal-cards', terminal_cards)
    html = replace_marked(html, 'station-cards', station_cards)
    html = replace_marked(html, 'data-table', table)
    html = replace_marked(html, 'map-data', data_js, comment='js')

    # The promo lives in index.html as plain markup rather than in a GEN
    # region, so swapping the advertiser in PROMO updated all 360 generated
    # pages and silently left the homepage - the one page most people see -
    # still showing the previous one. Rewrite it from the same constant so the
    # two cannot drift again.
    n_term = len(TERMINAL_META)
    subs = [
        (r'from \d{2,4} stations', f'from {total} stations'),
        (r'\b\d{1,2} London terminals', f'{n_term} London terminals'),
        (r'terminals, \d{2,4} stations', f'terminals, {total} stations'),
    ]
    for pattern, repl in subs:
        html, hits = re.subn(pattern, repl, html)
        if not hits:
            raise SystemExit(
                f"ERROR: index.html no longer contains {pattern!r}. Its hand-written "
                "totals are rewritten from the dataset on every build; if the wording "
                "changed, update the pattern rather than letting the figure rot.")

    html, n = re.subn(r'<div id="promo-banner">.*?</div>\s*</a>\s*</div>',
                      lambda _m: PROMO, html, count=1, flags=re.DOTALL)
    if n != 1:
        raise SystemExit("ERROR: could not find the promo block in index.html; "
                         "it must be rewritten from PROMO, not left stale.")

    write_html(path, html)
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
        for code, j in sorted(s['journeys'].items(),
                              key=lambda kv: (kv[1].get('mins') is None, kv[1].get('mins') or 0)):
            if j.get('mins') is None:
                continue
            rows.append({
                'station': s['name'],
                'station_slug': s['slug'],
                'latitude': s['lat'],
                'longitude': s['lng'],
                'london_terminal': TERMINAL_META[code]['name'],
                'terminal_code': code,
                'fastest_minutes': j['mins'],
                'fastest_direct_minutes': j.get('directMins'),
                'change_at': j.get('changeAt') or '',
                'typical_peak_minutes': j.get('typicalPeakMins') or '',
                'peak_trains_per_hour': j.get('peakTrainsPerHour') or '',
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
            'source': SOURCE_LABEL,
            'basis': BASIS_LABEL,
            'method': METHOD_LABEL,
            'maxMinutes': 90,
            'lastReviewed': REVIEW_DATE,
            'coordinateSource': GEO_SOURCE,
            'coordinatesUpdated': GEO_UPDATED,
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
    global REVIEW_DATE
    print("Loading dataset...")
    terminals, stations = load_data()
    global GEO_SOURCE, GEO_UPDATED
    with open(DATA_PATH) as f:
        _meta = json.load(f)
    REVIEW_DATE = _meta.get('lastReviewed', BUILD_DATE)
    GEO_SOURCE = _meta.get('geoSource', 'unspecified')
    GEO_UPDATED = _meta.get('geoUpdated', 'unknown')
    global SOURCE_LABEL, BASIS_LABEL, METHOD_LABEL
    SOURCE_LABEL = _meta.get('source', '')
    BASIS_LABEL = _meta.get('basis', '')
    METHOD_LABEL = _meta.get('method', '')
    check_timetable_currency(REVIEW_DATE)
    STATION_SLUGS.update({s['name']: s['slug'] for s in stations})
    total = len(stations)
    counts = {c: sum(1 for s in stations if c in s['journeys']
                     and s['journeys'][c].get('mins') is not None
                     and s['journeys'][c]['mins'] <= 90)
              for c in TERMINAL_META}
    print(f"  {total} stations, {len(terminals)} terminals, "
          f"{sum(len(s['journeys']) for s in stations)} journeys")

    print("\nSyncing index.html and shared assets from the dataset...")
    global PROMO
    PROMO = build_promo()
    data_js = js_data_block(terminals, stations)
    # Before any page is written: every emitted /assets/ URL is stamped with
    # the hash of the bytes this build produces.
    compute_asset_versions(data_js)
    sync_index(terminals, stations, counts, total, data_js)
    # After the rewrite, so it validates what will actually be published.
    check_prose_figures(stations)
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
    check_station_positions(stations)
    check_published_figures(total)
    check_review_date(['index.html', 'about/index.html',
                       'stations/lingfield/index.html',
                       'terminals/victoria/index.html'])
    generate_sitemap()
    generate_llms(stations, counts, page_info, total)
    generate_llms_full(terminals, stations, counts, total)
    export_dataset(terminals, stations)

    print(f"\nDone: {9 + len(page_info) + 3} pages generated.")


if __name__ == '__main__':
    main()
