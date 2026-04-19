#!/usr/bin/env python3
"""Find L2+L17 intersection — the 国家会展中心 transfer."""
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

clusters = extract_station_marker_clusters(page)

# Find clusters where BOTH L2 and L17 are within 30pt
print("Clusters with both L2 and L17 within 30pt:")
for cl in clusters:
    cx, cy = cl["cx"], cl["cy"]
    d2 = min(project_to_polyline((cx, cy), p)[0] for p in polylines["2"])
    d17 = min(project_to_polyline((cx, cy), p)[0] for p in polylines["17"])
    if d2 <= 30 and d17 <= 30:
        print(f"  ({cx:.0f},{cy:.0f}) small={cl.get('small')} L2={d2:.1f}pt L17={d17:.1f}pt")

# L2 extent
print("\nL2 polyline extent:")
for poly in polylines.get("2", []):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if len(poly) > 5:
        print(f"  poly {len(poly)} pts: x=[{min(xs):.0f},{max(xs):.0f}] y=[{min(ys):.0f},{max(ys):.0f}]")

# L17 extent
print("\nL17 polyline extent:")
for poly in polylines.get("17", []):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if len(poly) > 5:
        print(f"  poly {len(poly)} pts: x=[{min(xs):.0f},{max(xs):.0f}] y=[{min(ys):.0f},{max(ys):.0f}]")
