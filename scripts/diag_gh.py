#!/usr/bin/env python3
"""Check 国家会展中心 cluster."""
import sys, math, fitz
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_marker_clusters, extract_white_bordered_line,
    project_to_polyline,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)
white_al = extract_white_bordered_line(page)
if white_al:
    polylines.setdefault("AL", []).extend(white_al)

# Find 国家会展中心 label
for s in spans:
    if s.text == "国家会展中心":
        print(f"国家会展中心 label at ({s.cx:.0f},{s.cy:.0f})")
        target = (s.cx, s.cy)
        break

clusters = extract_station_marker_clusters(page)
print(f"\n{len(clusters)} total clusters")

# Clusters within 150pt of label
print(f"\nClusters within 150pt of label:")
for cl in clusters:
    d = math.hypot(cl["cx"]-target[0], cl["cy"]-target[1])
    if d < 150:
        members = []
        tol = 12 if cl.get("small") else 30
        for lid, polys in polylines.items():
            pd = min(project_to_polyline((cl["cx"], cl["cy"]), p)[0] for p in polys)
            if pd <= tol:
                members.append(f"L{lid}({pd:.0f})")
        print(f"  ({cl['cx']:.0f},{cl['cy']:.0f}) d={d:.0f} small={cl.get('small')} "
              f"members@{tol}={members}")

# Also look at all raw shapes near target
print(f"\nAll fs/f shapes within 80pt of target:")
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r:
        continue
    cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
    dist = math.hypot(cx - target[0], cy - target[1])
    if dist > 80:
        continue
    c = d.get("color")
    w = d.get("width", 0)
    items = d.get("items", [])
    print(f"  ({cx:.0f},{cy:.0f}) d={dist:.0f} type={d.get('type')} w={w} "
          f"size={r.width:.0f}x{r.height:.0f} items={len(items)}")
