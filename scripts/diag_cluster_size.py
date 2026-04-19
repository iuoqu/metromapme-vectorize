#!/usr/bin/env python3
"""Check cluster sizes to distinguish real transfers from pass-through."""
import sys, math
import fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_station_marker_clusters,
    extract_polylines_per_color, project_to_polyline,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)
spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)

# Re-extract clusters but preserve the sub-shape count and extent
raw = []
for d in page.get_drawings():
    fill = d.get("fill")
    if not fill or not all(x > 0.9 for x in fill):
        continue
    r = d.get("rect")
    if not r or r.width < 10 or r.height < 10 or r.width > 250 or r.height > 250:
        continue
    dtype = d.get("type")
    if dtype not in ("fs", "f"):
        continue
    raw.append({
        "cx": (r.x0+r.x1)/2, "cy": (r.y0+r.y1)/2,
        "w": r.width, "h": r.height, "rect": r,
    })

# Cluster
n = len(raw)
parent = list(range(n))
def _find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i
def _union(i, j):
    ri, rj = _find(i), _find(j)
    if ri != rj:
        parent[ri] = rj
for i in range(n):
    for j in range(i+1, n):
        if math.hypot(raw[i]["cx"]-raw[j]["cx"], raw[i]["cy"]-raw[j]["cy"]) < 35:
            _union(i, j)
groups = {}
for i in range(n):
    groups.setdefault(_find(i), []).append(i)

TARGETS = [
    ("上海体育馆", 2158, 3415),
    ("上海图书馆", 2324, 3063),
    ("徐家汇(L1+L9+L11)", 2329, 3243),
    ("交通大学(L10+L11)", 2330, 2898),
    ("上海南站(L1+L3+L15)", 1915, 3862),
    ("世纪大道(L2+L4+L6+L9)", 3941, 3030),
]

for name, tx, ty in TARGETS:
    # Find matching cluster
    best_group, best_d = None, float("inf")
    for root, members in groups.items():
        cx = sum(raw[m]["cx"] for m in members) / len(members)
        cy = sum(raw[m]["cy"] for m in members) / len(members)
        d = math.hypot(cx-tx, cy-ty)
        if d < best_d:
            best_d = d
            best_group = members
    cx = sum(raw[m]["cx"] for m in best_group) / len(best_group)
    cy = sum(raw[m]["cy"] for m in best_group) / len(best_group)
    # Bounding box of all sub-shapes
    x0 = min(raw[m]["rect"].x0 for m in best_group)
    x1 = max(raw[m]["rect"].x1 for m in best_group)
    y0 = min(raw[m]["rect"].y0 for m in best_group)
    y1 = max(raw[m]["rect"].y1 for m in best_group)

    # Lines within 30pt
    lines_30 = []
    for lid, polys in polylines.items():
        d = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if d <= 30:
            lines_30.append((lid, round(d, 1)))
    lines_30.sort()
    print(f"\n=== {name} ===")
    print(f"  cluster: center=({cx:.0f},{cy:.0f}) bbox=({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f})")
    print(f"  extent: {x1-x0:.0f}x{y1-y0:.0f}, n_shapes={len(best_group)}")
    print(f"  lines within 30pt: {lines_30}")
