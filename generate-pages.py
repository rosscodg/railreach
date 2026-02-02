#!/usr/bin/env python3
"""Generate all 36 spoke pages (9 terminal + 27 station) for RailReach."""

import os
import re
import json
import math

BASE = os.path.dirname(os.path.abspath(__file__))

# ── Terminal metadata ──────────────────────────────────────────────────────
TERMINAL_META = {
    'KGX': {'slug': 'kings-cross', 'name': 'Kings Cross', 'operators': 'Great Northern, Thameslink, LNER'},
    'WAT': {'slug': 'waterloo', 'name': 'Waterloo', 'operators': 'South Western Railway'},
    'PAD': {'slug': 'paddington', 'name': 'Paddington', 'operators': 'Great Western Railway, Elizabeth Line'},
    'LBG': {'slug': 'london-bridge', 'name': 'London Bridge', 'operators': 'Southeastern, Southern, Thameslink'},
    'VIC': {'slug': 'victoria', 'name': 'Victoria', 'operators': 'Southeastern, Southern'},
    'LST': {'slug': 'liverpool-street', 'name': 'Liverpool Street', 'operators': 'Greater Anglia'},
    'EUS': {'slug': 'euston', 'name': 'Euston', 'operators': 'Avanti West Coast, London Northwestern'},
    'MYB': {'slug': 'marylebone', 'name': 'Marylebone', 'operators': 'Chiltern Railways'},
    'FST': {'slug': 'fenchurch-street', 'name': 'Fenchurch Street', 'operators': 'c2c'},
}

STATION_SLUGS = {
    'Cambridge': 'cambridge', 'Reading': 'reading', 'Oxford': 'oxford',
    'Brighton': 'brighton', 'Guildford': 'guildford', 'Woking': 'woking',
    'St Albans City': 'st-albans', 'Stevenage': 'stevenage',
    'Milton Keynes Central': 'milton-keynes', 'Chelmsford': 'chelmsford',
    'Sevenoaks': 'sevenoaks', 'Basingstoke': 'basingstoke',
    'Winchester': 'winchester', 'Watford Junction': 'watford',
    'Swindon': 'swindon', 'Colchester': 'colchester', 'Ipswich': 'ipswich',
    'Peterborough': 'peterborough', 'Bedford': 'bedford',
    'High Wycombe': 'high-wycombe', 'Tonbridge': 'tonbridge',
    'Tunbridge Wells': 'tunbridge-wells', 'Crawley': 'crawley',
    'Bromley South': 'bromley-south', 'Richmond': 'richmond',
    'Slough': 'slough', 'Maidenhead': 'maidenhead',
}

# ── Parse stations data from index.html ────────────────────────────────────
def parse_index():
    with open(os.path.join(BASE, 'index.html'), 'r') as f:
        html = f.read()

    # Extract the JS block between line markers
    m = re.search(r'(const TERMINALS = \{.*?\};)\s*(.*?)(const STATIONS = \[.*?\];)', html, re.DOTALL)
    terminals_js = m.group(1)
    stations_js = m.group(3)

    # Parse TERMINALS
    terminals = {}
    for tm in re.finditer(r'(\w+):\s*\{\s*name:\s*"([^"]+)",\s*lat:\s*([\d.-]+),\s*lng:\s*([\d.-]+)\s*\}', terminals_js):
        terminals[tm.group(1)] = {'name': tm.group(2), 'lat': float(tm.group(3)), 'lng': float(tm.group(4))}

    # Parse STATIONS - use greedy match for journeys block (handle nested braces)
    stations = []
    for sm in re.finditer(r'\{\s*name:\s*"([^"]+)",\s*lat:\s*([\d.-]+),\s*lng:\s*([\d.-]+),\s*journeys:\s*\{((?:[^{}]|\{[^}]*\})*)\}\s*\}', stations_js):
        name = sm.group(1)
        lat = float(sm.group(2))
        lng = float(sm.group(3))
        journeys_str = sm.group(4)
        journeys = {}
        for jm in re.finditer(r'(\w+):\s*\{\s*mins:\s*(\d+),\s*direct:\s*(true|false)\s*\}', journeys_str):
            journeys[jm.group(1)] = {'mins': int(jm.group(2)), 'direct': jm.group(3) == 'true'}
        stations.append({'name': name, 'lat': lat, 'lng': lng, 'journeys': journeys})

    return terminals, stations, terminals_js + '\n\n' + stations_js


def write_stations_data_js(terminals_js_raw):
    """Write assets/js/stations-data.js with TERMINALS and STATIONS constants."""
    os.makedirs(os.path.join(BASE, 'assets', 'js'), exist_ok=True)
    with open(os.path.join(BASE, 'index.html'), 'r') as f:
        html = f.read()
    lines = html.split('\n')
    # Lines 171-587 (1-indexed) = indices 170-586
    js_block = '\n'.join(lines[170:587])
    path = os.path.join(BASE, 'assets', 'js', 'stations-data.js')
    with open(path, 'w') as f:
        f.write(js_block + '\n')
    print(f"  Created {path}")


def write_map_core_js():
    """Write assets/js/map-core.js with shared map functions."""
    path = os.path.join(BASE, 'assets', 'js', 'map-core.js')
    with open(path, 'w') as f:
        f.write("""// Shared map utilities for RailReach spoke pages
function initMap(lat, lng, zoom) {
  const map = L.map('map').setView([lat, lng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
  }).addTo(map);
  return map;
}

function getColor(mins) {
  if (mins < 30) return '#22c55e';
  if (mins < 60) return '#f59e0b';
  return '#ef4444';
}

function createStationMarker(map, lat, lng, mins, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 7, fillColor: getColor(mins), color: '#fff',
    weight: 2, opacity: 1, fillOpacity: 0.85
  }).bindPopup(popupHtml).addTo(map);
}

function createTerminalMarker(map, lat, lng, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 12, fillColor: '#7c3aed', color: '#fff',
    weight: 3, opacity: 1, fillOpacity: 0.9
  }).bindPopup(popupHtml).addTo(map);
}
""")
    print(f"  Created {path}")


def haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')


def json_esc(s):
    return json.dumps(s)[1:-1]  # strip quotes


# ── Generate terminal pages ────────────────────────────────────────────────
def generate_terminal_page(code, terminals, stations):
    meta = TERMINAL_META[code]
    slug = meta['slug']
    name = meta['name']
    operators = meta['operators']
    t = terminals[code]

    # Stations serving this terminal
    serving = []
    for s in stations:
        j = s['journeys'].get(code)
        if j and j['mins'] <= 90:
            serving.append((s['name'], j['mins'], j['direct'], s['lat'], s['lng']))
    serving.sort(key=lambda x: x[1])
    count = len(serving)

    top3 = ', '.join(f"{s[0]} ({s[1]} min)' " for s in serving[:3]).rstrip("' ")
    top3 = ', '.join(f"{s[0]} ({s[1]} min)" for s in serving[:3])
    top5 = ', '.join(s[0] for s in serving[:5])

    # Sorted station rows
    rows = '\n'.join(f'<tr><td>{esc(s[0])}</td><td>{s[1]} min</td><td>{"Yes" if s[2] else "No"}</td></tr>' for s in serving)

    # Other terminal links
    other_links = []
    for c2, m2 in TERMINAL_META.items():
        if c2 == code:
            other_links.append(f'<a class="current" href="/terminals/{m2["slug"]}/">{m2["name"]}</a>')
        else:
            other_links.append(f'<a href="/terminals/{m2["slug"]}/">{m2["name"]}</a>')
    terminal_nav = '\n'.join(other_links)

    # Under-30 stations
    under30 = [s for s in serving if s[1] < 30]
    under30_names = ', '.join(s[0] for s in under30[:5]) if under30 else 'none within 30 minutes'

    # Fastest station
    fastest = serving[0] if serving else None
    fastest_text = f"The fastest connection is from {fastest[0]} at just {fastest[1]} minutes." if fastest else ""

    # FAQ content unique to this terminal
    faqs_html = f"""<h3>What is the fastest train to {name}?</h3>
<p>{fastest_text} Services are operated by {operators}.</p>
<h3>Which commuter towns are within 30 minutes of {name}?</h3>
<p>Stations reachable within 30 minutes include {under30_names}. These are popular choices for London commuters seeking shorter journey times.</p>
<h3>How many stations connect to {name}?</h3>
<p>{count} stations have services to London {name} within 90 minutes. The terminal is served by {operators}.</p>
<h3>What areas does {name} serve?</h3>
<p>London {name} primarily serves {"the north and east of England" if code in ("KGX","EUS") else "the south and southeast" if code in ("VIC","LBG") else "the west and southwest" if code in ("PAD","WAT") else "East Anglia and Essex" if code in ("LST","FST") else "the Chiltern hills and Buckinghamshire"}. Key destinations include {top5}.</p>
<h3>Is {name} a good commuter terminal?</h3>
<p>Yes. With {count} stations within 90 minutes and frequent peak-hour services, {name} is one of London{"&#39;"}s busiest commuter terminals. Top commuter stations include {top5}.</p>"""

    # FAQ JSON-LD
    faq_items = []
    for faq_m in re.finditer(r'<h3>(.*?)</h3>\s*<p>(.*?)</p>', faqs_html, re.DOTALL):
        faq_items.append({
            "@type": "Question",
            "name": faq_m.group(1),
            "acceptedAnswer": {"@type": "Answer", "text": re.sub(r'<[^>]+>', '', faq_m.group(2))}
        })

    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "RailReach", "item": "https://railreach.co.uk/"},
            {"@type": "ListItem", "position": 2, "name": f"{name} Train Times", "item": f"https://railreach.co.uk/terminals/{slug}/"}
        ]
    }, indent=0)

    faq_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_items
    }, indent=0)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} Train Times | Journey Times to London {name} | RailReach</title>
<meta name="description" content="Train journey times to London {name} from {count}+ stations. Interactive map — {top3}. Free 2026 timetable data.">
<link rel="canonical" href="https://railreach.co.uk/terminals/{slug}/">
<meta property="og:type" content="website">
<meta property="og:url" content="https://railreach.co.uk/terminals/{slug}/">
<meta property="og:title" content="{name} Train Times | RailReach">
<meta property="og:description" content="Interactive map showing train times to {name} from {count}+ stations.">
<meta property="og:site_name" content="RailReach">
<meta property="og:image" content="https://railreach.co.uk/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://railreach.co.uk/og-image.png">
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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="../../assets/css/shared.css">
</head>
<body>
<header class="site-header">
<nav aria-label="Breadcrumb"><ol class="breadcrumb"><li><a href="/">RailReach</a></li><li>{name} Train Times</li></ol></nav>
</header>
<div id="map" role="application" aria-label="Map of train journey times to {name}"></div>
<div class="legend">
  <h4>Journey Time</h4>
  <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div> Under 30 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> 30–60 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div> 60–90 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#7c3aed"></div> London Terminal</div>
</div>
<div class="station-count" id="station-count"></div>
<div id="promo-banner">
  <a id="promo-slot-1" href="https://www.connells.co.uk/" target="_blank" rel="noopener">
    <div class="promo-connells">
      <div class="promo-logo">Connells<span>Est. 1936</span></div>
      <div class="promo-body">
        <div class="promo-headline">Found your perfect commute? Now find your perfect home.</div>
        <div class="promo-sub">Over 150 branches nationwide &bull; Free online valuations &bull; Expert local knowledge</div>
      </div>
      <div class="promo-cta">Search Now</div>
    </div>
  </a>
</div>
<button class="toggle-content" onclick="document.querySelector('.spoke-content').classList.toggle('open');this.textContent=this.textContent==='Show Details'?'Hide Details':'Show Details'">Show Details</button>
<div class="spoke-content">
<h1>Train Journey Times to {name}</h1>
<p>{name} is served by {operators}. {count}+ stations connect to {name} within 90 minutes. Key commuter towns include {top5}.</p>
<h2>Other London Terminals</h2>
<div class="terminal-nav">{terminal_nav}</div>
<h2>Frequently Asked Questions</h2>
{faqs_html}
<h2>All Stations to {name}</h2>
<table><thead><tr><th>Station</th><th>Time</th><th>Direct?</th></tr></thead><tbody>
{rows}
</tbody></table>
</div>

<script type="application/ld+json">{breadcrumb_ld}</script>
<script type="application/ld+json">{faq_ld}</script>

<script src="../../assets/js/stations-data.js"></script>
<script>
const code='{code}';
const t=TERMINALS[code];
const map=L.map('map').setView([t.lat,t.lng],8);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors',maxZoom:18}}).addTo(map);
L.circleMarker([t.lat,t.lng],{{radius:12,fillColor:'#7c3aed',color:'#fff',weight:3,opacity:1,fillOpacity:0.9}}).bindPopup('<strong>'+t.name+'</strong><br>London Terminal').addTo(map);
function getColor(m){{if(m<30)return'#22c55e';if(m<60)return'#f59e0b';return'#ef4444'}}
let count=0;
STATIONS.forEach(s=>{{const j=s.journeys[code];if(j&&j.mins<=90){{L.circleMarker([s.lat,s.lng],{{radius:7,fillColor:getColor(j.mins),color:'#fff',weight:2,opacity:1,fillOpacity:0.85}}).bindPopup('<strong>'+s.name+'</strong><br>To '+t.name+': <strong>'+j.mins+' min</strong><br>'+(j.direct?'Direct train':'Requires change')).addTo(map);count++}}}});
document.getElementById('station-count').textContent=count+' stations within 90 min of '+t.name;
</script>
<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');</script>
</body></html>'''

    outdir = os.path.join(BASE, 'terminals', slug)
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, 'index.html')
    with open(outpath, 'w') as f:
        f.write(html)
    print(f"  Terminal: {name} -> {outpath} ({count} stations)")


# ── Generate station pages ─────────────────────────────────────────────────
def generate_station_page(station_name, slug, terminals, stations):
    # Find station data
    sdata = None
    for s in stations:
        if s['name'] == station_name:
            sdata = s
            break
    if not sdata:
        print(f"  WARNING: Station '{station_name}' not found in data!")
        return

    journeys = sdata['journeys']
    # Sort journeys by time
    sorted_journeys = sorted(journeys.items(), key=lambda x: x[1]['mins'])

    # Build description with times
    times_desc = ', '.join(f"{TERMINAL_META[c]['name']} ({j['mins']} min)" for c, j in sorted_journeys[:3])

    # Nearby stations (by geographic distance, excluding self)
    dists = []
    for s2 in stations:
        if s2['name'] == station_name:
            continue
        d = haversine(sdata['lat'], sdata['lng'], s2['lat'], s2['lng'])
        # Only include stations that also have a slug (i.e. are spoke pages) OR just list nearest by data
        dists.append((s2['name'], d, s2))
    dists.sort(key=lambda x: x[1])
    nearby = dists[:5]

    # Nearby links - link if they have a spoke page, otherwise just text
    nearby_html_items = []
    for nb_name, nb_dist, nb_data in nearby:
        nb_slug = STATION_SLUGS.get(nb_name)
        if nb_slug:
            nearby_html_items.append(f'<li><a href="/stations/{nb_slug}/">{esc(nb_name)}</a> ({nb_dist:.0f} km away)</li>')
        else:
            nearby_html_items.append(f'<li>{esc(nb_name)} ({nb_dist:.0f} km away)</li>')
    nearby_html = '\n'.join(nearby_html_items)

    # Journey table
    table_rows = '\n'.join(
        f'<tr><td><a href="/terminals/{TERMINAL_META[c]["slug"]}/">{TERMINAL_META[c]["name"]}</a></td><td>{j["mins"]} min</td><td>{"Yes" if j["direct"] else "No"}</td></tr>'
        for c, j in sorted_journeys
    )

    # Terminal nav
    terminal_nav = '\n'.join(
        f'<a href="/terminals/{m["slug"]}/">{m["name"]}</a>'
        for m in TERMINAL_META.values()
    )

    # Determine fastest
    fastest_code, fastest_j = sorted_journeys[0]
    fastest_name = TERMINAL_META[fastest_code]['name']

    # Determine which terminals serve this station
    terminal_list = ', '.join(TERMINAL_META[c]['name'] for c, _ in sorted_journeys)
    direct_terminals = [TERMINAL_META[c]['name'] for c, j in sorted_journeys if j['direct']]
    direct_text = ', '.join(direct_terminals) if direct_terminals else 'none (all require changes)'

    # FAQ
    faqs_html = f"""<h3>How long does it take to get from {station_name} to London?</h3>
<p>The fastest train from {station_name} reaches London {fastest_name} in {fastest_j['mins']} minutes. {station_name} connects to {len(sorted_journeys)} London terminal{"s" if len(sorted_journeys) > 1 else ""}: {terminal_list}.</p>
<h3>Which London station should I travel to from {station_name}?</h3>
<p>The quickest route is to {fastest_name} ({fastest_j['mins']} min{", direct" if fastest_j['direct'] else ", requires change"}). Direct services are available to {direct_text}.</p>
<h3>Is {station_name} a good commuter town for London?</h3>
<p>With a fastest journey time of {fastest_j['mins']} minutes to London {fastest_name}, {station_name} {"is an excellent commuter choice with a sub-30-minute journey" if fastest_j['mins'] < 30 else "offers a reasonable commute under an hour" if fastest_j['mins'] < 60 else "is a longer commute but offers good value and quality of life"}. {"Direct trains make the commute straightforward." if fastest_j['direct'] else "A change of train is required on most services."}</p>
<h3>What are the nearest stations to {station_name}?</h3>
<p>Nearby stations include {', '.join(n[0] for n in nearby[:3])}. These offer alternative routes into London from the {station_name} area.</p>"""

    faq_items = []
    for faq_m in re.finditer(r'<h3>(.*?)</h3>\s*<p>(.*?)</p>', faqs_html, re.DOTALL):
        faq_items.append({
            "@type": "Question",
            "name": faq_m.group(1),
            "acceptedAnswer": {"@type": "Answer", "text": re.sub(r'<[^>]+>', '', faq_m.group(2))}
        })

    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "RailReach", "item": "https://railreach.co.uk/"},
            {"@type": "ListItem", "position": 2, "name": f"{station_name} to London", "item": f"https://railreach.co.uk/stations/{slug}/"}
        ]
    }, indent=0)

    faq_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": faq_items
    }, indent=0)

    # Build polyline JS - lines from station to each terminal
    polyline_js_parts = []
    for c, j in sorted_journeys:
        tm = terminals[c]
        dash = '' if j['direct'] else "dashArray:'8,6',"
        polyline_js_parts.append(
            f"L.polyline([[{sdata['lat']},{sdata['lng']}],[{tm['lat']},{tm['lng']}]],{{color:getColor({j['mins']}),weight:3,opacity:0.7,{dash}}}).addTo(map);"
        )
    polylines_js = '\n'.join(polyline_js_parts)

    # Terminal markers JS
    term_markers_parts = []
    for c, j in sorted_journeys:
        direct_label = "Direct" if j['direct'] else "Requires change"
        term_markers_parts.append(
            f"L.circleMarker([{terminals[c]['lat']},{terminals[c]['lng']}],{{radius:12,fillColor:'#7c3aed',color:'#fff',weight:3,opacity:1,fillOpacity:0.9}}).bindPopup('<strong>{json_esc(TERMINAL_META[c]['name'])}</strong><br>{j['mins']} min from {json_esc(station_name)}<br>{direct_label}').addTo(map);"
        )
    term_markers_js = '\n'.join(term_markers_parts)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{station_name} to London Train Times | Journey Times from {station_name} | RailReach</title>
<meta name="description" content="Train times from {station_name} to London — {times_desc}. Interactive map with direct and indirect routes. Free 2026 timetable data.">
<link rel="canonical" href="https://railreach.co.uk/stations/{slug}/">
<meta property="og:type" content="website">
<meta property="og:url" content="https://railreach.co.uk/stations/{slug}/">
<meta property="og:title" content="{station_name} to London Train Times | RailReach">
<meta property="og:description" content="Journey times from {station_name} to London terminals. {fastest_name} in {fastest_j['mins']} min.">
<meta property="og:site_name" content="RailReach">
<meta property="og:image" content="https://railreach.co.uk/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://railreach.co.uk/og-image.png">
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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="../../assets/css/shared.css">
</head>
<body>
<header class="site-header">
<nav aria-label="Breadcrumb"><ol class="breadcrumb"><li><a href="/">RailReach</a></li><li>{station_name} to London</li></ol></nav>
</header>
<div id="map" role="application" aria-label="Map showing train routes from {station_name} to London"></div>
<div class="legend">
  <h4>Journey Time</h4>
  <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div> Under 30 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> 30–60 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div> 60–90 min</div>
  <div class="legend-item"><div class="legend-dot" style="background:#3b82f6"></div> This Station</div>
  <div class="legend-item"><div class="legend-dot" style="background:#7c3aed"></div> London Terminal</div>
</div>
<div class="station-count" id="station-count"></div>
<div id="promo-banner">
  <a id="promo-slot-1" href="https://www.connells.co.uk/" target="_blank" rel="noopener">
    <div class="promo-connells">
      <div class="promo-logo">Connells<span>Est. 1936</span></div>
      <div class="promo-body">
        <div class="promo-headline">Found your perfect commute? Now find your perfect home.</div>
        <div class="promo-sub">Over 150 branches nationwide &bull; Free online valuations &bull; Expert local knowledge</div>
      </div>
      <div class="promo-cta">Search Now</div>
    </div>
  </a>
</div>
<button class="toggle-content" onclick="document.querySelector('.spoke-content').classList.toggle('open');this.textContent=this.textContent==='Show Details'?'Hide Details':'Show Details'">Show Details</button>
<div class="spoke-content">
<h1>Train Times from {station_name} to London</h1>
<p>{station_name} connects to {len(sorted_journeys)} London terminal{"s" if len(sorted_journeys)>1 else ""}. The fastest route is to {fastest_name} in {fastest_j['mins']} minutes{" (direct)" if fastest_j['direct'] else " (requires change)"}.</p>
<h2>Journey Comparison</h2>
<table><thead><tr><th>London Terminal</th><th>Time</th><th>Direct?</th></tr></thead><tbody>
{table_rows}
</tbody></table>
<h2>London Terminals</h2>
<div class="terminal-nav">{terminal_nav}</div>
<h2>Frequently Asked Questions</h2>
{faqs_html}
<h2>Nearby Stations</h2>
<ul>
{nearby_html}
</ul>
</div>

<script type="application/ld+json">{breadcrumb_ld}</script>
<script type="application/ld+json">{faq_ld}</script>

<script src="../../assets/js/stations-data.js"></script>
<script>
function getColor(m){{if(m<30)return'#22c55e';if(m<60)return'#f59e0b';return'#ef4444'}}
const map=L.map('map').setView([{sdata['lat']},{sdata['lng']}],9);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors',maxZoom:18}}).addTo(map);
// Station marker (blue)
L.circleMarker([{sdata['lat']},{sdata['lng']}],{{radius:12,fillColor:'#3b82f6',color:'#fff',weight:3,opacity:1,fillOpacity:0.9}}).bindPopup('<strong>{json_esc(station_name)}</strong>').addTo(map);
// Terminal markers
{term_markers_js}
// Polylines
{polylines_js}
document.getElementById('station-count').textContent='{json_esc(station_name)} — {len(sorted_journeys)} London terminal{"s" if len(sorted_journeys)>1 else ""}';
</script>
<script>if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');</script>
</body></html>'''

    outdir = os.path.join(BASE, 'stations', slug)
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, 'index.html')
    with open(outpath, 'w') as f:
        f.write(html)
    print(f"  Station: {station_name} -> {outpath} ({len(sorted_journeys)} terminals)")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print("Parsing index.html...")
    terminals, stations, raw_js = parse_index()
    print(f"  Found {len(terminals)} terminals, {len(stations)} stations")

    print("\nCreating shared JS files...")
    write_stations_data_js(raw_js)
    write_map_core_js()

    print(f"\nGenerating 9 terminal pages...")
    for code in TERMINAL_META:
        generate_terminal_page(code, terminals, stations)

    print(f"\nGenerating 27 station pages...")
    for station_name, slug in STATION_SLUGS.items():
        generate_station_page(station_name, slug, terminals, stations)

    print(f"\nDone! Generated 36 spoke pages.")


if __name__ == '__main__':
    main()
