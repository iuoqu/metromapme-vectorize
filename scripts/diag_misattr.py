#!/usr/bin/env python3
"""Diagnose why 上海体育馆→L3, 上海图书馆→L11, 石龙路→L15."""
import sys, math, json
import fitz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_v2 import (
    extract_text_spans, find_line_color_map, extract_polylines_per_color,
    extract_station_ticks, extract_station_marker_clusters,
    extract_white_bordered_line, extract_al_rect_markers,
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

data = json.load(open('public/v2/stations.json'))

# Find the misattributed stations in our JSON
for target_name, wrong_line, correct_line in [
    ("上海体育馆", "3", "4"),
    ("上海图书馆", "11", "10"),
    ("石龙路", "15", "3"),
]:
    print(f"\n=== {target_name} (detected on L{wrong_line}, should be L{correct_line}) ===")
    for sid, s in data['stations'].items():
        if s['line'] == wrong_line and s['name_zh'] == target_name:
            x, y = s['x'], s['y']
            print(f"  Detected position: ({x:.0f},{y:.0f}) id={sid} tg={s['transfer_group']}")
            # Check distance to ALL lines
            for lid, polys in sorted(polylines.items()):
                d = min(project_to_polyline((x, y), p)[0] for p in polys)
                if d < 80:
                    print(f"    L{lid}: {d:.1f}pt")
    # Also check the station label position
    for s in spans:
        if s.text == target_name:
            print(f"  Label position: ({s.cx:.0f},{s.cy:.0f}) size={s.size}")
            # Check distance to all lines from the label
            for lid, polys in sorted(polylines.items()):
                d = min(project_to_polyline((s.cx, s.cy), p)[0] for p in polys)
                if d < 150:
                    print(f"    L{lid} from label: {d:.1f}pt")
            break
