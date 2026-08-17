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


def measure(services, origin_tiplocs, terminal_tiplocs, days=1):
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
            'days_sampled': days,
            'direct': False,
        }

    all_mins = [m for _, m in pairs]
    peak = [m for arr, m in pairs if in_peak(arr)]

    return {
        'fastest_mins': min(all_mins),
        'typical_peak_mins': round(statistics.median(peak)) if peak else None,
        # Divided by the number of days pooled, or three midweek days would
        # look like three times the service.
        'peak_trains_per_hour': round(len(peak) / (PEAK_HOURS * days), 1) if peak else None,
        'peak_services': len(peak),
        'total_services': len(pairs),
        'days_sampled': days,
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


# ── Journeys with one change ────────────────────────────────────────────────
# Measuring only direct services understated 50 of 530 published journeys, some
# badly: Sevenoaks to St Pancras is 76 minutes direct and 43 with one change.
# Twenty more pairs had no direct service at all and so carried no time.
#
# One change, not two. Each additional change multiplies the search and, more
# to the point, a two-change itinerary is not a commute anybody sustains.

# A uniform allowance, because National Rail's station-by-station minimum
# connection times are not in the timetable feed. Eight minutes is deliberately
# more cautious than the five a journey planner will offer at a simple
# same-platform change: five also permits five-minute changes at termini where
# that is not realistic, and publishing a connection nobody can make is worse
# than publishing a slightly slow one. Stated on the methodology page, and one
# constant to change if station-level data ever becomes available.
MIN_INTERCHANGE_MINS = 8


def calling_points_abs(service):
    """Calling points as (tiploc, arrival, departure) in absolute minutes.

    Times in the feed are wall-clock, so a service running past midnight goes
    backwards. Walking the calls and adding a day whenever time decreases keeps
    each service monotonic, which is what makes one service's arrival
    comparable with another's departure.
    """
    out, bump, prev = [], 0, None
    for cp in service.calling_points:
        a = None if cp.arrival is None else cp.arrival.hour * 60 + cp.arrival.minute
        d = None if cp.departure is None else cp.departure.hour * 60 + cp.departure.minute
        base = a if a is not None else d
        if base is None:
            continue
        if prev is not None and base + bump < prev:
            bump += 24 * 60
        a = None if a is None else a + bump
        d = None if d is None else d + bump
        prev = max(x for x in (a, d) if x is not None)
        out.append((cp.tiploc, a, d))
    return out


def build_terminal_index(services, terminal_tiplocs, calls_cache=None):
    """Where can I get to the terminal from, and how soon?

    For every tiploc, the services calling there that later reach the terminal,
    as (departure, arrival at terminal), sorted by departure with a suffix
    minimum over arrivals. That turns "leave here no earlier than X, when do I
    arrive" into one binary search rather than a scan.
    """
    import bisect  # noqa: F401  (documented dependency of the lookup below)
    reach = {}
    terminal_tiplocs = set(terminal_tiplocs)
    for s in services:
        if not s.runs_weekdays:
            continue
        cs = calls_cache[id(s)] if calls_cache else calling_points_abs(s)
        arrives_at = None
        for i in range(len(cs) - 1, -1, -1):
            tpl, a, d = cs[i]
            if tpl in terminal_tiplocs and a is not None:
                arrives_at = a          # a later call at the terminal
                continue
            if arrives_at is not None and d is not None:
                reach.setdefault(tpl, []).append((d, arrives_at))
    index = {}
    for tpl, pairs in reach.items():
        pairs.sort()
        deps = [p[0] for p in pairs]
        best, running = [0] * len(pairs), None
        for i in range(len(pairs) - 1, -1, -1):
            running = pairs[i][1] if running is None else min(running, pairs[i][1])
            best[i] = running
        index[tpl] = (deps, best)
    return index


def earliest_arrival(index, tiploc, not_before):
    """Soonest arrival at the terminal leaving `tiploc` at or after a time."""
    import bisect
    entry = index.get(tiploc)
    if not entry:
        return None
    deps, best = entry
    i = bisect.bisect_left(deps, not_before)
    return best[i] if i < len(deps) else None


def fastest_one_change(services, origin_tiplocs, terminal_tiplocs, index,
                       min_connect=MIN_INTERCHANGE_MINS, calls_cache=None):
    """Quickest origin-to-terminal journey changing exactly once.

    Returns (minutes, interchange_tiploc), or (None, None). The terminal itself
    is never treated as an interchange: arriving there is the journey ending,
    not a place to change.
    """
    origin_tiplocs = set(origin_tiplocs)
    terminal_tiplocs = set(terminal_tiplocs)
    best, best_at = None, None
    for s in services:
        if not s.runs_weekdays:
            continue
        cs = calls_cache[id(s)] if calls_cache else calling_points_abs(s)
        for i, (tpl, _a, dep) in enumerate(cs):
            if tpl not in origin_tiplocs or dep is None:
                continue
            for j in range(i + 1, len(cs)):
                via, arr, _d = cs[j]
                if via in terminal_tiplocs or arr is None or via in origin_tiplocs:
                    continue
                reached = earliest_arrival(index, via, arr + min_connect)
                if reached is None:
                    continue
                total = reached - dep
                if 0 < total <= 24 * 60 and (best is None or total < best):
                    best, best_at = total, via
    return best, best_at
