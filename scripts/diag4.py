#!/usr/bin/env python3
"""Test: require >=2 lines per transfer cluster + smaller threshold."""
import sys, math
import fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    project_to_polyline,
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

OFFICIAL_TOTAL = {
    "1": 28, "2": 31, "3": 29, "4": 26, "5": 19, "6": 28, "7": 33,
    "8": 30, "9": 35, "10": 37, "11": 40, "12": 32, "13": 31, "14": 30,
    "15": 30, "16": 13, "17": 14, "18": 31, "AL": 7, "Pujiang": 6,
}

for tol in [20, 25, 30]:
    for min_lines in [1, 2]:
        total_abs = 0
        print(f"\n=== TOL={tol}pt, min_lines>={min_lines} ===")
        for lid in sorted(polylines.keys(), key=lambda x: (0, int(x)) if x.isdigit() else (1, x)):
            polys = polylines[lid]
            n_ticks = len(ticks.get(lid, []))
            # Count transfer clusters where this line is a member (with >=min_lines constraint)
            n_trans = 0
            for cl in clusters:
                cx, cy = cl["cx"], cl["cy"]
                # Count how many lines are within tol
                member_lines = [
                    lx for lx, px in polylines.items()
                    if min(project_to_polyline((cx, cy), p)[0] for p in px) <= tol
                ]
                if len(member_lines) < min_lines:
                    continue
                d = min(project_to_polyline((cx, cy), p)[0] for p in polys)
                if d <= tol:
                    n_trans += 1
            total_est = n_ticks + n_trans
            official = OFFICIAL_TOTAL.get(lid, "?")
            diff = total_est - official if isinstance(official, int) else "?"
            mark = " ◄" if isinstance(diff, int) and abs(diff) > 1 else ""
            print(f"  L{lid:8}: {n_ticks}+{n_trans}={total_est:3d} (want {official}) diff={diff:+}{mark}")
            if isinstance(diff, int):
                total_abs += abs(diff)
        print(f"  Total abs deviation: {total_abs}")
