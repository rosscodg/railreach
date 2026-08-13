#!/usr/bin/env python3
"""Report the structure of a downloaded timetable file.

Run this against whatever comes out of the Rail Data Marketplace Data files
tab before writing an adapter. It identifies the container, finds the schedule
records, and prints a couple of real examples with their calling points, so the
adapter is written against the actual file rather than an assumption about it.

Handles gzip, zip, plain XML, CIF and JSON without being told which it is.

Usage:  python3 _build/inspect_feed.py <path-to-file>
"""

import gzip
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter

PEEK = 400_000  # enough to characterise the file without loading gigabytes


def open_any(path):
    """Return (label, bytes) for the payload, unwrapping compression."""
    with open(path, 'rb') as f:
        head = f.read(4)
    if head[:2] == b'\x1f\x8b':
        with gzip.open(path, 'rb') as f:
            return 'gzip', f.read(PEEK)
    if head[:2] == b'PK':
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            print(f"  zip containing {len(names)} entries: {names[:8]}")
            inner = max(names, key=lambda n: z.getinfo(n).file_size)
            print(f"  inspecting the largest: {inner}")
            with z.open(inner) as f:
                return f'zip:{inner}', f.read(PEEK)
    with open(path, 'rb') as f:
        return 'plain', f.read(PEEK)


def describe_xml(text):
    print("\n  looks like XML")
    tags = Counter(re.findall(r'<([A-Za-z_][\w.:-]*)', text))
    print("  most frequent elements:")
    for tag, n in tags.most_common(14):
        print(f"    {tag:<28} {n}")

    # Darwin timetable files use <Journey> with calling points OR/IP/PP/DT.
    j = re.search(r'<(\w*[Jj]ourney)\b.*?</\1>', text, re.S)
    if j:
        snippet = j.group(0)
        print(f"\n  first journey record ({len(snippet)} chars):")
        for line in snippet.splitlines()[:18]:
            print("    " + line.strip()[:150])
        tiplocs = re.findall(r'tpl="([A-Z0-9]+)"', snippet)
        times = re.findall(r'(?:wtd|wta|ptd|pta|dep|arr)="([\d:]+)"', snippet)
        print(f"\n  TIPLOCs in that record: {tiplocs[:12]}")
        print(f"  times in that record:   {times[:12]}")
    else:
        print("\n  no <Journey> element found - print the first 1200 chars to eyeball:")
        print("    " + text[:1200].replace('\n', '\n    '))


def describe_cif(text):
    print("\n  looks like CIF (fixed-width records)")
    types = Counter(line[:2] for line in text.splitlines() if len(line) >= 2)
    print("  record types present:")
    labels = {'HD': 'header', 'TI': 'TIPLOC insert', 'BS': 'basic schedule',
              'BX': 'basic schedule extra', 'LO': 'origin', 'LI': 'intermediate',
              'LT': 'terminating', 'CR': 'changes en route', 'AA': 'association',
              'ZZ': 'trailer'}
    for t, n in types.most_common(12):
        print(f"    {t}  {labels.get(t, ''):<22} {n}")
    for want in ('BS', 'LO', 'LI', 'LT'):
        line = next((l for l in text.splitlines() if l.startswith(want)), None)
        if line:
            print(f"\n  sample {want} ({labels.get(want,'')}):")
            print(f"    {line[:120]}")


def describe_json(text):
    print("\n  looks like JSON")
    try:
        first = json.loads(text.splitlines()[0])
        print("  newline-delimited JSON; first record keys:", list(first.keys())[:14])
        print("  sample:", json.dumps(first)[:400])
    except Exception:
        try:
            obj = json.loads(text)
            print("  single JSON document; top-level keys:",
                  list(obj.keys())[:14] if isinstance(obj, dict) else f'array of {len(obj)}')
        except Exception as e:
            print("  could not parse as JSON:", e)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"No such file: {path}")
        return 1

    size = os.path.getsize(path)
    print(f"file: {path}")
    print(f"size: {size:,} bytes")

    label, raw = open_any(path)
    print(f"container: {label}")
    text = raw.decode('utf-8', errors='replace')

    stripped = text.lstrip()
    if stripped.startswith('<'):
        describe_xml(text)
    elif stripped.startswith('{') or stripped.startswith('['):
        describe_json(text)
    elif re.match(r'^(HD|BS|TI)', stripped):
        describe_cif(text)
    else:
        print("\n  unrecognised format; first 1000 chars:")
        print("    " + text[:1000].replace('\n', '\n    '))

    print("\nNext: the adapter turns these records into journey_times.Service objects.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
