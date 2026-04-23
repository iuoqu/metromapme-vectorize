#!/usr/bin/env python3
"""Find which lines pass through 三林南 and find any undetected line."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    project_to_polyline, LINE_STROKE_WIDTH,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)

# 三林南 is at approximately (2768, 4430)
SL = (2768, 4430)

print("=== Lines passing near 三林南 (2768,4430) ===")
distances = []
for lid, polys in polylines.items():
    d = min(project_to_polyline(SL, p)[0] for p in polys)
    distances.append((d, lid))
distances.sort()
for d, lid in distances[:10]:
    print(f"  Line {lid}: {d:.1f}pt from 三林南")

print()
print("=== All drawings within 60pt of 三林南 ===")
from collections import defaultdict
nearby = []
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    dist = math.hypot(cx - SL[0], cy - SL[1])
    if dist > 60:
        continue
    dtype = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x, 2) for x in c) if c else None
    fill_r = tuple(round(x, 2) for x in fill) if fill else None
    line_id = "?"
    if c:
        c_rounded = tuple(round(x, 3) for x in c)
        best_d, best_l = float("inf"), None
        for cl, lid in color_to_line.items():
            dd = sum(abs(c_rounded[i] - cl[i]) for i in range(3))
            if dd < best_d:
                best_d, best_l = dd, lid
        if best_l and best_d < 0.075:
            line_id = best_l
    nearby.append((dist, dtype, c_r, fill_r, w, len(items), line_id, (round(cx), round(cy))))

nearby.sort()
for dist, dtype, c_r, fill_r, w, ni, lid, pos in nearby:
    print(f"  d={dist:.0f}pt type={dtype} color={c_r} fill={fill_r} w={w} items={ni} line={lid} pos={pos}")

print()
print("=== Check for ALL gray-scale thick strokes (potential un-detected lines) ===")
# Look for strokes with gray/dark colors that are NOT in color_to_line
undetected_colors = defaultdict(list)
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype != "s":
        continue
    w = d.get("width", 0)
    if (w or 0) < 8:
        continue
    c = d.get("color")
    if not c:
        continue
    c_rounded = tuple(round(x, 3) for x in c)
    # Check if it's within 3*COLOR_TOL of any known line
    best_d, best_l = float("inf"), None
    for cl, lid in color_to_line.items():
        dd = sum(abs(c_rounded[i] - cl[i]) for i in range(3))
        if dd < best_d:
            best_d, best_l = dd, lid
    if best_d >= 0.075:  # not matched to any line
        r = d.get("rect")
        if r:
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            items = d.get("items", [])
            undetected_colors[c_rounded].append((cx, cy, w, len(items)))

print(f"  Undetected stroke colors (thick lines w>=8, not matching any known line):")
for c_r, pts in sorted(undetected_colors.items(), key=lambda x: -len(x[1]))[:15]:
    pts_sorted = sorted(pts, key=lambda p: p[0])
    print(f"  color={c_r}: {len(pts)} strokes, x-range=[{pts_sorted[0][0]:.0f},{pts_sorted[-1][0]:.0f}]")
    for cx, cy, w, ni in sorted(pts, key=lambda p: p[1])[:3]:
        print(f"    ({cx:.0f},{cy:.0f}) w={w} items={ni}")
