#!/usr/bin/env python3
"""Find the white line passing through 三林南, 康桥东, 上海国际旅游度假区."""
import sys, math, fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import extract_text_spans

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)

# Find all 3 station labels
targets = ["三林南", "康桥东", "上海国际旅游度假区", "国际旅游度假区", "康桥"]
print("=== Target station positions ===")
positions = {}
for s in spans:
    for t in targets:
        if t in s.text:
            print(f"  '{s.text}' at ({s.cx:.0f},{s.cy:.0f}) size={s.size:.0f}")
            if t not in positions:
                positions[t] = (s.cx, s.cy)

# Search for ALL WHITE (1,1,1) or off-white strokes with multiple items
print()
print("=== All white-fill/white-stroke line-shaped drawings ===")
white_drawings = []
for d in page.get_drawings():
    c = d.get("color")
    fill = d.get("fill")
    items = d.get("items", [])
    w = d.get("width", 0)
    r = d.get("rect")
    if not r:
        continue
    # Candidates: strokes with white color OR fills with white
    is_white_stroke = c and all(x > 0.95 for x in c)
    is_white_fill = fill and all(x > 0.95 for x in fill)
    if not (is_white_stroke or is_white_fill):
        continue
    if len(items) < 3:
        continue
    if r.width < 100 and r.height < 100:
        continue
    white_drawings.append({
        "cx": (r.x0+r.x1)/2, "cy": (r.y0+r.y1)/2,
        "type": d.get("type"), "c": c, "fill": fill, "w": w,
        "n_items": len(items), "rect": (r.x0, r.y0, r.x1, r.y1)
    })
for wd in sorted(white_drawings, key=lambda d: d["cy"]):
    print(f"  type={wd['type']} w={wd['w']} items={wd['n_items']} "
          f"color={tuple(round(x,2) for x in wd['c']) if wd['c'] else None} "
          f"fill={tuple(round(x,2) for x in wd['fill']) if wd['fill'] else None} "
          f"rect=({wd['rect'][0]:.0f},{wd['rect'][1]:.0f},{wd['rect'][2]:.0f},{wd['rect'][3]:.0f})")

# Now, for any "candidate" white line, check if it passes near the targets
print()
print("=== Check all strokes (any color) passing through all target positions ===")
# We'll look at thick strokes with items>=3 and check which ones pass within 100pt of all 3 targets
candidates = []
for d in page.get_drawings():
    if d.get("type") != "s":
        continue
    items = d.get("items", [])
    if len(items) < 3:
        continue
    w = d.get("width", 0)
    if (w or 0) < 4:
        continue
    # Extract all points from the path
    pts = []
    for it in items:
        op = it[0]
        if op == "l":
            pts.append((it[1].x, it[1].y))
            pts.append((it[2].x, it[2].y))
        elif op == "c":
            pts.append((it[1].x, it[1].y))
            pts.append((it[4].x, it[4].y))
    if not pts:
        continue
    # Check if the path passes near each target
    hits = {}
    for t, (tx, ty) in positions.items():
        min_d = min(math.hypot(p[0]-tx, p[1]-ty) for p in pts)
        if min_d < 250:
            hits[t] = round(min_d, 1)
    if len(hits) >= 2:
        c = d.get("color")
        r = d.get("rect")
        candidates.append({
            "c": tuple(round(x,2) for x in c) if c else None,
            "w": w, "items": len(items), "rect": r, "hits": hits,
        })

print(f"  {len(candidates)} multi-target candidate paths:")
for c in candidates:
    print(f"    color={c['c']} w={c['w']} items={c['items']} hits={c['hits']}")
