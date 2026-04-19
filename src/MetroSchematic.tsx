import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useCallback,
} from "react";
import Panzoom, { PanzoomObject } from "@panzoom/panzoom";
import "./MetroSchematic.css";

export type StationId = string;

export interface Segment {
  from: StationId;
  to: StationId;
  line: string;
}

export interface StationMeta {
  line: string;
  x: number;
  y: number;
  transfer_group?: string | null;
  /** present when extracted from v2 PDF */
  name_en?: string;
  name_zh?: string;
}

export interface LineData {
  id: string;
  color: string;
  trunk: StationId[];
  branches: Record<string, { fork_at: string; stations: StationId[] }>;
  /** present in v2 outputs */
  label?: string;
}

export interface StationsData {
  viewBox: [number, number, number, number];
  lines: LineData[];
  stations: Record<StationId, StationMeta>;
}

export interface Props {
  /**
   * URL prefix for assets. Defaults to "/v2/" (data with station names).
   * Use "/v1/" for the original ID-only dataset.
   */
  baseUrl?: string;
  highlightedStations?: StationId[];
  highlightedSegments?: Segment[];
  /** Optional override map for tooltip labels (overrides name_en/name_zh). */
  stationLabels?: Record<StationId, string>;
  onStationClick?(id: StationId): void;
  onStationHover?(id: StationId | null): void;
  className?: string;
  style?: React.CSSProperties;
}

export interface MetroSchematicHandle {
  highlightRoute(stationIds: StationId[]): void;
  clearHighlight(): void;
  focusStation(id: StationId): void;
}

// Build a lookup: stationId → ordered neighbors on its line
function buildNeighborMap(data: StationsData): Map<StationId, StationId[]> {
  const map = new Map<StationId, StationId[]>();
  const add = (a: StationId, b: StationId) => {
    if (!map.has(a)) map.set(a, []);
    map.get(a)!.push(b);
  };
  for (const line of data.lines) {
    const sequences: StationId[][] = [line.trunk];
    for (const br of Object.values(line.branches)) {
      sequences.push(br.stations);
    }
    for (const seq of sequences) {
      for (let i = 0; i < seq.length - 1; i++) {
        add(seq[i], seq[i + 1]);
        add(seq[i + 1], seq[i]);
      }
    }
  }
  return map;
}

// Returns the set of station IDs that lie on the path between consecutive IDs in the route
function resolveRouteSegments(
  route: StationId[],
  data: StationsData
): Set<StationId> {
  const highlighted = new Set<StationId>();
  if (route.length === 0) return highlighted;

  // Build line membership: stationId → Set<lineId>
  const stationLines = new Map<StationId, Set<string>>();
  for (const line of data.lines) {
    const allSeqs = [line.trunk, ...Object.values(line.branches).map((b) => b.stations)];
    for (const seq of allSeqs) {
      for (const sid of seq) {
        if (!stationLines.has(sid)) stationLines.set(sid, new Set());
        stationLines.get(sid)!.add(line.id);
      }
    }
  }

  for (const sid of route) {
    highlighted.add(sid);
  }

  // For each consecutive pair, find stations in between on a shared line
  for (let i = 0; i < route.length - 1; i++) {
    const a = route[i];
    const b = route[i + 1];
    const linesA = stationLines.get(a);
    const linesB = stationLines.get(b);
    if (!linesA || !linesB) continue;

    const sharedLines = [...linesA].filter((l) => linesB.has(l));
    for (const lineId of sharedLines) {
      const line = data.lines.find((l) => l.id === lineId)!;
      const allSeqs = [line.trunk, ...Object.values(line.branches).map((b) => b.stations)];
      for (const seq of allSeqs) {
        const idxA = seq.indexOf(a);
        const idxB = seq.indexOf(b);
        if (idxA === -1 || idxB === -1) continue;
        const lo = Math.min(idxA, idxB);
        const hi = Math.max(idxA, idxB);
        for (let k = lo; k <= hi; k++) {
          highlighted.add(seq[k]);
        }
      }
    }
  }

  return highlighted;
}

const MetroSchematic = forwardRef<MetroSchematicHandle, Props>(
  function MetroSchematic(
    {
      baseUrl = "/v2/",
      highlightedStations,
      highlightedSegments,
      stationLabels,
      onStationClick,
      onStationHover,
      className,
      style,
    },
    ref
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const overlaySvgRef = useRef<SVGSVGElement | null>(null);
    const panzoomRef = useRef<PanzoomObject | null>(null);
    const [stationsData, setStationsData] = useState<StationsData | null>(null);
    const [svgLoaded, setSvgLoaded] = useState(false);
    const [tooltip, setTooltip] = useState<{
      id: StationId;
      x: number;
      y: number;
    } | null>(null);
    const highlightedRef = useRef<Set<StationId>>(new Set());

    const base = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";

    // Load stations.json
    useEffect(() => {
      fetch(`${base}stations.json`)
        .then((r) => r.json())
        .then((d: StationsData) => setStationsData(d))
        .catch(console.error);
    }, [base]);

    // Load both SVGs into the container
    useEffect(() => {
      if (!containerRef.current || !stationsData) return;
      const container = containerRef.current;

      Promise.all([
        fetch(`${base}shanghai-metro.svg`).then((r) => r.text()),
        fetch(`${base}shanghai-metro-overlay.svg`).then((r) => r.text()),
      ])
        .then(([baseSvgText, overlaySvgText]) => {
          // Parse base SVG
          const parser = new DOMParser();
          const baseDoc = parser.parseFromString(baseSvgText, "image/svg+xml");
          const baseSvg = baseDoc.querySelector("svg")!;
          baseSvg.removeAttribute("width");
          baseSvg.removeAttribute("height");
          baseSvg.style.width = "100%";
          baseSvg.style.height = "100%";
          baseSvg.classList.add("metro-base-svg");

          // Parse overlay SVG
          const overlayDoc = parser.parseFromString(overlaySvgText, "image/svg+xml");
          const overlaySvg = overlayDoc.querySelector("svg")!;
          overlaySvg.removeAttribute("width");
          overlaySvg.removeAttribute("height");
          overlaySvg.style.width = "100%";
          overlaySvg.style.height = "100%";
          overlaySvg.style.position = "absolute";
          overlaySvg.style.top = "0";
          overlaySvg.style.left = "0";
          overlaySvg.classList.add("metro-overlay-svg");

          // Place in wrapper that panzoom controls
          const wrapper = document.createElement("div");
          wrapper.className = "metro-svg-wrapper";
          wrapper.style.position = "relative";
          wrapper.style.width = "100%";
          wrapper.style.height = "100%";
          wrapper.appendChild(baseSvg);
          wrapper.appendChild(overlaySvg);
          container.innerHTML = "";
          container.appendChild(wrapper);

          overlaySvgRef.current = overlaySvg as unknown as SVGSVGElement;

          // Init panzoom on wrapper
          if (panzoomRef.current) panzoomRef.current.destroy();
          const pz = Panzoom(wrapper, {
            maxScale: 12,
            minScale: 0.5,
            contain: "outside",
          });
          panzoomRef.current = pz;
          container.addEventListener("wheel", (e) => pz.zoomWithWheel(e), {
            passive: false,
          });

          // Attach station event listeners
          const circles = overlaySvg.querySelectorAll<SVGCircleElement>(
            "circle.station"
          );
          for (const circle of circles) {
            const sid = circle.id as StationId;
            circle.addEventListener("click", () => onStationClick?.(sid));
            circle.addEventListener("mouseenter", (e) => {
              const rect = container.getBoundingClientRect();
              const cx = parseFloat(circle.getAttribute("cx") || "0");
              const cy = parseFloat(circle.getAttribute("cy") || "0");
              // Transform SVG coords to screen coords via getScreenCTM
              const ctm = (overlaySvg as unknown as SVGGraphicsElement).getScreenCTM();
              if (ctm) {
                const pt = (overlaySvg as unknown as SVGSVGElement).createSVGPoint();
                pt.x = cx;
                pt.y = cy;
                const screenPt = pt.matrixTransform(ctm);
                setTooltip({
                  id: sid,
                  x: screenPt.x - rect.left,
                  y: screenPt.y - rect.top,
                });
              }
              onStationHover?.(sid);
              (e.currentTarget as SVGCircleElement).classList.add("hovered");
            });
            circle.addEventListener("mouseleave", (e) => {
              setTooltip(null);
              onStationHover?.(null);
              (e.currentTarget as SVGCircleElement).classList.remove("hovered");
            });
          }

          setSvgLoaded(true);
        })
        .catch(console.error);
    }, [base, stationsData]);

    const applyHighlight = useCallback(
      (ids: Set<StationId>) => {
        const overlaySvg = overlaySvgRef.current;
        if (!overlaySvg || !stationsData) return;
        highlightedRef.current = ids;

        const circles = overlaySvg.querySelectorAll<SVGCircleElement>(
          "circle.station"
        );
        const dimAll = ids.size > 0;

        for (const circle of circles) {
          const sid = circle.id as StationId;
          circle.classList.toggle("dimmed", dimAll && !ids.has(sid));
          circle.classList.toggle("highlighted", ids.has(sid));
        }

        // Dim/highlight the base SVG lines using data-line paths
        const baseSvg = containerRef.current?.querySelector<SVGSVGElement>(
          ".metro-base-svg"
        );
        if (baseSvg) {
          baseSvg.classList.toggle("metro--dimmed", dimAll);
          if (dimAll) {
            // Determine which lines carry at least one highlighted station
            const activeLines = new Set<string>();
            for (const sid of ids) {
              const meta = stationsData.stations[sid];
              if (meta) activeLines.add(meta.line);
            }
            // Also check transfer groups: if a transfer station is highlighted,
            // mark all its co-located line stations' lines active
            for (const sid of ids) {
              const meta = stationsData.stations[sid];
              if (meta?.transfer_group) {
                for (const [otherId, otherMeta] of Object.entries(
                  stationsData.stations
                )) {
                  if (
                    otherMeta.transfer_group === meta.transfer_group &&
                    ids.has(otherId)
                  ) {
                    activeLines.add(otherMeta.line);
                  }
                }
              }
            }
            // Apply to stroke groups
            const lineGroups = baseSvg.querySelectorAll<SVGGElement>(
              "[data-line]"
            );
            for (const g of lineGroups) {
              const lineId = g.getAttribute("data-line") || "";
              g.classList.toggle("line-active", activeLines.has(lineId));
            }
          } else {
            const lineGroups = baseSvg.querySelectorAll<SVGGElement>(
              "[data-line]"
            );
            for (const g of lineGroups) {
              g.classList.remove("line-active");
            }
          }
        }
      },
      [stationsData]
    );

    // React to prop-driven highlight changes
    useEffect(() => {
      if (!svgLoaded || !stationsData) return;
      if (highlightedStations && highlightedStations.length > 0) {
        applyHighlight(new Set(highlightedStations));
      } else if (
        highlightedSegments &&
        highlightedSegments.length > 0
      ) {
        const ids = new Set<StationId>(
          highlightedSegments.flatMap((s) => [s.from, s.to])
        );
        applyHighlight(ids);
      } else {
        applyHighlight(new Set());
      }
    }, [
      highlightedStations,
      highlightedSegments,
      svgLoaded,
      stationsData,
      applyHighlight,
    ]);

    // Imperative handle
    useImperativeHandle(
      ref,
      () => ({
        highlightRoute(stationIds: StationId[]) {
          if (!stationsData) return;
          const ids = resolveRouteSegments(stationIds, stationsData);
          applyHighlight(ids);
        },
        clearHighlight() {
          applyHighlight(new Set());
        },
        focusStation(id: StationId) {
          const meta = stationsData?.stations[id];
          if (!meta || !panzoomRef.current || !containerRef.current) return;
          const vb = stationsData.viewBox;
          const container = containerRef.current;
          const w = container.clientWidth;
          const h = container.clientHeight;
          const scale = Math.min(w / vb[2], h / vb[3]) * 3;
          panzoomRef.current.zoom(scale, { animate: true });
          // Pan to center the station
          const px = (meta.x / vb[2]) * w;
          const py = (meta.y / vb[3]) * h;
          panzoomRef.current.pan(w / 2 - px * scale, h / 2 - py * scale, {
            animate: true,
          });
        },
      }),
      [stationsData, applyHighlight]
    );

    return (
      <div
        className={`metro-schematic${className ? " " + className : ""}`}
        style={style}
      >
        <div
          ref={containerRef}
          className="metro-container"
          style={{ width: "100%", height: "100%", overflow: "hidden", position: "relative" }}
        />
        {tooltip && (() => {
          const meta = stationsData?.stations[tooltip.id];
          const overrideLabel = stationLabels?.[tooltip.id];
          const en = meta?.name_en;
          const zh = meta?.name_zh;
          return (
            <div
              className="metro-tooltip"
              style={{ left: tooltip.x, top: tooltip.y }}
            >
              <span className="metro-tooltip-id">{tooltip.id}</span>
              {overrideLabel ? (
                <span className="metro-tooltip-label">{overrideLabel}</span>
              ) : (
                <>
                  {en && <span className="metro-tooltip-label">{en}</span>}
                  {zh && <span className="metro-tooltip-label">{zh}</span>}
                </>
              )}
            </div>
          );
        })()}
      </div>
    );
  }
);

export default MetroSchematic;
