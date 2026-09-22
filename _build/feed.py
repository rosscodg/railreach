"""Which Darwin timetable files a refresh measures, discovered not listed.

The sample used to be three filenames and three dates written into
`recompute.py`, with the reference file named again in `build_dataset.py` and
the dates a third time in the `method` string. Four places to edit, in two
files, to change one thing - and a refresh that updated three of them would
publish a `method` describing days it had not measured.

Now: drop the `.xml.gz` files into `_build/data/` and run. The filenames carry
their own dates, so that is the whole edit.

Darwin names them `PPTimetable_YYYYMMDDHHMMSS_v8.xml.gz` for a day's
timetable, and `..._ref_v4.xml.gz` for the reference data that maps TIPLOC
codes to station names. The timestamp is when the file was generated, in the
small hours of the day it covers.
"""

import os
import re
import datetime

SAMPLE_RE = re.compile(r'^PPTimetable_(\d{8})\d{6}_v8\.xml\.gz$')
REF_RE = re.compile(r'^PPTimetable_(\d{8})\d{6}_ref_v\d+\.xml\.gz$')

# Below this, a median is an anecdote. Three days was the original sample and
# is the floor, not the target: five gives nearly twice the services per route,
# which is what thin-sample routes need.
MIN_DAYS = 3

WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')


class FeedError(Exception):
    """Raised when the files present cannot support an honest measurement."""


def _date_of(stamp):
    return datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))


def discover(data_dir):
    """The sample files and the reference file, oldest first.

    Returns (samples, ref_path) where samples is a list of (path, isodate).
    """
    names = sorted(os.listdir(data_dir))
    samples = []
    for n in names:
        m = SAMPLE_RE.match(n)
        if m:
            samples.append((os.path.join(data_dir, n), _date_of(m.group(1))))
    refs = [os.path.join(data_dir, n) for n in names if REF_RE.match(n)]

    if not samples:
        raise FeedError(
            f"No PPTimetable_*_v8.xml.gz files in {data_dir}.\n"
            "Download a weekday's timetable per sample day from the Rail Data\n"
            "Marketplace and drop them in unchanged - the filename carries the date.")
    if not refs:
        raise FeedError(
            f"No PPTimetable_*_ref_v*.xml.gz reference file in {data_dir}.\n"
            "It maps TIPLOC codes to station names; without it nothing can be\n"
            "matched to a station.")

    samples.sort(key=lambda s: s[1])
    dates = [d for _p, d in samples]
    if len(set(dates)) != len(dates):
        dupes = sorted({d.isoformat() for d in dates if dates.count(d) > 1})
        raise FeedError(f"Two timetable files cover the same day: {', '.join(dupes)}.\n"
                        "Remove the older one; measuring a day twice weights it double.")

    weekend = [d for d in dates if d.weekday() >= 5]
    if weekend:
        raise FeedError(
            "Weekend timetables in the sample: "
            + ', '.join(f'{d} ({WEEKDAYS[d.weekday()] if d.weekday() < 5 else d.strftime("%A")})'
                        for d in weekend)
            + ".\nThe site publishes weekday commutes. A Saturday service would drag\n"
              "every median it touches.")

    if len(samples) < MIN_DAYS:
        raise FeedError(f"Only {len(samples)} day(s) of timetable; {MIN_DAYS} is the "
                        "minimum.\nA median over fewer is an anecdote.")

    # The newest reference file: TIPLOC names change, and the one closest to
    # the sample is the one that describes it.
    ref = max(refs)
    return samples, ref


def sample_days(samples):
    return [d.isoformat() for _p, d in samples]


def describe(samples):
    """A phrase for the published `method`, so it can never name days that
    were not measured."""
    n = len(samples)
    words = {3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven',
             8: 'eight', 9: 'nine', 10: 'ten'}.get(n, str(n))
    span = ', '.join(sample_days(samples))
    return f'{words} midweek days ({span})'


def report(samples, ref):
    """What was found, printed before anything is measured."""
    print(f"  timetable sample: {len(samples)} days")
    for path, d in samples:
        print(f"    {d} {d.strftime('%A'):<10} {os.path.basename(path)}")
    print(f"  reference data:   {os.path.basename(ref)}")
    span = (samples[-1][1] - samples[0][1]).days + 1
    if span != len(samples):
        print(f"  note: the {len(samples)} days span {span} calendar days, so they "
              "are not consecutive")
