#!/usr/bin/env python3
"""Check L7 polyline extent and L11 missing transfer stations."""
import sys, math, fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    project_to_polyline, _dist,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)
ticks = extract_station_ticks(page, color_to_line)
clusters = extract_station_marker_clusters(page)

TOL = 30

print("=== L7 polyline extent ===")
L7_polys = polylines.get("7", [])
all_pts = [p for poly in L7_polys for p in poly]
xs = [p[0] for p in all_pts]
ys = [p[1] for p in all_pts]
print(f"  {len(L7_polys)} polylines, {len(all_pts)} points")
print(f"  x range: {min(xs):.0f} – {max(xs):.0f}")
print(f"  y range: {min(ys):.0f} – {max(ys):.0f}")
print(f"  Easternmost points (x>4000):")
for poly in L7_polys:
    for p in poly:
        if p[0] > 4000:
            print(f"    ({p[0]:.0f},{p[1]:.0f})")

print()
print("=== L7 transfer clusters ===")
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    d_L7 = min(project_to_polyline((cx, cy), p)[0] for p in L7_polys)
    if d_L7 > TOL:
        continue
    members = {}
    for lid, polys in polylines.items():
        bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if bd <= TOL:
            members[lid] = round(bd, 1)
    if len(members) >= 2:
        print(f"  Cluster {ci:3d} ({cx:.0f},{cy:.0f}): d_L7={d_L7:.1f} members={members}")

print()
print("=== L11 missing transfer stations (need 14, at TOL=30pt) ===")
L11_polys = polylines.get("11", [])
print(f"  L11: {len(L11_polys)} polylines")
all_L11_pts = [p for poly in L11_polys for p in poly]
xs11 = [p[0] for p in all_L11_pts]
ys11 = [p[1] for p in all_L11_pts]
print(f"  x range: {min(xs11):.0f} – {max(xs11):.0f}")
print(f"  y range: {min(ys11):.0f} – {max(ys11):.0f}")
print("  L11 transfer clusters at TOL=30:")
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    d_L11 = min(project_to_polyline((cx, cy), p)[0] for p in L11_polys)
    if d_L11 > TOL:
        continue
    members = {}
    for lid, polys in polylines.items():
        bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if bd <= TOL:
            members[lid] = round(bd, 1)
    if len(members) >= 2:
        print(f"  Cluster {ci:3d} ({cx:.0f},{cy:.0f}): d_L11={d_L11:.1f} members={members}")

# Check what L11 looks like at 35pt vs 30pt
print()
print("=== L11 transfer clusters at TOL=35pt but not 30pt ===")
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    d_L11 = min(project_to_polyline((cx, cy), p)[0] for p in L11_polys)
    if d_L11 <= TOL or d_L11 > 35:
        continue
    members_35 = {}
    for lid, polys in polylines.items():
        bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if bd <= 35:
            members_35[lid] = round(bd, 1)
    if "11" in members_35 and len(members_35) >= 2:
        print(f"  Cluster {ci:3d} ({cx:.0f},{cy:.0f}): d_L11={d_L11:.1f} members_35={members_35}")
