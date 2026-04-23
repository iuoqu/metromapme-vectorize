#!/usr/bin/env python3
"""Diagnostic: find L2/L7 overcounting and L18/AL tick issues."""
import sys, math, fitz
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    project_to_polyline, _closest_point_on_polyline, _dist,
    color_close, COLOR_TOL, LINE_STROKE_WIDTH, TRANSFER_CLUSTER_TOL_PT
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

print("=== Tick counts ===")
OFFICIAL = {
    "1": 16, "2": 18, "3": 17, "4": 11, "5": 11, "6": 19, "7": 21,
    "8": 17, "9": 23, "10": 24, "11": 26, "12": 20, "13": 18, "14": 18,
    "15": 19, "16": 8, "17": 8, "18": 20, "AL": 4, "Pujiang": 4,
}
for lid in sorted(ticks.keys(), key=lambda x: (0, int(x)) if x.isdigit() else (1, x)):
    got = len(ticks[lid])
    want = OFFICIAL.get(lid, "?")
    diff = f"{got-want:+d}" if isinstance(want, int) else ""
    print(f"  L{lid}: {got} ticks (want {want}) {diff}")

print()
print("=== Transfer cluster → line membership (tol=65pt vs 30pt) ===")
for ci, cl in enumerate(clusters[:20]):
    cx, cy = cl["cx"], cl["cy"]
    members_65 = set()
    members_30 = set()
    for lid, polys in polylines.items():
        best_d = min(project_to_polyline((cx, cy), p)[0] for p in polys)
        if best_d <= 65:
            members_65.add(f"{lid}({best_d:.0f})")
        if best_d <= 30:
            members_30.add(f"{lid}({best_d:.0f})")
    n65, n30 = len(members_65), len(members_30)
    if n65 != n30:
        print(f"  Cluster {ci:3d} at ({cx:.0f},{cy:.0f}): 65pt={members_65}, 30pt={members_30}")

print()
print("=== L2 transfer cluster overcounting ===")
L2_polys = polylines.get("2", [])
for ci, cl in enumerate(clusters):
    cx, cy = cl["cx"], cl["cy"]
    best_d2 = min(project_to_polyline((cx, cy), p)[0] for p in L2_polys)
    if best_d2 <= 65:
        # Show all lines within 65pt
        members = {}
        for lid, polys in polylines.items():
            bd = min(project_to_polyline((cx, cy), p)[0] for p in polys)
            if bd <= 65:
                members[lid] = round(bd, 1)
        if len(members) > 2:  # potentially incorrect extra assignment
            print(f"  Cluster {ci} at ({cx:.0f},{cy:.0f}): d_L2={best_d2:.1f}, all_lines={members}")

print()
print("=== L18 tick diagnostic: check nearby strokes ===")
L18_polys = polylines.get("18", [])
if L18_polys:
    # Get the L18 color
    L18_color = None
    for rgb, lid in color_to_line.items():
        if lid == "18":
            L18_color = rgb
            break
    print(f"  L18 color: {L18_color}")

    # Scan ALL drawings near L18 polyline
    from extract_v2 import _closest_point_on_polyline
    print("  Strokes within 20pt of L18 line (not width=16):")
    near_strokes = []
    for d in page.get_drawings():
        if d.get("type") != "s":
            continue
        r = d.get("rect")
        if not r:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        best_d = min(project_to_polyline((cx, cy), p)[0] for p in L18_polys)
        if best_d <= 25:
            w = d.get("width", 0)
            c = d.get("color")
            items = d.get("items", [])
            if abs(w - 16.0) > 0.5:  # NOT the main line stroke
                near_strokes.append((best_d, w, c, len(items), r.width, r.height))
    near_strokes.sort()
    for bd, w, c, ni, rw, rh in near_strokes[:30]:
        print(f"    d={bd:.1f} w={w} color={c} items={ni} rect=({rw:.1f}x{rh:.1f})")

print()
print("=== AL diagnostic ===")
AL_polys = polylines.get("AL", [])
if AL_polys:
    AL_color = None
    for rgb, lid in color_to_line.items():
        if lid == "AL":
            AL_color = rgb
            break
    print(f"  AL color: {AL_color}")
    print("  AL polyline points (first poly):", AL_polys[0][:5] if AL_polys else "none")
    print("  Strokes within 30pt of AL line:")
    near = []
    for d in page.get_drawings():
        if d.get("type") != "s":
            continue
        r = d.get("rect")
        if not r:
            continue
        cx2, cy2 = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        best_d = min(project_to_polyline((cx2, cy2), p)[0] for p in AL_polys)
        if best_d <= 30:
            w = d.get("width", 0)
            c = d.get("color")
            items = d.get("items", [])
            near.append((best_d, w, c, len(items), r.width, r.height))
    near.sort()
    for bd, w, c, ni, rw, rh in near[:20]:
        print(f"    d={bd:.1f} w={w} color={c} items={ni} rect=({rw:.1f}x{rh:.1f})")
