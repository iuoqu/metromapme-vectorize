# Shanghai Metro Vectorize

Automated pipeline to convert `Shanghai Metro Network Map.pdf` into an
interactive vector schematic: clean SVG + structured JSON + a React component
that can highlight routes.

---

## Quick start

```bash
# 1. Extract (Python)
pip install pymupdf
python3 scripts/extract.py

# 2. Demo (Node ≥ 18, pnpm recommended)
pnpm install
pnpm dev          # opens localhost:5173
```

---

## Pipeline: `scripts/extract.py`

```
Shanghai Metro Network Map.pdf
        │
        ▼
scripts/extract.py
        │
        ├── public/shanghai-metro.svg          full-fidelity SVG render
        ├── public/shanghai-metro-overlay.svg  transparent station circles
        ├── public/stations.json               line / station / branch data
        ├── public/transfers.json              auto-clustered transfer groups
        └── transfers_review.csv               human-review CSV
```

### Debug mode

```bash
python3 scripts/extract.py --debug
```

Writes `debug/debug-overlay.svg` with station circles and sequence numbers
overlaid on the raw PDF render. Use this to verify station ordering.

---

## Output schemas

### `stations.json`

```jsonc
{
  "viewBox": [0, 0, 612, 792],   // PDF coordinate space
  "lines": [
    {
      "id": "1",
      "color": "#e81a38",
      "trunk": ["01-01", "01-02", "…"],
      "branches": {
        // only present for branching lines
        "B": { "fork_at": "10-18", "stations": ["10-B01", "…"] }
      }
    }
  ],
  "stations": {
    "01-09": { "line": "1", "x": 240.5, "y": 411.3, "transfer_group": "T001" }
  }
}
```

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

## Station ID table

IDs are assigned left-to-right (westernmost = `LL-01`) along each line.
Map these IDs to Chinese/English names on your side after deployment.

| Line | Color     | Range            | Count |
|------|-----------|------------------|-------|
| 1    | `#e81a38` | `01-01`…`01-29`  | 29    |
| 2    | `#83c340` | `02-01`…`02-33`  | 33    |
| 3    | `#fbd004` | `03-01`…`03-31`  | 31    |
| 4    | `#9056a3` | `04-01`…`04-19`  | 19 (loop) |
| 5    | `#b8a4c9` | `05-01`…`05-13`  | 13    |
| 6    | `#e70a6f` | `06-01`…`06-28`  | 28    |
| 7    | `#f47121` | `07-01`…`07-34`  | 34    |
| 8    | `#009dd8` | `08-01`…`08-31`  | 31    |
| 9    | `#7ac7ea` | `09-01`…`09-23`  | 23    |
| 10   | `#bca7d0` | `10-01`…`10-13`  | 13    |
| 11   | `#7e2130` | `11-01`…`11-38`  | 38    |
| 12   | `#007a64` | `12-01`…`12-33`  | 33    |
| 13   | `#e694c0` | `13-01`…`13-33`  | 33    |
| 14   | `#8ed1c1` | `14-01`…`14-13`  | 13    |
| 15   | `#a8a9ad` | `15-01`…`15-06`  | 6     |
| 16   | `#2d7977` | sparse           | 1     |
| 17   | `#b87875` | sparse           | 1     |
| 18   | `#4e2d8b` | `18-01`…`18-19`  | 19    |

> **Note:** Lines 16 and 17 have very few colored marker shapes in this PDF
> version; they may need manual coordinate entry via `scripts/line_overrides.yaml`.

**Transfer groups:** 60 groups auto-detected.  
Review `transfers_review.csv` to catch false merges (cluster diameter > 8 pt)
or missed merges (physically overlapping stations in different groups).

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
| `baseUrl` | `string` | URL prefix for SVG/JSON assets (default: `"/"`) |
| `highlightedStations` | `StationId[]` | Station IDs to highlight |
| `highlightedSegments` | `Segment[]` | `{from, to, line}` segments to highlight |
| `stationLabels` | `Record<StationId, string>` | Optional display labels for tooltip |
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

The schematic reads assets from `baseUrl`. Copy `public/` to wherever your
server serves static files and set `baseUrl` accordingly.
