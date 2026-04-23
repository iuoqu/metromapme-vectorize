#!/usr/bin/env python3
"""Count all white-fill + dark-border small rectangles (AL-style non-transfer markers)."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# AL-style non-transfer marker: fs, w=3, dark-gray stroke, white fill, ~40x30pt
markers = []
for d in page.get_drawings():
    if d.get("type") != "fs":
        continue
    c = d.get("color")
    fill = d.get("fill")
    if not c or not fill:
        continue
    if not all(x > 0.95 for x in fill):
        continue  # fill must be white
    if not all(x < 0.2 for x in c):
        continue  # stroke must be dark gray/black
    w = d.get("width", 0)
    if abs((w or 0) - 3.0) > 0.5:
        continue
    r = d.get("rect")
    if not r:
        continue
    if max(r.width, r.height) > 50 or min(r.width, r.height) < 10:
        continue
    items = d.get("items", [])
    if len(items) != 6:
        continue
    markers.append({
        "cx": (r.x0+r.x1)/2, "cy": (r.y0+r.y1)/2,
        "rw": r.width, "rh": r.height, "items": len(items),
    })

print(f"Found {len(markers)} candidate AL-style non-transfer markers")

# Now check how many are on the white line path (based on rough bounds)
def on_al_line(cx, cy):
    if 1401 <= cx <= 4612 and 4320 <= cy <= 4380:  # horizontal
        return True
    if 4550 <= cx <= 5150 and 4320 <= cy <= 4900:  # east curve
        return True
    if 1050 <= cx <= 1080 and 2828 <= cy <= 4100:  # west vertical
        return True
    return False

on_al = [m for m in markers if on_al_line(m["cx"], m["cy"])]
off_al = [m for m in markers if not on_al_line(m["cx"], m["cy"])]

print(f"  {len(on_al)} on AL path")
print(f"  {len(off_al)} elsewhere (Jinshan Line + other white-bordered lines?)")

print()
print("=== AL-path markers ===")
for m in sorted(on_al, key=lambda x: (x["cy"], x["cx"])):
    print(f"  ({m['cx']:.0f},{m['cy']:.0f}) size={m['rw']:.0f}x{m['rh']:.0f}")

print()
print("=== Off-AL markers (first 30) ===")
for m in sorted(off_al, key=lambda x: (x["cy"], x["cx"]))[:30]:
    print(f"  ({m['cx']:.0f},{m['cy']:.0f}) size={m['rw']:.0f}x{m['rh']:.0f}")

# Also look for circular transfer markers in a similar style
print()
print("=== Larger white-fill black-border complex-path shapes (transfer markers?) ===")
# A circular transfer marker would be "f" or "fs" with many items (many Bezier curves)
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype not in ("f", "fs"):
        continue
    fill = d.get("fill")
    if not fill or not all(x > 0.95 for x in fill):
        continue
    items = d.get("items", [])
    if len(items) < 20:
        continue  # complex shape
    r = d.get("rect")
    if not r:
        continue
    if max(r.width, r.height) > 120 or min(r.width, r.height) < 15:
        continue
    c = d.get("color")
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    print(f"  ({cx:.0f},{cy:.0f}) type={dtype} size={r.width:.0f}x{r.height:.0f} "
          f"items={len(items)} color={tuple(round(x,2) for x in c) if c else None}")
