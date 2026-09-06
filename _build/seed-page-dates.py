#!/usr/bin/env python3
"""Rebuild _build/data/page-hashes.json from git history.

The sitemap gives each URL a lastmod taken from when that page's content last
actually changed, tracked in a manifest that the generator maintains. This
script recovers that manifest for pages that predate it, or after it has been
deleted, by walking the history and finding the commit that introduced each
page's current content.

It is not part of the build: a normal build only needs to know what changed
since the last one, which the manifest already records. Run it by hand.

Why not `git log -1 -- <path>`: every past build rewrote all 590 pages, so the
last commit touching a file is nearly always the last build, not the last time
the file said anything different. That is precisely the fault the manifest
exists to fix, so seeding from it would reproduce it.

Usage:  python3 _build/seed-page-dates.py [--write]
"""

import os
import sys
import json
import subprocess
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pagehash import content_hash          # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(BASE, '_build', 'data', 'page-hashes.json')
SITE = "https://railreach.co.uk"

def run(args):
    return subprocess.run(args, cwd=BASE, capture_output=True, text=True,
                          check=True).stdout


def sitemap_paths():
    """The URLs the sitemap publishes, paired with the file behind each."""
    tree = ET.parse(os.path.join(BASE, 'sitemap.xml'))
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    out = {}
    for loc in tree.iterfind('.//s:url/s:loc', ns):
        url = loc.text.strip()
        path = url[len(SITE):]
        rel = 'index.html' if path == '/' else path.strip('/') + '/index.html'
        out[path] = rel
    return out


def history():
    """Commits that touched any HTML, newest first, as (sha, date)."""
    out = run(['git', 'log', '--format=%H %ad', '--date=short', '--', '*.html'])
    rows = []
    for line in out.splitlines():
        sha, _, date = line.partition(' ')
        if sha and date:
            rows.append((sha, date.strip()))
    return rows


def blobs_at(sha, rels):
    """Normalised hash of each path at one commit; missing files are skipped.

    One `git cat-file --batch` process for the whole commit rather than a
    subprocess per file: at 590 pages across 55 commits the difference is
    minutes.
    """
    req = ''.join(f'{sha}:{rel}\n' for rel in rels)
    proc = subprocess.run(['git', 'cat-file', '--batch'], cwd=BASE,
                          input=req.encode(), capture_output=True)
    data, out, i = proc.stdout, {}, 0
    for rel in rels:
        nl = data.index(b'\n', i)
        header = data[i:nl].decode()
        if header.endswith(' missing'):
            i = nl + 1
            continue
        size = int(header.rsplit(' ', 1)[1])
        body = data[nl + 1:nl + 1 + size]
        i = nl + 1 + size + 1          # trailing newline after the blob
        out[rel] = content_hash(body.decode('utf-8', 'replace'))
    return out


def main():
    write = '--write' in sys.argv
    paths = sitemap_paths()
    print(f"{len(paths)} URLs in the sitemap")

    current = {}
    for path, rel in paths.items():
        full = os.path.join(BASE, rel)
        if not os.path.exists(full):
            print(f"  missing on disk, skipped: {rel}")
            continue
        with open(full, encoding='utf-8') as f:
            current[path] = content_hash(f.read())

    commits = history()
    print(f"{len(commits)} commits touching HTML, "
          f"{commits[-1][1]} to {commits[0][1]}")

    # Walk back in time. A page's date is the oldest commit still carrying the
    # content it has now; once a commit disagrees, the page is settled.
    settled, dates = set(), {}
    rel_of = {p: r for p, r in paths.items() if p in current}
    for sha, date in commits:
        live = [p for p in current if p not in settled]
        if not live:
            break
        got = blobs_at(sha, [rel_of[p] for p in live])
        for path in live:
            h = got.get(rel_of[path])
            if h is not None and h == current[path]:
                dates[path] = date        # still the same this far back
            else:
                settled.add(path)         # differs, or did not exist yet

    manifest = {}
    for path, h in current.items():
        manifest[path] = {'hash': h, 'lastmod': dates.get(path, commits[0][1])}

    spread = {}
    for v in manifest.values():
        spread[v['lastmod']] = spread.get(v['lastmod'], 0) + 1
    print(f"\n{len(spread)} distinct dates:")
    for d in sorted(spread, reverse=True):
        print(f"  {d}  {spread[d]:>4} pages")

    if write:
        with open(MANIFEST, 'w') as f:
            json.dump(manifest, f, indent=1, sort_keys=True)
        print(f"\nwrote {os.path.relpath(MANIFEST, BASE)}")
    else:
        print("\nreport only; pass --write to update the manifest")


if __name__ == '__main__':
    main()
