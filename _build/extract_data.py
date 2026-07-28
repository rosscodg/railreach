#!/usr/bin/env python3
"""One-time extraction: index.html's inline JS -> _build/data/stations.json.

After this runs, stations.json is the single source of truth. The generator
reads it and rewrites index.html's inline data block from it, so the two can
no longer drift (which is what produced the broken stations-data.js).
"""

import os
import re
import json
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, '_build', 'data', 'stations.json')

# Slugs already live and indexed — these must never change.
LOCKED_SLUGS = {
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


def slugify(name):
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    s = s.lower()
    s = s.replace('&', ' and ')
    s = re.sub(r"['’]", '', s)
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def main():
    with open(os.path.join(BASE, 'index.html')) as f:
        html = f.read()

    tmatch = re.search(r'const TERMINALS = \{(.*?)\n\};', html, re.DOTALL)
    smatch = re.search(r'const STATIONS = \[(.*?)\n\];', html, re.DOTALL)

    terminals = {}
    for m in re.finditer(r'(\w+):\s*\{\s*name:\s*"([^"]+)",\s*lat:\s*([\d.-]+),\s*lng:\s*([\d.-]+)\s*\}',
                         tmatch.group(1)):
        terminals[m.group(1)] = {'name': m.group(2),
                                 'lat': float(m.group(3)), 'lng': float(m.group(4))}

    pattern = (r'\{\s*name:\s*"([^"]+)",\s*lat:\s*([\d.-]+),\s*lng:\s*([\d.-]+),'
               r'\s*journeys:\s*\{((?:[^{}]|\{[^}]*\})*)\}\s*\}')
    stations, seen = [], {}
    for m in re.finditer(pattern, smatch.group(1)):
        name = m.group(1)
        journeys = {}
        for jm in re.finditer(r'(\w+):\s*\{\s*mins:\s*(\d+),\s*direct:\s*(true|false)\s*\}', m.group(4)):
            journeys[jm.group(1)] = {'mins': int(jm.group(2)), 'direct': jm.group(3) == 'true'}

        slug = LOCKED_SLUGS.get(name) or slugify(name)
        if slug in seen:
            raise SystemExit(f"Slug collision: '{name}' and '{seen[slug]}' both -> '{slug}'")
        seen[slug] = name

        stations.append({
            'name': name,
            'slug': slug,
            'lat': float(m.group(2)),
            'lng': float(m.group(3)),
            'journeys': journeys,
        })

    # Sanity checks before this becomes the source of truth
    assert len(terminals) == 9, f"expected 9 terminals, got {len(terminals)}"
    for s in stations:
        assert s['journeys'], f"{s['name']} has no journeys"
        for code in s['journeys']:
            assert code in terminals, f"{s['name']} references unknown terminal {code}"
            assert 0 < s['journeys'][code]['mins'] <= 90, \
                f"{s['name']} -> {code} out of range: {s['journeys'][code]['mins']}"

    for locked_name, locked_slug in LOCKED_SLUGS.items():
        match = next((s for s in stations if s['name'] == locked_name), None)
        assert match, f"locked station missing from data: {locked_name}"
        assert match['slug'] == locked_slug, f"slug drift on {locked_name}"

    stations.sort(key=lambda s: s['name'])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump({
            'source': 'National Rail operator timetables, 2026',
            'basis': 'fastest typical weekday service',
            'maxMinutes': 90,
            'terminals': terminals,
            'stations': stations,
        }, f, indent=2, ensure_ascii=False)
        f.write('\n')

    pairs = sum(len(s['journeys']) for s in stations)
    print(f"Wrote {os.path.relpath(OUT, BASE)}")
    print(f"  {len(stations)} stations, {len(terminals)} terminals, {pairs} journeys")
    print(f"  {len(LOCKED_SLUGS)} locked slugs preserved")
    longest = max(stations, key=lambda s: len(s['slug']))
    print(f"  longest slug: {longest['slug']} ({longest['name']})")


if __name__ == '__main__':
    main()
