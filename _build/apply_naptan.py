#!/usr/bin/env python3
"""Attach authoritative coordinates and TIPLOC codes from NaPTAN.

Two jobs:

1. **Coordinates.** The positions in stations.json were compiled by an unknown
   method and are wrong for dozens of stations - 66 by more than 500m and 22 by
   more than a kilometre, the worst being Hockley at 3.9km. Wrong positions put
   markers in the wrong place on the map and corrupt every distance the site
   computes (the discovery module's 20km London ring and 8km spacing rule).

2. **TIPLOCs.** CIF timetable schedules identify calling points by TIPLOC, not
   by name, so the journey time refresh cannot even begin without them.

TIPLOCs are stored as a list because a single station often has several, one
per platform group or route path: Clapham Junction has five. Matching a
timetable against only one of them would silently miss most of its services.

Source: NaPTAN (Department for Transport), ATCO area 910, held alongside this
script as data/naptan-rail-stations.csv for reproducibility.

Usage:  python3 _build/apply_naptan.py [--write]
Without --write it reports what it would change and touches nothing.
"""

import csv
import json
import math
import os
import re
import sys
import unicodedata
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAPTAN = os.path.join(BASE, '_build', 'data', 'naptan-rail-stations.csv')
STATIONS = os.path.join(BASE, '_build', 'data', 'stations.json')

# Candidates this far apart are genuinely different stations rather than
# platform groups of one. Catford and Catford Bridge sit 312m apart, so a
# nearest-neighbour match alone would silently mix them up.
SAME_STATION_KM = 1.2
# Beyond this, our stored coordinate disagrees with NaPTAN enough to report.
NOTABLE_ERROR_KM = 0.5


def km(a, b):
    R = 6371
    p = math.pi / 180
    dlat = (b[0] - a[0]) * p
    dlng = (b[1] - a[1]) * p
    x = (math.sin(dlat / 2) ** 2
         + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(x))


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = s.replace(' rail station', '')
    # NaPTAN disambiguates with a county; our names usually do not.
    s = re.sub(r'\((london|berks|herts|kent|surrey|sussex|essex|hants|lancs|'
               r'yorks|staffs|notts|glos|salop|manchester|birmingham)\)', '', s)
    s = s.replace('&', 'and').replace("'", '')
    return re.sub(r'[^a-z0-9]+', '', s)


def load_naptan():
    out = []
    with open(NAPTAN, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['StopType'] != 'RLY' or r['Status'] != 'active':
                continue
            if not r['ATCOCode'].startswith('9100'):
                continue
            try:
                lat, lng = float(r['Latitude']), float(r['Longitude'])
            except (TypeError, ValueError):
                continue
            out.append({'name': r['CommonName'], 'tiploc': r['ATCOCode'][4:],
                        'lat': lat, 'lng': lng})
    return out


def resolve(station, naptan, by_name):
    """Return (tiplocs, lat, lng, note) or None if it cannot be resolved."""
    ours = (station['lat'], station['lng'])
    cands = by_name.get(norm(station['name']), [])

    if not cands:
        # No name match. Accept only an unambiguous, very close neighbour, and
        # only when the names are at least a prefix of one another - this is
        # what stops Catford being matched to Catford Bridge.
        near = sorted(naptan, key=lambda n: km(ours, (n['lat'], n['lng'])))[:1]
        if near:
            n = near[0]
            d = km(ours, (n['lat'], n['lng']))
            a, b = norm(station['name']), norm(n['name'])
            if d <= SAME_STATION_KM and (a.startswith(b) or b.startswith(a)):
                return [n['tiploc']], n['lat'], n['lng'], f'matched on position ({d:.2f}km)'
        return None

    if len(cands) == 1:
        n = cands[0]
        return [n['tiploc']], n['lat'], n['lng'], ''

    # Several candidates. If they cluster, it is one station with several
    # platform groups: keep every TIPLOC. If they are far apart (Rainham in
    # Essex versus Rainham in Kent), pick the one nearest our position.
    nearest = min(cands, key=lambda n: km(ours, (n['lat'], n['lng'])))
    cluster = [n for n in cands
               if km((nearest['lat'], nearest['lng']), (n['lat'], n['lng'])) <= SAME_STATION_KM]
    tiplocs = sorted(n['tiploc'] for n in cluster)
    note = f'{len(tiplocs)} platform groups' if len(tiplocs) > 1 else 'nearest of several'
    if len(cluster) < len(cands):
        note += f'; ignored {len(cands) - len(cluster)} distant same-name station(s)'
    return tiplocs, nearest['lat'], nearest['lng'], note


def main():
    write = '--write' in sys.argv
    naptan = load_naptan()
    by_name = {}
    for n in naptan:
        by_name.setdefault(norm(n['name']), []).append(n)

    with open(STATIONS) as f:
        data = json.load(f)

    resolved, unresolved, moved = 0, [], []
    for s in data['stations']:
        got = resolve(s, naptan, by_name)
        if not got:
            unresolved.append(s['name'])
            continue
        tiplocs, lat, lng, note = got
        err = km((s['lat'], s['lng']), (lat, lng))
        if err >= NOTABLE_ERROR_KM:
            moved.append((err, s['name'], s['lat'], s['lng'], lat, lng))
        s['tiplocs'] = tiplocs
        s['lat'] = round(lat, 6)
        s['lng'] = round(lng, 6)
        resolved += 1

    print(f"NaPTAN rail stations loaded: {len(naptan)}")
    print(f"resolved: {resolved}/{len(data['stations'])}")
    print(f"unresolved: {len(unresolved)} {unresolved if unresolved else ''}")
    print(f"\ncoordinates corrected by more than {NOTABLE_ERROR_KM}km: {len(moved)}")
    for err, name, olat, olng, lat, lng in sorted(moved, reverse=True)[:12]:
        print(f"    {name:<26} {err:5.2f} km   {olat:.4f},{olng:.4f} -> {lat:.4f},{lng:.4f}")

    multi = [s for s in data['stations'] if len(s.get('tiplocs', [])) > 1]
    print(f"\nstations with several TIPLOCs: {len(multi)}")
    for s in multi[:8]:
        print(f"    {s['name']:<26} {', '.join(s['tiplocs'])}")

    if not write:
        print("\nDry run. Re-run with --write to apply.")
        return

    data['geoSource'] = 'NaPTAN (Department for Transport), ATCO area 910'
    data['geoUpdated'] = datetime.date.today().isoformat()
    with open(STATIONS, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f"\nWritten to {os.path.relpath(STATIONS, BASE)}")


if __name__ == '__main__':
    main()
