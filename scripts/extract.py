#!/usr/bin/env python3
"""
Shanghai Metro PDF → interactive vector schematic pipeline.

Usage:
  python3 scripts/extract.py [--pdf PATH] [--out DIR] [--debug]

Outputs:
  public/shanghai-metro.svg         # full vector render of the PDF
  public/stations.json              # station IDs, coords, line ordering
  public/transfers.json             # auto-clustered transfer groups
  transfers_review.csv              # for user to audit transfer clusters
  debug/ (with --debug flag)        # overlay images for visual inspection
"""

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Exact stroke/fill colors from THIS specific PDF (measured via get_drawings() inspection).
# Use tight tolerance (COLOR_TOL) to avoid cross-line false-positives.
# Note: L5 and L10 are only ~0.028 apart — tolerance must be < 0.014 to separate them.
LINE_COLORS: dict[str, tuple[float, float, float]] = {
    "1":  (0.910, 0.102, 0.220),  # #e81a38  red
    "2":  (0.514, 0.765, 0.251),  # #83c340  green
    "3":  (0.984, 0.816, 0.016),  # #fad004  yellow
    "4":  (0.565, 0.337, 0.639),  # #9055a2  purple
    "5":  (0.722, 0.643, 0.788),  # #b8a3c8  light purple
    "6":  (0.906, 0.039, 0.435),  # #e7096e  magenta
    "7":  (0.957, 0.443, 0.129),  # #f47020  orange
    "8":  (0.000, 0.616, 0.847),  # #009dd7  blue
    "9":  (0.478, 0.780, 0.918),  # #79c6ea  light blue
    "10": (0.737, 0.655, 0.816),  # #bba7d0  lilac
    "11": (0.494, 0.129, 0.188),  # #7d202f  maroon
    "12": (0.000, 0.478, 0.392),  # #007963  teal
    "13": (0.902, 0.580, 0.753),  # #e693c0  pink
    "14": (0.557, 0.820, 0.757),  # #8ed1c1  light teal
    "15": (0.659, 0.663, 0.678),  # #a8a9ac  grey
    "16": (0.176, 0.475, 0.467),  # #2c7977  teal-green
    "17": (0.722, 0.471, 0.459),  # #b87875  rose-brown
    "18": (0.306, 0.176, 0.545),  # #4e2c8a  indigo
}

# Lines that form a closed loop (ordering starts at westernmost, goes clockwise)
LOOP_LINES = {"4"}

# Station marker settings
STATION_MARKER_R = 4   # radius in SVG pts for regular station circles in overlay
TRANSFER_MARKER_R = 6  # radius for transfer stations in overlay

# Render zoom for image-based station detection
DETECT_ZOOM = 5  # 5× → ~360 DPI

# Tolerance for color matching (0-1 range).
# Must be < half the minimum color distance between any two lines.
# L5 vs L10 differ by ~0.028, so tol must be < 0.014.
COLOR_TOL = 0.012

# Transfer cluster tolerance in PDF pts
TRANSFER_TOL_PT = 12.0

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LineGeom:
    line_id: str
    color_hex: str
    # List of polylines (each is a list of (x,y) tuples in PDF pts, y-down)
    polylines: list[list[tuple[float, float]]] = field(default_factory=list)

@dataclass
class Station:
    sid: str          # e.g. "02-01"
    line_id: str
    x: float          # PDF pt, y-down
    y: float
    branch: str = ""  # "" = trunk, "B" = branch B, etc.
    transfer_group: Optional[str] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rgb_close(c1, c2, tol=COLOR_TOL) -> bool:
    if c1 is None or c2 is None:
        return False
    return all(abs(a - b) < tol for a, b in zip(c1, c2))


def color_to_hex(rgb_01: tuple) -> str:
    r, g, b = (max(0, min(255, round(x * 255))) for x in rgb_01)
    return f"#{r:02x}{g:02x}{b:02x}"


def pt_distance(p1, p2) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def project_to_segment(px, py, x1, y1, x2, y2):
    """Returns arc-length parameter t in [0,1] and closest point on segment."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return 0.0, (x1, y1), 0.0
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    dist = math.hypot(px - cx, py - cy)
    return t, (cx, cy), dist


def polyline_length(pts: list) -> float:
    total = 0.0
    for i in range(len(pts) - 1):
        total += pt_distance(pts[i], pts[i + 1])
    return total


def project_to_polyline(px, py, pts: list) -> tuple[float, float]:
    """Returns arc-length along polyline for point (px,py) projected onto it."""
    best_arc = 0.0
    best_dist = float("inf")
    arc = 0.0
    for i in range(len(pts) - 1):
        seg_len = pt_distance(pts[i], pts[i + 1])
        t, cp, d = project_to_segment(px, py, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
        arc_here = arc + t * seg_len
        if d < best_dist:
            best_dist = d
            best_arc = arc_here
        arc += seg_len
    return best_arc, best_dist


def merge_polylines(segments: list[tuple]) -> list[list[tuple[float, float]]]:
    """
    Given a set of (p0, p1) endpoint pairs (rounded), merge into chains.
    Returns list of polylines (each a list of (x,y) tuples).
    """
    from collections import defaultdict

    adj: dict[tuple, list[tuple]] = defaultdict(list)
    for seg in segments:
        p0, p1 = seg
        adj[p0].append(p1)
        adj[p1].append(p0)

    visited_edges: set[frozenset] = set()
    chains = []

    def walk(start, nxt):
        chain = [start, nxt]
        visited_edges.add(frozenset([start, nxt]))
        current = nxt
        prev = start
        while True:
            neighbors = [n for n in adj[current] if n != prev]
            # Continue only if single unambiguous next (degree 2)
            unvisited = [n for n in adj[current]
                         if frozenset([current, n]) not in visited_edges]
            if len(unvisited) == 1:
                nxt_pt = unvisited[0]
                visited_edges.add(frozenset([current, nxt_pt]))
                chain.append(nxt_pt)
                prev = current
                current = nxt_pt
            else:
                break
        return chain

    # Start from degree-1 nodes first (endpoints), then handle loops
    degree1 = [p for p, nb in adj.items() if len(nb) == 1]
    starts = degree1 if degree1 else list(adj.keys())[:1]

    all_nodes = set(adj.keys())
    visited_nodes: set[tuple] = set()

    for start in list(all_nodes):
        for neighbor in list(adj[start]):
            key = frozenset([start, neighbor])
            if key not in visited_edges:
                chain = walk(start, neighbor)
                chains.append(chain)
                for pt in chain:
                    visited_nodes.add(pt)

    return chains


def round_pt(p, decimals=1) -> tuple:
    return (round(p.x, decimals), round(p.y, decimals))


# ---------------------------------------------------------------------------
# Step 1: Extract line polylines from PDF vector drawings
# ---------------------------------------------------------------------------

def extract_line_geoms(page: fitz.Page) -> dict[str, LineGeom]:
    """Return LineGeom per line ID, containing merged polylines.

    Handles both stroke-based lines (type='s') and fill-based lines (type='f'/'fs')
    where the line body is drawn as a filled polygon rather than a stroked path.
    """
    drawings = page.get_drawings()
    line_segments: dict[str, list] = {lid: [] for lid in LINE_COLORS}

    unmapped: dict = {}

    def _process_drawing_items(items, matched):
        """Extract polyline segments from drawing items."""
        for item in items:
            op = item[0]
            if op == "l":
                p0, p1 = round_pt(item[1]), round_pt(item[2])
                if p0 != p1:
                    line_segments[matched].append((p0, p1))
            elif op == "c":
                p0 = round_pt(item[1])
                c1, c2 = item[2], item[3]
                p1 = round_pt(item[4])
                pts = []
                for t_int in range(1, 8):
                    t = t_int / 8
                    it = 1 - t
                    bx = it**3*p0[0] + 3*it**2*t*c1.x + 3*it*t**2*c2.x + t**3*p1[0]
                    by = it**3*p0[1] + 3*it**2*t*c1.y + 3*it*t**2*c2.y + t**3*p1[1]
                    pts.append((round(bx, 1), round(by, 1)))
                prev = p0
                for pt in pts + [p1]:
                    line_segments[matched].append((prev, pt))
                    prev = pt

    for d in drawings:
        dtype = d.get("type")
        color = d.get("color")
        fill = d.get("fill")
        r = d.get("rect")

        if r is None:
            continue

        # Skip white strokes (used for station-marker rings)
        if color and all(x > 0.95 for x in color):
            continue

        # Skip legend area
        if r.y1 > 665:
            continue

        # Try stroke color first (type 's' or 'fs')
        matched = None
        c_to_try = color if dtype in ("s", "fs") else None
        if c_to_try and not all(x > 0.95 for x in c_to_try):
            for lid, lc in LINE_COLORS.items():
                if rgb_close(c_to_try, lc):
                    matched = lid
                    break

        # For fills (type 'f') or unmatched stroke: try fill color
        if matched is None and fill and not all(x > 0.95 for x in fill):
            for lid, lc in LINE_COLORS.items():
                if rgb_close(fill, lc):
                    matched = lid
                    break

        if matched is None:
            # Track truly unmapped stroke colors for reporting
            if dtype == "s" and color and not all(x > 0.95 for x in color):
                key = tuple(round(x, 2) for x in color)
                unmapped[key] = unmapped.get(key, 0) + 1
            continue

        items = d.get("items", [])

        if dtype == "s":
            _process_drawing_items(items, matched)
        elif dtype in ("f", "fs"):
            # For fill-based lines, derive centerline from the fill shape.
            # If it's a long thin rectangle: add a segment along the long axis.
            w, h = r.width, r.height
            if w > 0 and h > 0:
                aspect = w / h
                if aspect > 3:  # wide horizontal band → horizontal segment
                    y_mid = round((r.y0 + r.y1) / 2, 1)
                    p0 = (round(r.x0, 1), y_mid)
                    p1 = (round(r.x1, 1), y_mid)
                    line_segments[matched].append((p0, p1))
                elif aspect < 0.33:  # tall vertical band → vertical segment
                    x_mid = round((r.x0 + r.x1) / 2, 1)
                    p0 = (x_mid, round(r.y0, 1))
                    p1 = (x_mid, round(r.y1, 1))
                    line_segments[matched].append((p0, p1))
                else:
                    # Roughly square or diagonal — use items if they contain lines
                    _process_drawing_items(items, matched)

    if unmapped:
        print(f"\n[WARN] Unmapped stroke colors (add to LINE_COLORS if needed):")
        for c, n in sorted(unmapped.items(), key=lambda x: -x[1]):
            print(f"  {color_to_hex(c)}  rgb={c}  count={n}")

    result = {}
    for lid in LINE_COLORS:
        segs = line_segments.get(lid, [])
        if not segs:
            print(f"  [INFO] Line {lid}: no geometry found — skipped")
            continue
        polylines = merge_polylines(segs)
        polylines = [p for p in polylines if len(p) >= 2]
        hex_color = color_to_hex(LINE_COLORS[lid])
        g = LineGeom(line_id=lid, color_hex=hex_color, polylines=polylines)
        result[lid] = g
        total_pts = sum(len(p) for p in polylines)
        total_len = sum(polyline_length(p) for p in polylines)
        print(f"  Line {lid}: {len(polylines)} chain(s), {total_pts} vertices, length={total_len:.0f} pt")

    return result


# ---------------------------------------------------------------------------
# Step 2: Image-based station detection
# ---------------------------------------------------------------------------

def detect_stations_vector(pdf_path: str, line_geoms: dict[str, LineGeom],
                            debug_dir: Optional[Path] = None
                            ) -> dict[str, list[tuple[float, float]]]:
    """
    Extract station positions from PDF vector drawings.

    Each station is marked in one of three ways:
      A) Tiny 're' (rectangle) items inside composite colored fills — regular stations
      B) Small 4-segment diamond fills (rotated square) — terminal/transfer variants
      C) White-fill + gray-stroke circles/pills — transfer station markers

    Returns dict line_id → list of (x, y) in PDF pts.
    """
    doc = fitz.open(pdf_path)
    page = doc[0]
    drawings = page.get_drawings()

    # ── Type C: white+gray transfer markers (shared across all lines) ──────
    def is_gray(c):
        return c is not None and all(abs(x - 0.25) < 0.06 for x in c)

    transfer_markers: list[tuple[float, float]] = []
    for d in drawings:
        r = d.get("rect")
        if r is None or r.y1 > 665: continue
        if (d.get("fill") and all(x > 0.9 for x in d["fill"])
                and is_gray(d.get("color"))
                and r.width < 15 and r.height < 15):
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            transfer_markers.append((cx, cy))
    transfer_markers = _cluster_pts(transfer_markers, tol=4.0)

    all_candidates: dict[str, list[tuple[float, float]]] = {}

    for lid, lg in line_geoms.items():
        color = LINE_COLORS[lid]
        line_draws = [d for d in drawings
                      if (rgb_close(d.get("fill"), color)
                          or rgb_close(d.get("color"), color))
                      and d.get("rect") and d["rect"].y1 < 665]

        raw_pts: list[tuple[float, float]] = []

        for d in line_draws:
            items = d.get("items", [])
            ops = [it[0] for it in items]
            r = d.get("rect")

            # Type A: 're' items within composite fill
            for it in items:
                if it[0] == "re":
                    rect = it[1]
                    if 0.4 < rect.width < 4.5 and 0.4 < rect.height < 4.5:
                        cx = (rect.x0 + rect.x1) / 2
                        cy = (rect.y0 + rect.y1) / 2
                        raw_pts.append((cx, cy))

            # Type B: pure 4-L diamond (small rotated square)
            if (r and len(ops) == 4 and all(op == "l" for op in ops)
                    and r.width < 5 and r.height < 5):
                cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
                raw_pts.append((cx, cy))

        # Type C: associate transfer markers to this line if near any polyline
        all_polylines = lg.polylines
        for (tx, ty) in transfer_markers:
            min_d = min(
                project_to_polyline(tx, ty, pl)[1]
                for pl in all_polylines
            ) if all_polylines else float("inf")
            if min_d < 8.0:
                raw_pts.append((tx, ty))

        # Cluster duplicates (tick marks duplicated in overlapping composite shapes)
        merged = _cluster_pts(raw_pts, tol=4.0)

        # Project to polyline and keep only points close enough
        valid = []
        for px, py in merged:
            min_d = min(
                project_to_polyline(px, py, pl)[1]
                for pl in all_polylines
            ) if all_polylines else float("inf")
            if min_d < 10.0:
                valid.append((px, py))

        all_candidates[lid] = valid
        print(f"  Line {lid}: {len(valid)} station markers found"
              f" ({len(raw_pts)} raw, {len(merged)} after cluster)")

        if debug_dir and _CV2_AVAILABLE:
            zoom_d = 3
            mat = fitz.Matrix(zoom_d, zoom_d)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n)
            _save_debug_stations(img[:int(665*zoom_d)], lid, valid, zoom_d, debug_dir)

    doc.close()
    return all_candidates


def _cluster_pts(pts: list[tuple], tol: float) -> list[tuple[float, float]]:
    """Merge points within tol distance via simple greedy single-linkage."""
    if not pts:
        return []
    remaining = list(pts)
    merged = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        new_remaining = []
        for p in remaining:
            if pt_distance(seed, p) < tol:
                group.append(p)
            else:
                new_remaining.append(p)
        remaining = new_remaining
        cx = sum(p[0] for p in group) / len(group)
        cy = sum(p[1] for p in group) / len(group)
        merged.append((cx, cy))
    return merged


def _save_debug_stations(img, lid, pts, zoom, debug_dir: Path):
    if not _CV2_AVAILABLE:
        return
    out = cv2.cvtColor(img, cv2.COLOR_RGB2BGR).copy()
    for px, py in pts:
        cv2.circle(out, (int(px * zoom), int(py * zoom)), 6, (0, 0, 255), 2)
        cv2.circle(out, (int(px * zoom), int(py * zoom)), 2, (0, 0, 255), -1)
    scale = 1/2
    small = cv2.resize(out, (int(out.shape[1]*scale), int(out.shape[0]*scale)))
    debug_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(debug_dir / f"stations_line{lid}.png"), small)


# ---------------------------------------------------------------------------
# Step 3: Order stations along each line
# ---------------------------------------------------------------------------

def _full_polyline(lg: LineGeom) -> list[tuple[float, float]]:
    """Concatenate all polylines of a line into the longest chain."""
    if not lg.polylines:
        return []
    # Return the longest single chain
    return max(lg.polylines, key=lambda p: polyline_length(p))


def _westernmost_terminal_idx(polyline: list) -> int:
    """Index of the degree-1 terminal closest to west (smallest x)."""
    # For a simple chain, terminals are first and last vertices
    if not polyline:
        return 0
    x0, y0 = polyline[0]
    xn, yn = polyline[-1]
    return 0 if x0 <= xn else len(polyline) - 1


def _is_clockwise(polyline: list) -> bool:
    """
    Compute signed area of polyline (shoelace) to determine orientation.
    Positive signed area in screen coords (y-down) = clockwise.
    """
    area = 0.0
    n = len(polyline)
    for i in range(n):
        x1, y1 = polyline[i]
        x2, y2 = polyline[(i + 1) % n]
        area += (x2 - x1) * (y2 + y1)
    return area > 0  # in screen coords (y-down), CW has positive shoelace


def order_stations_for_line(lid: str, lg: LineGeom,
                             candidates: list[tuple[float, float]]
                             ) -> tuple[list[tuple], list]:
    """
    Given candidate station positions (x, y) and the line geometry:
    - Project each candidate onto the main polyline
    - Sort by arc-length
    - For loop lines: start at westernmost, go clockwise
    - Returns (ordered_xy_list, is_loop)
    """
    if not candidates:
        return [], lid in LOOP_LINES

    main_pl = _full_polyline(lg)
    if not main_pl:
        return [], False

    is_loop = lid in LOOP_LINES

    # Project all candidates
    arced = []
    for px, py in candidates:
        arc, dist = project_to_polyline(px, py, main_pl)
        arced.append((arc, px, py))

    arced.sort(key=lambda x: x[0])
    ordered = [(px, py) for _, px, py in arced]

    if is_loop:
        # Reorder so that westernmost station is first and traversal is CW
        westmost_idx = min(range(len(ordered)), key=lambda i: ordered[i][0])
        ordered = ordered[westmost_idx:] + ordered[:westmost_idx]
        # Check if loop direction is CW; if not, reverse (skip first elem as anchor)
        if len(ordered) > 2:
            loop_pts = ordered + [ordered[0]]
            if not _is_clockwise(loop_pts):
                ordered = [ordered[0]] + ordered[1:][::-1]
    else:
        # Ensure west → east direction (smallest x first)
        if ordered and ordered[-1][0] < ordered[0][0]:
            ordered = ordered[::-1]

    return ordered, is_loop


# ---------------------------------------------------------------------------
# Step 4: Assign IDs
# ---------------------------------------------------------------------------

def assign_ids(lid: str, ordered_xy: list) -> list[Station]:
    """Create Station objects with IDs like '02-01', '02-02', …"""
    stations = []
    padded = lid.zfill(2)
    for i, (x, y) in enumerate(ordered_xy, start=1):
        sid = f"{padded}-{i:02d}"
        stations.append(Station(sid=sid, line_id=lid, x=x, y=y))
    return stations


# ---------------------------------------------------------------------------
# Step 5: Transfer clustering (union-find)
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def cluster_transfers(all_stations: list[Station],
                      tol: float = TRANSFER_TOL_PT
                      ) -> list[list[Station]]:
    """Return groups of stations (from different lines) that share a physical location."""
    uf = UnionFind()
    sids = [s.sid for s in all_stations]
    # Index by (line, station)
    by_id = {s.sid: s for s in all_stations}

    for i, s1 in enumerate(all_stations):
        for s2 in all_stations[i + 1:]:
            if s1.line_id == s2.line_id:
                continue
            if pt_distance((s1.x, s1.y), (s2.x, s2.y)) < tol:
                uf.union(s1.sid, s2.sid)

    groups: dict[str, list[Station]] = {}
    for s in all_stations:
        root = uf.find(s.sid)
        groups.setdefault(root, []).append(s)

    # Only groups with >= 2 stations from different lines
    transfers = []
    for root, members in groups.items():
        lines_in_group = {m.line_id for m in members}
        if len(lines_in_group) >= 2:
            transfers.append(members)

    return transfers


# ---------------------------------------------------------------------------
# Step 6: Build & emit SVG (full visual + overlay)
# ---------------------------------------------------------------------------

SVG_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 612 792" width="612" height="792">
"""

def build_full_svg(pdf_path: str, line_geoms: dict[str, LineGeom],
                   out_path: Path):
    """
    Export the complete PDF page as SVG (all vectors preserved).
    Add data-line attributes to stroke paths that match a known line color.
    """
    doc = fitz.open(pdf_path)
    page = doc[0]
    svg_text = page.get_svg_image()

    # Inject data-line attribute by color matching in the SVG XML
    # Colors appear as stroke="..." attributes in the paths
    for lid, lc in LINE_COLORS.items():
        hex_color = color_to_hex(lc)
        # Match paths with this stroke color (also uppercase variants)
        svg_text = re.sub(
            rf'(<(?:path|line|polyline)[^>]*\bstroke="{re.escape(hex_color)}")',
            lambda m: m.group(0).replace('stroke=', f'data-line="{lid}" stroke='),
            svg_text, flags=re.IGNORECASE)

    out_path.write_text(svg_text, encoding="utf-8")
    print(f"  Saved full SVG: {out_path} ({out_path.stat().st_size // 1024} KB)")


def build_overlay_svg(all_stations: list[Station],
                      transfer_groups: list[list[Station]],
                      line_geoms: dict[str, LineGeom],
                      out_path: Path):
    """
    Build a transparent overlay SVG with clickable station circles.
    viewBox matches the full SVG (612×792).
    """
    transfer_sids: dict[str, str] = {}  # sid → group_id
    for i, grp in enumerate(transfer_groups):
        gid = f"T{i+1:03d}"
        for s in grp:
            transfer_sids[s.sid] = gid

    lines_svg = []
    # Draw line paths in the overlay too (for highlighting)
    for lid, lg in sorted(line_geoms.items(), key=lambda x: x[0]):
        hex_col = lg.color_hex
        paths_d = []
        for pl in lg.polylines:
            if len(pl) < 2:
                continue
            parts = [f"M {pl[0][0]:.2f} {pl[0][1]:.2f}"]
            for pt in pl[1:]:
                parts.append(f"L {pt[0]:.2f} {pt[1]:.2f}")
            paths_d.append(" ".join(parts))
        if paths_d:
            lines_svg.append(
                f'  <g id="line-path-{lid}" class="metro-line-path" data-line="{lid}"'
                f' stroke="{hex_col}" stroke-width="2.4" fill="none"'
                f' opacity="0" pointer-events="none">')
            for d in paths_d:
                lines_svg.append(f'    <path d="{d}"/>')
            lines_svg.append('  </g>')

    # Draw station circles
    station_circles = ['  <g id="stations">']
    for s in all_stations:
        hex_col = line_geoms[s.line_id].color_hex
        tg = transfer_sids.get(s.sid, "")
        r = TRANSFER_MARKER_R if tg else STATION_MARKER_R
        station_circles.append(
            f'    <circle id="{s.sid}" class="station{" transfer" if tg else ""}"'
            f' data-line="{s.line_id}" data-tgroup="{tg}"'
            f' cx="{s.x:.2f}" cy="{s.y:.2f}" r="{r}"'
            f' fill="white" stroke="{hex_col}" stroke-width="1.5"'
            f' style="cursor:pointer"/>')
    station_circles.append('  </g>')

    content = (
        SVG_HEADER
        + "\n".join(lines_svg)
        + "\n"
        + "\n".join(station_circles)
        + "\n</svg>"
    )

    out_path.write_text(content, encoding="utf-8")
    print(f"  Saved overlay SVG: {out_path}")


# ---------------------------------------------------------------------------
# Step 7: Emit JSON / CSV
# ---------------------------------------------------------------------------

def emit_json(line_geoms: dict[str, LineGeom],
              all_stations: list[Station],
              transfer_groups: list[list[Station]],
              stations_out: Path,
              transfers_out: Path):
    transfer_sids: dict[str, str] = {}
    for i, grp in enumerate(transfer_groups):
        gid = f"T{i+1:03d}"
        for s in grp:
            transfer_sids[s.sid] = gid

    # Build per-line station lists
    lines_json = []
    stations_by_line: dict[str, list[Station]] = {}
    for s in all_stations:
        stations_by_line.setdefault(s.line_id, []).append(s)

    for lid in sorted(line_geoms.keys(), key=lambda x: (len(x), x)):
        lg = line_geoms[lid]
        trunk_ids = [s.sid for s in stations_by_line.get(lid, []) if s.branch == ""]
        lines_json.append({
            "id": lid,
            "color": lg.color_hex,
            "trunk": trunk_ids,
            "branches": {}
        })

    stations_json = {}
    for s in all_stations:
        stations_json[s.sid] = {
            "line": s.line_id,
            "x": round(s.x, 2),
            "y": round(s.y, 2),
            "transfer_group": transfer_sids.get(s.sid, "")
        }

    stations_data = {
        "viewBox": [0, 0, 612, 792],
        "lines": lines_json,
        "stations": stations_json
    }

    stations_out.write_text(json.dumps(stations_data, ensure_ascii=False, indent=2))
    print(f"  Saved stations JSON: {stations_out}")

    transfers_data = []
    for i, grp in enumerate(transfer_groups):
        gid = f"T{i+1:03d}"
        transfers_data.append({
            "group_id": gid,
            "station_ids": [s.sid for s in grp],
            "center_x": round(sum(s.x for s in grp) / len(grp), 2),
            "center_y": round(sum(s.y for s in grp) / len(grp), 2),
        })

    transfers_out.write_text(json.dumps(transfers_data, ensure_ascii=False, indent=2))
    print(f"  Saved transfers JSON: {transfers_out} ({len(transfers_data)} groups)")


def emit_review_csv(transfer_groups: list[list[Station]],
                    line_geoms: dict[str, LineGeom],
                    csv_out: Path):
    with csv_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "station_ids", "lines", "center_x", "center_y",
                    "cluster_diameter_pt", "note"])
        for i, grp in enumerate(transfer_groups):
            gid = f"T{i+1:03d}"
            xs = [s.x for s in grp]
            ys = [s.y for s in grp]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            diam = max(
                pt_distance((s1.x, s1.y), (s2.x, s2.y))
                for s1 in grp for s2 in grp
            ) if len(grp) > 1 else 0
            w.writerow([
                gid,
                "|".join(s.sid for s in grp),
                "|".join(sorted({s.line_id for s in grp})),
                round(cx, 1),
                round(cy, 1),
                round(diam, 1),
                ""
            ])
    print(f"  Saved review CSV: {csv_out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Shanghai Metro PDF → SVG + JSON pipeline")
    parser.add_argument("--pdf", default="Shanghai Metro Network Map.pdf",
                        help="Input PDF path")
    parser.add_argument("--out", default="public/v1",
                        help="Output directory for SVG and JSON files")
    parser.add_argument("--debug", action="store_true",
                        help="Save debug images to debug/")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)
    debug_dir = Path("debug") if args.debug else None
    out_dir.mkdir(exist_ok=True)

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print("=== Step 1: Extract line polylines ===")
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    line_geoms = extract_line_geoms(page)
    doc.close()
    print(f"  → {len(line_geoms)} lines extracted")

    print("\n=== Step 2: Detect station markers ===")
    station_candidates = detect_stations_vector(
        str(pdf_path), line_geoms, debug_dir=debug_dir)

    print("\n=== Step 3: Order stations and assign IDs ===")
    all_stations: list[Station] = []
    for lid in sorted(line_geoms.keys(), key=lambda x: (len(x), x)):
        candidates = station_candidates.get(lid, [])
        ordered_xy, is_loop = order_stations_for_line(lid, line_geoms[lid], candidates)
        stations = assign_ids(lid, ordered_xy)
        all_stations.extend(stations)
        loop_tag = " [loop]" if is_loop else ""
        print(f"  Line {lid}{loop_tag}: {len(stations)} stations "
              f"({lid.zfill(2)}-01 … {lid.zfill(2)}-{len(stations):02d})")

    print("\n=== Step 4: Cluster transfer stations ===")
    transfer_groups = cluster_transfers(all_stations)
    print(f"  → {len(transfer_groups)} transfer groups found")

    print("\n=== Step 5: Emit outputs ===")
    build_full_svg(str(pdf_path), line_geoms, out_dir / "shanghai-metro.svg")
    build_overlay_svg(all_stations, transfer_groups, line_geoms,
                      out_dir / "shanghai-metro-overlay.svg")
    emit_json(line_geoms, all_stations, transfer_groups,
              out_dir / "stations.json",
              out_dir / "transfers.json")
    emit_review_csv(transfer_groups, line_geoms, out_dir / "transfers_review.csv")

    print("\n=== Summary ===")
    print(f"  Total stations: {len(all_stations)}")
    print(f"  Transfer groups: {len(transfer_groups)}")
    print()
    print("  Station IDs by line:")
    for lid in sorted(line_geoms.keys(), key=lambda x: (len(x), x)):
        stns = [s for s in all_stations if s.line_id == lid]
        if stns:
            padded = lid.zfill(2)
            print(f"    Line {lid:>2} ({line_geoms[lid].color_hex}): "
                  f"{padded}-01 … {padded}-{len(stns):02d}  ({len(stns)} stations)")
    print()
    print("  Top transfer groups (station_ids):")
    for grp in sorted(transfer_groups, key=lambda g: -len(g))[:10]:
        print(f"    {' + '.join(s.sid for s in grp)}")


if __name__ == "__main__":
    main()
