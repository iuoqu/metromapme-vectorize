#!/usr/bin/env python3
"""Analyze the black+white double-stroke line."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import extract_text_spans

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)

# The black stroke polyline items
print("=== Black stroke path items ===")
for d in page.get_drawings():
    if d.get("type") != "s":
        continue
    c = d.get("color")
    if not c:
        continue
    c_r = tuple(round(x, 3) for x in c)
    if c_r != (0.0, 0.0, 0.0):
        continue
    w = d.get("width", 0)
    if (w or 0) != 18.0:
        continue
    items = d.get("items", [])
    if len(items) < 3:
        continue
    print(f"  Black polyline w={w}, {len(items)} items:")
    for it in items:
        op = it[0]
        if op == "l":
            p0, p1 = it[1], it[2]
            print(f"    l: ({p0.x:.0f},{p0.y:.0f}) → ({p1.x:.0f},{p1.y:.0f})")
        elif op == "c":
            p0, p3 = it[1], it[4]
            print(f"    c: ({p0.x:.0f},{p0.y:.0f}) → ({p3.x:.0f},{p3.y:.0f})")

print()
print("=== All Chinese text near the line (x=600-2200, y=3700-6200) ===")
nearby_text = []
for s in spans:
    if not any('\u4e00' <= c <= '\u9fff' for c in s.text):
        continue
    if 600 <= s.cx <= 2200 and 3700 <= s.cy <= 6200:
        nearby_text.append((s.cy, s.cx, s.text, s.size))
nearby_text.sort()
for cy, cx, text, size in nearby_text:
    print(f"  ({cx:.0f},{cy:.0f}) size={size:.0f}: {text}")

print()
print("=== Black tick marks (single segment, w=16 or 18, color=black) ===")
for d in page.get_drawings():
    if d.get("type") != "s":
        continue
    c = d.get("color")
    if not c:
        continue
    c_r = tuple(round(x, 2) for x in c)
    if c_r != (0.0, 0.0, 0.0):
        continue
    w = d.get("width", 0)
    if (w or 0) < 8:
        continue
    items = d.get("items", [])
    if len(items) != 1 or items[0][0] != "l":
        continue
    it = items[0]
    p0, p1 = it[1], it[2]
    seg_len = math.hypot(p0.x - p1.x, p0.y - p1.y)
    print(f"  tick: ({(p0.x+p1.x)/2:.0f},{(p0.y+p1.y)/2:.0f}) len={seg_len:.1f} w={w}")
