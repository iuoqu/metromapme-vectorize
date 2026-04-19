#!/usr/bin/env python3
"""Find the undetected line passing through 三林南."""
import sys, math, fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    project_to_polyline, color_close, COLOR_TOL,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)

# Find all thick strokes with items >= 3 in y range 3500-5500 (where 三林南 is)
# These are candidate line segments
print("=== Thick strokes with multi-item paths in y=3500-5500 band ===")
segments = []
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype != "s":
        continue
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    if cy < 3500 or cy > 5500:
        continue
    w = d.get("width", 0)
    if (w or 0) < 8:
        continue
    c = d.get("color")
    if not c:
        continue
    items = d.get("items", [])
    if len(items) < 2:
        continue
    c_r = tuple(round(x, 3) for x in c)
    # Check if known or unknown
    best_d, best_l = float("inf"), None
    for cl, lid in color_to_line.items():
        dd = sum(abs(c_r[i] - cl[i]) for i in range(3))
        if dd < best_d:
            best_d, best_l = dd, lid
    known = best_l if best_d < 0.075 else "UNKNOWN"
    segments.append((cx, cy, w, len(items), c_r, known, r))

segments.sort(key=lambda x: x[1])
for cx, cy, w, ni, c_r, known, r in segments:
    mark = " *** UNDETECTED ***" if known == "UNKNOWN" else ""
    print(f"  ({cx:.0f},{cy:.0f}) w={w} items={ni} color={c_r} → {known} rect=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f}){mark}")

# Also look for black/white strokes with items >= 2
print()
print("=== Black (0,0,0) and white (1,1,1) thick strokes anywhere ===")
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype != "s":
        continue
    c = d.get("color")
    if not c:
        continue
    w = d.get("width", 0)
    if (w or 0) < 8:
        continue
    c_r = tuple(round(x, 2) for x in c)
    if c_r not in [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]:
        continue
    r = d.get("rect")
    items = d.get("items", [])
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    print(f"  color={c_r} w={w} items={len(items)} at ({cx:.0f},{cy:.0f}) rect=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f})")

# Find where texts near 三林南 are and what's in that area
print()
print("=== All strokes within 200pt of 三林南 (2768,4430) ===")
SL = (2768, 4430)
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    dist = math.hypot(cx - SL[0], cy - SL[1])
    if dist > 200:
        continue
    dtype = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x, 2) for x in c) if c else None
    fill_r = tuple(round(x, 2) for x in fill) if fill else None
    print(f"  d={dist:.0f}pt type={dtype} w={w} color={c_r} fill={fill_r} items={len(items)} at ({cx:.0f},{cy:.0f})")
