#!/usr/bin/env python3
"""Check if transfer clusters have colored indicators (dots) for each line served."""
import sys, math
import fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_station_marker_clusters,
    extract_polylines_per_color, project_to_polyline,
    color_close, COLOR_TOL,
)

PDF = Path(__file__).parent.parent / "metro.pdf"
doc = fitz.open(str(PDF))
page = doc.load_page(0)

spans = extract_text_spans(page)
lcm = find_line_color_map(page, spans)
color_to_line = {rgb: lid for lid, (_, rgb) in lcm.items()}
polylines = extract_polylines_per_color(page, color_to_line)
clusters = extract_station_marker_clusters(page)

# For each problematic cluster, look at what's inside its bbox
TARGETS = [
    ("上海体育馆", 2131, 3415, ["1", "4"]),  # expected lines
    ("上海图书馆", 2329, 3063, ["10"]),
    ("上海南站", 1915, 3862, ["1", "3", "15"]),
]

for name, tx, ty, expected in TARGETS:
    print(f"\n=== {name} at ({tx},{ty}), expected lines: {expected} ===")

    # Find the matching cluster
    best_cl, best_d = None, float("inf")
    for cl in clusters:
        d = math.hypot(cl["cx"]-tx, cl["cy"]-ty)
        if d < best_d:
            best_d = d
            best_cl = cl
    if not best_cl:
        print("  no cluster found")
        continue
    print(f"  cluster at ({best_cl['cx']:.0f},{best_cl['cy']:.0f}) d={best_d:.0f}")

    # Check which lines' polylines pass within 30pt
    print("  Lines with polyline within 30pt:")
    for lid, polys in sorted(polylines.items()):
        d = min(project_to_polyline((best_cl["cx"], best_cl["cy"]), p)[0] for p in polys)
        if d <= 30:
            marker = " ✓" if lid in expected else " ? (unexpected)"
            print(f"    L{lid}: {d:.1f}pt{marker}")

    # Look at ALL drawings within a wider bbox around the cluster
    BBOX_R = 35  # within 35pt of cluster center
    print(f"  Small drawings within {BBOX_R}pt of cluster center:")
    for d in page.get_drawings():
        r = d.get("rect")
        if not r:
            continue
        cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
        dist = math.hypot(cx-best_cl["cx"], cy-best_cl["cy"])
        if dist > BBOX_R:
            continue
        # Exclude the cluster's own white shapes
        if (d.get("fill") and all(x > 0.9 for x in d["fill"])
                and r.width > 10):
            continue
        dtype = d.get("type")
        c = d.get("color")
        fill = d.get("fill")
        w = d.get("width", 0)
        items = d.get("items", [])
        c_r = tuple(round(x, 2) for x in c) if c else None
        fill_r = tuple(round(x, 2) for x in fill) if fill else None

        # Try to match color to a line
        line_hit = None
        for src, label in [(c, "stroke"), (fill, "fill")]:
            if not src:
                continue
            src_r = tuple(round(x, 3) for x in src)
            for cl_rgb, lid in color_to_line.items():
                if sum(abs(src_r[i]-cl_rgb[i]) for i in range(3)) < 0.05:
                    line_hit = f"L{lid}({label})"
                    break
            if line_hit:
                break

        note = f" → {line_hit}" if line_hit else ""
        print(f"    ({cx:.0f},{cy:.0f}) d={dist:.0f} type={dtype} w={w} "
              f"size={r.width:.0f}x{r.height:.0f} items={len(items)} "
              f"color={c_r} fill={fill_r}{note}")
