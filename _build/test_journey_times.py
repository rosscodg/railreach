#!/usr/bin/env python3
"""Tests for the journey time measures, using synthetic timetable data.

Written before feed access so the logic is proven independently of whichever
format we end up parsing. Run: python3 _build/test_journey_times.py
"""

from datetime import time
import sys

from journey_times import CallingPoint, Service, measure, journeys_for_pair

RDG = {'RDNGSTN', 'RDNG4AB'}   # Reading, two platform groups
PAD = {'PADTON'}               # Paddington
TWY = {'TWYFORD'}


def svc(uid, stops, weekdays=True):
    """stops: [(tiploc, 'HH:MM' arrival|None, 'HH:MM' departure|None)]"""
    cps = []
    for tiploc, arr, dep in stops:
        a = time(*map(int, arr.split(':'))) if arr else None
        d = time(*map(int, dep.split(':'))) if dep else None
        cps.append(CallingPoint(tiploc, a, d))
    return Service(uid, cps, runs_weekdays=weekdays)


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"          got  {got}\n          want {want}")
    return ok


def main():
    ok = True

    # --- a normal peak timetable -------------------------------------------
    services = [
        svc('A', [('RDNGSTN', None, '06:40'), ('PADTON', '07:12', None)]),   # 32, peak
        svc('B', [('RDNGSTN', None, '07:30'), ('PADTON', '08:05', None)]),   # 35, peak
        svc('C', [('RDNGSTN', None, '07:50'), ('PADTON', '08:41', None)]),   # 51, peak
        svc('D', [('RDNGSTN', None, '08:20'), ('PADTON', '09:00', None)]),   # 40, peak
        svc('E', [('RDNGSTN', None, '11:00'), ('PADTON', '11:28', None)]),   # 28, off-peak
    ]
    m = measure(services, RDG, PAD)
    ok &= check('fastest is the quickest of all services, peak or not',
                m['fastest_mins'], 28)
    ok &= check('typical peak is the median of peak arrivals only (32,35,40,51)',
                m['typical_peak_mins'], 38)
    ok &= check('peak frequency counts peak arrivals over 2.5 hours',
                m['peak_trains_per_hour'], 1.6)
    ok &= check('peak service count reported for transparency', m['peak_services'], 4)
    ok &= check('total services reported', m['total_services'], 5)

    # --- the gap that makes this worth publishing --------------------------
    ok &= check('fastest understates the real commute here',
                m['typical_peak_mins'] - m['fastest_mins'], 10)

    # --- multiple TIPLOCs for one station ----------------------------------
    alt = [svc('F', [('RDNG4AB', None, '07:00'), ('PADTON', '07:30', None)])]
    ok &= check('a service using the other platform group still matches',
                measure(alt, RDG, PAD)['fastest_mins'], 30)

    # --- direction matters -------------------------------------------------
    reverse = [svc('G', [('PADTON', None, '07:00'), ('RDNGSTN', '07:30', None)])]
    ok &= check('the return working is not counted as a journey to London',
                measure(reverse, RDG, PAD)['total_services'], 0)

    # --- intermediate calling points ---------------------------------------
    via = [svc('H', [('RDNGSTN', None, '07:00'), ('TWYFORD', '07:06', '07:07'),
                     ('PADTON', '07:35', None)])]
    ok &= check('a stopping service is measured origin to terminal',
                measure(via, RDG, PAD)['fastest_mins'], 35)
    ok &= check('an intermediate station is measurable in its own right',
                measure(via, TWY, PAD)['fastest_mins'], 28)

    # --- no peak service ---------------------------------------------------
    offpeak = [svc('I', [('RDNGSTN', None, '11:00'), ('PADTON', '11:30', None)])]
    m2 = measure(offpeak, RDG, PAD)
    ok &= check('a station with no peak service reports no typical time',
                m2['typical_peak_mins'], None)
    ok &= check('...and no frequency, rather than zero',
                m2['peak_trains_per_hour'], None)
    ok &= check('...but still has a fastest time', m2['fastest_mins'], 30)

    # --- weekend-only services excluded ------------------------------------
    weekend = [svc('J', [('RDNGSTN', None, '07:00'), ('PADTON', '07:20', None)],
                   weekdays=False)]
    ok &= check('a service that does not run on weekdays is ignored',
                measure(weekend, RDG, PAD)['total_services'], 0)

    # --- crossing midnight -------------------------------------------------
    late = [svc('K', [('RDNGSTN', None, '23:40'), ('PADTON', '00:15', None)])]
    ok &= check('a journey over midnight is 35 minutes, not negative',
                measure(late, RDG, PAD)['fastest_mins'], 35)

    # --- peak boundaries are inclusive -------------------------------------
    edges = [
        svc('L', [('RDNGSTN', None, '06:30'), ('PADTON', '07:00', None)]),   # exactly 07:00
        svc('M', [('RDNGSTN', None, '09:00'), ('PADTON', '09:30', None)]),   # exactly 09:30
        svc('N', [('RDNGSTN', None, '09:10'), ('PADTON', '09:31', None)]),   # just outside
    ]
    ok &= check('services arriving exactly on the peak boundary count',
                measure(edges, RDG, PAD)['peak_services'], 2)

    # --- pooling several days ----------------------------------------------
    three_days = []
    for d in range(3):
        three_days += [svc(f'P{d}a', [('RDNGSTN', None, '07:00'), ('PADTON', '07:30', None)]),
                       svc(f'P{d}b', [('RDNGSTN', None, '08:00'), ('PADTON', '08:34', None)])]
    m4 = measure(three_days, RDG, PAD, days=3)
    ok &= check('pooling 3 days does not treble the apparent frequency',
                m4['peak_trains_per_hour'], 0.8)
    ok &= check('...and the median is unchanged by repetition',
                m4['typical_peak_mins'], 32)
    ok &= check('...with the day count recorded', m4['days_sampled'], 3)

    # --- nothing at all ----------------------------------------------------
    m3 = measure([], RDG, PAD)
    ok &= check('no services yields nulls, not zeros', m3['fastest_mins'], None)
    ok &= check('...and is not reported as a direct journey', m3['direct'], False)

    # --- journeys with one change ------------------------------------------
    from journey_times import (build_terminal_index, fastest_one_change,
                               calling_points_abs, earliest_arrival)

    # Tilehurst's real shape: a slow direct, and a fast connection at Reading.
    net = [
        svc('D1', [('TILHRST', None, '12:31'), ('PADTON', '13:12', None)]),   # direct, 41
        svc('L1', [('TILHRST', None, '12:31'), ('RDNGSTN', '12:38', None)]),  # feeder, 7
        svc('F1', [('RDNGSTN', None, '12:46'), ('PADTON', '13:09', None)]),   # fast, 23
    ]
    idx = build_terminal_index(net, PAD)
    m, at = fastest_one_change(net, {'TILHRST'}, PAD, idx, min_connect=8)
    ok &= check('one change beats a slow direct (12:31 -> 13:09)', m, 38)
    ok &= check('...and reports where the change happens', at, 'RDNGSTN')
    ok &= check('the direct service is still measured on its own',
                measure(net, {'TILHRST'}, PAD)['fastest_mins'], 41)

    # The interchange allowance is a real constraint, not decoration.
    m2, _ = fastest_one_change(net, {'TILHRST'}, PAD, idx, min_connect=9)
    ok &= check('a connection tighter than the allowance is not offered', m2, None)

    # A pair with no direct service at all still yields a time.
    nodirect = [
        svc('A1', [('WELHAMG', None, '08:00'), ('FNPK', '08:20', None)]),
        svc('B1', [('FNPK', None, '08:30'), ('PADTON', '08:55', None)]),
    ]
    idx2 = build_terminal_index(nodirect, PAD)
    m3, at3 = fastest_one_change(nodirect, {'WELHAMG'}, PAD, idx2, min_connect=8)
    ok &= check('a station with no direct service still gets a time', m3, 55)
    ok &= check('...via the right interchange', at3, 'FNPK')
    ok &= check('...and has no direct time to report',
                measure(nodirect, {'WELHAMG'}, PAD)['fastest_mins'], None)

    # The terminal is a destination, not an interchange.
    silly = [
        svc('C1', [('TILHRST', None, '09:00'), ('PADTON', '09:40', None)]),
        svc('C2', [('PADTON', None, '09:50'), ('PADTON', '09:55', None)]),
    ]
    idx3 = build_terminal_index(silly, PAD)
    m4, _ = fastest_one_change(silly, {'TILHRST'}, PAD, idx3, min_connect=8)
    ok &= check('changing at the terminal itself is not a journey', m4, None)

    # Crossing midnight must not produce a negative or absurd connection.
    late = [
        svc('N1', [('TILHRST', None, '23:40'), ('RDNGSTN', '23:50', None)]),
        svc('N2', [('RDNGSTN', None, '00:05'), ('PADTON', '00:35', None)]),
    ]
    idx4 = build_terminal_index(late, PAD)
    m5, _ = fastest_one_change(late, {'TILHRST'}, PAD, idx4, min_connect=8)
    ok &= check('a connection over midnight is not offered as negative',
                m5 is None or m5 > 0, True)

    # Absolute times stay monotonic across midnight.
    cs = calling_points_abs(late[0])
    ok &= check('calling points are monotonic in absolute minutes',
                [c[1] or c[2] for c in cs], [23*60+40, 23*60+50])

    print('\nALL TESTS PASSED' if ok else '\nFAILURES ABOVE')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
