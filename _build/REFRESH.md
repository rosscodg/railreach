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

## Known gap in provenance

**How the original numbers were compiled is not documented, and cannot be
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

1. **Re-check the times.** For each terminal, the value is the fastest typical
   weekday service, not an average and not a one-off record. National Rail's
   journey planner is the reference. Where no direct service exists, the figure
   is the quickest one-change routing including a realistic interchange
   allowance, and `direct` must be `false`.

2. **Edit `_build/data/stations.json`.** It is the single source of truth. Do
   not edit `index.html`, the station pages or `assets/js/stations-data.js` by
   hand: the generator overwrites all of them.

3. **Set `lastReviewed`** to the date the review actually happened.

4. **Record what you did.** Add or update a `method` field alongside `source`
   describing how the times were obtained, so the next refresh does not start
   from the same blank page this one did.

5. **Regenerate:**

   ```bash
   python3 _build/generate-pages.py
   ```

   This rewrites all 358 pages, the sitemap, `llms.txt`, `llms-full.txt`, the
   markdown alternates, the CSV and JSON exports, and re-stamps the service
   worker cache so returning visitors get the new data.

6. **Check the build output.** It should report the new review date and confirm
   the timetable in force. The station and terminal counts should match what
   you expect.

7. **Verify, commit, push.** Pushing to `main` deploys to GitHub Pages.

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

The last row matters. The homepage FAQ and terminal summaries quote specific
times ("Stevenage 20 min", "Cambridge 49 min") in hand-written prose that the
generator does not touch. After a refresh, grep the homepage for any figure
that has moved.
