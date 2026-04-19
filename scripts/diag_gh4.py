#!/usr/bin/env python3
"""All white-fill shapes in the Hongqiao area."""
import sys, math, fitz
from pathlib import Path
PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# Get all white-fill shapes in the Hongqiao cluster area
print("All white-fill fs/f shapes in x=700-1200, y=2700-2900:")
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r or r.width < 10 or r.height < 10:
        continue
    dtype = d.get("type")
    if dtype not in ("fs", "f"):
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not (700 <= cx <= 1200 and 2700 <= cy <= 2900):
        continue
    c = d.get("color")
    w = d.get("width", 0)
    items = d.get("items", [])
    print(f"  ({cx:.0f},{cy:.0f}) type={dtype} w={w} size={r.width:.0f}x{r.height:.0f} "
          f"items={len(items)} color={tuple(round(x,2) for x in c) if c else None}")
