#!/usr/bin/env python3
"""Validate all 20 lines at a glance."""
import json

data = json.load(open('public/v2/stations.json'))

OFFICIAL = {
    "1": 28, "2": 31, "3": 29, "4": 26, "5": 19, "6": 28, "7": 33,
    "8": 30, "9": 35, "10": 37, "11": 40, "12": 32, "13": 31, "14": 30,
    "15": 30, "16": 13, "17": 14, "18": 31, "AL": 7, "Pujiang": 6, "ML": 2,
}

from collections import Counter
counts = Counter(s['line'] for s in data['stations'].values())
print(f"{'Line':>8} {'Official':>8} {'Detected':>8} {'Diff':>6}")
for lid in list(OFFICIAL.keys()):
    off = OFFICIAL[lid]
    det = counts.get(lid, 0)
    diff = det - off
    mark = " ✓" if diff == 0 else ""
    print(f"{lid:>8} {off:>8} {det:>8} {diff:>+6}{mark}")
