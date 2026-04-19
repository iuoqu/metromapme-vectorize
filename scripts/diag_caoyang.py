#!/usr/bin/env python3
"""Check why 曹杨路 isn't on L4 and 花桥 is missing from L11."""
import sys, math, json
import fitz
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

clusters = extract_station_marker_clusters(page)

# Find cluster at 曹杨路 area
tx, ty = 2328, 2210
best, best_d = None, float("inf")
for cl in clusters:
    d = math.hypot(cl["cx"]-tx, cl["cy"]-ty)
    if d < best_d:
        best_d = d
        best = cl
print(f"Cluster near 曹杨路: ({best['cx']:.0f},{best['cy']:.0f}) small={best.get('small')}")
print(f"  distance from target: {best_d:.1f}")
print()
print("Distances to each line polyline from cluster center:")
for lid, polys in sorted(polylines.items()):
    d = min(project_to_polyline((best["cx"], best["cy"]), p)[0] for p in polys)
    marker = " ✓ (within 30pt)" if d <= 30 else ""
    if d < 80:
        print(f"  L{lid}: {d:.1f}pt{marker}")

# Find 花桥 text position and look for L11 polyline near there
print()
print("=== 花桥 text position ===")
for s in spans:
    if s.text == "花桥":
        print(f"  '{s.text}' at ({s.cx:.0f},{s.cy:.0f}) size={s.size}")
        for lid, polys in sorted(polylines.items()):
            d = min(project_to_polyline((s.cx, s.cy), p)[0] for p in polys)
            if d < 200:
                print(f"  L{lid} from 花桥 label: {d:.1f}pt")
        print()
        print("  Clusters within 200pt of 花桥 label:")
        for cl in clusters:
            d = math.hypot(cl["cx"] - s.cx, cl["cy"] - s.cy)
            if d < 200:
                # What lines does this cluster cover?
                members = []
                tol = 12 if cl.get("small") else 30
                for lid, polys in polylines.items():
                    pd = min(project_to_polyline((cl["cx"], cl["cy"]), p)[0] for p in polys)
                    if pd <= tol:
                        members.append(f"L{lid}({pd:.0f})")
                print(f"    ({cl['cx']:.0f},{cl['cy']:.0f}) d={d:.0f} small={cl.get('small')} members@{tol}pt={members}")
        break
