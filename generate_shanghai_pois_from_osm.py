#!/usr/bin/env python3
"""
Generate a batch of Shanghai POIs from OSM (via Overpass), intended for offline-first builds.

Output format matches your POI list requirement:
[
  {"id": "...", "name_zh": "...", "lat": 31.2, "lon": 121.4},
  ...
]

Strategy (pragmatic "known-ish" heuristic):
- Query within Shanghai bbox/area for objects that look like attractions:
  tourism=attraction/museum/zoo/theme_park/gallery,
  leisure=park/garden,
  man_made=tower,
  historic=monument/memorial/archaeological_site,
  amenity=place_of_worship (temples etc.)
- Require name:zh and (wikidata OR wikipedia) to bias toward notable, well-defined POIs.
- Use center coordinates for ways/relations.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests


DEFAULT_SHANGHAI_BBOX: Tuple[float, float, float, float] = (30.67, 120.85, 31.87, 122.12)


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def parse_bbox(s: str) -> Tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have 4 comma-separated numbers: south,west,north,east")
    return tuple(float(x) for x in parts)  # type: ignore[return-value]


def dump_json(path: str, obj: Any, *, utf8_bom: bool) -> None:
    enc = "utf-8-sig" if utf8_bom else "utf-8"
    with open(path, "w", encoding=enc) as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def load_json(path: str) -> Any:
    with open(path, "rb") as f:
        raw = f.read()
    last: Optional[Exception] = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(raw.decode(enc))
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise ValueError(f"Failed to decode JSON file '{path}' as utf-8/utf-8-sig/gbk: {last}")


def overpass_post(
    overpass_url: str,
    query: str,
    *,
    rate_limit_sleep_s: float,
    timeout_s: float,
    max_retries: int,
) -> Dict[str, Any]:
    headers = {
        "User-Agent": "shanghai-poi-generator/1.0 (offline-first build script)",
        "Accept": "application/json",
    }
    backoff_s = 2.0
    last_err: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        if rate_limit_sleep_s > 0:
            time.sleep(rate_limit_sleep_s)
        try:
            resp = requests.post(overpass_url, data={"data": query}, headers=headers, timeout=timeout_s)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 502, 503, 504):
                eprint(
                    f"[warn] Overpass HTTP {resp.status_code} (attempt {attempt}/{max_retries}); "
                    f"backing off {backoff_s:.1f}s"
                )
                time.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.8, 30.0)
                continue
            resp.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            eprint(
                f"[warn] Overpass request failed (attempt {attempt}/{max_retries}): {exc}; backing off {backoff_s:.1f}s"
            )
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 1.8, 30.0)

    raise RuntimeError(f"Overpass request failed after {max_retries} attempts: {last_err}")


def build_poi_query_bbox(bbox: Tuple[float, float, float, float], timeout_s: int) -> str:
    s, w, n, e = bbox
    # Keep this fairly strict to reduce noise:
    # - name:zh required
    # - wikidata or wikipedia required
    # - categories constrained
    return f"""
[out:json][timeout:{timeout_s}];
(
  // tourism=attraction is very noisy inside theme parks (rides use attraction=*). Exclude those.
  node({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];

  node({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];

  node({s},{w},{n},{e})["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];

  node({s},{w},{n},{e})["name:zh"]["wikidata"]["man_made"="tower"];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["man_made"="tower"];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["man_made"="tower"];

  node({s},{w},{n},{e})["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];

  node({s},{w},{n},{e})["name:zh"]["wikidata"]["amenity"="place_of_worship"];
  way({s},{w},{n},{e})["name:zh"]["wikidata"]["amenity"="place_of_worship"];
  relation({s},{w},{n},{e})["name:zh"]["wikidata"]["amenity"="place_of_worship"];

  node({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];
  way({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];
  relation({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];

  node({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  way({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  relation({s},{w},{n},{e})["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
);
out tags center;
""".strip()


def build_poi_query_area(timeout_s: int) -> str:
    return f"""
[out:json][timeout:{timeout_s}];
(
  area["boundary"="administrative"]["admin_level"="4"]["name"="Shanghai"];
  area["boundary"="administrative"]["admin_level"="4"]["name"="上海市"];
  area["boundary"="administrative"]["name"="Shanghai"];
  area["boundary"="administrative"]["name"="上海市"];
)->.searchArea;
(
  node(area.searchArea)["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];
  way(area.searchArea)["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];
  relation(area.searchArea)["name:zh"]["wikidata"]["tourism"="attraction"]["attraction"!~"."];

  node(area.searchArea)["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  way(area.searchArea)["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  relation(area.searchArea)["name:zh"]["wikidata"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];

  node(area.searchArea)["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];
  way(area.searchArea)["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];
  relation(area.searchArea)["name:zh"]["wikidata"]["leisure"~"^(park|garden)$"];

  node(area.searchArea)["name:zh"]["wikidata"]["man_made"="tower"];
  way(area.searchArea)["name:zh"]["wikidata"]["man_made"="tower"];
  relation(area.searchArea)["name:zh"]["wikidata"]["man_made"="tower"];

  node(area.searchArea)["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];
  way(area.searchArea)["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];
  relation(area.searchArea)["name:zh"]["wikidata"]["historic"~"^(monument|memorial|archaeological_site)$"];

  node(area.searchArea)["name:zh"]["wikidata"]["amenity"="place_of_worship"];
  way(area.searchArea)["name:zh"]["wikidata"]["amenity"="place_of_worship"];
  relation(area.searchArea)["name:zh"]["wikidata"]["amenity"="place_of_worship"];

  node(area.searchArea)["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];
  way(area.searchArea)["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];
  relation(area.searchArea)["name:zh"]["wikipedia"]["tourism"="attraction"]["attraction"!~"."];

  node(area.searchArea)["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  way(area.searchArea)["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
  relation(area.searchArea)["name:zh"]["wikipedia"]["tourism"~"^(museum|zoo|theme_park|gallery|viewpoint)$"];
);
out tags center;
""".strip()


def elem_center(el: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    lat = el.get("lat")
    lon = el.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    center = el.get("center")
    if isinstance(center, dict):
        clat = center.get("lat")
        clon = center.get("lon")
        if isinstance(clat, (int, float)) and isinstance(clon, (int, float)):
            return float(clat), float(clon)
    return None


def generate_pois(
    overpass_json: Dict[str, Any],
    *,
    limit: int,
    dedupe_by_name: bool,
    require_cjk: bool,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    def has_cjk(text: str) -> bool:
        # Simple CJK Unified Ideographs range check is enough for our use case.
        for ch in text:
            o = ord(ch)
            if 0x4E00 <= o <= 0x9FFF:
                return True
        return False

    for el in overpass_json.get("elements", []):
        if not isinstance(el, dict):
            continue
        typ = el.get("type")
        osm_id = el.get("id")
        if typ not in ("node", "way", "relation") or not isinstance(osm_id, int):
            continue

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        name_zh = tags.get("name:zh")
        if not isinstance(name_zh, str) or not name_zh.strip():
            continue
        name_zh = name_zh.strip()
        if require_cjk and not has_cjk(name_zh):
            continue

        center = elem_center(el)
        if not center:
            continue
        lat, lon = center

        if dedupe_by_name:
            key = name_zh
            if key in seen_names:
                continue
            seen_names.add(key)

        items.append(
            {
                "id": f"poi_osm_{typ}_{osm_id}",
                "name_zh": name_zh,
                "lat": lat,
                "lon": lon,
            }
        )

    # Stable order: name_zh, then id
    items.sort(key=lambda x: (x["name_zh"], x["id"]))
    if limit > 0:
        items = items[:limit]
    return items


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate Shanghai POI list from OSM (Overpass).")
    p.add_argument("--out", default="pois_shanghai_generated.json", help="Output POIs JSON list.")
    p.add_argument("--raw-cache", default="shanghai_pois_raw_cache.json", help="Raw Overpass response cache.")
    p.add_argument("--refresh-cache", action="store_true", help="Force refresh from Overpass.")

    p.add_argument("--overpass-url", default="https://overpass-api.de/api/interpreter", help="Overpass endpoint.")
    p.add_argument("--query-mode", choices=["bbox", "area"], default="bbox", help="Shanghai scope mode.")
    p.add_argument("--bbox", default=",".join(str(x) for x in DEFAULT_SHANGHAI_BBOX), help="south,west,north,east")
    p.add_argument("--overpass-timeout-s", type=int, default=180)
    p.add_argument("--http-timeout-s", type=float, default=240.0)
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--rate-limit-sleep-s", type=float, default=1.0)

    p.add_argument("--limit", type=int, default=120, help="Max POIs to output (0 = no limit).")
    p.add_argument("--no-dedupe-by-name", action="store_true", help="Allow duplicate name:zh entries.")
    p.add_argument(
        "--allow-non-cjk-name-zh",
        action="store_true",
        help="Allow name:zh values without Chinese characters (default filters them out).",
    )

    args = p.parse_args(argv)
    bbox = parse_bbox(args.bbox)
    dedupe = not args.no_dedupe_by_name
    require_cjk = not args.allow_non_cjk_name_zh

    raw: Optional[Dict[str, Any]] = None
    if not args.refresh_cache:
        try:
            cached = load_json(args.raw_cache)
            if isinstance(cached, dict) and "elements" in cached:
                raw = cached
                eprint(f"[info] Loaded raw cache: {args.raw_cache}")
        except FileNotFoundError:
            pass
        except Exception as exc:
            eprint(f"[warn] Failed to read raw cache '{args.raw_cache}': {exc} (will re-fetch)")

    if raw is None:
        eprint("[info] Fetching POIs from Overpass...")
        q = build_poi_query_area(args.overpass_timeout_s) if args.query_mode == "area" else build_poi_query_bbox(bbox, args.overpass_timeout_s)
        raw = overpass_post(
            args.overpass_url,
            q,
            rate_limit_sleep_s=args.rate_limit_sleep_s,
            timeout_s=args.http_timeout_s,
            max_retries=args.max_retries,
        )
        dump_json(args.raw_cache, raw, utf8_bom=False)
        eprint(f"[info] Wrote raw cache: {args.raw_cache}")

    pois = generate_pois(raw, limit=args.limit, dedupe_by_name=dedupe, require_cjk=require_cjk)
    dump_json(args.out, pois, utf8_bom=True)
    eprint(f"[info] Wrote POIs: {args.out} (count={len(pois)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
