# Shanghai Metro Vectorize

Automated pipeline to convert Shanghai Metro PDFs into an interactive vector
schematic: clean SVG + structured JSON + a React component that can highlight
routes.

Two source PDFs are supported, with separate pipelines:

| Version | Source PDF | Key difference |
|---------|-----------|-----------------|
| **v1** (legacy) | `Shanghai Metro Network Map.pdf` (612×792 pt) | Text is rasterised; only IDs available |
| **v2** (default) | `metro.pdf` (5348×7213 pt) | Real text — extracts Chinese + English station names |

---

## Quick start

```bash
# 1. Extract (Python)
pip install pymupdf
python3 scripts/extract_v2.py    # primary — gives station names
python3 scripts/extract.py       # legacy — IDs only, kept for reference

# 2. Demo (Node ≥ 18)
npm install
npm run dev                      # opens localhost:5173
```

The demo's top-left buttons toggle between v1/v2.

---

## Pipelines

### `scripts/extract_v2.py` — recommended

Reads `metro.pdf` and writes:

```
public/v2/
  ├── shanghai-metro.svg          full vector render of the PDF
  ├── shanghai-metro-overlay.svg  transparent overlay with station circles
  ├── stations.json               lines + stations w/ name_en + name_zh
  ├── transfers.json              auto-clustered transfer groups
  └── transfers_review.csv        diameter & names for human review
```

Key techniques used:
- Line colours auto-detected from coloured `re` badges behind each "Line N" text label
- Station labels paired EN↔ZH via mutual-best-match on row centre-Y
- Stations snapped to closest line polyline; transfers detected by checking
  whether other line polylines pass through the snap point

### `scripts/extract.py` — legacy

Reads the older `Shanghai Metro Network Map.pdf`. No text in source, so
stations are detected geometrically and IDs are emitted without names.
Outputs to `public/v1/`.

### Debug mode

```bash
python3 scripts/extract.py --debug
```

Writes `debug/debug-overlay.svg` with station circles and sequence numbers
overlaid on the raw PDF render. Use this to verify station ordering.

---

## Output schemas

### `stations.json` (v2)

```jsonc
{
  "viewBox": [0, 0, 5348, 7213],   // PDF coordinate space
  "lines": [
    {
      "id": "1",
      "label": "Line 1",
      "color": "#e20229",
      "trunk": ["01-01", "01-02", "…"],
      "branches": {}
    }
  ],
  "stations": {
    "01-09": {
      "line": "1",
      "x": 2345.4, "y": 3253.0,
      "name_en": "Xujiahui",
      "name_zh": "徐家汇",
      "transfer_group": "T012"
    }
  }
}
```

The v1 schema is the same, minus the `name_en`/`name_zh`/`label` fields.

### `transfers.json`

```jsonc
[
  {
    "group_id": "T001",
    "station_ids": ["01-09", "04-05", "09-15"],
    "center_x": 241.0,
    "center_y": 411.2
  }
]
```

---

## Station / line table (v2 — current run)

IDs are assigned left-to-right (westernmost = `LL-01`) along each line.
v2 includes Chinese + English names directly (no manual mapping needed).

| Line | Color | Endpoints (EN / ZH) | Count |
|------|-------|---------------------|-------|
| Line 1  | `#e20229` | Xinzhuang → Hanzhong Rd. | 25 |
| Line 2  | `#8bc21f` | Songhong Rd. → 蟠龙路 | 31 |
| Line 3  | `#fdd700` | Caoxi Rd. → 长江南路 | 32 |
| Line 4  | `#461d85` | Shanghai Indoor Stadium → World Expo Museum | 27 |
| Line 5  | `#964b9b` | Wenjing Rd. → Xinzhuang | 18 |
| Line 6  | `#e20169` | Pudian Rd. → Gangcheng Rd. | 22 |
| Line 7  | `#ec6e00` | Huamu Rd. → Fengxiang Rd. | 40 |
| Line 8  | `#0095da` | Anshan Xincun → Oriental Sports Center | 22 |
| Line 9  | `#87c9ec` | Qibao → Yishan Rd. | 24 |
| Line 10 | `#c6afd3` | Shuangjiang Rd. → Terminal 2 | 32 |
| Line 11 | `#861a2a` | Zhaofeng Rd. → Zhenru | 28 |
| Line 12 | `#00785f` | Fuxing Island → Hongxin Rd. | 28 |
| Line 13 | `#e899c0` | Xia'nan Rd. → Qilianshan Rd. (S) | 25 |
| Line 14 | `#626020` | Stadium → Taierzhuang Rd. | 33 |
| Line 15 | `#cab08d` | Luoxiu Rd. → Guilin Rd. | 18 |
| Line 16 | `#98d1c0` | Xinchang → Dishui Lake | 17 |
| Line 17 | `#bc7970` | Station → 国家会展中心 | 10 |
| Line 18 | `#c4984f` | 长江南路 → Yuqiao | 35 |
| Pujiang Line | `#ef7002` | 8 stations | 8 |

**Total:** 467 stations across 19 lines, 54 transfer groups auto-detected.

> **Known limitations of v2 extraction:**
> - Several lines (esp. 6, 8, 11, 13, 15) under-count due to stations near
>   line crossings being assigned to the wrong line.
> - A handful of lines slightly over-count when polyline merging fragments.
> - Transfer detection uses snap-point coincidence; some real transfers may
>   be missed if the polylines don't quite intersect.
>
> Audit by opening `transfers_review.csv` and the demo. The
> `transfer_group` field on each station and the cluster diameter help find
> false positives quickly.

---

## React component

```tsx
import MetroSchematic, {
  MetroSchematicHandle,
  StationId,
} from "./src/MetroSchematic";

// Declarative highlight
<MetroSchematic
  highlightedStations={["01-09", "04-05", "04-06"]}
  onStationClick={(id) => console.log(id)}
/>

// Imperative highlight (e.g. from your routing engine)
const ref = useRef<MetroSchematicHandle>(null);
ref.current?.highlightRoute(["01-01", "01-09", "04-05", "04-08"]);
ref.current?.clearHighlight();
ref.current?.focusStation("01-09");
```

### Props

| Prop | Type | Description |
|------|------|-------------|
| `baseUrl` | `string` | URL prefix for SVG/JSON assets (default: `"/v2/"`; use `"/v1/"` for the legacy dataset) |
| `highlightedStations` | `StationId[]` | Station IDs to highlight |
| `highlightedSegments` | `Segment[]` | `{from, to, line}` segments to highlight |
| `stationLabels` | `Record<StationId, string>` | Optional override for tooltip labels (otherwise tooltip shows `name_en` + `name_zh` from stations.json) |
| `onStationClick` | `(id) => void` | Click callback |
| `onStationHover` | `(id \| null) => void` | Hover callback |

### Imperative handle

| Method | Description |
|--------|-------------|
| `highlightRoute(ids)` | Highlights stations + all in-between stations on shared lines |
| `clearHighlight()` | Removes all highlights |
| `focusStation(id)` | Pans and zooms to center a station |

---

## Integration with your routing tool

Your existing lat/lon routing engine produces a list of station IDs. Pass them
directly to the schematic:

```tsx
// In your RouteResult component:
const schRef = useRef<MetroSchematicHandle>(null);

useEffect(() => {
  if (route?.stationIds) {
    schRef.current?.highlightRoute(route.stationIds);
  }
}, [route]);

return (
  <div style={{ display: "flex" }}>
    <RealMapView route={route} />
    <MetroSchematic ref={schRef} baseUrl="/metro-assets" />
  </div>
);
```

The schematic reads assets from `baseUrl`. Copy `public/v2/` (or `public/v1/`)
to wherever your server serves static files and set `baseUrl` accordingly.

---

## OSM Metro Exits (Shanghai)

This repo also includes a small, offline-first build step to fetch Shanghai metro entrances/exits from OpenStreetMap via Overpass and export JSON for embedding into an app.

### Export all stations + exits

```powershell
python .\export_shanghai_metro_station_exits.py --out .\shanghai_metro_station_exits.json
```

Options:
- `--max-assign-m 800`: max distance to associate an exit to its nearest station (meters)
- `--include-unassigned`: include an `_unassigned` bucket for exits that could not be matched to a station
- `--refresh-entrance-cache` / `--refresh-station-cache`: force refresh from Overpass

### Map POIs to nearest exit

```powershell
python .\map_pois_to_metro_exits.py --pois .\pois_example.json --out .\poi_to_metro_exit.json
```

Notes:
- Output JSON is written as UTF-8 with BOM for PowerShell readability.
- Caches are written as plain UTF-8 (no BOM).
