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
from journey_times import (measure, build_terminal_index, fastest_one_change,
                           calling_points_abs, MIN_INTERCHANGE_MINS)

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
# Moorgate is added for the same reason. Great Northern's inner-suburban
# stations run there in the peak, not to Kings Cross: Welham Green, Brookmans
# Park, Cuffley and Gordon Hill have ZERO peak services to Kings Cross, and
# Crews Hill and Bayford have none at any hour. Publishing a Kings Cross time
# for those was telling commuters to catch a train that does not exist.
TERMINAL_CRS = {
    'KGX': 'Kings Cross', 'STP': 'St Pancras', 'WAT': 'Waterloo',
    'PAD': 'Paddington', 'LBG': 'London Bridge', 'VIC': 'Victoria',
    'LST': 'Liverpool Street', 'EUS': 'Euston', 'MYB': 'Marylebone',
    'FST': 'Fenchurch Street', 'MOG': 'Moorgate',
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
        terminal_tiplocs[code] = crs_to_tpls.get(code, set())
    print("terminal TIPLOCs from Darwin reference data:")
    for c, t in terminal_tiplocs.items():
        print(f"  {c} {TERMINAL_NAMES[c]:<18} {sorted(t)}")
    print()

    print("Loading timetables")
    services = []
    per_day = []          # kept separate as well: see the note on connections
    for fname, date in FILES:
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"  MISSING {fname}")
            continue
        svcs, skipped = load(path, service_date=date)
        print(f"  {date}: {len(svcs):,} passenger services")
        services.extend(svcs)
        per_day.append((date, svcs))
    days = len(per_day)
    print(f"  pooled: {len(services):,} services across {days} midweek days\n")

    # Direct journeys can be measured on the pooled set, because a direct
    # journey never spans two services. Connections cannot: pooling would let
    # one day's arrival meet the next day's departure, which is not a journey
    # anybody can make. So the one-change search runs a day at a time and the
    # best result is taken across days, which is what "fastest" already means.
    print(f"Indexing connections (interchange allowance {MIN_INTERCHANGE_MINS} min)")
    day_calls = [{id(s): calling_points_abs(s) for s in svcs} for _, svcs in per_day]

    # Index by TIPLOC so we test each station against only the services that
    # actually call there, rather than all 75,000.
    by_tiploc = defaultdict(list)
    for s in services:
        for cp in s.calling_points:
            by_tiploc[cp.tiploc].append(s)

    # One connection index per terminal per day, built once and reused for
    # every station rather than rebuilt 345 times.
    indexes = {}
    for code, tips in terminal_tiplocs.items():
        indexes[code] = [build_terminal_index(svcs, tips, calls_cache=day_calls[i])
                         for i, (_d, svcs) in enumerate(per_day)]
    print(f"  built {sum(len(v) for v in indexes.values())} connection indexes\n")

    # Services calling at each TIPLOC, per day, so the change search only looks
    # at trains that actually serve the origin.
    day_by_tiploc = []
    for _d, svcs in per_day:
        m = defaultdict(list)
        for s in svcs:
            for cp in s.calling_points:
                m[cp.tiploc].append(s)
        day_by_tiploc.append(m)

    print("Measuring")
    results = {}
    for st in stations:
        candidates = []
        seen = set()
        station_tips = expand(st['tiplocs'], tpl_to_crs, crs_to_tpls)
        for t in station_tips:
            for s in by_tiploc.get(t, []):
                if id(s) not in seen:
                    seen.add(id(s))
                    candidates.append(s)
        if not candidates:
            continue
        for code, tips in terminal_tiplocs.items():
            m = measure(candidates, station_tips, tips, days=days)

            # Best single-change itinerary, taken as the best across days.
            change_mins, change_at = None, None
            for i in range(days):
                pool, seen_d = [], set()
                for t in station_tips:
                    for s in day_by_tiploc[i].get(t, []):
                        if id(s) not in seen_d:
                            seen_d.add(id(s))
                            pool.append(s)
                if not pool:
                    continue
                cm, ca = fastest_one_change(pool, station_tips, tips, indexes[code][i],
                                            calls_cache=day_calls[i])
                if cm is not None and (change_mins is None or cm < change_mins):
                    change_mins, change_at = cm, ca

            direct_mins = m['fastest_mins']
            best = min([x for x in (direct_mins, change_mins) if x is not None], default=None)
            if best is None or best > MAX_MINUTES:
                continue
            m['direct_mins'] = direct_mins
            m['change_mins'] = change_mins
            m['change_at'] = change_at
            m['fastest_mins'] = best
            m['fastest_is_direct'] = (direct_mins is not None and direct_mins <= (
                change_mins if change_mins is not None else direct_mins))
            results.setdefault(st['name'], {})[code] = m

    # ---- comparison -------------------------------------------------------
    published = {s['name']: s['journeys'] for s in stations}
    exact = close = drifted = 0
    new_pairs = []
    lost_pairs = []
    drift_rows = []
    newly_timed = []

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
            if j['mins'] is None:
                # Published as change-required with no time. Now measurable,
                # so there is nothing to compare it against: count it as newly
                # timed rather than as drift.
                newly_timed.append((name, code, alt['fastest_mins'], alt.get('change_at')))
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

    if newly_timed:
        print(f"\njourneys published with no time that are now measurable ({len(newly_timed)}):")
        for name, code, m, at in newly_timed[:20]:
            print(f"    {name:<26} {TERMINAL_NAMES[code]:<17} {m:>3} min via {at}")

    changed_better = [(n, c, m) for n, c, m in
                      ((st['name'], code, res) for st in stations
                       for code, res in results.get(st['name'], {}).items())
                      if m.get('change_mins') is not None and m.get('direct_mins') is not None
                      and m['change_mins'] < m['direct_mins'] - 1]
    print(f"\njourneys where one change beats the direct service: {len(changed_better)}")
    for n, c, m in sorted(changed_better, key=lambda x: x[2]['direct_mins'] - x[2]['change_mins'],
                          reverse=True)[:12]:
        print(f"    {n:<26} {TERMINAL_NAMES[c]:<17} direct {m['direct_mins']:>3} -> "
              f"{m['change_mins']:>3} via {m['change_at']}")

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
