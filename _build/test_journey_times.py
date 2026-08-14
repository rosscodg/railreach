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

    print('\nALL TESTS PASSED' if ok else '\nFAILURES ABOVE')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
