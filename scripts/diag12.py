#!/usr/bin/env python3
"""Find station shapes (rectangles and circles) along the white AL line path."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# The AL line horizontal section is at y≈4349 from x=1401 to x=4612
# East lobe: y=4357 curves to (5115, 4877)
# West vertical: x=1056-1072, y=2828-4050

# First, list ALL small drawings (size < 60pt) near the AL line
def on_al_line(cx, cy):
    """Very rough: within 40pt of the white-line path."""
    # Horizontal section
    if 1401 <= cx <= 4612 and 4300 <= cy <= 4400:
        return True
    # East curve/lobe
    if 4600 <= cx <= 5150 and 4300 <= cy <= 4900:
        return True
    # West vertical
    if 1050 <= cx <= 1080 and 2828 <= cy <= 4100:
        return True
    return False

print("=== All drawings near white-line path ===")
by_type = {}
candidates = []
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not on_al_line(cx, cy):
        continue
    rw, rh = r.width, r.height
    if max(rw, rh) > 60 or (rw < 3 and rh < 3):
        continue
    dtype = d.get("type")
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    items = d.get("items", [])
    c_r = tuple(round(x,2) for x in c) if c else None
    fill_r = tuple(round(x,2) for x in fill) if fill else None
    candidates.append({
        "cx": round(cx), "cy": round(cy), "type": dtype,
        "w": w, "c": c_r, "fill": fill_r, "items": len(items),
        "rw": round(rw,1), "rh": round(rh,1), "rect": r,
    })

# Group by type/color signature
print(f"  {len(candidates)} small drawings found:")
# Dedupe by rounded position + type
seen = set()
for c in sorted(candidates, key=lambda x: (x["cx"], x["cy"])):
    key = (c["cx"]//5*5, c["cy"]//5*5, c["type"], c["c"], c["fill"])
    if key in seen:
        continue
    seen.add(key)
    print(f"  ({c['cx']},{c['cy']}) type={c['type']} w={c['w']} "
          f"size={c['rw']}x{c['rh']} items={c['items']} "
          f"color={c['c']} fill={c['fill']}")

# Specifically along the horizontal y=4349 section
print()
print("=== Drawings exactly on horizontal y=4335-4365 ===")
on_line = []
for d in page.get_drawings():
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    if not (1400 <= cx <= 4612 and 4330 <= cy <= 4370):
        continue
    # Skip the main white-fill line path itself
    if r.width > 100 or r.height > 100:
        continue
    c = d.get("color")
    fill = d.get("fill")
    items = d.get("items", [])
    w = d.get("width", 0)
    c_r = tuple(round(x,2) for x in c) if c else None
    fill_r = tuple(round(x,2) for x in fill) if fill else None
    on_line.append((cx, cy, d.get("type"), w, c_r, fill_r, len(items),
                    round(r.width,1), round(r.height,1)))

on_line.sort()
for cx, cy, dt, w, c_r, fill_r, ni, rw, rh in on_line:
    print(f"  ({cx:.0f},{cy:.0f}) type={dt} w={w} size={rw}x{rh} items={ni} "
          f"color={c_r} fill={fill_r}")
