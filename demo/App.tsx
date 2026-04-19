import { useRef, useState } from "react";
import MetroSchematic, {
  MetroSchematicHandle,
  StationId,
} from "@/MetroSchematic";

type Version = "v1" | "v2";

const EXAMPLE_ROUTES: Record<Version, Record<string, string>> = {
  v1: {
    "L1 partial": "01-04,01-05,01-06,01-07,01-08,01-09",
    "L2 partial": "02-10,02-11,02-12,02-13,02-14,02-15",
    "L1→L4 via transfer": "01-08,01-09,01-10,04-05,04-06,04-07",
  },
  v2: {
    "L1 partial": "01-04,01-05,01-06,01-07,01-08,01-09,01-10",
    "L2 partial": "02-10,02-11,02-12,02-13,02-14,02-15",
    "L1↔L4 transfer": "01-08,01-09,04-05,04-06",
  },
};

export default function App() {
  const schRef = useRef<MetroSchematicHandle>(null);
  const [version, setVersion] = useState<Version>("v2");
  const [inputValue, setInputValue] = useState("");
  const [highlighted, setHighlighted] = useState<StationId[]>([]);
  const [lastClicked, setLastClicked] = useState<StationId | null>(null);

  function handleHighlight() {
    const ids = inputValue
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean) as StationId[];
    setHighlighted(ids);
    schRef.current?.highlightRoute(ids);
  }

  function handleClear() {
    setInputValue("");
    setHighlighted([]);
    schRef.current?.clearHighlight();
  }

  function handleExampleClick(ids: string) {
    setInputValue(ids);
    const parsed = ids.split(",").map((s) => s.trim()) as StationId[];
    setHighlighted(parsed);
    schRef.current?.highlightRoute(parsed);
  }

  function handleStationClick(id: StationId) {
    setLastClicked(id);
    schRef.current?.focusStation(id);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* ── Control panel ── */}
      <div
        style={{
          padding: "12px 16px",
          background: "#0f0f23",
          borderBottom: "1px solid #333",
          display: "flex",
          flexWrap: "wrap",
          gap: "10px",
          alignItems: "center",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 16, color: "#e8c94a" }}>
          Shanghai Metro Schematic
        </span>

        <div style={{ display: "flex", gap: 4 }}>
          {(["v2", "v1"] as Version[]).map((v) => (
            <button
              key={v}
              onClick={() => {
                setVersion(v);
                setHighlighted([]);
                setInputValue("");
                schRef.current?.clearHighlight();
              }}
              style={btnStyle(version === v ? "#e8c94a" : "#333", {
                color: version === v ? "#000" : "#ccc",
                fontWeight: 600,
                fontSize: 11,
              })}
            >
              {v.toUpperCase()}{v === "v2" ? " (with names)" : ""}
            </button>
          ))}
        </div>

        <textarea
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Paste station IDs (e.g. 01-01,01-02,02-14)"
          rows={1}
          style={{
            flex: "1 1 280px",
            minWidth: 200,
            resize: "vertical",
            padding: "6px 10px",
            borderRadius: 4,
            border: "1px solid #555",
            background: "#1e1e3a",
            color: "#eee",
            fontFamily: "monospace",
            fontSize: 13,
          }}
        />

        <button onClick={handleHighlight} style={btnStyle("#3a7bd5")}>
          Highlight
        </button>
        <button onClick={handleClear} style={btnStyle("#555")}>
          Clear
        </button>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {Object.entries(EXAMPLE_ROUTES[version]).map(([label, ids]) => (
            <button
              key={label}
              onClick={() => handleExampleClick(ids)}
              style={btnStyle("#2a5a2a", { fontSize: 11 })}
            >
              {label}
            </button>
          ))}
        </div>

        {lastClicked && (
          <span style={{ fontSize: 12, color: "#aaa", marginLeft: "auto" }}>
            Clicked: <code style={{ color: "#fff" }}>{lastClicked}</code>
          </span>
        )}
        {highlighted.length > 0 && (
          <span style={{ fontSize: 12, color: "#aaa" }}>
            {highlighted.length} station{highlighted.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* ── Map area ── */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <MetroSchematic
          key={version}  /* force remount on version switch */
          ref={schRef}
          baseUrl={`/${version}/`}
          highlightedStations={highlighted.length > 0 ? highlighted : undefined}
          onStationClick={handleStationClick}
          style={{ width: "100%", height: "100%" }}
        />
      </div>

      {/* ── Footer hints ── */}
      <div
        style={{
          padding: "6px 16px",
          background: "#0f0f23",
          borderTop: "1px solid #333",
          fontSize: 11,
          color: "#666",
        }}
      >
        Scroll to zoom · Click and drag to pan · Click a station circle to focus
        · Hover for ID
      </div>
    </div>
  );
}

function btnStyle(
  bg: string,
  extra?: React.CSSProperties
): React.CSSProperties {
  return {
    background: bg,
    color: "#fff",
    border: "none",
    borderRadius: 4,
    padding: "6px 14px",
    cursor: "pointer",
    fontSize: 13,
    whiteSpace: "nowrap",
    ...extra,
  };
}
