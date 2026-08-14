#!/usr/bin/env python3
"""Recompute every journey from the Darwin timetable and compare with the site.

Reports only. Nothing is written until the comparison has been read, because
the published figures have no traceable provenance and we are replacing them
on the strength of this.

Usage:  python3 _build/recompute.py [--write]
"""

import csv
import json
import math
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from darwin_adapter import load
from journey_times import measure

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, '_build', 'data')
STATIONS = os.path.join(DATA, 'stations.json')

# Three consecutive midweek days. A single day can be skewed by engineering
# work on one route; three lets that show up as an outlier instead of becoming
# the published figure.
FILES = [
    ('PPTimetable_20260811020500_v8.xml.gz', '2026-08-11'),   # Tuesday
    ('PPTimetable_20260812020537_v8.xml.gz', '2026-08-12'),   # Wednesday
    ('PPTimetable_20260813023858_v8.xml.gz', '2026-08-13'),   # Thursday
]

# Kings Cross and St Pancras are adjacent but separate stations, and the
# original data merged them: St Albans and Bedford have no Kings Cross service
# at all, they run to St Pancras. Split, on the grounds that a journey guide
# should say which station you actually arrive at.
TERMINAL_CRS = {
    'KGX': 'Kings Cross', 'STP': 'St Pancras', 'WAT': 'Waterloo',
    'PAD': 'Paddington', 'LBG': 'London Bridge', 'VIC': 'Victoria',
    'LST': 'Liverpool Street', 'EUS': 'Euston', 'MYB': 'Marylebone',
    'FST': 'Fenchurch Street',
}
TERMINAL_NAMES = dict(TERMINAL_CRS)
REF_FILE = 'PPTimetable_20260812020537_ref_v4.xml.gz'


def load_reference():
    """TIPLOC groupings from Darwin's own reference data.

    Hand-writing these was a mistake: I missed PADTLL, Paddington's Elizabeth
    line platforms, which carries more calls than PADTON itself, and the same
    omission applied to Liverpool Street and to 19 origin stations. Darwin
    groups TIPLOCs by CRS, so use that grouping rather than guessing which
    platform groups exist.
    """
    import gzip
    import xml.etree.ElementTree as ET
    with gzip.open(os.path.join(DATA, REF_FILE), 'rb') as f:
        root = ET.fromstring(f.read())
    tpl_to_crs = {}
    crs_to_tpls = defaultdict(set)
    for c in root:
        if not c.tag.endswith('LocationRef'):
            continue
        tpl, crs = c.get('tpl'), c.get('crs')
        if not crs:
            continue
        # Rail replacement bus stops share the CRS but are not the railway.
        if 'BUS' in tpl:
            continue
        tpl_to_crs[tpl] = crs
        crs_to_tpls[crs].add(tpl)
    return tpl_to_crs, crs_to_tpls


def expand(tiplocs, tpl_to_crs, crs_to_tpls):
    """Widen a TIPLOC set to every platform group Darwin gives that station."""
    out = set(tiplocs)
    for t in tiplocs:
        crs = tpl_to_crs.get(t)
        if crs:
            out |= crs_to_tpls[crs]
    return out


MAX_MINUTES = 90


def main():
    write = '--write' in sys.argv
    data = json.load(open(STATIONS))
    stations = data['stations']

    tpl_to_crs, crs_to_tpls = load_reference()
    terminal_tiplocs = {}
    for code, name in TERMINAL_CRS.items():
        crs = {'KGX': 'KGX', 'STP': 'STP', 'WAT': 'WAT', 'PAD': 'PAD', 'LBG': 'LBG',
               'VIC': 'VIC', 'LST': 'LST', 'EUS': 'EUS', 'MYB': 'MYB', 'FST': 'FST'}[code]
        terminal_tiplocs[code] = crs_to_tpls.get(crs, set())
    print("terminal TIPLOCs from Darwin reference data:")
    for c, t in terminal_tiplocs.items():
        print(f"  {c} {TERMINAL_NAMES[c]:<18} {sorted(t)}")
    print()

    print("Loading timetables")
    services = []
    for fname, date in FILES:
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"  MISSING {fname}")
            continue
        svcs, skipped = load(path, service_date=date)
        print(f"  {date}: {len(svcs):,} passenger services")
        services.extend(svcs)
    days = len([f for f, _ in FILES if os.path.exists(os.path.join(DATA, f))])
    print(f"  pooled: {len(services):,} services across {days} midweek days\n")

    # Index by TIPLOC so we test each station against only the services that
    # actually call there, rather than all 75,000.
    by_tiploc = defaultdict(list)
    for s in services:
        for cp in s.calling_points:
            by_tiploc[cp.tiploc].append(s)

    results = {}
    for st in stations:
        candidates = []
        seen = set()
        for t in expand(st['tiplocs'], tpl_to_crs, crs_to_tpls):
            for s in by_tiploc.get(t, []):
                if id(s) not in seen:
                    seen.add(id(s))
                    candidates.append(s)
        if not candidates:
            continue
        station_tips = expand(st['tiplocs'], tpl_to_crs, crs_to_tpls)
        for code, tips in terminal_tiplocs.items():
            m = measure(candidates, station_tips, tips, days=days)
            if m['fastest_mins'] is not None and m['fastest_mins'] <= MAX_MINUTES:
                results.setdefault(st['name'], {})[code] = m

    # ---- comparison -------------------------------------------------------
    published = {s['name']: s['journeys'] for s in stations}
    exact = close = drifted = 0
    new_pairs = []
    lost_pairs = []
    drift_rows = []

    for st in stations:
        name = st['name']
        pub = published.get(name, {})
        got = results.get(name, {})
        for code, j in pub.items():
            # the old KGX may legitimately now be STP
            alt = got.get(code) or (got.get('STP') if code == 'KGX' else None)
            if not alt:
                lost_pairs.append((name, code, j['mins']))
                continue
            d = alt['fastest_mins'] - j['mins']
            if d == 0:
                exact += 1
            elif abs(d) <= 2:
                close += 1
            else:
                drifted += 1
                drift_rows.append((abs(d), name, code, j['mins'], alt['fastest_mins']))
        for code, m in got.items():
            if code not in pub and not (code == 'STP' and 'KGX' in pub):
                new_pairs.append((name, code, m['fastest_mins']))

    total_pub = sum(len(v) for v in published.values())
    total_new = sum(len(v) for v in results.values())
    print(f"published journeys: {total_pub}")
    print(f"measured journeys:  {total_new}   (across {len(results)} stations)\n")
    print(f"  exact match:            {exact}")
    print(f"  within 2 minutes:       {close}")
    print(f"  differs by 3+ minutes:  {drifted}")
    print(f"  published but no service found: {len(lost_pairs)}")
    print(f"  services found that were not published: {len(new_pairs)}")

    if drift_rows:
        print("\nlargest disagreements (published -> measured):")
        for d, name, code, p, n in sorted(drift_rows, reverse=True)[:15]:
            print(f"    {name:<26} {TERMINAL_NAMES[code]:<17} {p:>3} -> {n:>3}  ({n-p:+d})")

    if lost_pairs:
        print(f"\npublished journeys with no service in the timetable ({len(lost_pairs)}):")
        for name, code, p in lost_pairs[:15]:
            print(f"    {name:<26} {TERMINAL_NAMES.get(code, code):<17} published {p}")

    # the fastest/typical gap, which is the reason for doing any of this
    gaps = []
    for name, terms in results.items():
        for code, m in terms.items():
            if m['typical_peak_mins'] and m['fastest_mins']:
                gaps.append((m['typical_peak_mins'] - m['fastest_mins'], name, code,
                             m['fastest_mins'], m['typical_peak_mins'], m['peak_trains_per_hour']))
    gaps.sort(reverse=True)
    print(f"\nwhere the headline most understates the real commute:")
    for g, name, code, f, t, tph in gaps[:12]:
        print(f"    {name:<26} {TERMINAL_NAMES[code]:<17} fastest {f:>3}, typical {t:>3}  (+{g})  {tph}/hr")

    if not write:
        print("\nReport only. Re-run with --write to apply.")
        return

    json.dump({'generated': True, 'results': {
        n: {c: m for c, m in t.items()} for n, t in results.items()}},
        open(os.path.join(DATA, 'measured.json'), 'w'), indent=1, default=str)
    print(f"\nWrote measured.json ({total_new} journeys) for review.")


if __name__ == '__main__':
    main()
