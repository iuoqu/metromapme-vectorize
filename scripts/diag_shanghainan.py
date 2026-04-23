#!/usr/bin/env python3
"""Investigate 上海南站 cluster shape."""
import sys, math, fitz
from pathlib import Path

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# Look for drawings near 上海南站 position (1915, 3862)
tx, ty = 1915, 3862
print(f"Shapes near ({tx},{ty}):")
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    dist = math.hypot(cx - tx, cy - ty)
    if dist > 50:
        continue
    c = d.get("color")
    w = d.get("width", 0)
    items = d.get("items", [])
    print(f"  ({cx:.0f},{cy:.0f}) dist={dist:.0f} type={d.get('type')} w={w} "
          f"size={r.width:.0f}x{r.height:.0f} items={len(items)} "
          f"color={tuple(round(x,2) for x in c) if c else None}")

# Also check L4 transfer at 曹杨路 (approx x=2328, y=2234 from earlier data)
print()
print("Shapes near 曹杨路 (2328, 2234):")
tx, ty = 2328, 2234
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    dist = math.hypot(cx - tx, cy - ty)
    if dist > 50:
        continue
    c = d.get("color")
    w = d.get("width", 0)
    items = d.get("items", [])
    print(f"  ({cx:.0f},{cy:.0f}) dist={dist:.0f} type={d.get('type')} w={w} "
          f"size={r.width:.0f}x{r.height:.0f} items={len(items)} "
          f"color={tuple(round(x,2) for x in c) if c else None}")
