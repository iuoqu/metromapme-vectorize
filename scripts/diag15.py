#!/usr/bin/env python3
"""Scan for all small drawings exactly on the AL centerline."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# AL centerline: y≈4349 on horizontal from x=1401-4612; x≈1064 on vertical y=2828-4050; east curve
print("=== All drawings centered on AL horizontal y=4340-4358, x=1400-4620 ===")
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not (1400 <= cx <= 4620 and 4340 <= cy <= 4358):
        continue
    # Skip the big white-fill line itself
    if r.width > 200 or r.height > 100:
        continue
    dt = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x,2) for x in c) if c else None
    fill_r = tuple(round(x,2) for x in fill) if fill else None
    print(f"  ({cx:.0f},{cy:.0f}) type={dt} w={w} size={r.width:.1f}x{r.height:.1f} "
          f"items={len(items)} color={c_r} fill={fill_r}")

print()
print("=== All drawings in AL east curve area (x=4600-5200, y=4300-4900) ===")
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not (4600 <= cx <= 5200 and 4300 <= cy <= 4900):
        continue
    if r.width > 200 or r.height > 200:
        continue
    dt = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x,2) for x in c) if c else None
    fill_r = tuple(round(x,2) for x in fill) if fill else None
    print(f"  ({cx:.0f},{cy:.0f}) type={dt} w={w} size={r.width:.1f}x{r.height:.1f} "
          f"items={len(items)} color={c_r} fill={fill_r}")

print()
print("=== All drawings on AL west vertical (x=1050-1080, y=2820-4060) ===")
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not (1050 <= cx <= 1080 and 2820 <= cy <= 4060):
        continue
    if r.width > 100 or r.height > 100:
        continue
    dt = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x,2) for x in c) if c else None
    fill_r = tuple(round(x,2) for x in fill) if fill else None
    print(f"  ({cx:.0f},{cy:.0f}) type={dt} w={w} size={r.width:.1f}x{r.height:.1f} "
          f"items={len(items)} color={c_r} fill={fill_r}")
