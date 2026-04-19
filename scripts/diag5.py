#!/usr/bin/env python3
"""Find 三林南 location and investigate nearby line strokes."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    project_to_polyline,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)

# Find 三林南 text position
print("=== 三林南 text positions ===")
for s in spans:
    if "三林南" in s.text or "三林" in s.text:
        print(f"  '{s.text}' at ({s.cx:.0f},{s.cy:.0f}) size={s.size:.1f}")

# More generally, find all text in the Sanlinnan area
# From context: Line 11 goes through Sanlinnan, which is in southeastern Pudong
print()
print("=== All strokes in bottom-right area (x>3000, y>5000) ===")
from collections import defaultdict
area_strokes = defaultdict(list)
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    if cx > 3500 and cy > 4500:
        dtype = d.get("type")
        c = d.get("color")
        fill = d.get("fill")
        w = d.get("width", 0)
        items = d.get("items", [])
        if (w or 0) >= 8 and dtype == "s":  # thick stroke lines
            c_r = tuple(round(x, 2) for x in c) if c else None
            area_strokes[c_r].append({
                "cx": round(cx), "cy": round(cy), "w": w,
                "n_items": len(items), "rect": (round(r.x0), round(r.y0), round(r.x1), round(r.y1))
            })

for color, entries in sorted(area_strokes.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
    # Find the line this color maps to
    line_id = color_to_line.get(color, "unknown")
    print(f"\n  Color {color} → Line {line_id}: {len(entries)} strokes")
    for e in sorted(entries, key=lambda x: x["cy"])[:5]:
        print(f"    ({e['cx']},{e['cy']}) w={e['w']} items={e['n_items']} rect={e['rect']}")

# Specifically look for gray/black strokes that might be a special line
print()
print("=== All strokes NOT mapped to any known line (x>3000, y>4000) ===")
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    if cx < 3000 or cy < 4000:
        continue
    dtype = d.get("type")
    if dtype != "s":
        continue
    c = d.get("color")
    if not c:
        continue
    w = d.get("width", 0)
    if w < 8:
        continue
    c_r = tuple(round(x, 3) for x in c)
    if c_r not in color_to_line:
        items = d.get("items", [])
        print(f"  Unmapped stroke: color={c_r} w={w} items={len(items)} at ({cx:.0f},{cy:.0f})")
