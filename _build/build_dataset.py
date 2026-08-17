#!/usr/bin/env python3
"""Rebuild stations.json from the measured timetable data.

Replaces journey times whose provenance could not be traced with figures
computed from Darwin timetable files, and records how and when.

Each journey now carries three measures rather than one:

  mins               fastest weekday service. Kept under the original key so
                     every existing consumer keeps working
  typicalPeakMins    median of services arriving 07:00-09:30
  peakTrainsPerHour  how often those run

Journeys with no direct service keep their entry with mins set to null and
changeRequired true. Publishing the old unverified number would repeat exactly
the mistake this exercise exists to correct, and inventing one would be worse.

Usage:  python3 _build/build_dataset.py [--write]
"""

import csv
import json
import re
import math
import os
import sys
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, '_build', 'data')

MEASURED = os.path.join(DATA, 'measured.json')
STATIONS = os.path.join(DATA, 'stations.json')
NAPTAN = os.path.join(DATA, 'naptan-rail-stations.csv')

MEASURED_ON = '2026-08-17'
SAMPLE_DAYS = ['2026-08-11', '2026-08-12', '2026-08-13']

TERMINALS = {
    'KGX': {'name': 'Kings Cross', 'naptan': 'London Kings Cross Rail Station'},
    'STP': {'name': 'St Pancras', 'naptan': 'London St Pancras International Rail Station'},
    'WAT': {'name': 'Waterloo', 'naptan': 'London Waterloo Rail Station'},
    'PAD': {'name': 'Paddington', 'naptan': 'London Paddington Rail Station'},
    'LBG': {'name': 'London Bridge', 'naptan': 'London Bridge Rail Station'},
    'VIC': {'name': 'Victoria', 'naptan': 'London Victoria Rail Station'},
    'LST': {'name': 'Liverpool Street', 'naptan': 'London Liverpool Street Rail Station'},
    'EUS': {'name': 'Euston', 'naptan': 'London Euston Rail Station'},
    'MYB': {'name': 'Marylebone', 'naptan': 'London Marylebone Rail Station'},
    'FST': {'name': 'Fenchurch Street', 'naptan': 'London Fenchurch Street Rail Station'},
    'MOG': {'name': 'Moorgate', 'naptan': 'Moorgate Rail Station'},
}

MAX_MINUTES = 90

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journey_times import MIN_INTERCHANGE_MINS


def terminal_coords():
    """Positions for the terminals, from NaPTAN like the stations."""
    out = {}
    with open(NAPTAN, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['StopType'] != 'RLY' or r['Status'] != 'active':
                continue
            for code, meta in TERMINALS.items():
                if r['CommonName'] == meta['naptan'] and code not in out:
                    try:
                        out[code] = (float(r['Latitude']), float(r['Longitude']))
                    except (TypeError, ValueError):
                        pass
    return out


def tiploc_names():
    """TIPLOC to human station name, from Darwin's own reference data.

    The measurement works in TIPLOCs, but "change at RDNGSTN" is no use to a
    reader. Darwin publishes a locname for every location, so the name comes
    from the same source as the timetable rather than a hand-built mapping that
    would drift. Platform-specific entries ("Reading Platform 4") are trimmed
    back to the station.
    """
    import gzip
    import xml.etree.ElementTree as ET
    ref = os.path.join(DATA, 'PPTimetable_20260812020537_ref_v4.xml.gz')
    with gzip.open(ref, 'rb') as f:
        root = ET.fromstring(f.read())
    out = {}
    for c in root:
        if not c.tag.endswith('LocationRef'):
            continue
        tpl, name = c.get('tpl'), c.get('locname')
        if not tpl or not name:
            continue
        name = re.sub(r'\s+(Platform|Plat)\s+\S+$', '', name).strip()
        # An all-caps locname is Darwin's placeholder for an operational point,
        # not a station anybody changes at.
        if name.isupper() and len(name) > 3:
            continue
        out[tpl] = name
    return out


def main():
    write = '--write' in sys.argv
    names = tiploc_names()
    measured = json.load(open(MEASURED))['results']
    data = json.load(open(STATIONS))
    coords = terminal_coords()

    missing = [c for c in TERMINALS if c not in coords]
    if missing:
        print(f"ERROR: no coordinates for {missing}")
        return 1

    # ---- terminals --------------------------------------------------------
    data['terminals'] = {
        code: {'name': meta['name'],
               'lat': round(coords[code][0], 6),
               'lng': round(coords[code][1], 6)}
        for code, meta in TERMINALS.items()
    }

    # ---- journeys ---------------------------------------------------------
    # The published set of station-to-terminal pairs is left alone. Allowing a
    # change makes 265 further pairs reachable within 90 minutes, which would
    # grow the dataset by half and change what every page and the map show;
    # that is a decision about coverage, not about measuring what we already
    # publish correctly, so it is deliberately not taken here.
    kept = improved = rescued = unverified = added = 0
    for st in data['stations']:
        published = st.get('journeys', {})
        got = measured.get(st['name'], {})
        new = {}

        # Every pair the timetable supports within the cap, not only the ones
        # that happened to have a direct service. A station that reaches a
        # terminal in 40 minutes with one change is a useful answer to "can I
        # commute from here", and withholding it because no through train
        # exists made the map answer a narrower question than people ask.
        for code in sorted(set(published) | set(got)):
            m = got.get(code)
            if not m or m.get('fastest_mins') is None or m['fastest_mins'] > MAX_MINUTES:
                if code in published:
                    new[code] = {
                        'mins': None, 'direct': False, 'changeRequired': True,
                        'directMins': None, 'changeAt': None,
                        'typicalPeakMins': None, 'peakTrainsPerHour': None,
                    }
                    unverified += 1
                continue

            direct_mins = m.get('direct_mins')
            change_mins = m.get('change_mins')
            fastest_is_direct = bool(m.get('fastest_is_direct'))
            old = published.get(code)

            new[code] = {
                # Headline: quickest way there with at most one change. Drives
                # the map colour, the journey-time filter and sorting.
                'mins': m['fastest_mins'],
                'direct': fastest_is_direct,
                # Quickest without changing; null where no through train runs.
                'directMins': direct_mins,
                'changeAt': None if fastest_is_direct
                            else names.get(m.get('change_at'), m.get('change_at')),
                # Peak measures describe direct services only. Where there is
                # no direct service they are null, and the pages say so rather
                # than reporting "no peak service", which would read as "you
                # cannot do this in the peak" when the truth is that we have
                # not measured connections in the peak.
                'typicalPeakMins': m.get('typical_peak_mins'),
                'peakTrainsPerHour': m.get('peak_trains_per_hour'),
                'peakServices': m.get('peak_services'),
                'totalServices': m.get('total_services'),
            }
            if old is None:
                added += 1
            elif old.get('mins') is None:
                rescued += 1
            elif direct_mins is not None and change_mins is not None and change_mins < direct_mins:
                improved += 1

        st['journeys'] = new
        kept += len(new)

    # ---- provenance -------------------------------------------------------
    data['source'] = 'Darwin Timetable Files (Rail Delivery Group), via Rail Data Marketplace'
    data['sourceLicence'] = 'Open Government Licence v3.0'
    data['basis'] = ('fastest weekday journey allowing at most one change, with the '
                     'fastest direct service and the median peak service alongside, '
                     'measured from published timetables')
    data['method'] = (
        'Journey times computed from Darwin PPTimetable files for three midweek days '
        f'({", ".join(SAMPLE_DAYS)}). Only passenger services are counted; passing '
        'points, operational stops and cancelled services are excluded. Stations and '
        'terminals are matched on TIPLOC using Darwin reference data. "Fastest" is the '
        'quickest journey of the day allowing at most one change, and names the '
        'interchange where it uses one; "fastest direct" is the quickest service that '
        'does not require changing. Connections allow '
        f'{MIN_INTERCHANGE_MINS} minutes to change, applied uniformly because '
        'station-by-station minimum connection times are not published in the feed, '
        'and are searched within a single day so that one day\'s arrival is never '
        'matched to the next day\'s departure. "Typical peak" is the median of direct '
        'services arriving at the London terminal between 07:00 and 09:30, and the '
        'peak frequency counts those same direct services.'
    )
    data['lastReviewed'] = MEASURED_ON
    data['sampleDays'] = SAMPLE_DAYS
    data['maxMinutes'] = MAX_MINUTES

    direct = sum(1 for s in data['stations'] for j in s['journeys'].values() if j['direct'])
    via_change = sum(1 for s in data['stations'] for j in s['journeys'].values()
                     if j.get('mins') is not None and not j['direct'])
    with_typical = sum(1 for s in data['stations'] for j in s['journeys'].values()
                       if j.get('typicalPeakMins'))
    print(f"terminals: {len(data['terminals'])}")
    nodirect = sum(1 for s in data['stations'] for j in s['journeys'].values()
                   if j.get('mins') is not None and j.get('directMins') is None)
    print(f"journeys:  {kept}   ({added} newly reachable with a change, {improved} now "
          f"quicker with a change, {rescued} newly timed, {unverified} still with no time)")
    print(f"  reachable only by changing:  {nodirect}")
    print(f"  fastest is via a change:     {via_change}")
    print(f"  direct with a measured time: {direct}")
    print(f"  with a typical peak figure:  {with_typical}")
    stations_with = sum(1 for s in data['stations'] if s['journeys'])
    print(f"stations with at least one journey: {stations_with}/{len(data['stations'])}")

    if not write:
        print("\nDry run. Re-run with --write to apply.")
        return 0

    with open(STATIONS, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f"\nWritten to {os.path.relpath(STATIONS, BASE)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
