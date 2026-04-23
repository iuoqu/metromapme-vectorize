#!/usr/bin/env python3
"""Find the white-fill black-border line near Sanlinnan, and L2/L7 extra clusters."""
import sys, math, fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    project_to_polyline, _dist, color_close, LINE_STROKE_WIDTH,
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

print("=== Looking for black-outline strokes (potential new lines) ===")
# Black-bordered white or gray strokes (type="fs", fill=white or near-white, stroke=black)
black_border_strokes = []
for d in page.get_drawings():
    fill = d.get("fill")
    color = d.get("color")  # stroke color
    if not fill or not color:
        continue
    # White or near-white fill
    if not all(x > 0.85 for x in fill):
        continue
    # Black or dark stroke
    if not all(x < 0.15 for x in color):
        continue
    w = d.get("width", 0)
    if w < 8:
        continue
    r = d.get("rect")
    if not r:
        continue
    items = d.get("items", [])
    black_border_strokes.append({
        "cx": (r.x0 + r.x1) / 2,
        "cy": (r.y0 + r.y1) / 2,
        "w": w,
        "fill": tuple(round(x, 2) for x in fill),
        "color": tuple(round(x, 2) for x in color),
        "n_items": len(items),
        "rect": (round(r.x0), round(r.y0), round(r.x1), round(r.y1)),
    })

print(f"  Found {len(black_border_strokes)} black-border strokes with white fill")
if black_border_strokes:
    # Sort by y (top to bottom)
    black_border_strokes.sort(key=lambda d: d["cy"])
    for s in black_border_strokes[:30]:
        print(f"    ({s['cx']:.0f},{s['cy']:.0f}) w={s['w']} fill={s['fill']} stroke={s['color']} items={s['n_items']} rect={s['rect']}")

print()
print("=== Looking for fs/f strokes with any non-white fill but black outline ===")
# More general: any stroke drawing with a dark border
black_stroke_lines = []
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype != "s":
        continue
    color = d.get("color")
    if not color:
        continue
    if not all(x < 0.15 for x in color):  # not black/dark
        continue
    w = d.get("width", 0)
    if w < 8:
        continue
    r = d.get("rect")
    if not r:
        continue
    items = d.get("items", [])
    n = len(items)
    if n < 5:
        continue
    black_stroke_lines.append({
        "cx": (r.x0 + r.x1) / 2,
        "cy": (r.y0 + r.y1) / 2,
        "w": w,
        "color": tuple(round(x, 2) for x in color),
        "n_items": n,
        "rect": (round(r.x0), round(r.y0), round(r.x1), round(r.y1)),
    })

print(f"  Found {len(black_stroke_lines)} thick dark-stroke lines")
for s in sorted(black_stroke_lines, key=lambda d: d["cy"])[:20]:
    print(f"    ({s['cx']:.0f},{s['cy']:.0f}) w={s['w']} color={s['color']} items={s['n_items']} rect={s['rect']}")

print()
print("=== L2 overcounting at 30pt: which clusters are wrong? ===")
L2_polys = polylines.get("2", [])
tol = 30
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    d_L2 = min(project_to_polyline((cx, cy), p)[0] for p in L2_polys)
    if d_L2 > tol:
        continue
    # Check all lines at 30pt
    members = {}
    for lid, polys in polylines.items():
        bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if bd <= tol:
            members[lid] = round(bd, 1)
    print(f"  Cluster {ci:3d} ({cx:.0f},{cy:.0f}): d_L2={d_L2:.1f} members={members}")

print()
print("=== L7 overcounting at 30pt: which clusters are wrong? ===")
L7_polys = polylines.get("7", [])
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    d_L7 = min(project_to_polyline((cx, cy), p)[0] for p in L7_polys)
    if d_L7 > tol:
        continue
    members = {}
    for lid, polys in polylines.items():
        bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if bd <= tol:
            members[lid] = round(bd, 1)
    print(f"  Cluster {ci:3d} ({cx:.0f},{cy:.0f}): d_L7={d_L7:.1f} members={members}")
