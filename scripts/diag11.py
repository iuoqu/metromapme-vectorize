#!/usr/bin/env python3
"""Deep-dive on the white-fill gray-stroke line."""
import sys, math, fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import extract_text_spans

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)

# Find the huge white-fill drawing
print("=== The white-fill + gray-stroke drawing ===")
for d in page.get_drawings():
    fill = d.get("fill")
    c = d.get("color")
    items = d.get("items", [])
    if fill and all(x > 0.95 for x in fill) and c and 0.4 < c[0] < 0.5 and len(items) >= 20:
        r = d.get("rect")
        print(f"  type={d.get('type')} w={d.get('width')} items={len(items)}")
        print(f"  rect=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f})")
        print(f"  color={c}, fill={fill}")
        print(f"  Path items:")
        for it in items[:50]:
            op = it[0]
            if op == "l":
                p0, p1 = it[1], it[2]
                print(f"    l: ({p0.x:.0f},{p0.y:.0f}) → ({p1.x:.0f},{p1.y:.0f})")
            elif op == "c":
                p0, p3 = it[1], it[4]
                print(f"    c: ({p0.x:.0f},{p0.y:.0f}) → ({p3.x:.0f},{p3.y:.0f})")
            elif op == "re":
                rr = it[1]
                print(f"    re: rect=({rr.x0:.0f},{rr.y0:.0f},{rr.x1:.0f},{rr.y1:.0f})")
            else:
                print(f"    {op}: {it[1:]}")
        break

# Look for any OTHER light-gray or white shapes that could be line-like
print()
print("=== Other thin gray/white line-shaped drawings ===")
for d in page.get_drawings():
    items = d.get("items", [])
    if len(items) < 5:
        continue
    c = d.get("color")
    fill = d.get("fill")
    w = d.get("width", 0)
    r = d.get("rect")
    if not r:
        continue
    is_gray_stroke = c and abs(c[0]-c[1])<0.05 and abs(c[1]-c[2])<0.05 and 0.3 < c[0] < 0.9
    is_white_fill = fill and all(x > 0.95 for x in fill)
    if not (is_gray_stroke or is_white_fill):
        continue
    if r.width < 50 and r.height < 50:
        continue
    print(f"  type={d.get('type')} w={w} items={len(items)} "
          f"color={tuple(round(x,2) for x in c) if c else None} "
          f"fill={tuple(round(x,2) for x in fill) if fill else None} "
          f"rect=({r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f})")

# Find any Chinese text labels along the white line path (x=1056-5127, y=2828-4877)
print()
print("=== Chinese labels in the white line area (x=2000-5200, y=4000-4800) ===")
for s in spans:
    if not any('\u4e00' <= ch <= '\u9fff' for ch in s.text):
        continue
    if 2000 <= s.cx <= 5200 and 4000 <= s.cy <= 4800:
        print(f"  '{s.text}' at ({s.cx:.0f},{s.cy:.0f}) size={s.size:.0f}")
