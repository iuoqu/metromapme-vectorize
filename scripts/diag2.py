#!/usr/bin/env python3
"""Count per-line transfer clusters at different distance thresholds."""
import sys, math
import fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    project_to_polyline, _dist,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)
ticks = extract_station_ticks(page, color_to_line)
clusters = extract_station_marker_clusters(page)

OFFICIAL_TRANSFER = {
    "1": 12, "2": 13, "3": 12, "4": 15, "5": 8, "6": 9, "7": 12,
    "8": 13, "9": 12, "10": 13, "11": 14, "12": 12, "13": 13, "14": 12,
    "15": 11, "16": 5, "17": 6, "18": 11, "AL": 3, "Pujiang": 2,
}
OFFICIAL_TOTAL = {
    "1": 28, "2": 31, "3": 29, "4": 26, "5": 19, "6": 28, "7": 33,
    "8": 30, "9": 35, "10": 37, "11": 40, "12": 32, "13": 31, "14": 30,
    "15": 30, "16": 13, "17": 14, "18": 31, "AL": 7, "Pujiang": 6, "ML": 2,
}

for tol in [30, 35, 40, 45, 65]:
    print(f"\n=== TOL = {tol}pt ===")
    total_extra = 0
    for lid in sorted(polylines.keys(), key=lambda x: (0, int(x)) if x.isdigit() else (1, x)):
        polys = polylines[lid]
        n_transfer = sum(
            1 for cl in clusters
            if min(project_to_polyline((cl["cx"], cl["cy"]), p)[0] for p in polys) <= tol
        )
        n_ticks = len(ticks.get(lid, []))
        total_est = n_ticks + n_transfer
        official_total = OFFICIAL_TOTAL.get(lid, "?")
        official_trans = OFFICIAL_TRANSFER.get(lid, "?")
        diff = total_est - official_total if isinstance(official_total, int) else "?"
        diff_t = n_transfer - official_trans if isinstance(official_trans, int) else "?"
        mark = " ◄" if abs(diff) > 1 and isinstance(diff, int) else ""
        print(f"  L{lid:8}: ticks={n_ticks:2d}+trans={n_transfer:2d}={total_est:3d} (want {official_total}) diff={diff:+d} trans_diff={diff_t:+d}{mark}")
        if isinstance(diff, int):
            total_extra += abs(diff)
    print(f"  Total abs deviation: {total_extra}")
