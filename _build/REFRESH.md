# Refreshing the journey time data

The site stamps a "Data reviewed" date on all 358 pages, repeats it in the
schema `dateModified`, and states it in `llms.txt` and the published dataset.
Those claims are the basis of the site's credibility with both Google and the
language models that cite it, so the date must never move without a real
review behind it.

## When

National Rail changes the national timetable twice a year:

- the **second Sunday of December** (the larger change)
- the **third Sunday of May**

`_build/generate-pages.py` computes these dates and prints the timetable
currently in force on every build. If the data predates it, the build prints a
loud warning. That warning is the trigger to do the work below.

Between those dates the published times do not go out of date in any
structural sense. Short-term disruption, engineering works and strikes are
explicitly out of scope and disclaimed on `/about/`.

## Provenance

Resolved. `build_dataset.py`, `journey_times.py` and `darwin_adapter.py`
compute the dataset from Darwin PPTimetable files, and `method` in
`stations.json` records exactly how. The gap described below applied to the
pre-August data and is kept for history.

### The original gap

**How the original numbers were compiled was not documented, and cannot be
reconstructed from this repository.**

`london_commute_comprehensive_90min.csv` in this directory is the earliest
surviving artefact. It contains **201 journeys**. The live dataset contains
**357**. The other 156 were added directly to the station data at some point
with no record of their source or method.

The practical consequence: there is no way to re-run the original process,
because nobody wrote it down. The first real refresh is therefore also the
moment to establish a repeatable one. Until that happens, treat
`source: National Rail operator timetables, 2026` in `stations.json` as a
statement of intent rather than a traceable citation.

## How

The sample is whatever `PPTimetable_*.xml.gz` files are sitting in
`_build/data/`. `feed.py` finds them, reads the date out of each filename and
refuses anything that cannot support an honest measurement. Nothing about the
sample is written in code any more, so a refresh is: swap the files, run three
commands.

1. **Download the timetable files** from the Rail Data Marketplace — one
   `_v8.xml.gz` per sample day, plus one `_ref_v4.xml.gz`. Keep Darwin's
   filenames; the date is in them.

   Pick a normal working week — avoid August, and the weeks either side of
   Christmas and Easter. Nothing in the pipeline can detect engineering work,
   because a reduced timetable is still a valid timetable, and the three
   sampled days come out near-identical whether or not the line is blocked.

   That is a precaution, not a diagnosis. The August 2026 sample was checked
   against Realtime Trains and holds up: Brighton's 60 minutes to Victoria on
   2.0 peak trains an hour is simply what the timetable does — the Gatwick
   Express runs twice an hour and takes 65 in the peak, which is the figure
   the dataset publishes. An earlier note here claimed that sample had caught
   engineering work. It had not.

   **Five days beats three.** The floor is three, but 26 routes currently rest
   on two peak trains a day, where a median is an anecdote. Five days nearly
   doubles the services behind every figure.

2. **Replace the old files.** Delete the previous `_v8` and `_ref` files —
   leaving them in means measuring the old days as well, and `feed.py` will
   refuse a duplicate day but happily pool two separate weeks.

3. **Measure:**

   ```bash
   python3 _build/recompute.py --write
   ```

   Prints the sample it found before doing anything, then writes
   `measured.json`. Takes about 20 seconds. Read the comparison it prints —
   that is the point of the step.

4. **Rebuild the dataset:**

   ```bash
   python3 _build/build_dataset.py --write
   ```

   `lastReviewed` is set to today. Pass `--reviewed YYYY-MM-DD` to record a
   different date, which is only right if the review genuinely happened then.
   The `method` string, `sampleDays` and the "N midweek days" phrasing all come
   from the files found in step 1, so they cannot describe days that were not
   measured.

5. **Regenerate the site:**

   ```bash
   python3 _build/generate-pages.py
   ```

6. **Check the output.** It should report the new review date, the timetable in
   force, and 100 quoted figures agreeing with the data.

   Spot-check against <https://www.realtimetrains.co.uk>, which shows the
   working timetable rather than a journey planner's suggestion. Verified
   against the August sample: Reading to Paddington 23 minutes, Watford
   Junction to Euston 15, Brighton to Victoria 60 fastest with a 65-minute
   peak median, Chatham to St Pancras 39 fastest against a 68-minute median.
   Check memory against the feed rather than the other way round — three of
   those looked wrong to me and were not.

7. **Run the tests:** `python3 _build/test_journey_times.py`

8. **Verify, commit, push.** Pushing to `main` deploys to GitHub Pages.

### What the sample check refuses

`feed.py` stops the run rather than publishing a measurement it cannot stand
behind:

| Situation | Why |
| --- | --- |
| No `_v8` files | Nothing to measure |
| No `_ref_v4` file | TIPLOC codes cannot be matched to stations |
| Fewer than three days | A median over fewer is an anecdote |
| Any Saturday or Sunday | The site publishes weekday commutes |
| Two files covering one day | Measuring a day twice weights it double |

Non-consecutive days are allowed, and noted in the output so the choice is
visible.

## What must stay in step

Changing the journey data touches more than the pages:

| Surface | Regenerated automatically |
| --- | --- |
| 358 HTML pages | yes |
| 354 markdown alternates | yes |
| `sitemap.xml` | yes (`lastmod` = build date) |
| `llms.txt`, `llms-full.txt` | yes |
| `data/journey-times.{csv,json}` | yes |
| `sw.js` cache name | yes (content-hashed) |
| Hand-written FAQ prose on the homepage | **no — check manually** |

The last row is out of date: `sync_index()` now regenerates the homepage FAQ
and terminal summaries from the dataset, so those figures cannot drift and do
not need grepping. `check_prose_figures()` verifies all 100 of them on every
build and fails loudly if the generator writes one the data does not support.

Both forms are checked - "Stevenage (20 min)" against every terminal it
serves, and "Kentish Town (5 min to St Pancras)" against St Pancras
specifically.
