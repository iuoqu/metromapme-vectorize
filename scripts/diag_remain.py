#!/usr/bin/env python3
"""Investigate remaining mis-attributions: 上海图书馆 on L11, 石龙路 on L15."""
import sys, math, json
import fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_white_bordered_line, project_to_polyline,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)
white_al = extract_white_bordered_line(page)
if white_al:
    polylines.setdefault("AL", []).extend(white_al)

data = json.load(open('public/v2/stations.json'))

# 上海图书馆 on L11
print("=== 上海图书馆 on L11 ===")
for sid, s in data['stations'].items():
    if s['line'] == '11' and s['name_zh'] == '上海图书馆':
        x, y = s['x'], s['y']
        print(f"  Detected at ({x},{y}) tg={s['transfer_group']}")
        # Check if this is a transfer group shared with L10
        if s['transfer_group']:
            members = [m for m, st in data['stations'].items()
                       if st['transfer_group'] == s['transfer_group']]
            print(f"  Transfer group members: {members}")
            for m in members:
                ms = data['stations'][m]
                print(f"    {m}: L{ms['line']} ({ms['x']},{ms['y']}) {ms['name_zh']}")

# Look for the cluster at (2324, 3063) and see what lines it ACTUALLY touches tightly
print()
print("=== Cluster at (2324, 3063) — all lines within various tolerances ===")
cx, cy = 2324, 3063
for lid, polys in sorted(polylines.items()):
    d = min(project_to_polyline((cx, cy), p)[0] for p in polys)
    if d < 40:
        print(f"  L{lid}: {d:.2f}pt")

# 石龙路: mismatch of label for L15 tick at (2100, 4038)
print()
print("=== 石龙路 on L15: marker at (2100, 4038) ===")
target_x, target_y = 2100, 4038
# Find all Chinese labels within 150pt
print("  Nearby Chinese labels:")
labels_near = []
for s in spans:
    if not any('\u4e00' <= c <= '\u9fff' for c in s.text):
        continue
    d = math.hypot(s.cx - target_x, s.cy - target_y)
    if d < 150:
        labels_near.append((d, s.text, s.cx, s.cy))
for d, t, x, y in sorted(labels_near):
    print(f"    d={d:.0f} '{t}' at ({x:.0f},{y:.0f})")

# Also check: is there a L3 polyline near this marker position?
print(f"  Polyline distances from ({target_x},{target_y}):")
for lid, polys in sorted(polylines.items()):
    d = min(project_to_polyline((target_x, target_y), p)[0] for p in polys)
    if d < 100:
        print(f"    L{lid}: {d:.1f}pt")
