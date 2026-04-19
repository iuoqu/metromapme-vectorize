#!/usr/bin/env python3
"""For each 39x29 rectangle, find its nearest line."""
import sys, math
import fitz
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map,
    extract_polylines_per_color, project_to_polyline,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)

# Find all 39x29 rectangles (single-line station markers)
rects = []
for d in page.get_drawings():
    if d.get("type") != "fs":
        continue
    c = d.get("color")
    fill = d.get("fill")
    if not c or not fill:
        continue
    if not all(x > 0.95 for x in fill):
        continue
    if not all(x < 0.2 for x in c):
        continue
    w = d.get("width", 0)
    if abs((w or 0) - 3.0) > 0.5:
        continue
    r = d.get("rect")
    if not r:
        continue
    if max(r.width, r.height) > 50 or min(r.width, r.height) < 10:
        continue
    items = d.get("items", [])
    if len(items) != 6:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    rects.append((cx, cy, r.width, r.height))

print(f"Found {len(rects)} 39x29 rectangles")

# For each, find nearest line
counts = Counter()
for cx, cy, rw, rh in rects:
    best_lid, best_d = None, float("inf")
    for lid, polys in polylines.items():
        d = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if d < best_d:
            best_d = d
            best_lid = lid
    counts[best_lid] += 1

print("\nNearest line distribution:")
for lid, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  L{lid}: {n} rectangles")
