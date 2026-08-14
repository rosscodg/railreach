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
import math
import os
import sys
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, '_build', 'data')

MEASURED = os.path.join(DATA, 'measured.json')
STATIONS = os.path.join(DATA, 'stations.json')
NAPTAN = os.path.join(DATA, 'naptan-rail-stations.csv')

MEASURED_ON = '2026-08-14'
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


def main():
    write = '--write' in sys.argv
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
    kept = replaced = unverified = added = 0
    for st in data['stations']:
        old = st.get('journeys', {})
        got = measured.get(st['name'], {})
        new = {}

        for code, m in got.items():
            if m['fastest_mins'] is None or m['fastest_mins'] > MAX_MINUTES:
                continue
            new[code] = {
                'mins': m['fastest_mins'],
                'direct': True,
                'typicalPeakMins': m['typical_peak_mins'],
                'peakTrainsPerHour': m['peak_trains_per_hour'],
                'peakServices': m['peak_services'],
                'totalServices': m['total_services'],
            }
            if code in old:
                replaced += 1
            else:
                added += 1

        # A published journey with no direct service in the timetable. Keep the
        # pair so the station page can say a change is needed, but drop the
        # unverifiable time rather than republish it.
        for code, j in old.items():
            target = code
            if code == 'KGX' and 'KGX' not in got and 'STP' in got:
                continue          # it was really St Pancras all along
            if target in new:
                continue
            new[target] = {
                'mins': None,
                'direct': False,
                'changeRequired': True,
                'typicalPeakMins': None,
                'peakTrainsPerHour': None,
            }
            unverified += 1

        st['journeys'] = new
        kept += len(new)

    # ---- provenance -------------------------------------------------------
    data['source'] = 'Darwin Timetable Files (Rail Delivery Group), via Rail Data Marketplace'
    data['sourceLicence'] = 'Open Government Licence v3.0'
    data['basis'] = ('fastest and median-peak weekday service, measured from published '
                     'timetables')
    data['method'] = (
        'Journey times computed from Darwin PPTimetable files for three midweek days '
        f'({", ".join(SAMPLE_DAYS)}). Only passenger services are counted; passing '
        'points, operational stops and cancelled services are excluded. Stations and '
        'terminals are matched on TIPLOC using Darwin reference data. "Fastest" is the '
        'quickest service of the day; "typical peak" is the median of services arriving '
        'at the London terminal between 07:00 and 09:30.'
    )
    data['lastReviewed'] = MEASURED_ON
    data['sampleDays'] = SAMPLE_DAYS
    data['maxMinutes'] = MAX_MINUTES

    direct = sum(1 for s in data['stations'] for j in s['journeys'].values() if j['direct'])
    with_typical = sum(1 for s in data['stations'] for j in s['journeys'].values()
                       if j.get('typicalPeakMins'))
    print(f"terminals: {len(data['terminals'])}")
    print(f"journeys:  {kept}   ({replaced} replaced, {added} newly found, "
          f"{unverified} kept as change-required with no time)")
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
