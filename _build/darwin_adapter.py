#!/usr/bin/env python3
"""Turn Darwin PPTimetable files into journey_times.Service objects.

Written against the real files rather than a guess. What the inspection of
20260813023858_v8 (82MB uncompressed, 68,923 journeys) established:

  OR    origin of a passenger service       ptd + wtd
  IP    intermediate passenger call         pta/ptd + wta/wtd
  DT    destination of a passenger service  pta + wta
  PP    PASSING POINT - the train runs through without stopping. 396,161 of
        them, more than every genuine intermediate call except IP itself.
        Counting these would invent journeys from stations where no train
        actually stops, which is the single worst mistake available here.
  OP*   operational stops on a passenger service; not public calls.

Also excluded: 15,827 non-passenger journeys (empty stock, light engines) and
any journey carrying a cancelReason.

Public times (pta/ptd) are preferred over working times (wta/wtd) because they
are what a passenger is told; working times exist for operational planning and
can differ by a minute or so. Public times are present on 99.8% of calls, so
working times are only a fallback.
"""

import gzip
import os
import sys
import xml.etree.ElementTree as ET
from datetime import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journey_times import CallingPoint, Service

NS = '{http://www.thalesgroup.com/rtti/XmlTimetable/v8}'

# Only these are places a passenger can board or alight.
PUBLIC_CALLS = {'OR', 'IP', 'DT'}


def _parse_time(v):
    if not v:
        return None
    parts = v.split(':')
    try:
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def load(path, service_date=None, passenger_only=True):
    """Parse a PPTimetable file into Service objects.

    service_date: 'YYYY-MM-DD'. A file generated on one morning carries several
    days; without this you would mix a Thursday and a Friday timetable together
    and quietly double the apparent frequency.
    """
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rb') as f:
        root = ET.fromstring(f.read())

    services = []
    skipped = {'not_passenger': 0, 'cancelled': 0, 'wrong_date': 0, 'too_few_calls': 0}

    for j in root:
        if not j.tag.endswith('Journey'):
            continue

        if service_date and j.get('ssd') != service_date:
            skipped['wrong_date'] += 1
            continue
        if passenger_only and j.get('isPassengerSvc') == 'false':
            skipped['not_passenger'] += 1
            continue
        if any(c.tag.endswith('cancelReason') for c in j):
            skipped['cancelled'] += 1
            continue

        calls = []
        for cp in j:
            tag = cp.tag.split('}')[-1]
            if tag not in PUBLIC_CALLS:
                continue          # drops PP passing points and OP* operational stops
            arr = _parse_time(cp.get('pta')) or _parse_time(cp.get('wta'))
            dep = _parse_time(cp.get('ptd')) or _parse_time(cp.get('wtd'))
            calls.append(CallingPoint(cp.get('tpl'), arrival=arr, departure=dep))

        if len(calls) < 2:
            skipped['too_few_calls'] += 1
            continue

        services.append(Service(j.get('uid') or j.get('rid'), calls,
                                operator=j.get('toc'), runs_weekdays=True))

    return services, skipped


def load_many(paths, service_dates):
    """Load several files, one service date each, and pool the services.

    Averaging across midweek days guards against a single day's engineering
    work making a route look permanently slower than it is.
    """
    all_services = []
    for path, date in zip(paths, service_dates):
        svcs, skipped = load(path, service_date=date)
        print(f"  {os.path.basename(path)}  {date}: {len(svcs):,} passenger services"
              f"  (skipped {skipped['not_passenger']:,} non-passenger,"
              f" {skipped['cancelled']:,} cancelled)")
        all_services.extend(svcs)
    return all_services


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    svcs, skipped = load(sys.argv[1], service_date=sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"loaded {len(svcs):,} services")
    print("skipped:", skipped)
    if svcs:
        s = svcs[0]
        print(f"\nfirst service {s.uid} ({s.operator}), {len(s.calling_points)} public calls:")
        for cp in s.calling_points[:6]:
            print(f"    {cp.tiploc:<9} arr={cp.arrival} dep={cp.departure}")
