#!/usr/bin/env python3
"""
Shanghai Metro v2 PDF → SVG + JSON pipeline.

Differences from v1 extractor:
  * v2 PDF has real extractable text (Chinese + English station names).
  * Lines are stored as a few long polyline strokes (~17-29 per line) instead
    of thousands of tiny segments — much simpler to reconstruct.
  * Line→color mapping is auto-detected from "Line N" / "Pujiang Line" text
    labels (size=30 spans) sitting next to colored strokes.
  * Stations are extracted from text label positions (English + Chinese pairs)
    projected onto the nearest line stroke.

Outputs (under public/v2/):
  - shanghai-metro.svg          full vector render of the PDF
  - shanghai-metro-overlay.svg  transparent overlay with station circles
  - stations.json               line/station data with name_en + name_zh
  - transfers.json              auto-clustered transfer groups
  - transfers_review.csv        for human review
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

# ── Paths ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "metro.pdf"
OUT_DIR = ROOT / "public" / "v2"
DEBUG_DIR = ROOT / "debug"

# ── Tunables ─────────────────────────────────────────────────────────
LINE_STROKE_WIDTH = 16.0          # base line stroke width in v2 PDF
COLOR_TOL = 0.025                 # color matching tolerance
TEXT_PAIR_DX = 80.0               # max x-diff to pair English+Chinese text
TEXT_PAIR_DY = 80.0               # max y-diff (Chinese typically below English)
STATION_TO_LINE_MAX_DIST = 130.0  # how far a label center can be from a line
SECONDARY_ASSIGN_TOL_PT = 50.0    # snap-point proximity for secondary line assignment
TRANSFER_CLUSTER_TOL_PT = 30.0    # spatial tolerance for transfer group clustering
SECONDARY_LINE_MAX_DIST = 35.0    # only assign to extra lines if very close
# Lines that allow a larger label-to-polyline distance (labels placed far from stroke)
LINE_STATION_MAX_DIST_OVERRIDES: dict[str, float] = {
    "AL": 175.0,
}
LOOP_LINES = {"4"}

# Stations not drawn in the PDF (new/planned/extension) that we inject manually.
# Each entry: {line, name_zh, name_en, x, y, extend_line}. If extend_line is True,
# the overlay SVG draws a short colored line segment from the nearest existing
# station on that line to this one (for stations BEYOND the drawn polyline).
MANUAL_STATIONS: list[dict] = [
    # L11 康恒路 — 浦三路 (3678,4287) 与 御桥 (4066,4301) 的中点
    {"line": "11", "name_zh": "康恒路", "name_en": "Kangheng Rd.",
     "x": 3872, "y": 4294, "extend_line": False},
    # L17 西岑 — 东方绿舟 (445,3878) 向西南外推 (朱家角→东方绿舟 方向延续)
    {"line": "17", "name_zh": "西岑", "name_en": "Xicen",
     "x": 360, "y": 3972, "extend_line": True},
]

# Filter out non-station text patterns
NON_STATION_TEXT_PATTERNS = [
    re.compile(r"^Transfer", re.I),
    re.compile(r"^转乘", re.I),
    re.compile(r"^换乘", re.I),
    re.compile(r"^Pujiang Line", re.I),
    re.compile(r"^Airport Link Line", re.I),
    re.compile(r"^机场联络线"),
    re.compile(r"^市域机场线"),
    re.compile(r"^Jinshan Line", re.I),
    re.compile(r"^Suzhou", re.I),
    re.compile(r"^Maglev", re.I),
    re.compile(r"^磁浮", re.I),
    re.compile(r"^浦江线"),
    re.compile(r"^金山线"),
    re.compile(r"^to\s", re.I),
    re.compile(r"^SHANGHAI METRO", re.I),
    # Fragment filters: partial station names split across text rows
    re.compile(r"^Station$", re.I),           # lone fragment from "… Railway Station"
    re.compile(r"^and\s+[A-Z]", re.I),        # "and Convention Center"
    re.compile(r"·\s*$"),                      # trailing Chinese-separator artifact
    re.compile(r"[a-zA-Z]\s*[\u4e00-\u9fff]+\s*$"),  # EN text bleeding into ZH chars
]


def is_chinese(s: str) -> bool:
    return any("CJK UNIFIED" in unicodedata.name(c, "") for c in s)


def is_station_text(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    for pat in NON_STATION_TEXT_PATTERNS:
        if pat.search(text):
            return False
    # Filter pure line-label English ("Line 7", "Line 11")
    if re.match(r"^Line\s+\d+$", text):
        return False
    return True


# ── Data classes ─────────────────────────────────────────────────────
@dataclass
class TextSpan:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class StationLabel:
    name_en: str
    name_zh: str
    x: float          # center x of the label cluster
    y: float          # center y
    spans: list[TextSpan] = field(default_factory=list)


@dataclass
class LineData:
    line_id: str           # "1", "2", ..., "Pujiang"
    label: str             # "Line 1", "Pujiang Line"
    color_rgb: tuple[float, float, float]
    color_hex: str
    polylines: list[list[tuple[float, float]]] = field(default_factory=list)


# ── Color helpers ────────────────────────────────────────────────────
def color_close(a: tuple, b: tuple, tol: float = COLOR_TOL) -> bool:
    return all(abs(a[i] - b[i]) < tol for i in range(3))


def rgb_to_hex(rgb: tuple) -> str:
    r, g, b = (int(round(c * 255)) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Phase 1: extract text spans ──────────────────────────────────────
def extract_text_spans(page: fitz.Page) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                t = sp["text"].strip()
                if not t:
                    continue
                spans.append(TextSpan(
                    text=t,
                    x0=sp["bbox"][0], y0=sp["bbox"][1],
                    x1=sp["bbox"][2], y1=sp["bbox"][3],
                    size=sp["size"],
                ))
    return spans


# ── Phase 2: line-label spans (size~30) → color mapping ──────────────
def find_line_color_map(
    page: fitz.Page, spans: list[TextSpan]
) -> dict[str, tuple[str, tuple[float, float, float]]]:
    """
    Returns: line_id -> (label, color_rgb)

    Strategy: For each "Line N" text label, find the small colored `re`
    rectangle (~104×43 pt) that contains or sits behind the text — that
    is the line's badge with its canonical color.

    For lines without a badge (Pujiang, Airport Link Line), find the stroke
    nearest to the line's text label.
    """
    line_label_spans: list[TextSpan] = []
    for s in spans:
        t = s.text.strip()
        if abs(s.size - 30) < 0.5:
            if (re.match(r"^Line\s+\d+$", t)
                    or t == "Pujiang Line"
                    or t == "Suzhou Line 11"):
                line_label_spans.append(s)

    drawings = page.get_drawings()
    # Candidate badges: small filled re rectangles, not white/black/gray
    badges = []
    for d in drawings:
        if d.get("type") not in ("f", "fs"):
            continue
        if not d.get("fill"):
            continue
        items = d.get("items", [])
        if not any(it[0] == "re" for it in items):
            continue
        r = d["rect"]
        if r.width > 200 or r.height > 80:
            continue
        fill = tuple(round(x, 3) for x in d["fill"])
        if color_close(fill, (1, 1, 1)):
            continue
        # skip pure grays (badge legend swatches handled below)
        if max(fill) - min(fill) < 0.02 and 0.3 < min(fill) < 0.95:
            continue
        badges.append((fill, r))

    result: dict[str, tuple[str, tuple[float, float, float]]] = {}
    for span in line_label_spans:
        label = span.text.strip()
        if label == "Suzhou Line 11":
            continue
        m = re.match(r"^Line\s+(\d+)$", label)
        if m:
            line_id = m.group(1)
        elif label == "Pujiang Line":
            line_id = "Pujiang"
        else:
            continue

        if line_id in result:
            continue

        # Find the badge that the text label sits inside (or nearest)
        best, best_d = None, float("inf")
        for fill, r in badges:
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            # require text center to be reasonably inside badge bbox
            if not (r.x0 - 30 <= span.cx <= r.x1 + 30):
                continue
            if not (r.y0 - 20 <= span.cy <= r.y1 + 20):
                continue
            d2 = abs(cx - span.cx) + abs(cy - span.cy)
            if d2 < best_d:
                best_d = d2
                best = fill
        if best is not None:
            result[line_id] = (label, best)
            continue

        # No badge found: fall back to nearest non-white/black width-16 stroke
        # Only use if the nearest stroke is within 500pt (guards against
        # legend labels that are far from the actual line on the schematic).
        best_c, best_d2 = None, float("inf")
        for d in drawings:
            if d.get("type") != "s":
                continue
            if abs(d.get("width", 0) - LINE_STROKE_WIDTH) > 0.5:
                continue
            c = d.get("color")
            if not c:
                continue
            c_r = tuple(round(x, 3) for x in c)
            if color_close(c_r, (0, 0, 0)) or color_close(c_r, (1, 1, 1)):
                continue
            dr = d.get("rect")
            if not dr:
                continue
            dist = math.hypot((dr.x0 + dr.x1) / 2 - span.cx,
                              (dr.y0 + dr.y1) / 2 - span.cy)
            if dist < best_d2:
                best_d2 = dist
                best_c = c_r
        if best_c is not None and best_d2 < 500:
            result[line_id] = (label, best_c)

    # Airport Link Line: teal color, no badge, label far from actual stroke.
    # Detect directly from the unique teal (low-R, G≈B≈0.44) width-16 stroke.
    if "AL" not in result:
        for d in drawings:
            if d.get("type") != "s":
                continue
            if abs(d.get("width", 0) - LINE_STROKE_WIDTH) > 0.5:
                continue
            c = d.get("color")
            if not c:
                continue
            c_r = tuple(round(x, 3) for x in c)
            # Teal: very low red, G and B both moderate and close to each other
            if (c_r[0] < 0.15 and c_r[1] > 0.35 and c_r[2] > 0.35
                    and abs(c_r[1] - c_r[2]) < 0.05):
                result["AL"] = ("Airport Link Line", c_r)
                break

    # The badge color often differs slightly (or substantially for lines 6/15/16)
    # from the actual stroke color. Replace each badge color with the closest
    # stroke color we actually find on the page.
    stroke_colors: set[tuple[float, float, float]] = set()
    for d in drawings:
        if d.get("type") != "s":
            continue
        w = d.get("width", 0)
        if abs(w - LINE_STROKE_WIDTH) >= 0.5 and abs(w - 8.0) >= 0.5:
            continue
        c = d.get("color")
        if not c:
            continue
        c_rounded = tuple(round(x, 3) for x in c)
        if color_close(c_rounded, (1, 1, 1)) or color_close(c_rounded, (0, 0, 0)):
            continue
        stroke_colors.add(c_rounded)

    used_strokes: set[tuple[float, float, float]] = set()
    # Process in order of best-match strength so unique perfect matches lock first
    items_list = list(result.items())
    items_list.sort(key=lambda kv: min(
        sum(abs(kv[1][1][i] - sc[i]) for i in range(3)) for sc in stroke_colors
    ))
    refined: dict[str, tuple[str, tuple[float, float, float]]] = {}
    for line_id, (label, badge) in items_list:
        candidates = sorted(
            (sc for sc in stroke_colors if sc not in used_strokes),
            key=lambda sc: sum(abs(sc[i] - badge[i]) for i in range(3))
        )
        if not candidates:
            refined[line_id] = (label, badge)
            continue
        best = candidates[0]
        # Only accept if the diff is < 0.5 total (lets even Line 16 match)
        if sum(abs(best[i] - badge[i]) for i in range(3)) < 0.5:
            refined[line_id] = (label, best)
            used_strokes.add(best)
        else:
            refined[line_id] = (label, badge)
    return refined


# ── Phase 3: pair English + Chinese spans into station labels ────────
def build_station_labels_from_blocks(page: fitz.Page) -> list[StationLabel]:
    """
    Use PyMuPDF text *lines* (one text-row each) and pair English↔Chinese
    rows that share an x-range with a typical y-gap (~30 pt).

    A single "block" can contain MANY stations (5+ side-by-side), so we
    cannot merge whole blocks; we must work at line granularity.
    """
    blocks = page.get_text("dict")["blocks"]

    @dataclass
    class TextRow:
        text: str
        x0: float
        y0: float
        x1: float
        y1: float
        size: float

        @property
        def cx(self) -> float:
            return (self.x0 + self.x1) / 2

        @property
        def cy(self) -> float:
            return (self.y0 + self.y1) / 2

    # Collect rows WITHOUT individual fragment filtering first, so that
    # multi-line station names (e.g. "National Exhibition" + "and Convention
    # Center") can be clustered before filtering.  Only hard exclusions
    # (size, line-name labels, truly non-station tokens) are applied here.
    HARD_EXCLUDE = [
        re.compile(r"^Line\s+\d+$"),
        re.compile(r"^Suzhou Line", re.I),
        re.compile(r"^(Transfer|转乘|换乘)", re.I),
        re.compile(r"^(Pujiang Line|浦江线|金山线|Jinshan Line)", re.I),
        re.compile(r"^(Maglev|磁浮)", re.I),
        re.compile(r"^(Airport Link Line|机场联络线|市域机场线)", re.I),
        re.compile(r"^to\s", re.I),
        re.compile(r"^SHANGHAI METRO", re.I),
    ]

    def _hard_exclude(text: str) -> bool:
        return any(p.search(text) for p in HARD_EXCLUDE)

    rows: list[TextRow] = []
    for b in blocks:
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = " ".join(sp["text"].strip() for sp in spans).strip()
            if not text:
                continue
            sz = max(sp["size"] for sp in spans)
            if sz > 28:  # line-name labels & title
                continue
            if _hard_exclude(text):
                continue
            bb = line["bbox"]
            rows.append(TextRow(
                text=text,
                x0=bb[0], y0=bb[1], x1=bb[2], y1=bb[3], size=sz,
            ))

    en_rows = [r for r in rows if not is_chinese(r.text)]
    zh_rows = [r for r in rows if is_chinese(r.text)]

    def _cluster_rows(row_list: list) -> list[list[TextRow]]:
        """Cluster vertically-adjacent rows with same x-position.

        Text rows in this PDF have large y-bboxes that overlap the next row
        (ascenders/descenders ~40pt), so y_top/y_bot gap is always negative.
        Use center-y distance instead: two rows that are part of the same
        multi-line label will have cy-gap ≈ 31pt (same as EN↔ZH gap).
        Two rows from *different* stations are typically ≥ 60pt apart.
        """
        row_list = sorted(row_list, key=lambda r: (round(r.x0 / 5), r.cy))
        clusters: list[list[TextRow]] = []
        used = [False] * len(row_list)
        for i, r in enumerate(row_list):
            if used[i]:
                continue
            cluster = [r]
            used[i] = True
            for j, t in enumerate(row_list):
                if used[j] or i == j:
                    continue
                # Same column (x-diff < 10pt) and cy directly below within 45pt
                dcy = t.cy - cluster[-1].cy
                if abs(t.x0 - cluster[-1].x0) < 10 and 0 < dcy < 45:
                    cluster.append(t)
                    used[j] = True
            clusters.append(cluster)
        return clusters

    # Use ONLY Chinese rows for station detection.
    # English text in this PDF wraps onto multiple lines unpredictably and
    # creates many fragmentation/pairing problems (e.g. "Hongqiao Railway"
    # + "Station", "National Exhibition" + "and Convention Center"). Chinese
    # labels are single-token and always one row per station.
    zh_clusters_raw = _cluster_rows(zh_rows)

    labels: list[StationLabel] = []
    for cluster in zh_clusters_raw:
        zh_text = "".join(r.text for r in cluster).strip()
        if not is_station_text(zh_text):
            continue
        x = sum(r.cx for r in cluster) / len(cluster)
        y = sum(r.cy for r in cluster) / len(cluster)
        labels.append(StationLabel(
            name_en="", name_zh=zh_text, x=x, y=y,
            spans=[TextSpan(text=r.text, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, size=r.size) for r in cluster],
        ))

    return labels


def build_station_labels(spans: list[TextSpan]) -> list[StationLabel]:
    """[Deprecated] kept for reference; build_station_labels_from_blocks is used."""
    station_spans = [s for s in spans if abs(s.size - 26) < 1.5 and is_station_text(s.text)]
    en = [s for s in station_spans if not is_chinese(s.text)]
    zh = [s for s in station_spans if is_chinese(s.text)]

    # Cluster English spans that are vertically adjacent (multiline names)
    en.sort(key=lambda s: (s.x0, s.y0))
    en_clusters: list[list[TextSpan]] = []
    used = [False] * len(en)
    for i, s in enumerate(en):
        if used[i]:
            continue
        cluster = [s]
        used[i] = True
        for j, t in enumerate(en):
            if used[j]:
                continue
            # Same x-range, t directly below
            if abs(s.x0 - t.x0) < 30 and 0 < (t.y0 - cluster[-1].y1) < 8:
                cluster.append(t)
                used[j] = True
        en_clusters.append(cluster)

    # Cluster Chinese spans similarly
    zh.sort(key=lambda s: (s.x0, s.y0))
    zh_clusters: list[list[TextSpan]] = []
    used = [False] * len(zh)
    for i, s in enumerate(zh):
        if used[i]:
            continue
        cluster = [s]
        used[i] = True
        for j, t in enumerate(zh):
            if used[j]:
                continue
            if abs(s.x0 - t.x0) < 30 and 0 < (t.y0 - cluster[-1].y1) < 8:
                cluster.append(t)
                used[j] = True
        zh_clusters.append(cluster)

    # Use mutual-best-match bipartite pairing.
    # Score = horizontal misalignment + |dy - typical_gap|.
    TYPICAL_GAP = 33.0  # observed typical en→zh vertical offset

    def pair_score(ec, zc) -> float:
        ec_xmid = sum(s.cx for s in ec) / len(ec)
        ec_y_bot = max(s.y1 for s in ec)
        zc_xmid = sum(s.cx for s in zc) / len(zc)
        zc_y_top = min(s.y0 for s in zc)
        dx = abs(zc_xmid - ec_xmid)
        dy = zc_y_top - ec_y_bot
        if dx > TEXT_PAIR_DX:
            return float("inf")
        if dy < -10 or dy > TEXT_PAIR_DY:
            return float("inf")
        return dx + 2 * abs(dy - TYPICAL_GAP)

    en_best_zh = []
    for ec in en_clusters:
        scores = [(pair_score(ec, zc), j) for j, zc in enumerate(zh_clusters)]
        scores.sort()
        en_best_zh.append(scores[0][1] if scores and scores[0][0] < float("inf") else -1)

    zh_best_en = []
    for zc in zh_clusters:
        scores = [(pair_score(ec, zc), i) for i, ec in enumerate(en_clusters)]
        scores.sort()
        zh_best_en.append(scores[0][1] if scores and scores[0][0] < float("inf") else -1)

    labels: list[StationLabel] = []
    used_en = [False] * len(en_clusters)
    used_zh = [False] * len(zh_clusters)

    # Mutual best-match
    for i, j in enumerate(en_best_zh):
        if j == -1:
            continue
        if zh_best_en[j] == i:
            ec = en_clusters[i]
            zc = zh_clusters[j]
            name_en = " ".join(s.text for s in ec).strip()
            name_zh = "".join(s.text for s in zc).strip()
            xs = [s.cx for s in ec + zc]
            ys = [(s.y0 + s.y1) / 2 for s in ec + zc]
            labels.append(StationLabel(
                name_en=name_en, name_zh=name_zh,
                x=sum(xs) / len(xs), y=sum(ys) / len(ys),
                spans=list(ec) + list(zc),
            ))
            used_en[i] = True
            used_zh[j] = True

    # Pass 2: greedy match remaining via best score
    while True:
        best_pair, best_score = None, float("inf")
        for i, ec in enumerate(en_clusters):
            if used_en[i]:
                continue
            for j, zc in enumerate(zh_clusters):
                if used_zh[j]:
                    continue
                s = pair_score(ec, zc)
                if s < best_score:
                    best_score = s
                    best_pair = (i, j)
        if best_pair is None or best_score == float("inf"):
            break
        i, j = best_pair
        ec = en_clusters[i]
        zc = zh_clusters[j]
        name_en = " ".join(s.text for s in ec).strip()
        name_zh = "".join(s.text for s in zc).strip()
        xs = [s.cx for s in ec + zc]
        ys = [(s.y0 + s.y1) / 2 for s in ec + zc]
        labels.append(StationLabel(
            name_en=name_en, name_zh=name_zh,
            x=sum(xs) / len(xs), y=sum(ys) / len(ys),
            spans=list(ec) + list(zc),
        ))
        used_en[i] = True
        used_zh[j] = True

    # Orphan English clusters
    for i, ec in enumerate(en_clusters):
        if used_en[i]:
            continue
        name_en = " ".join(s.text for s in ec).strip()
        xs = [s.cx for s in ec]
        ys = [(s.y0 + s.y1) / 2 for s in ec]
        labels.append(StationLabel(
            name_en=name_en, name_zh="",
            x=sum(xs) / len(xs), y=sum(ys) / len(ys),
            spans=list(ec),
        ))

    # Orphan Chinese clusters
    for j, zc in enumerate(zh_clusters):
        if used_zh[j]:
            continue
        name_zh = "".join(s.text for s in zc).strip()
        xs = [s.cx for s in zc]
        ys = [(s.y0 + s.y1) / 2 for s in zc]
        labels.append(StationLabel(
            name_en="", name_zh=name_zh,
            x=sum(xs) / len(xs), y=sum(ys) / len(ys),
            spans=list(zc),
        ))

    return labels


# ── Phase 4a: extract non-transfer station "tick" markers ────────────
def extract_station_ticks(
    page: fitz.Page, color_to_line: dict[tuple, str]
) -> dict[str, list[tuple[float, float]]]:
    """
    Each non-transfer station in the v2 PDF is rendered as a single short
    perpendicular stroke of the line's color (length ~25pt, width = line width).
    Group these per line and return their midpoints as exact station positions.
    """
    per_line: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in page.get_drawings():
        if d.get("type") != "s":
            continue
        w = d.get("width", 0)
        if abs(w - LINE_STROKE_WIDTH) >= 0.5 and abs(w - 8.0) >= 0.5:
            continue
        items = d.get("items", [])
        if len(items) != 1 or items[0][0] != "l":
            continue
        it = items[0]
        p0 = (it[1].x, it[1].y)
        p1 = (it[2].x, it[2].y)
        seg_len = math.hypot(p0[0] - p1[0], p0[1] - p1[1])
        if not (16 <= seg_len <= 34):
            continue
        c = d.get("color")
        if not c:
            continue
        c_rounded = tuple(round(x, 3) for x in c)
        if color_close(c_rounded, (1, 1, 1)) or color_close(c_rounded, (0, 0, 0)):
            continue
        line_id, best_dist = None, float("inf")
        for cl, lid in color_to_line.items():
            dist = sum(abs(c_rounded[i] - cl[i]) for i in range(3))
            if dist < best_dist:
                best_dist = dist
                line_id = lid
        if line_id is None or best_dist >= 3 * COLOR_TOL:
            continue
        cx = (p0[0] + p1[0]) / 2
        cy = (p0[1] + p1[1]) / 2
        per_line[line_id].append((cx, cy))
    return per_line


# ── Phase 4a.1: extract the white-bordered "planned/suburban" line (AL) ──
def extract_white_bordered_line(page: fitz.Page) -> list[list[tuple[float, float]]]:
    """
    The Airport Link Line (机场联络线) planned segment is drawn as a filled
    polygon (type='fs', fill=white, stroke=gray #757575, w=2) with outer+inner
    boundaries ~16pt apart forming a "pipe" shape.

    Returns the centerline polyline(s) approximated by sampling boundary
    midpoints. Used to register AL as a proper line so its station markers
    can be geometrically matched.
    """
    target = None
    for d in page.get_drawings():
        if d.get("type") != "fs":
            continue
        fill = d.get("fill")
        c = d.get("color")
        items = d.get("items", [])
        if not fill or not c or len(items) < 20:
            continue
        if not all(x > 0.95 for x in fill):
            continue
        if not (0.4 < c[0] < 0.5 and abs(c[0] - c[1]) < 0.05 and abs(c[1] - c[2]) < 0.05):
            continue
        w = d.get("width", 0)
        if abs((w or 0) - 2.0) > 0.5:
            continue
        target = d
        break
    if not target:
        return []

    # Collect each segment's pair of endpoints (from `l` and `c` items).
    # Then: for each "long" segment (len > 50pt), find its matching parallel
    # segment on the OPPOSITE side of the pipe (~16pt away) and produce the
    # centerline by averaging. Works because the pipe is axis-aligned or
    # smoothly curved.
    segments: list[tuple[tuple[float,float], tuple[float,float]]] = []
    for it in target["items"]:
        op = it[0]
        if op == "l":
            segments.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        elif op == "c":
            p0, p3 = it[1], it[4]
            segments.append(((p0.x, p0.y), (p3.x, p3.y)))

    # Collect dense sample points for distance queries
    dense_pts: list[tuple[float, float]] = []
    for a, b in segments:
        seg_len = math.hypot(b[0]-a[0], b[1]-a[1])
        n = max(2, int(seg_len / 10) + 1)
        for k in range(n+1):
            t = k / n
            dense_pts.append((a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1])))

    def nearest_d(pt):
        return min(math.hypot(pt[0]-q[0], pt[1]-q[1]) for q in dense_pts)

    # For each dense point, move inward by 8pt perpendicular to the local boundary.
    # Approximation: for each dense point p, find the dense point q that's
    # ~16pt away; their midpoint is on the centerline.
    LINE_W = 16.0
    centerline_set: set[tuple[float, float]] = set()
    for p in dense_pts:
        # find any point q where |d - 16| < 3 and q is not super-close to p
        for q in dense_pts:
            d = math.hypot(p[0]-q[0], p[1]-q[1])
            if abs(d - LINE_W) < 3 and d > 8:
                mx, my = (p[0]+q[0])/2, (p[1]+q[1])/2
                # Snap to 2pt grid to dedupe
                centerline_set.add((round(mx/2)*2, round(my/2)*2))
                break

    if not centerline_set:
        return []

    pts_list = list(centerline_set)
    # Chain: greedy nearest-neighbor starting from westernmost-lowest point
    start = min(pts_list, key=lambda p: p[0] + p[1])
    chain = [start]
    remaining = [p for p in pts_list if p != start]
    while remaining:
        last = chain[-1]
        nxt = min(remaining, key=lambda p: (p[0]-last[0])**2 + (p[1]-last[1])**2)
        if math.hypot(nxt[0]-last[0], nxt[1]-last[1]) > 60:
            break
        chain.append(nxt)
        remaining.remove(nxt)
    return [chain] if len(chain) >= 5 else []


def extract_maglev_line(page: fitz.Page) -> list[list[tuple[float, float]]]:
    """
    The Shanghai Maglev (磁浮线) runs from 龙阳路 to 浦东国际机场 as a single
    stroke path with color ~(0.94, 0.44, 0.01) and width 8 — distinct from
    L7's orange color (0.925, 0.431, 0.0, w=16) by its thinner stroke width.
    Returns the polyline as a list of (x,y) sample points along the path.
    """
    for d in page.get_drawings():
        if d.get("type") != "s":
            continue
        c = d.get("color")
        if not c:
            continue
        # Maglev orange is slightly brighter than L7 orange; also w=8 (thin)
        if not (0.93 < c[0] < 0.95 and 0.42 < c[1] < 0.46 and c[2] < 0.02):
            continue
        if abs((d.get("width", 0) or 0) - 8.0) > 0.5:
            continue
        items = d.get("items", [])
        if len(items) < 5:
            continue
        # Sample dense points along the path
        pts: list[tuple[float, float]] = []
        for it in items:
            if it[0] == "l":
                a, b = it[1], it[2]
                pts.extend([(a.x, a.y), (b.x, b.y)])
            elif it[0] == "c":
                a, p1, p2, b = it[1], it[2], it[3], it[4]
                # sample cubic bezier
                for k in range(11):
                    t = k / 10
                    mt = 1 - t
                    x = mt**3*a.x + 3*mt**2*t*p1.x + 3*mt*t**2*p2.x + t**3*b.x
                    y = mt**3*a.y + 3*mt**2*t*p1.y + 3*mt*t**2*p2.y + t**3*b.y
                    pts.append((x, y))
        return [pts] if pts else []
    return []


def extract_al_polygon_ticks(page: fitz.Page) -> list[tuple[float, float]]:
    """
    The AL white-bordered polygon has small rectangular INDENTATIONS or V-notches
    along its boundary at non-transfer station positions (三林南, 康桥东,
    上海国际旅游度假区).  These show up as runs of 3+ consecutive short (<25pt)
    items in the polygon's path.  Return the centroid of each run as a station
    position on the AL line.
    """
    target = None
    for d in page.get_drawings():
        if d.get("type") != "fs":
            continue
        fill = d.get("fill")
        c = d.get("color")
        items = d.get("items", [])
        if not fill or not c or len(items) < 20:
            continue
        if not all(x > 0.95 for x in fill):
            continue
        if not (0.4 < c[0] < 0.5 and abs(c[0] - c[1]) < 0.05 and abs(c[1] - c[2]) < 0.05):
            continue
        w = d.get("width", 0)
        if abs((w or 0) - 2.0) > 0.5:
            continue
        target = d
        break
    if not target:
        return []

    def _item_len(it):
        if it[0] == "l":
            a, b = it[1], it[2]
            return math.hypot(b.x - a.x, b.y - a.y)
        if it[0] == "c":
            a, b = it[1], it[4]
            return math.hypot(b.x - a.x, b.y - a.y)
        return 0.0

    items = target["items"]
    ticks: list[tuple[float, float]] = []
    i = 0
    while i < len(items):
        if items[i][0] not in ("l", "c") or _item_len(items[i]) >= 25.0:
            i += 1
            continue
        run_start = i
        while i < len(items) and items[i][0] in ("l", "c") and _item_len(items[i]) < 25.0:
            i += 1
        if i - run_start >= 3:
            pts = []
            for j in range(run_start, i):
                it = items[j]
                pts.append(it[1])
                pts.append(it[-1])
            cx = sum(p.x for p in pts) / len(pts)
            cy = sum(p.y for p in pts) / len(pts)
            ticks.append((cx, cy))
    return ticks


def extract_al_rect_markers(page: fitz.Page) -> list[tuple[float, float]]:
    """
    Non-transfer station markers drawn as a rounded-rectangle shape with
    dark-gray border (w=3, fill=white, ~39×29pt, 6-item path).

    These appear on multiple lines (not just AL) — used for stations drawn
    in the "box" style rather than the colored-tick style. Caller assigns
    each marker to its nearest line.
    """
    markers: list[tuple[float, float]] = []
    for d in page.get_drawings():
        if d.get("type") != "fs":
            continue
        c = d.get("color")
        fill = d.get("fill")
        if not c or not fill:
            continue
        if not all(x > 0.95 for x in fill):
            continue
        if not all(x < 0.2 for x in c):
            continue
        w = d.get("width", 0)
        if abs((w or 0) - 3.0) > 0.5:
            continue
        r = d.get("rect")
        if not r:
            continue
        if max(r.width, r.height) > 50 or min(r.width, r.height) < 10:
            continue
        items = d.get("items", [])
        if len(items) != 6:
            continue
        markers.append(((r.x0+r.x1)/2, (r.y0+r.y1)/2))
    return markers


# ── Phase 4: extract per-color polylines ─────────────────────────────
def extract_polylines_per_color(
    page: fitz.Page, color_to_line: dict[tuple, str]
) -> dict[str, list[list[tuple[float, float]]]]:
    """
    Walk page strokes (width=16). For each stroke drawing, sample its path
    points (handle 'l' and 'c' Bézier curves) → list of polylines per line.
    """
    drawings = page.get_drawings()
    raw_per_line: dict[str, list[list[tuple[float, float]]]] = defaultdict(list)

    for d in drawings:
        if d.get("type") != "s":
            continue
        # Accept both standard (width=16) and Pujiang-style (width=8) strokes.
        # w=8 is ONLY used by the Pujiang Line — other lines use this width for
        # shared-track indicators that must not be merged into the regular polyline.
        w = d.get("width", 0)
        is_thin = abs(w - 8.0) < 0.5
        is_std = abs(w - LINE_STROKE_WIDTH) < 0.5
        if not is_std and not is_thin:
            continue
        c = d.get("color")
        if not c:
            continue
        c_rounded = tuple(round(x, 3) for x in c)
        # Use closest-match rather than first-within-tolerance to avoid
        # ambiguity between adjacent colors (e.g. Line 7 vs Pujiang).
        line_id = None
        best_dist = float("inf")
        for cl, lid in color_to_line.items():
            dist = sum(abs(c_rounded[i] - cl[i]) for i in range(3))
            if dist < best_dist:
                best_dist = dist
                line_id = lid
        if line_id is None or best_dist >= 3 * COLOR_TOL:
            continue
        # Only allow thin (w=8) strokes for lines that officially use that width
        if is_thin and line_id != "Pujiang":
            continue

        # Reconstruct path from items
        # Each path can have multiple subpaths separated by `re`/`m`-style breaks.
        # We track "current" path: starts at first move-equivalent point.
        items = d.get("items", [])
        current: list[tuple[float, float]] = []
        for it in items:
            op = it[0]
            if op == "l":
                # ('l', Point start, Point end)
                p0 = (it[1].x, it[1].y)
                p1 = (it[2].x, it[2].y)
                if not current:
                    current.append(p0)
                elif _dist(current[-1], p0) > 0.5:
                    if len(current) >= 2:
                        raw_per_line[line_id].append(current)
                    current = [p0]
                current.append(p1)
            elif op == "c":
                # ('c', P0, P1, P2, P3) — cubic Bezier
                p0 = (it[1].x, it[1].y)
                p3 = (it[4].x, it[4].y)
                ctrl1 = (it[2].x, it[2].y)
                ctrl2 = (it[3].x, it[3].y)
                if not current:
                    current.append(p0)
                elif _dist(current[-1], p0) > 0.5:
                    if len(current) >= 2:
                        raw_per_line[line_id].append(current)
                    current = [p0]
                # Sample bezier into ~8 segments
                for t in range(1, 9):
                    tt = t / 8
                    x = (1 - tt) ** 3 * p0[0] + 3 * (1 - tt) ** 2 * tt * ctrl1[0] \
                        + 3 * (1 - tt) * tt ** 2 * ctrl2[0] + tt ** 3 * p3[0]
                    y = (1 - tt) ** 3 * p0[1] + 3 * (1 - tt) ** 2 * tt * ctrl1[1] \
                        + 3 * (1 - tt) * tt ** 2 * ctrl2[1] + tt ** 3 * p3[1]
                    current.append((x, y))
            elif op == "re":
                # rectangle — emit and skip
                if len(current) >= 2:
                    raw_per_line[line_id].append(current)
                current = []
        if len(current) >= 2:
            raw_per_line[line_id].append(current)

    # Merge polylines that share endpoints (within 1 pt)
    merged_per_line: dict[str, list[list[tuple[float, float]]]] = {}
    for line_id, polys in raw_per_line.items():
        merged_per_line[line_id] = _merge_chains(polys)

    return merged_per_line


def _dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _merge_chains(
    polys: list[list[tuple[float, float]]], tol: float = 1.0
) -> list[list[tuple[float, float]]]:
    """Greedy merge of polylines whose endpoints touch."""
    polys = [list(p) for p in polys if len(p) >= 2]
    changed = True
    while changed:
        changed = False
        for i in range(len(polys)):
            if not polys[i]:
                continue
            for j in range(len(polys)):
                if i == j or not polys[j]:
                    continue
                a_start, a_end = polys[i][0], polys[i][-1]
                b_start, b_end = polys[j][0], polys[j][-1]
                if _dist(a_end, b_start) <= tol:
                    polys[i] = polys[i] + polys[j][1:]
                    polys[j] = []
                    changed = True
                    break
                if _dist(a_end, b_end) <= tol:
                    polys[i] = polys[i] + list(reversed(polys[j]))[1:]
                    polys[j] = []
                    changed = True
                    break
                if _dist(a_start, b_end) <= tol:
                    polys[i] = polys[j] + polys[i][1:]
                    polys[j] = []
                    changed = True
                    break
                if _dist(a_start, b_start) <= tol:
                    polys[i] = list(reversed(polys[j])) + polys[i][1:]
                    polys[j] = []
                    changed = True
                    break
            if changed:
                break
    return [p for p in polys if p]


# ── Phase 5: assign each station label to the nearest line(s) ────────
def project_to_polyline(
    pt: tuple[float, float], poly: list[tuple[float, float]]
) -> tuple[float, float]:
    """Returns (closest distance, arc-length position along polyline)."""
    best_d = float("inf")
    best_arc = 0.0
    arc = 0.0
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        seg_len = _dist(a, b)
        if seg_len == 0:
            continue
        # Project pt onto segment
        t = ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / (seg_len ** 2)
        t = max(0, min(1, t))
        proj = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        d = _dist(pt, proj)
        if d < best_d:
            best_d = d
            best_arc = arc + t * seg_len
        arc += seg_len
    return best_d, best_arc


def assign_stations_to_lines(
    labels: list[StationLabel],
    polylines_per_line: dict[str, list[list[tuple[float, float]]]],
) -> dict[str, list[tuple[StationLabel, float, float, float]]]:
    """
    For each line, returns list of (label, snap_x, snap_y, arc_length)
    sorted by arc_length.

    Step 1: assign each label to its closest line (primary).
    Step 2: at the primary snap point, check if any OTHER line's polyline
            passes within SECONDARY_ASSIGN_TOL_PT — if yes, it's a transfer
            station and the label is also added to that line.
    """
    per_line: dict[str, list[tuple[StationLabel, float, float, float]]] = defaultdict(list)

    for label in labels:
        # Step 1: closest line
        best_d, best_line, best_pt, best_arc = float("inf"), None, (0.0, 0.0), 0.0
        for line_id, polys in polylines_per_line.items():
            for poly in polys:
                d, arc = project_to_polyline((label.x, label.y), poly)
                if d < best_d:
                    best_d = d
                    best_line = line_id
                    best_arc = arc
                    best_pt = _closest_point_on_polyline((label.x, label.y), poly)
        if best_line is None or best_d > STATION_TO_LINE_MAX_DIST:
            continue
        per_line[best_line].append((label, best_pt[0], best_pt[1], best_arc))

        # Step 2: which other lines pass through the primary snap point?
        for line_id, polys in polylines_per_line.items():
            if line_id == best_line:
                continue
            # Find the closest point on this OTHER line to our primary snap point
            sub_d, sub_arc, sub_pt = float("inf"), 0.0, (0.0, 0.0)
            for poly in polys:
                d, arc = project_to_polyline(best_pt, poly)
                if d < sub_d:
                    sub_d = d
                    sub_arc = arc
                    sub_pt = _closest_point_on_polyline(best_pt, poly)
            if sub_d <= SECONDARY_ASSIGN_TOL_PT:
                per_line[line_id].append((label, sub_pt[0], sub_pt[1], sub_arc))

    # Extra pass: lines with larger per-line max-distance overrides.
    # Used for lines (e.g. AL) whose labels are placed far from the stroke in the PDF.
    for override_line_id, override_max_d in LINE_STATION_MAX_DIST_OVERRIDES.items():
        if override_line_id not in polylines_per_line:
            continue
        assigned_labels = {id(e[0]) for e in per_line.get(override_line_id, [])}
        for label in labels:
            if id(label) in assigned_labels:
                continue
            best_d, best_arc, best_pt = float("inf"), 0.0, (0.0, 0.0)
            for poly in polylines_per_line[override_line_id]:
                d, arc = project_to_polyline((label.x, label.y), poly)
                if d < best_d:
                    best_d = d
                    best_arc = arc
                    best_pt = _closest_point_on_polyline((label.x, label.y), poly)
            if best_d <= override_max_d:
                per_line[override_line_id].append((label, best_pt[0], best_pt[1], best_arc))

    # Sort each line's stations by arc length and dedupe near-duplicates
    for lid in per_line:
        per_line[lid].sort(key=lambda x: x[3])
        # Drop consecutive entries with same label name (created by labels
        # whose snap projects to multiple disjoint polylines on one line)
        dedup = []
        seen_names = set()
        for entry in per_line[lid]:
            label = entry[0]
            key = (label.name_en, label.name_zh, round(entry[1] / 30), round(entry[2] / 30))
            if key in seen_names:
                continue
            seen_names.add(key)
            dedup.append(entry)
        per_line[lid] = dedup
    return per_line


def _closest_point_on_polyline(
    pt: tuple[float, float], poly: list[tuple[float, float]]
) -> tuple[float, float]:
    best_d = float("inf")
    best_pt = poly[0]
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        seg_len = _dist(a, b)
        if seg_len == 0:
            continue
        t = ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / (seg_len ** 2)
        t = max(0, min(1, t))
        proj = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        d = _dist(pt, proj)
        if d < best_d:
            best_d = d
            best_pt = proj
    return best_pt


# ── Phase 5b: geometry-first station assignment ──────────────────────
def assign_stations_geometric(
    labels: list[StationLabel],
    ticks_per_line: dict[str, list[tuple[float, float]]],
    transfer_clusters: list[dict],
    polylines_per_line: dict[str, list[list[tuple[float, float]]]],
    polygon_tick_lines: set[str] | None = None,
) -> tuple[
    dict[str, list[tuple[StationLabel, float, float, float, str]]],
    dict[int, set[str]],
]:
    """
    Geometry-first station extraction:
      * Tick marks (1-segment width-16 strokes) are exact non-transfer station positions.
      * Transfer cluster centers are exact transfer station positions; line membership
        is determined by which polylines pass within TRANSFER_CLUSTER_TOL_PT.
      * Chinese labels are matched to markers by nearest-neighbor (only for naming).

    Returns:
      per_line: line_id -> [(label, x, y, arc_len, marker_id)] sorted by arc_len
      cluster_lines: cluster_idx -> set of line_ids that pass through this transfer cluster
    """
    # Determine which lines pass through each transfer cluster.
    # Small single-box markers (39×29 rectangles) use a tight tolerance (12pt)
    # because their "membership" is only real for lines whose polyline truly
    # coincides with the box — nearby parallel lines don't stop here.
    # Larger transfer capsules use the standard tolerance (30pt).
    SMALL_BOX_TOL = 12.0
    cluster_lines: dict[int, set[str]] = {}
    for ci, cl in enumerate(transfer_clusters):
        cx, cy = cl["cx"], cl["cy"]
        tol = SMALL_BOX_TOL if cl.get("small") else TRANSFER_CLUSTER_TOL_PT
        # For large (non-small) clusters: test all member shape centers so a line
        # passing near one sub-shape isn't excluded just because the centroid is far.
        # (e.g. 曹杨路: L14 passes near the upper 29×29 box at y=2187, but the
        # dominant centroid is the 29×59 capsule at y=2237 which is 34.6pt from L14.)
        test_pts = [(cx, cy)] if cl.get("small") else cl.get("shape_centers", [(cx, cy)])
        members = set()
        for line_id, polys in polylines_per_line.items():
            best_d = float("inf")
            for sx, sy in test_pts:
                for poly in polys:
                    d, _ = project_to_polyline((sx, sy), poly)
                    if d < best_d:
                        best_d = d
            if best_d <= tol:
                members.add(line_id)
        cluster_lines[ci] = members

    # Collect every (line_id, x, y, marker_id) station position
    all_markers: list[tuple[str, float, float, str]] = []
    for line_id, ticks in ticks_per_line.items():
        for i, (x, y) in enumerate(ticks):
            all_markers.append((line_id, x, y, f"tick:{line_id}:{i}"))
    # Lines that have no tick marks rely solely on transfer clusters for any stations.
    # Allow single-line clusters for those lines (they're real station markers, not
    # decorative shapes). For lines WITH ticks, require ≥2 lines per cluster to
    # suppress false-positive decorative white shapes.
    # tick_lines controls the single-line cluster filter and terminus filter.
    # Lines whose ticks come only from polygon-boundary indents (AL) are NOT
    # included here: their circle/box clusters (Pudong T1/T2) remain valid
    # single-line clusters.
    tick_lines = set(ticks_per_line.keys()) - (polygon_tick_lines or set())

    # Special case: a small-box cluster located at the TERMINUS (first/last polyline
    # point) of a non-tick line is that line's own station marker, not a shared
    # transfer.  If a tick-enabled line also claims it only because the polyline
    # passes within SMALL_BOX_TOL but has no tick there, remove that tick-line.
    # (Fixes L2 falsely claiming the AL western-terminus marker at Hongqiao.)
    _NON_TICK_TERMINUS_TOL = 15.0
    _TICK_NEAR_TOL = 20.0
    _line_endpoints: dict[str, list[tuple[float, float]]] = {
        lid: [poly[0] for poly in polys if poly] + [poly[-1] for poly in polys if poly]
        for lid, polys in polylines_per_line.items()
    }
    for ci, cl in enumerate(transfer_clusters):
        if not cl.get("small"):
            continue
        cx, cy = cl["cx"], cl["cy"]
        members = cluster_lines[ci]
        at_non_tick_terminus = any(
            lid not in tick_lines and any(
                math.hypot(cx - ex, cy - ey) <= _NON_TICK_TERMINUS_TOL
                for ex, ey in _line_endpoints.get(lid, [])
            )
            for lid in members
        )
        if not at_non_tick_terminus:
            continue
        to_remove = {
            lid for lid in members
            if lid in tick_lines
            and not any(math.hypot(cx - tx, cy - ty) <= _TICK_NEAR_TOL
                        for tx, ty in ticks_per_line[lid])
        }
        cluster_lines[ci] -= to_remove

    for ci, members in cluster_lines.items():
        cl = transfer_clusters[ci]
        # Apply min_lines filter. A single-line cluster is valid when:
        #  * the line has no tick marks (AL etc.), OR
        #  * the cluster is a "small" (39×29) single-box marker — this IS a
        #    genuine non-transfer station marker, not a decorative shape.
        # A single-line LARGE (capsule) cluster on a ticked line is almost
        # always a decorative artifact and is skipped.
        if len(members) < 2 and not cl.get("small"):
            if not members or (members & tick_lines):
                continue

        # Snap to each line's polyline so the marker sits on that line, not at the
        # cluster centroid (which is between lines)
        for line_id in members:
            polys = polylines_per_line[line_id]
            best_d, best_pt = float("inf"), (cl["cx"], cl["cy"])
            for poly in polys:
                d, _ = project_to_polyline((cl["cx"], cl["cy"]), poly)
                if d < best_d:
                    best_d = d
                    best_pt = _closest_point_on_polyline((cl["cx"], cl["cy"]), poly)
            all_markers.append((line_id, best_pt[0], best_pt[1], f"trans:{ci}"))

    # Match labels to markers with label uniqueness via greedy bipartite.
    # Each distinct mid (transfer cluster OR tick) gets one label. Transfer
    # markers sharing the same mid ("trans:ci") naturally share that label
    # across all their member lines. Enforce that each label NAME is used by
    # at most one mid, to prevent a label like 石龙路 being stolen from its
    # legitimate marker by a nearby unrelated marker on a different line.
    marker_to_label: dict[str, StationLabel] = {}

    # One representative position per mid (cluster center or tick position)
    unique_mids: dict[str, tuple[float, float]] = {}
    for line_id, x, y, mid in all_markers:
        if mid not in unique_mids:
            unique_mids[mid] = (x, y)

    # For each marker, ranked list of nearest labels (within 200pt)
    ranked_labels: dict[str, list[tuple[float, StationLabel]]] = {}
    for mid, (x, y) in unique_mids.items():
        cands = []
        for label in labels:
            d = math.hypot(label.x - x, label.y - y)
            if d <= 200:
                cands.append((d, label))
        cands.sort(key=lambda t: t[0])
        ranked_labels[mid] = cands

    # Greedy bipartite: iteratively pick the smallest-distance (mid, label) pair
    # from top-available candidates. Each label name is taken by at most one mid.
    assigned_label_names: set[str] = set()
    cursor: dict[str, int] = {mid: 0 for mid in unique_mids}
    while True:
        best = None
        best_d = float("inf")
        for mid in unique_mids:
            if mid in marker_to_label:
                continue
            # Advance cursor past already-taken labels
            cands = ranked_labels[mid]
            i = cursor[mid]
            while i < len(cands) and (cands[i][1].name_zh in assigned_label_names):
                i += 1
            cursor[mid] = i
            if i >= len(cands):
                marker_to_label[mid] = None  # no available label
                continue
            d, lab = cands[i]
            if d < best_d:
                best_d = d
                best = (mid, lab)
        if best is None:
            break
        mid, lab = best
        marker_to_label[mid] = lab
        if lab.name_zh:
            assigned_label_names.add(lab.name_zh)

    # Drop None entries
    marker_to_label = {k: v for k, v in marker_to_label.items() if v is not None}

    # Build per_line
    per_line: dict[str, list[tuple[StationLabel, float, float, float, str]]] = defaultdict(list)
    for line_id, x, y, mid in all_markers:
        polys = polylines_per_line.get(line_id, [])
        # arc-length on this line
        best_d, arc = float("inf"), 0.0
        for poly in polys:
            d, a = project_to_polyline((x, y), poly)
            if d < best_d:
                best_d = d
                arc = a
        label = marker_to_label.get(mid) or StationLabel(
            name_en="", name_zh="", x=x, y=y, spans=[]
        )
        per_line[line_id].append((label, x, y, arc, mid))

    # Sort each line by arc-length, then dedupe markers that are too close
    # (within 25pt) — happens when the same station is detected as both a
    # tick rectangle and a transfer-cluster circle.
    DEDUP_TOL = 10.0
    for lid in per_line:
        per_line[lid].sort(key=lambda e: e[3])
        deduped = []
        for entry in per_line[lid]:
            _, x, y, _, _ = entry
            if any(math.hypot(x - px, y - py) < DEDUP_TOL
                   for _, px, py, _, _ in deduped):
                continue
            deduped.append(entry)
        per_line[lid] = deduped

    return per_line, cluster_lines


# ── Phase 6: compute station IDs + transfer clusters ─────────────────
def compute_station_ids_and_transfers(
    per_line: dict[str, list[tuple[StationLabel, float, float, float, str]]],
    polylines_per_line: dict[str, list[list[tuple[float, float]]]],
) -> tuple[dict[str, dict], list[dict], list[dict]]:
    """
    Returns:
      - stations: {station_id: {line, x, y, name_en, name_zh, transfer_group}}
      - lines_data: [{id, color, trunk, branches}]
      - transfers: [{group_id, station_ids, center_x, center_y}]

    Each per_line entry is (label, x, y, arc_len, marker_id).  Markers prefixed
    with "trans:<idx>" are transfer-cluster markers; sids sharing the same
    marker_id are the same physical transfer station on different lines.
    """
    stations: dict[str, dict] = {}
    lines_data: list[dict] = []
    marker_to_sids: dict[str, list[str]] = defaultdict(list)

    sorted_line_ids = _sort_line_ids(per_line.keys())

    for line_id in sorted_line_ids:
        entries = per_line[line_id]
        if line_id in LOOP_LINES and entries:
            start_idx = min(range(len(entries)), key=lambda i: entries[i][1])
            entries = entries[start_idx:] + entries[:start_idx]

        trunk_ids = []
        for i, (label, x, y, arc, mid) in enumerate(entries, start=1):
            sid = f"{_pad(line_id)}-{i:02d}"
            trunk_ids.append(sid)
            stations[sid] = {
                "line": line_id,
                "x": round(x, 2),
                "y": round(y, 2),
                "name_en": label.name_en,
                "name_zh": label.name_zh,
                "transfer_group": None,
            }
            marker_to_sids[mid].append(sid)

        lines_data.append({
            "id": line_id,
            "trunk": trunk_ids,
            "branches": {},
        })

    # Transfer detection: marker_ids that begin with "trans:" cluster their sids
    transfers: list[dict] = []
    sid_list = list(stations.keys())
    parent = {sid: sid for sid in sid_list}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for mid, sids in marker_to_sids.items():
        if mid.startswith("trans:") and len(sids) >= 2:
            for s in sids[1:]:
                union(sids[0], s)

    cluster_map: dict[str, list[str]] = defaultdict(list)
    for sid in sid_list:
        cluster_map[find(sid)].append(sid)

    transfer_idx = 1
    for root, members in cluster_map.items():
        if len(members) < 2:
            continue
        gid = f"T{transfer_idx:03d}"
        transfer_idx += 1
        cx = sum(stations[m]["x"] for m in members) / len(members)
        cy = sum(stations[m]["y"] for m in members) / len(members)
        for m in members:
            stations[m]["transfer_group"] = gid
        transfers.append({
            "group_id": gid,
            "station_ids": sorted(members),
            "center_x": round(cx, 2),
            "center_y": round(cy, 2),
        })

    return stations, lines_data, transfers


def _pad(line_id: str) -> str:
    if line_id.isdigit():
        return f"{int(line_id):02d}"
    return line_id


def _sort_line_ids(ids: Iterable[str]) -> list[str]:
    nums, names = [], []
    for x in ids:
        if x.isdigit():
            nums.append(x)
        else:
            names.append(x)
    return sorted(nums, key=int) + sorted(names)


# ── Phase 7: SVG output ──────────────────────────────────────────────

def _items_to_svg_path(items: list) -> str:
    """Convert a PyMuPDF drawing items list to an SVG path data string."""
    parts: list[str] = []
    cursor: tuple[float, float] | None = None
    for it in items:
        op = it[0]
        if op == "l":
            p0 = (round(it[1].x, 1), round(it[1].y, 1))
            p1 = (round(it[2].x, 1), round(it[2].y, 1))
            if cursor is None or abs(cursor[0]-p0[0]) > 0.5 or abs(cursor[1]-p0[1]) > 0.5:
                parts.append(f"M{p0[0]},{p0[1]}")
            parts.append(f"L{p1[0]},{p1[1]}")
            cursor = p1
        elif op == "c":
            p0 = (round(it[1].x, 1), round(it[1].y, 1))
            c1 = (round(it[2].x, 1), round(it[2].y, 1))
            c2 = (round(it[3].x, 1), round(it[3].y, 1))
            p3 = (round(it[4].x, 1), round(it[4].y, 1))
            if cursor is None or abs(cursor[0]-p0[0]) > 0.5 or abs(cursor[1]-p0[1]) > 0.5:
                parts.append(f"M{p0[0]},{p0[1]}")
            parts.append(f"C{c1[0]},{c1[1]} {c2[0]},{c2[1]} {p3[0]},{p3[1]}")
            cursor = p3
        elif op == "re":
            r = it[1]
            parts.append(f"M{r.x0:.1f},{r.y0:.1f}H{r.x1:.1f}V{r.y1:.1f}H{r.x0:.1f}Z")
            cursor = None
    if parts and not parts[-1].endswith("Z"):
        parts.append("Z")
    return " ".join(parts)


def extract_station_marker_clusters(page: fitz.Page) -> list[dict]:
    """
    Extract white-fill station marker shapes from the PDF and cluster nearby ones.
    Returns list of dicts: {cx, cy, path_d, small} where `small` is True if the
    cluster came from a single small rectangle marker (caller uses this flag to
    apply a tighter line-membership tolerance).
    """
    raw: list[dict] = []
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
        items = d.get("items", [])
        if not items:
            continue
        # Flag "small" rectangles: 39×29-ish single-box markers whose shape can
        # be attributed to 1-2 lines at most. Used later to tighten membership.
        c = d.get("color")
        w = d.get("width", 0)
        is_small_box = bool(
            c and all(x < 0.2 for x in c)
            and abs((w or 0) - 3.0) < 0.5
            and len(items) == 6
            and max(r.width, r.height) < 50
        )
        path_d = _items_to_svg_path(items)
        if not path_d:
            continue
        raw.append({
            "cx": (r.x0 + r.x1) / 2,
            "cy": (r.y0 + r.y1) / 2,
            "path_d": path_d,
            "small": is_small_box,
            "area": r.width * r.height,
        })

    if not raw:
        return []

    # Cluster nearby shapes via union-find (tol = 35 pt)
    n = len(raw)
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _dist((raw[i]["cx"], raw[i]["cy"]), (raw[j]["cx"], raw[j]["cy"])) < 35.0:
                _union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(i)

    clusters: list[dict] = []
    for members in groups.values():
        # Centroid: if one member shape has clearly the largest area (>1.5× the
        # next one), that's the main transfer capsule — use its center and
        # ignore the smaller decorative shapes (label boxes, icons) that get
        # clustered with it. Otherwise (equal-size shapes, like 3 identical
        # 29×29 segments of a 3-line transfer marker) use the arithmetic mean.
        sorted_members = sorted(members, key=lambda m: -raw[m]["area"])
        top = raw[sorted_members[0]]
        next_area = raw[sorted_members[1]]["area"] if len(sorted_members) > 1 else 0
        if top["area"] >= 1.5 * next_area:
            cx, cy = top["cx"], top["cy"]
        else:
            cx = sum(raw[m]["cx"] for m in members) / len(members)
            cy = sum(raw[m]["cy"] for m in members) / len(members)
        path_d = " ".join(raw[m]["path_d"] for m in members)
        small = all(raw[m]["small"] for m in members)
        shape_centers = [(raw[m]["cx"], raw[m]["cy"]) for m in members]
        clusters.append({"cx": cx, "cy": cy, "path_d": path_d, "small": small,
                         "shape_centers": shape_centers})
    return clusters


def write_full_svg(page: fitz.Page, out_path: Path) -> None:
    svg_text = page.get_svg_image()
    out_path.write_text(svg_text, encoding="utf-8")


def write_overlay_svg(
    page: fitz.Page,
    stations: dict[str, dict],
    line_colors: dict[str, str],
    out_path: Path,
) -> None:
    """
    Overlay SVG drawing order (SVG paints later elements on top):
      Layer 1 — regular (non-transfer) station boxes: small rounded-rect per station
      Layer 2 — transfer station shapes: actual PDF capsule/circle/irregular geometry
    """
    rect = page.rect

    # Extract marker shape clusters from the PDF (capsules/circles on transfer stations)
    marker_clusters = extract_station_marker_clusters(page)

    # Associate each station with its nearest shape cluster (within 60 pt)
    station_cluster: dict[str, dict | None] = {}
    for sid, meta in stations.items():
        best_d, best_cl = float("inf"), None
        for cl in marker_clusters:
            d = _dist((cl["cx"], cl["cy"]), (meta["x"], meta["y"]))
            if d < 60.0 and d < best_d:
                best_d = d
                best_cl = cl
        station_cluster[sid] = best_cl

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {rect.width:.0f} {rect.height:.0f}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'style="width:100%;height:100%;pointer-events:none">',
        '<g id="stations" style="pointer-events:auto">',
    ]

    # ── Layer 0: line extensions for manual-injection stations that sit
    #    BEYOND the drawn polyline (e.g. L17 西岑). Draw a colored stroke
    #    from the nearest existing same-line station to the manual station.
    ext_parts: list[str] = []
    for sid, meta in stations.items():
        if not meta.get("extend_line"):
            continue
        lid = meta["line"]
        color = line_colors.get(lid, "#000")
        # Find nearest same-line station (non-manual) by Euclidean distance
        nearest = None
        best_d = float("inf")
        for osid, ometa in stations.items():
            if osid == sid or ometa["line"] != lid or ometa.get("manual"):
                continue
            d = _dist((meta["x"], meta["y"]), (ometa["x"], ometa["y"]))
            if d < best_d:
                best_d = d
                nearest = ometa
        if nearest is None:
            continue
        ext_parts.append(
            f'<line class="line-extension" data-line="{lid}" '
            f'x1="{nearest["x"]:.1f}" y1="{nearest["y"]:.1f}" '
            f'x2="{meta["x"]:.1f}" y2="{meta["y"]:.1f}" '
            f'stroke="{color}" stroke-width="16" stroke-linecap="round" fill="none" />'
        )
    if ext_parts:
        parts.append('<!-- manual line extensions -->')
        parts.extend(ext_parts)

    # ── Layer 1: regular station boxes (drawn first = painted below) ──────────
    parts.append('<!-- regular stations -->')
    for sid, meta in stations.items():
        if meta.get("transfer_group"):
            continue   # skipped here; handled in Layer 2
        color = line_colors.get(meta["line"], "#000")
        x, y = meta["x"], meta["y"]
        # Small white rounded-rect capsule oriented horizontally (32×22 pt)
        hw, hh = 16, 11
        parts.append(
            f'<rect id="{sid}" class="station" '
            f'data-line="{meta["line"]}" '
            f'x="{x - hw:.1f}" y="{y - hh:.1f}" width="{hw*2}" height="{hh*2}" rx="11" ry="11" '
            f'fill="white" stroke="{color}" stroke-width="5" '
            f'style="cursor:pointer" />'
        )

    # ── Layer 2: transfer station shapes (drawn on top) ───────────────────────
    parts.append('<!-- transfer stations -->')
    rendered_clusters: set[int] = set()
    for sid, meta in stations.items():
        if not meta.get("transfer_group"):
            continue
        tg_attr = f' data-tgroup="{meta["transfer_group"]}"'
        cl = station_cluster.get(sid)

        if cl is not None:
            cl_key = id(cl)
            if cl_key not in rendered_clusters:
                rendered_clusters.add(cl_key)
                # Render the actual PDF shape (capsule / circle / irregular)
                parts.append(
                    f'<path id="{sid}" class="station" '
                    f'data-line="{meta["line"]}"{tg_attr} '
                    f'data-cx="{meta["x"]:.1f}" data-cy="{meta["y"]:.1f}" '
                    f'd="{cl["path_d"]}" '
                    f'fill="white" stroke="#333333" stroke-width="6" '
                    f'style="cursor:pointer" />'
                )
            else:
                # Secondary station in same cluster: invisible hit circle
                parts.append(
                    f'<circle id="{sid}" class="station" '
                    f'data-line="{meta["line"]}"{tg_attr} '
                    f'cx="{meta["x"]:.1f}" cy="{meta["y"]:.1f}" r="22" '
                    f'fill="transparent" stroke="transparent" '
                    f'style="cursor:pointer" />'
                )
        else:
            # Transfer station but no geometric shape found: fallback circle
            color = line_colors.get(meta["line"], "#000")
            parts.append(
                f'<circle id="{sid}" class="station" '
                f'data-line="{meta["line"]}"{tg_attr} '
                f'cx="{meta["x"]:.1f}" cy="{meta["y"]:.1f}" r="22" '
                f'fill="white" stroke="{color}" stroke-width="6" '
                f'style="cursor:pointer" />'
            )

    parts.append("</g></svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    if not PDF_PATH.exists():
        print(f"ERROR: {PDF_PATH} not found", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.debug:
        DEBUG_DIR.mkdir(exist_ok=True)

    print(f"Opening {PDF_PATH.name}...")
    doc = fitz.open(PDF_PATH)
    page = doc[0]

    print("→ Extracting text spans...")
    spans = extract_text_spans(page)
    print(f"  {len(spans)} spans")

    print("→ Mapping line labels to colors...")
    line_color_map_by_id = find_line_color_map(page, spans)
    color_to_line: dict[tuple, str] = {
        rgb: line_id for line_id, (_, rgb) in line_color_map_by_id.items()
    }
    print(f"  {len(line_color_map_by_id)} lines identified:")
    for lid, (label, rgb) in sorted(line_color_map_by_id.items()):
        print(f"    {label} (id={lid}): {rgb_to_hex(rgb)}")

    print("→ Building station label pairs (block-based)...")
    labels = build_station_labels_from_blocks(page)
    print(f"  {len(labels)} labels")

    print("→ Extracting line polylines...")
    polylines = extract_polylines_per_color(page, color_to_line)

    # Use the white-bordered polygon's centerline as AL's ONLY polyline.
    # (Replace any color-extracted AL strokes — e.g. the teal auxiliary branch
    # from (4314,3429) that's actually a decorative/maglev overlay, not the
    # main AL route — otherwise it causes false station detection at 4314,3429
    # and pulls 浦东T2 into AL when it should be merged with T1.)
    white_al = extract_white_bordered_line(page)
    if white_al:
        polylines["AL"] = white_al
        print(f"  + AL white-bordered centerline: {len(white_al[0])} pts")

    # The Maglev (磁浮线) isn't detected via find_line_color_map (it lacks a
    # "Line N" style label). Extract it directly from the w=8 orange stroke.
    maglev = extract_maglev_line(page)
    if maglev:
        polylines["ML"] = maglev
        line_color_map_by_id["ML"] = ("Maglev Line", (0.937, 0.439, 0.008))
        print(f"  + Maglev line: {len(maglev[0])} pts")

    for lid, polys in sorted(polylines.items()):
        n = sum(len(p) for p in polys)
        print(f"  Line {lid}: {len(polys)} polylines, {n} pts")

    print("→ Extracting station tick markers...")
    ticks_per_line = extract_station_ticks(page, color_to_line)

    # AL's non-transfer stations (三林南, 康桥东, 上海国际旅游度假区) are drawn
    # as tiny rectangular/V-notches in the AL polygon boundary itself, not as
    # separate marker shapes. Detect them from the polygon path.
    al_polygon_ticks = extract_al_polygon_ticks(page)
    polygon_tick_lines: set[str] = set()
    if al_polygon_ticks:
        ticks_per_line.setdefault("AL", []).extend(al_polygon_ticks)
        polygon_tick_lines.add("AL")
        print(f"  + AL polygon-boundary ticks: {len(al_polygon_ticks)}")

    # 39×29 dark-gray bordered white-fill rectangles are handled via
    # extract_station_marker_clusters (flagged "small") with a tight
    # line-membership tolerance. No separate tick registration needed.

    for lid, ticks in sorted(ticks_per_line.items()):
        print(f"  Line {lid}: {len(ticks)} ticks")
    total_ticks = sum(len(t) for t in ticks_per_line.values())
    print(f"  Total non-transfer markers: {total_ticks}")

    print("→ Extracting transfer marker clusters...")
    transfer_clusters = extract_station_marker_clusters(page)
    print(f"  {len(transfer_clusters)} transfer clusters")

    print("→ Assigning stations geometrically...")
    per_line, _ = assign_stations_geometric(
        labels, ticks_per_line, transfer_clusters, polylines,
        polygon_tick_lines=polygon_tick_lines,
    )

    print("→ Computing IDs + transfers...")
    stations, lines_data, transfers = compute_station_ids_and_transfers(
        per_line, polylines
    )

    # Inject manually-specified stations not present in the PDF (new/planned
    # stations like L11 康恒路 and L17 西岑).  Assigned the next ID on their line.
    if MANUAL_STATIONS:
        print("→ Injecting manual stations...")
        lines_by_id = {ld["id"]: ld for ld in lines_data}
        for m in MANUAL_STATIONS:
            lid = m["line"]
            ld = lines_by_id.get(lid)
            if ld is None:
                continue
            next_idx = len(ld["trunk"]) + 1
            sid = f"{_pad(lid)}-{next_idx:02d}"
            stations[sid] = {
                "line": lid,
                "x": float(m["x"]),
                "y": float(m["y"]),
                "name_en": m.get("name_en", ""),
                "name_zh": m.get("name_zh", ""),
                "transfer_group": None,
                "manual": True,
                "extend_line": bool(m.get("extend_line", False)),
            }
            ld["trunk"].append(sid)
            print(f"  + {sid} {m.get('name_zh','')} ({m['x']},{m['y']}) on L{lid}")

    line_colors_hex = {
        lid: rgb_to_hex(rgb) for lid, (_, rgb) in line_color_map_by_id.items()
    }

    # Augment lines_data with colors
    for ld in lines_data:
        ld["color"] = line_colors_hex.get(ld["id"], "#000")
        ld["label"] = line_color_map_by_id.get(ld["id"], (f"Line {ld['id']}", None))[0]

    rect = page.rect
    out = {
        "viewBox": [0, 0, round(rect.width, 2), round(rect.height, 2)],
        "lines": lines_data,
        "stations": stations,
    }

    (OUT_DIR / "stations.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    (OUT_DIR / "transfers.json").write_text(json.dumps(transfers, ensure_ascii=False, indent=2))

    print("→ Writing transfers_review.csv...")
    csv_path = OUT_DIR / "transfers_review.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "n_stations", "diameter_pt", "names_en", "names_zh", "station_ids"])
        for t in transfers:
            members = t["station_ids"]
            xs = [stations[m]["x"] for m in members]
            ys = [stations[m]["y"] for m in members]
            diam = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            names_en = " / ".join(stations[m]["name_en"] for m in members if stations[m]["name_en"])
            names_zh = " / ".join(stations[m]["name_zh"] for m in members if stations[m]["name_zh"])
            w.writerow([t["group_id"], len(members), f"{diam:.1f}", names_en, names_zh, " ".join(members)])

    print("→ Writing full SVG...")
    write_full_svg(page, OUT_DIR / "shanghai-metro.svg")

    print("→ Writing overlay SVG...")
    write_overlay_svg(page, stations, line_colors_hex, OUT_DIR / "shanghai-metro-overlay.svg")

    print()
    print(f"✓ Total stations: {len(stations)}")
    print(f"✓ Transfer groups: {len(transfers)}")
    print(f"✓ Lines: {len(lines_data)}")
    print()
    for ld in lines_data:
        n = len(ld["trunk"])
        first = ld["trunk"][0] if ld["trunk"] else "—"
        last = ld["trunk"][-1] if ld["trunk"] else "—"
        first_name = stations[first]["name_zh"] if ld["trunk"] else ""
        last_name = stations[last]["name_zh"] if ld["trunk"] else ""
        print(f"  {ld['label']:>16} ({ld['color']}): {first} ({first_name}) … {last} ({last_name}) — {n} stations")

    return 0


if __name__ == "__main__":
    sys.exit(main())
