# Shanghai Metro POI Exit Mapper (Offline-First Build Step)

This repo contains a lightweight Python script that maps a predefined list of POIs to their **closest** Shanghai metro entrance/exit using the **Overpass API** (OpenStreetMap).

## Files

- `map_pois_to_metro_exits.py`: main script
- `pois_example.json`: example POI input
- `requirements.txt`: Python dependency

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python .\map_pois_to_metro_exits.py --pois .\pois_example.json --out .\poi_to_metro_exit.json
```

## Behavior Notes

- Entrances are fetched via Overpass query `node["railway"="subway_entrance"]` within Shanghai (default: bbox).
- Uses Haversine distance (meters) to find the closest entrance for each POI.
- Walk time assumes `1.2 m/s` and is rounded to the nearest whole minute.
- If the nearest entrance is **strictly greater than 1500 m**, the POI is skipped and a warning is logged.
- Missing tags are handled:
  - Missing `ref` / `local_ref` -> `"Unknown Exit"`
  - Missing station tags -> `"Unknown Station"`

## Offline-First Caching

The first run writes a local cache file (default `shanghai_subway_entrances_cache.json`) so subsequent runs do not hit Overpass again.

Refresh cache:
```powershell
python .\map_pois_to_metro_exits.py --pois .\pois_example.json --refresh-cache
```

## Optional: Area Query Mode

If you prefer querying by Shanghai administrative boundary (can be more brittle than bbox depending on OSM tags):
```powershell
python .\map_pois_to_metro_exits.py --pois .\pois_example.json --query-mode area
```

