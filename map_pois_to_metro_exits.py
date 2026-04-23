#!/usr/bin/env python3
"""
Map POIs to their closest Shanghai metro entrances/exits using Overpass API.

Example input POIs JSON (list):
[
  {"id": "poi_001", "name_zh": "陆家嘴三件套", "lat": 31.2363, "lon": 121.5031},
  {"id": "poi_002", "name_zh": "外滩万国建筑群", "lat": 31.2397, "lon": 121.4896}
]

Output JSON (dict keyed by POI id):
{
  "poi_001": {
    "name": {"zh": "陆家嘴三件套"},
    "anchor_station": "Station Name (from Overpass)",
    "best_exit": "Exit X (from Overpass 'ref')",
    "walk_distance_m": 400,
    "walk_time_min": 6
  }
}

Notes:
- Overpass nodes may miss tags like "ref" (exit number) or "station". We fall back gracefully.
- For offline-first workflows, use --entrance-cache to persist the downloaded entrances.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


# A generous bbox covering Shanghai municipality (including some surrounding water).
# Format: south, west, north, east
DEFAULT_SHANGHAI_BBOX: Tuple[float, float, float, float] = (30.67, 120.85, 31.87, 122.12)


@dataclass(frozen=True)
class Entrance:
    lat: float
    lon: float
    station_name: str
    exit_ref: str  # raw ref/local_ref (may be "Unknown Exit")


@dataclass(frozen=True)
class Station:
    lat: float
    lon: float
    name: str


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two points on Earth in meters.
    """
    r = 6371000.0  # mean Earth radius (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def build_overpass_query(bbox: Tuple[float, float, float, float], timeout_s: int) -> str:
    south, west, north, east = bbox
    # Required logic: node["railway"="subway_entrance"] within Shanghai bbox/area.
    return f"""
[out:json][timeout:{timeout_s}];
node["railway"="subway_entrance"]({south},{west},{north},{east});
out body;
""".strip()


def build_overpass_query_area(timeout_s: int) -> str:
    """
    Try to resolve Shanghai administrative area and query entrances inside it.
    This is optional because area matching can be brittle across OSM tag variations.
    """
    # Overpass "area" objects are derived from relations/ways; boundary tagging varies.
    # We union a couple of common variants (English + Chinese names).
    return f"""
[out:json][timeout:{timeout_s}];
(
  area["boundary"="administrative"]["admin_level"="4"]["name"="Shanghai"];
  area["boundary"="administrative"]["admin_level"="4"]["name"="上海市"];
  area["boundary"="administrative"]["name"="Shanghai"];
  area["boundary"="administrative"]["name"="上海市"];
)->.searchArea;
node["railway"="subway_entrance"](area.searchArea);
out body;
""".strip()


def build_overpass_station_query_bbox(bbox: Tuple[float, float, float, float], timeout_s: int) -> str:
    south, west, north, east = bbox
    # Stations can be tagged using railway=station or public_transport=station (nodes/ways/relations).
    # We request "center" for non-node geometries so we still have a representative coordinate.
    return f"""
[out:json][timeout:{timeout_s}];
(
  node["railway"="station"]["station"="subway"]({south},{west},{north},{east});
  node["railway"="station"]["subway"="yes"]({south},{west},{north},{east});
  node["public_transport"="station"]["station"="subway"]({south},{west},{north},{east});
  node["public_transport"="station"]["subway"="yes"]({south},{west},{north},{east});
  way["railway"="station"]["station"="subway"]({south},{west},{north},{east});
  way["public_transport"="station"]["station"="subway"]({south},{west},{north},{east});
  relation["railway"="station"]["station"="subway"]({south},{west},{north},{east});
  relation["public_transport"="station"]["station"="subway"]({south},{west},{north},{east});
);
out tags center;
""".strip()


def build_overpass_station_query_area(timeout_s: int) -> str:
    # Same as bbox version but constrained to Shanghai administrative area.
    return f"""
[out:json][timeout:{timeout_s}];
(
  area["boundary"="administrative"]["admin_level"="4"]["name"="Shanghai"];
  area["boundary"="administrative"]["admin_level"="4"]["name"="上海市"];
  area["boundary"="administrative"]["name"="Shanghai"];
  area["boundary"="administrative"]["name"="上海市"];
)->.searchArea;
(
  node["railway"="station"]["station"="subway"](area.searchArea);
  node["railway"="station"]["subway"="yes"](area.searchArea);
  node["public_transport"="station"]["station"="subway"](area.searchArea);
  node["public_transport"="station"]["subway"="yes"](area.searchArea);
  way["railway"="station"]["station"="subway"](area.searchArea);
  way["public_transport"="station"]["station"="subway"](area.searchArea);
  relation["railway"="station"]["station"="subway"](area.searchArea);
  relation["public_transport"="station"]["station"="subway"](area.searchArea);
);
out tags center;
""".strip()


def overpass_post(
    overpass_url: str,
    query: str,
    *,
    rate_limit_sleep_s: float,
    timeout_s: float,
    max_retries: int,
) -> Dict[str, Any]:
    headers = {
        # Please include contact info if you deploy this widely.
        "User-Agent": "shanghai-metro-poi-mapper/1.0 (offline-first data build script)",
        "Accept": "application/json",
    }

    backoff_s = 2.0
    last_err: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        if rate_limit_sleep_s > 0:
            time.sleep(rate_limit_sleep_s)

        try:
            # Overpass accepts the query in a form field named "data".
            resp = requests.post(
                overpass_url,
                data={"data": query},
                headers=headers,
                timeout=timeout_s,
            )

            if resp.status_code == 200:
                return resp.json()

            # Retry common transient / rate-limit responses.
            if resp.status_code in (429, 502, 503, 504):
                eprint(
                    f"[warn] Overpass returned HTTP {resp.status_code} (attempt {attempt}/{max_retries}); "
                    f"backing off {backoff_s:.1f}s"
                )
                time.sleep(backoff_s)
                backoff_s = min(backoff_s * 1.8, 30.0)
                continue

            # Non-retriable response.
            resp.raise_for_status()

        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            eprint(
                f"[warn] Overpass request failed (attempt {attempt}/{max_retries}): {exc}; "
                f"backing off {backoff_s:.1f}s"
            )
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 1.8, 30.0)

    raise RuntimeError(f"Overpass request failed after {max_retries} attempts: {last_err}")


def parse_entrances(overpass_json: Dict[str, Any]) -> List[Entrance]:
    elements = overpass_json.get("elements", [])
    entrances: List[Entrance] = []

    for el in elements:
        if not isinstance(el, dict) or el.get("type") != "node":
            continue

        lat = el.get("lat")
        lon = el.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}

        # Prefer actual human-readable name tags. The "station" tag is sometimes an id/code (can be numeric),
        # so keep it as a lower-priority fallback.
        station_name = (
            tags.get("name:zh")
            or tags.get("name")
            or tags.get("station:zh")
            or tags.get("station")
            or "Unknown Station"
        )
        if not isinstance(station_name, str) or not station_name.strip():
            station_name = "Unknown Station"

        # Exit number is typically ref; sometimes local_ref.
        exit_ref = tags.get("ref") or tags.get("local_ref") or "Unknown Exit"
        if not isinstance(exit_ref, str) or not exit_ref.strip():
            exit_ref = "Unknown Exit"

        entrances.append(Entrance(lat=float(lat), lon=float(lon), station_name=station_name, exit_ref=exit_ref))

    return entrances


def parse_stations(overpass_json: Dict[str, Any]) -> List[Station]:
    elements = overpass_json.get("elements", [])
    stations: List[Station] = []

    for el in elements:
        if not isinstance(el, dict):
            continue

        lat = el.get("lat")
        lon = el.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            center = el.get("center") if isinstance(el.get("center"), dict) else None
            if center:
                lat = center.get("lat")
                lon = center.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}

        name = tags.get("name:zh") or tags.get("name") or "Unknown Station"
        if not isinstance(name, str) or not name.strip():
            name = "Unknown Station"
        if name == "Unknown Station":
            continue

        stations.append(Station(lat=float(lat), lon=float(lon), name=name))

    return stations


def station_name_needs_infer(name: str) -> bool:
    if not isinstance(name, str):
        return True
    s = name.strip()
    if not s or s == "Unknown Station":
        return True
    # A lot of entrances in Shanghai are tagged with name/ref as exit number only (e.g. "1", "7").
    if s.isdigit():
        return True
    return False


def infer_station_for_entrances(
    entrances: List[Entrance],
    stations: List[Station],
    *,
    max_entrance_to_station_m: float,
) -> List[Entrance]:
    if not stations:
        return entrances

    enriched: List[Entrance] = []
    for ent in entrances:
        if not station_name_needs_infer(ent.station_name):
            enriched.append(ent)
            continue

        best_station: Optional[Station] = None
        best_d: float = 0.0
        for st in stations:
            d = haversine_m(ent.lat, ent.lon, st.lat, st.lon)
            if best_station is None or d < best_d:
                best_station = st
                best_d = d

        if best_station is not None and best_d <= max_entrance_to_station_m:
            enriched.append(Entrance(lat=ent.lat, lon=ent.lon, station_name=best_station.name, exit_ref=ent.exit_ref))
        else:
            enriched.append(ent)

    return enriched


def load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    # Be robust to common Windows encodings (UTF-8 without BOM, UTF-8 with BOM, GBK/ANSI).
    with open(path, "rb") as f:
        raw = f.read()
    last_exc: Optional[Exception] = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(raw.decode(enc))
        except Exception as exc:  # noqa: BLE001 - keep this build script resilient
            last_exc = exc
    raise ValueError(f"Failed to decode JSON file '{path}' as utf-8/utf-8-sig/gbk: {last_exc}")


def dump_json(path: str, obj: Any, *, utf8_bom: bool = False) -> None:
    # For Windows readability in tools like PowerShell Get-Content, writing BOM can help.
    # For caches, prefer plain UTF-8 (no BOM) for maximum interoperability.
    encoding = "utf-8-sig" if utf8_bom else "utf-8"
    with open(path, "w", encoding=encoding) as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def normalize_pois(pois_raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(pois_raw, list):
        raise ValueError("POIs JSON must be a list of objects.")

    pois: List[Dict[str, Any]] = []
    for i, item in enumerate(pois_raw):
        if not isinstance(item, dict):
            raise ValueError(f"POI at index {i} is not an object.")

        poi_id = item.get("id")
        name_zh = item.get("name_zh", "")
        lat = item.get("lat")
        lon = item.get("lon")

        if not isinstance(poi_id, str) or not poi_id.strip():
            raise ValueError(f"POI at index {i} is missing a non-empty string 'id'.")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise ValueError(f"POI '{poi_id}' is missing numeric 'lat'/'lon'.")
        if not isinstance(name_zh, str):
            name_zh = str(name_zh)

        pois.append({"id": poi_id, "name_zh": name_zh, "lat": float(lat), "lon": float(lon)})

    return pois


def find_closest_entrance(
    poi_lat: float,
    poi_lon: float,
    entrances: Iterable[Entrance],
) -> Optional[Tuple[Entrance, float]]:
    best_ent: Optional[Entrance] = None
    best_dist: float = 0.0

    for ent in entrances:
        d = haversine_m(poi_lat, poi_lon, ent.lat, ent.lon)
        if best_ent is None or d < best_dist:
            best_ent = ent
            best_dist = d

    if best_ent is None:
        return None
    return best_ent, best_dist


def format_best_exit(exit_ref: str) -> str:
    if exit_ref == "Unknown Exit":
        return "Unknown Exit"
    # Requirement wants "Exit X (from Overpass 'ref')".
    return f"Exit {exit_ref}"


def parse_bbox(s: str) -> Tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have 4 comma-separated numbers: south,west,north,east")
    south, west, north, east = (float(x) for x in parts)
    return south, west, north, east


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Map POIs to closest Shanghai subway exits via Overpass API.")
    p.add_argument("--pois", required=True, help="Path to POIs JSON file (or '-' for stdin).")
    p.add_argument("--out", default="poi_to_metro_exit.json", help="Output JSON path.")

    p.add_argument(
        "--overpass-url",
        default="https://overpass-api.de/api/interpreter",
        help="Overpass API interpreter endpoint.",
    )
    p.add_argument(
        "--query-mode",
        choices=["bbox", "area"],
        default="bbox",
        help="Overpass query mode: bbox (default, robust) or area (admin boundary lookup).",
    )
    p.add_argument(
        "--bbox",
        default=",".join(str(x) for x in DEFAULT_SHANGHAI_BBOX),
        help="Bounding box as 'south,west,north,east'.",
    )
    p.add_argument("--overpass-timeout-s", type=int, default=180, help="Overpass QL timeout seconds.")
    p.add_argument("--http-timeout-s", type=float, default=240.0, help="HTTP request timeout seconds.")
    p.add_argument("--max-retries", type=int, default=6, help="Overpass request retry count.")
    p.add_argument(
        "--rate-limit-sleep-s",
        type=float,
        default=1.0,
        help="Sleep before each Overpass attempt to be polite.",
    )

    p.add_argument(
        "--entrance-cache",
        default="shanghai_subway_entrances_cache.json",
        help="Cache file for fetched entrances (raw Overpass JSON).",
    )
    p.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore existing cache and re-fetch entrances from Overpass.",
    )

    p.add_argument(
        "--station-cache",
        default="shanghai_subway_stations_cache.json",
        help="Cache file for fetched stations (raw Overpass JSON).",
    )
    p.add_argument(
        "--refresh-station-cache",
        action="store_true",
        help="Ignore existing station cache and re-fetch stations from Overpass.",
    )
    p.add_argument(
        "--max-entrance-to-station-m",
        type=float,
        default=1200.0,
        help="Max distance to associate an entrance with its nearest station name.",
    )

    p.add_argument("--max-distance-m", type=float, default=1500.0, help="Skip POIs farther than this from any exit.")
    p.add_argument(
        "--walk-speed-mps",
        type=float,
        default=1.2,
        help="Walking speed in meters/second (default 1.2).",
    )

    args = p.parse_args(argv)

    pois = normalize_pois(load_json(args.pois))
    bbox = parse_bbox(args.bbox)

    # Load or fetch entrances
    overpass_json: Optional[Dict[str, Any]] = None
    if not args.refresh_cache:
        try:
            cached = load_json(args.entrance_cache)
            if isinstance(cached, dict) and "elements" in cached:
                overpass_json = cached
                eprint(f"[info] Loaded entrances cache: {args.entrance_cache}")
        except FileNotFoundError:
            pass
        except Exception as exc:
            eprint(f"[warn] Failed to read cache '{args.entrance_cache}': {exc} (will re-fetch)")

    if overpass_json is None:
        if args.query_mode == "area":
            query = build_overpass_query_area(args.overpass_timeout_s)
        else:
            query = build_overpass_query(bbox, args.overpass_timeout_s)
        eprint("[info] Fetching subway entrances from Overpass...")
        overpass_json = overpass_post(
            args.overpass_url,
            query,
            rate_limit_sleep_s=args.rate_limit_sleep_s,
            timeout_s=args.http_timeout_s,
            max_retries=args.max_retries,
        )
        dump_json(args.entrance_cache, overpass_json, utf8_bom=False)
        eprint(f"[info] Wrote entrances cache: {args.entrance_cache}")

    entrances = parse_entrances(overpass_json)
    if not entrances:
        eprint("[warn] No subway entrances found from Overpass query (bbox may be wrong).")

    # Fetch stations and enrich entrance station_name when missing / numeric.
    stations_json: Optional[Dict[str, Any]] = None
    if not args.refresh_station_cache:
        try:
            cached = load_json(args.station_cache)
            if isinstance(cached, dict) and "elements" in cached:
                stations_json = cached
                eprint(f"[info] Loaded stations cache: {args.station_cache}")
        except FileNotFoundError:
            pass
        except Exception as exc:
            eprint(f"[warn] Failed to read station cache '{args.station_cache}': {exc} (will re-fetch)")

    if stations_json is None:
        if args.query_mode == "area":
            st_query = build_overpass_station_query_area(args.overpass_timeout_s)
        else:
            st_query = build_overpass_station_query_bbox(bbox, args.overpass_timeout_s)
        eprint("[info] Fetching subway stations from Overpass (for entrance -> station name association)...")
        stations_json = overpass_post(
            args.overpass_url,
            st_query,
            rate_limit_sleep_s=args.rate_limit_sleep_s,
            timeout_s=args.http_timeout_s,
            max_retries=args.max_retries,
        )
        dump_json(args.station_cache, stations_json, utf8_bom=False)
        eprint(f"[info] Wrote stations cache: {args.station_cache}")

    stations = parse_stations(stations_json)
    if not stations:
        eprint("[warn] No subway stations found; 'anchor_station' may remain unknown or numeric.")
    else:
        entrances = infer_station_for_entrances(
            entrances,
            stations,
            max_entrance_to_station_m=args.max_entrance_to_station_m,
        )

    # Map POIs -> closest entrance
    out: Dict[str, Any] = {}
    meters_per_min = args.walk_speed_mps * 60.0

    for poi in pois:
        poi_id = poi["id"]
        name_zh = poi["name_zh"]
        lat = poi["lat"]
        lon = poi["lon"]

        best = find_closest_entrance(lat, lon, entrances)
        if best is None:
            eprint(f"[warn] {poi_id}: no entrances available to match")
            continue

        ent, dist_m = best
        if dist_m > args.max_distance_m:
            eprint(f"[warn] {poi_id}: POI too far from metro (nearest {dist_m:.0f} m > {args.max_distance_m:.0f} m)")
            continue

        walk_distance_m = int(round(dist_m))
        walk_time_min = int(round(walk_distance_m / meters_per_min)) if meters_per_min > 0 else 0

        out[poi_id] = {
            "name": {"zh": name_zh},
            "anchor_station": ent.station_name,
            "best_exit": format_best_exit(ent.exit_ref),
            "walk_distance_m": walk_distance_m,
            "walk_time_min": walk_time_min,
        }

    dump_json(args.out, out, utf8_bom=True)
    eprint(f"[info] Wrote output: {args.out} ({len(out)} POIs matched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
