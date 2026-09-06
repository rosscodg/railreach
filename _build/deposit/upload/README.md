---
license: cc-by-4.0
language:
  - en
pretty_name: UK train journey times to London terminals (2026)
size_categories:
  - 1K<n<10K
tags:
  - rail
  - transport
  - united-kingdom
  - london
  - commuting
  - open-data
configs:
  - config_name: default
    data_files:
      - split: train
        path: journey-times.csv
---

# UK train journey times to London terminals (2026)

Scheduled train journey times from 571 British railway stations to the 11 London main line terminals, covering 1228 station-to-terminal pairs of 90 minutes or less.

Each pair carries the fastest weekday journey allowing at most one change (naming the interchange where it uses one), the fastest direct service, the median journey of direct services arriving in London between 07:00 and 09:30, and how many such services run per hour. 734 of the pairs are direct and 769 carry a peak median.

The peak median is the reason this dataset exists. Published journey times are almost always the fastest service of the day, which is rarely the one a commuter can catch; holding both figures makes the difference measurable. Across the 534 direct routes the peak is slower than the advertised best on 490 of them and faster on none, by a median of 5 minutes and by as much as 31.

Computed from Darwin Timetable Files published by the Rail Delivery Group under the Open Government Licence v3.0, sampled across 2026-08-11, 2026-08-12, 2026-08-13. Station coordinates come from NaPTAN. Only passenger services are counted; passing points, operational stops and cancelled services are excluded, and stations are matched to timetable records on TIPLOC.

Limitations: these are scheduled times, not observed ones. They exclude delays, cancellations, engineering work and crowding, and they are not live departure times. Connections allow a uniform 8 minutes because station-by-station minimum connection times are not published in the feed. Fares are not included.

## Columns

| Column | Meaning |
| --- | --- |
| `station` | Station name as published by NaPTAN |
| `station_slug` | URL-safe identifier, stable across releases |
| `latitude, longitude` | Station coordinates (NaPTAN, WGS84) |
| `london_terminal` | Destination terminal name |
| `terminal_code` | Three-letter terminal code, e.g. WAT |
| `fastest_minutes` | Quickest weekday journey, at most one change |
| `fastest_direct_minutes` | Quickest journey with no change; empty if none runs |
| `change_at` | Interchange used by the fastest journey; empty when direct |
| `typical_peak_minutes` | Median of direct services arriving 07:00-09:30 |
| `peak_trains_per_hour` | Direct arrivals per hour in that window |
| `direct` | Whether the fastest journey is direct |
| `operators` | Train operating companies on the route |

## Provenance

- Source: Darwin Timetable Files (Rail Delivery Group), via the Rail Data Marketplace, under the Open Government Licence v3.0
- Sample days: 2026-08-11, 2026-08-12, 2026-08-13
- Coordinates: NaPTAN (Department for Transport), ATCO area 910, updated 2026-08-13
- Threshold: journeys of 90 minutes or less
- Last reviewed: 2026-08-17

## Citation

```
RailReach (2026). UK train journey times to London terminals. Dataset, reviewed 2026-08-17. CC BY 4.0. https://railreach.co.uk/
```

## Documentation

Full methodology, including what the figures do not cover: https://railreach.co.uk/about/
