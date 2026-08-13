#!/usr/bin/env python3
"""Compute journey time measures from timetable data.

Deliberately format-agnostic. The input is a list of Service objects, each a
sequence of calling points. Whichever feed we end up with - Network Rail's CIF
SCHEDULE, Darwin's XML timetable files - only the adapter that produces those
Service objects changes. The measures below stay put.

Three measures per station-to-terminal pair:

  fastest        the quickest weekday service. What the site publishes today
                 and what people search for, but on its own it is the estate
                 agent's number: a single 06:42 express is no comfort if the
                 08:15 takes twenty minutes longer.

  typical_peak   the median journey time of services arriving at the London
                 terminal inside the morning peak. This is what a commuter
                 actually experiences. The gap between it and `fastest` is
                 itself worth publishing: 32 against 35 is genuinely fast,
                 32 against 51 means the headline is flattering.

  peak_trains_per_hour
                 how often those services run. Somewhere 35 minutes out with
                 six trains an hour beats 32 minutes with one, and the data
                 is right there once the query exists.

The mean is deliberately not computed: off-peak stopping services and
late-night runs drag it around, and nobody experiences an average journey.
"""

import statistics
from datetime import time

# Morning peak, defined by ARRIVAL at the London terminal - that is what a
# commuter is constrained by, not when they leave home.
PEAK_START = time(7, 0)
PEAK_END = time(9, 30)
PEAK_HOURS = 2.5


class CallingPoint:
    """One stop on a service. Times are datetime.time, either may be None."""

    __slots__ = ('tiploc', 'arrival', 'departure')

    def __init__(self, tiploc, arrival=None, departure=None):
        self.tiploc = tiploc
        self.arrival = arrival
        self.departure = departure

    def __repr__(self):
        return f'CallingPoint({self.tiploc}, arr={self.arrival}, dep={self.departure})'


class Service:
    """A single train, as an ordered list of calling points."""

    __slots__ = ('uid', 'calling_points', 'operator', 'runs_weekdays')

    def __init__(self, uid, calling_points, operator=None, runs_weekdays=True):
        self.uid = uid
        self.calling_points = calling_points
        self.operator = operator
        self.runs_weekdays = runs_weekdays

    def index_of(self, tiplocs):
        """First calling point matching any of these TIPLOCs, or None.

        Takes a set because a station often has several TIPLOCs - Clapham
        Junction has five, one per platform group - and a service may use any.
        """
        for i, cp in enumerate(self.calling_points):
            if cp.tiploc in tiplocs:
                return i
        return None


def _minutes_between(dep, arr):
    """Journey length in minutes, allowing for a service crossing midnight."""
    d = dep.hour * 60 + dep.minute
    a = arr.hour * 60 + arr.minute
    if a < d:
        a += 24 * 60
    return a - d


def journeys_for_pair(services, origin_tiplocs, terminal_tiplocs):
    """Every direct journey from origin to terminal, as (arrival, minutes).

    A service counts only if it calls at the origin *before* the terminal, so
    return workings in the opposite direction are excluded.
    """
    out = []
    origin_tiplocs = set(origin_tiplocs)
    terminal_tiplocs = set(terminal_tiplocs)

    for s in services:
        if not s.runs_weekdays:
            continue
        i = s.index_of(origin_tiplocs)
        if i is None:
            continue
        # The terminal must come after the origin on this service.
        j = None
        for k in range(i + 1, len(s.calling_points)):
            if s.calling_points[k].tiploc in terminal_tiplocs:
                j = k
                break
        if j is None:
            continue

        dep = s.calling_points[i].departure or s.calling_points[i].arrival
        arr = s.calling_points[j].arrival or s.calling_points[j].departure
        if dep is None or arr is None:
            continue

        mins = _minutes_between(dep, arr)
        if 0 < mins <= 24 * 60:
            out.append((arr, mins))
    return out


def in_peak(arrival):
    return PEAK_START <= arrival <= PEAK_END


def measure(services, origin_tiplocs, terminal_tiplocs):
    """Return the three measures, plus the evidence behind them.

    Every field is None when there is nothing to compute it from, rather than
    a zero or a guess - a station with no peak service should say so, not
    silently claim a typical time it does not have.
    """
    pairs = journeys_for_pair(services, origin_tiplocs, terminal_tiplocs)
    if not pairs:
        return {
            'fastest_mins': None,
            'typical_peak_mins': None,
            'peak_trains_per_hour': None,
            'peak_services': 0,
            'total_services': 0,
            'direct': False,
        }

    all_mins = [m for _, m in pairs]
    peak = [m for arr, m in pairs if in_peak(arr)]

    return {
        'fastest_mins': min(all_mins),
        'typical_peak_mins': round(statistics.median(peak)) if peak else None,
        'peak_trains_per_hour': round(len(peak) / PEAK_HOURS, 1) if peak else None,
        'peak_services': len(peak),
        'total_services': len(pairs),
        'direct': True,
    }


def compare_to_published(measured, published_mins):
    """How far a measured figure has drifted from what the site claims.

    Used to triage the refresh: the journeys that disagree most with the
    published number are the ones to look at first.
    """
    if measured.get('fastest_mins') is None or published_mins is None:
        return None
    return measured['fastest_mins'] - published_mins
