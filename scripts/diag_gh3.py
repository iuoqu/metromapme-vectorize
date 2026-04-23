#!/usr/bin/env python3
"""Inspect shapes near the 国家会展中心 cluster position."""
import sys, math, fitz
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

# Around (977, 2825) where the cluster is
tx, ty = 977, 2825
print(f"White-fill shapes within 50pt of ({tx},{ty}):")
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r or r.width < 10 or r.height < 10 or r.width > 250 or r.height > 250:
        continue
    dtype = d.get("type")
    if dtype not in ("fs", "f"):
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    dist = math.hypot(cx - tx, cy - ty)
    if dist > 50:
        continue
    c = d.get("color")
    w = d.get("width", 0)
    items = d.get("items", [])
    area = r.width * r.height
    print(f"  ({cx:.0f},{cy:.0f}) d={dist:.0f} type={dtype} w={w} "
          f"size={r.width:.0f}x{r.height:.0f} area={area:.0f} items={len(items)}")
    # Also L17 distance from this shape's center
    d17 = min(project_to_polyline((cx, cy), p)[0] for p in polylines["17"])
    d2 = min(project_to_polyline((cx, cy), p)[0] for p in polylines["2"])
    print(f"      L2 from this shape: {d2:.1f}pt  L17: {d17:.1f}pt")
