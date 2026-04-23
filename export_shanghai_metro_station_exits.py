#!/usr/bin/env python3
"""
Export all Shanghai metro stations and all their exits (OSM subway_entrance nodes) using Overpass API.

What this script does:
1) Fetch all entrance/exit nodes: node["railway"="subway_entrance"] within Shanghai bbox/area.
2) Fetch all subway stations (nodes/ways/relations), using center for non-node geometries.
3) Assign each entrance to its nearest station within a configurable radius.
4) Write a clean JSON for embedding into an offline-first frontend.

Output JSON shape (by default):
{
  "陆家嘴": {
    "station": {"name": "陆家嘴", "lat": 31.2401, "lon": 121.4970},
    "exits": [
      {"id": 2703743734, "ref": "1", "display": "Exit 1", "lat": 31.2407, "lon": 121.4971}
    ]
  }
}

Notes:
- OSM data quality varies: many entrances only have ref/name like "1", and no direct station tag.
  This script infers station membership via nearest-station association.
- Caches are written as plain UTF-8 (no BOM). Final output is UTF-8 with BOM for Windows readability.
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


# Format: south, west, north, east
DEFAULT_SHANGHAI_BBOX: Tuple[float, float, float, float] = (30.67, 120.85, 31.87, 122.12)


@dataclass(frozen=True)
class Entrance:
    osm_id: int
    lat: float
    lon: float
    ref: str
    display: str


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def parse_bbox(s: str) -> Tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have 4 comma-separated numbers: south,west,north,east")
    south, west, north, east = (float(x) for x in parts)
    return south, west, north, east


def build_entrance_query_bbox(bbox: Tuple[float, float, float, float], timeout_s: int) -> str:
    south, west, north, east = bbox
    return f"""
[out:json][timeout:{timeout_s}];
node["railway"="subway_entrance"]({south},{west},{north},{east});
out body;
""".strip()


def build_entrance_query_area(timeout_s: int) -> str:
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


def build_station_query_bbox(bbox: Tuple[float, float, float, float], timeout_s: int) -> str:
    south, west, north, east = bbox
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


def build_station_query_area(timeout_s: int) -> str:
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
        "User-Agent": "shanghai-metro-export/1.0 (offline-first build script)",
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
                f"[warn] Overpass request failed (attempt {attempt}/{max_retries}): {exc}; "
                f"backing off {backoff_s:.1f}s"
            )
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 1.8, 30.0)

    raise RuntimeError(f"Overpass request failed after {max_retries} attempts: {last_err}")


def load_json(path: str) -> Any:
    with open(path, "rb") as f:
        raw = f.read()
    last_exc: Optional[Exception] = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(raw.decode(enc))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise ValueError(f"Failed to decode JSON file '{path}' as utf-8/utf-8-sig/gbk: {last_exc}")


def dump_json(path: str, obj: Any, *, utf8_bom: bool) -> None:
    encoding = "utf-8-sig" if utf8_bom else "utf-8"
    with open(path, "w", encoding=encoding) as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def parse_entrances(overpass_json: Dict[str, Any]) -> List[Entrance]:
    entrances: List[Entrance] = []
    for el in overpass_json.get("elements", []):
        if not isinstance(el, dict) or el.get("type") != "node":
            continue
        osm_id = el.get("id")
        lat = el.get("lat")
        lon = el.get("lon")
        if not isinstance(osm_id, int) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}

        ref = tags.get("ref") or tags.get("local_ref") or "Unknown Exit"
        if not isinstance(ref, str) or not ref.strip():
            ref = "Unknown Exit"

        display = "Unknown Exit" if ref == "Unknown Exit" else f"Exit {ref}"
        entrances.append(Entrance(osm_id=osm_id, lat=float(lat), lon=float(lon), ref=ref, display=display))

    return entrances


def parse_stations(overpass_json: Dict[str, Any]) -> List[Station]:
    stations: List[Station] = []
    for el in overpass_json.get("elements", []):
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

        name = tags.get("name:zh") or tags.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        stations.append(Station(name=name.strip(), lat=float(lat), lon=float(lon)))

    return stations


def assign_entrances_to_stations(
    entrances: Iterable[Entrance],
    stations: List[Station],
    *,
    max_assign_m: float,
) -> Tuple[Dict[str, List[Entrance]], List[Entrance]]:
    by_station: Dict[str, List[Entrance]] = {}
    unassigned: List[Entrance] = []

    if not stations:
        return by_station, list(entrances)

    for ent in entrances:
        best: Optional[Station] = None
        best_d = 0.0
        for st in stations:
            d = haversine_m(ent.lat, ent.lon, st.lat, st.lon)
            if best is None or d < best_d:
                best = st
                best_d = d

        if best is None or best_d > max_assign_m:
            unassigned.append(ent)
            continue

        by_station.setdefault(best.name, []).append(ent)

    return by_station, unassigned


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Export Shanghai metro stations and their exits from OSM via Overpass.")
    p.add_argument("--out", default="shanghai_metro_station_exits.json", help="Output JSON path.")

    p.add_argument("--overpass-url", default="https://overpass-api.de/api/interpreter", help="Overpass endpoint.")
    p.add_argument("--query-mode", choices=["bbox", "area"], default="bbox", help="Query mode for Shanghai scope.")
    p.add_argument("--bbox", default=",".join(str(x) for x in DEFAULT_SHANGHAI_BBOX), help="south,west,north,east")
    p.add_argument("--overpass-timeout-s", type=int, default=180, help="Overpass QL timeout seconds.")
    p.add_argument("--http-timeout-s", type=float, default=240.0, help="HTTP request timeout seconds.")
    p.add_argument("--max-retries", type=int, default=6, help="Overpass request retry count.")
    p.add_argument("--rate-limit-sleep-s", type=float, default=1.0, help="Sleep before each Overpass attempt.")

    p.add_argument("--entrance-cache", default="shanghai_subway_entrances_cache.json", help="Entrances raw cache.")
    p.add_argument("--station-cache", default="shanghai_subway_stations_cache.json", help="Stations raw cache.")
    p.add_argument("--refresh-entrance-cache", action="store_true", help="Re-fetch entrances.")
    p.add_argument("--refresh-station-cache", action="store_true", help="Re-fetch stations.")

    p.add_argument(
        "--max-assign-m",
        type=float,
        default=800.0,
        help="Max distance to associate an exit to its nearest station (meters).",
    )
    p.add_argument(
        "--include-unassigned",
        action="store_true",
        help="Include an _unassigned bucket in output for exits that couldn't be matched to a station.",
    )

    args = p.parse_args(argv)
    bbox = parse_bbox(args.bbox)

    # Entrances
    entrances_json: Optional[Dict[str, Any]] = None
    if not args.refresh_entrance_cache:
        try:
            cached = load_json(args.entrance_cache)
            if isinstance(cached, dict) and "elements" in cached:
                entrances_json = cached
                eprint(f"[info] Loaded entrances cache: {args.entrance_cache}")
        except FileNotFoundError:
            pass
        except Exception as exc:
            eprint(f"[warn] Failed to read entrances cache '{args.entrance_cache}': {exc} (will re-fetch)")

    if entrances_json is None:
        eprint("[info] Fetching subway entrances from Overpass...")
        q = build_entrance_query_area(args.overpass_timeout_s) if args.query_mode == "area" else build_entrance_query_bbox(bbox, args.overpass_timeout_s)
        entrances_json = overpass_post(
            args.overpass_url,
            q,
            rate_limit_sleep_s=args.rate_limit_sleep_s,
            timeout_s=args.http_timeout_s,
            max_retries=args.max_retries,
        )
        dump_json(args.entrance_cache, entrances_json, utf8_bom=False)
        eprint(f"[info] Wrote entrances cache: {args.entrance_cache}")

    entrances = parse_entrances(entrances_json)
    eprint(f"[info] Entrances parsed: {len(entrances)}")

    # Stations
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
            eprint(f"[warn] Failed to read stations cache '{args.station_cache}': {exc} (will re-fetch)")

    if stations_json is None:
        eprint("[info] Fetching subway stations from Overpass...")
        q = build_station_query_area(args.overpass_timeout_s) if args.query_mode == "area" else build_station_query_bbox(bbox, args.overpass_timeout_s)
        stations_json = overpass_post(
            args.overpass_url,
            q,
            rate_limit_sleep_s=args.rate_limit_sleep_s,
            timeout_s=args.http_timeout_s,
            max_retries=args.max_retries,
        )
        dump_json(args.station_cache, stations_json, utf8_bom=False)
        eprint(f"[info] Wrote stations cache: {args.station_cache}")

    stations = parse_stations(stations_json)
    eprint(f"[info] Stations parsed: {len(stations)}")

    by_station, unassigned = assign_entrances_to_stations(entrances, stations, max_assign_m=args.max_assign_m)
    eprint(f"[info] Assigned entrances: {sum(len(v) for v in by_station.values())}")
    eprint(f"[info] Unassigned entrances: {len(unassigned)} (max_assign_m={args.max_assign_m:.0f}m)")

    # Build station lookup for output station center
    station_lookup: Dict[str, Station] = {}
    for st in stations:
        # If duplicates exist, keep the first; we merge exits by name.
        station_lookup.setdefault(st.name, st)

    out: Dict[str, Any] = {}
    for st_name, exits in by_station.items():
        st = station_lookup.get(st_name)
        if st is None:
            # Shouldn't happen, but keep output consistent.
            st_obj = {"name": st_name, "lat": None, "lon": None}
        else:
            st_obj = {"name": st.name, "lat": st.lat, "lon": st.lon}

        # Sort exits for stable output: numeric refs first, then lexicographic.
        def sort_key(ent: Entrance) -> Tuple[int, str, int]:
            if ent.ref.isdigit():
                return (0, f"{int(ent.ref):06d}", ent.osm_id)
            return (1, ent.ref, ent.osm_id)

        exits_sorted = sorted(exits, key=sort_key)
        out[st_name] = {
            "station": st_obj,
            "exits": [
                {"id": e.osm_id, "ref": e.ref, "display": e.display, "lat": e.lat, "lon": e.lon} for e in exits_sorted
            ],
        }

    if args.include_unassigned:
        out["_unassigned"] = {
            "station": {"name": "_unassigned", "lat": None, "lon": None},
            "exits": [{"id": e.osm_id, "ref": e.ref, "display": e.display, "lat": e.lat, "lon": e.lon} for e in unassigned],
        }

    dump_json(args.out, out, utf8_bom=True)
    eprint(f"[info] Wrote output: {args.out} (stations={len(by_station)}, exits={len(entrances)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

