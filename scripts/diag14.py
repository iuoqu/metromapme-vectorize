#!/usr/bin/env python3
"""Scan for all AL-line station markers with wider tolerance."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

# Extract the white AL centerline by sampling points along its boundaries.
# The shape has outer/inner boundary forming a 16pt-wide pipe.
# For each x in the horizontal section, both boundaries are at y=4341 and y=4357 → centerline y=4349.
# For vertical section, x=1056/1072 → centerline x=1064.
# East curve: parameterize.

# Approach: collect all points from the white-line's path, walk along it to build a centerline
white_line = None
for d in page.get_drawings():
    fill = d.get("fill")
    c = d.get("color")
    items = d.get("items", [])
    if fill and all(x > 0.95 for x in fill) and c and 0.4 < c[0] < 0.5 and len(items) >= 20:
        white_line = d
        break

if not white_line:
    print("White line not found")
    sys.exit(1)

# Dump all points
pts = []
for it in white_line["items"]:
    op = it[0]
    if op == "l":
        pts.append((it[1].x, it[1].y))
        pts.append((it[2].x, it[2].y))
    elif op == "c":
        # Sample Bezier
        p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
        for t in range(0, 9):
            tt = t / 8
            x = (1-tt)**3*p0.x + 3*(1-tt)**2*tt*p1.x + 3*(1-tt)*tt**2*p2.x + tt**3*p3.x
            y = (1-tt)**3*p0.y + 3*(1-tt)**2*tt*p1.y + 3*(1-tt)*tt**2*p2.y + tt**3*p3.y
            pts.append((x, y))

def dist_to_line(px, py):
    """Distance from point to the white-line boundary path (as segments)."""
    best = float("inf")
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i+1]
        seg_len_sq = (b[0]-a[0])**2 + (b[1]-a[1])**2
        if seg_len_sq == 0:
            best = min(best, math.hypot(px-a[0], py-a[1]))
            continue
        t = ((px-a[0])*(b[0]-a[0]) + (py-a[1])*(b[1]-a[1])) / seg_len_sq
        t = max(0, min(1, t))
        proj_x = a[0] + t*(b[0]-a[0])
        proj_y = a[1] + t*(b[1]-a[1])
        d = math.hypot(px - proj_x, py - proj_y)
        if d < best:
            best = d
    return best

# Find all 39x29 rectangles within 40pt of the line
print("=== AL rectangular markers (non-transfer, within 50pt of white line) ===")
markers_rect = []
for d in page.get_drawings():
    if d.get("type") != "fs":
        continue
    c = d.get("color")
    fill = d.get("fill")
    if not c or not fill:
        continue
    if not all(x > 0.95 for x in fill):
        continue
    if not all(x < 0.2 for x in c):
        continue
    w = d.get("width", 0)
    if abs((w or 0) - 3.0) > 0.5:
        continue
    r = d.get("rect")
    if not r or max(r.width, r.height) > 50 or min(r.width, r.height) < 10:
        continue
    items = d.get("items", [])
    if len(items) != 6:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    d_line = dist_to_line(cx, cy)
    if d_line < 50:
        markers_rect.append((cx, cy, d_line, r.width, r.height))

for cx, cy, dl, rw, rh in sorted(markers_rect, key=lambda x: (x[1], x[0])):
    print(f"  ({cx:.0f},{cy:.0f}) d={dl:.1f} size={rw:.0f}x{rh:.0f}")

# Find circular white-fill shapes near the line
print()
print("=== Circular transfer markers near white line (f type, items>=20) ===")
for d in page.get_drawings():
    dtype = d.get("type")
    if dtype not in ("f", "fs"):
        continue
    fill = d.get("fill")
    if not fill or not all(x > 0.95 for x in fill):
        continue
    items = d.get("items", [])
    if len(items) < 20:
        continue
    r = d.get("rect")
    if not r or max(r.width, r.height) > 120:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    d_line = dist_to_line(cx, cy)
    if d_line < 50:
        print(f"  ({cx:.0f},{cy:.0f}) d={d_line:.1f} size={r.width:.0f}x{r.height:.0f} "
              f"type={dtype} items={len(items)}")

# Match Chinese labels near each marker
from extract_v2 import extract_text_spans
spans = extract_text_spans(page)
print()
print("=== Chinese labels near each rectangular marker ===")
for cx, cy, dl, rw, rh in sorted(markers_rect, key=lambda x: (x[1], x[0])):
    # Find nearest Chinese label within 120pt
    nearest = []
    for s in spans:
        if not any('\u4e00' <= ch <= '\u9fff' for ch in s.text):
            continue
        dd = math.hypot(s.cx - cx, s.cy - cy)
        if dd < 120:
            nearest.append((dd, s.text, s.cx, s.cy))
    nearest.sort()
    if nearest:
        names = ", ".join(f"{t}({dd:.0f}pt)" for dd, t, _, _ in nearest[:3])
        print(f"  ({cx:.0f},{cy:.0f}): {names}")
