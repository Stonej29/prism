import { useEffect, useMemo, useRef, useState } from "react";
import { P, SRC, srcColor } from "../theme";
import type { GraphPayload } from "../types";
import { nodeRadius, useGraphSimulation, type LayoutMode, type SimNode } from "../hooks/useGraphSimulation";

function Mono({ children, s = 11, c = P.mid }: { children: React.ReactNode; s?: number; c?: string }) {
  return <span style={{ fontFamily: P.mono, fontSize: s, color: c }}>{children}</span>;
}

export function GraphPane({
  graph,
  sourceFilter,
  onSourceFilter,
  selectedId,
  highlightIds,
  onSelect,
}: {
  graph: GraphPayload | null;
  sourceFilter: string | null;
  onSourceFilter: (s: string | null) => void;
  selectedId: string | null;
  highlightIds: Set<string> | null;
  onSelect: (id: string) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [layout, setLayout] = useState<LayoutMode>("force");
  const [hover, setHover] = useState<string | null>(null);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const transformRef = useRef(transform);
  transformRef.current = transform;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    if (!sourceFilter) return { nodes: graph.nodes, edges: graph.edges };
    const keep = new Set(graph.nodes.filter((n) => n.source_kind === sourceFilter).map((n) => n.id));
    return {
      nodes: graph.nodes.filter((n) => keep.has(n.id)),
      edges: graph.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [graph, sourceFilter]);

  const { sim, tick, simRef } = useGraphSimulation(nodes, edges, size.w, size.h, layout);
  void tick; // re-render trigger

  // ---- zoom / pan ----
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const rect = wrapRef.current!.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const t = transformRef.current;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const k = Math.max(0.25, Math.min(4, t.k * factor));
    const x = px - ((px - t.x) / t.k) * k;
    const y = py - ((py - t.y) / t.k) * k;
    setTransform({ k, x, y });
  };

  const panRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const onBgDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    panRef.current = { sx: e.clientX, sy: e.clientY, ox: transform.x, oy: transform.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onBgMove = (e: React.PointerEvent) => {
    if (!panRef.current) return;
    setTransform((t) => ({ ...t, x: panRef.current!.ox + (e.clientX - panRef.current!.sx), y: panRef.current!.oy + (e.clientY - panRef.current!.sy) }));
  };
  const onBgUp = () => (panRef.current = null);

  const zoomBy = (factor: number) => {
    const t = transformRef.current;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const k = Math.max(0.25, Math.min(4, t.k * factor));
    setTransform({ k, x: cx - ((cx - t.x) / t.k) * k, y: cy - ((cy - t.y) / t.k) * k });
  };

  // ---- node drag ----
  const dragRef = useRef<SimNode | null>(null);
  const toGraph = (clientX: number, clientY: number) => {
    const rect = wrapRef.current!.getBoundingClientRect();
    const t = transformRef.current;
    return { x: (clientX - rect.left - t.x) / t.k, y: (clientY - rect.top - t.y) / t.k };
  };
  const onNodeDown = (e: React.PointerEvent, n: SimNode) => {
    e.stopPropagation();
    dragRef.current = n;
    simRef.current?.alphaTarget(0.2).restart();
    const move = (ev: PointerEvent) => {
      if (!dragRef.current) return;
      const p = toGraph(ev.clientX, ev.clientY);
      dragRef.current.fx = p.x;
      dragRef.current.fy = p.y;
    };
    const up = () => {
      if (dragRef.current) {
        dragRef.current.fx = null;
        dragRef.current.fy = null;
      }
      dragRef.current = null;
      simRef.current?.alphaTarget(0);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={wrapRef} style={{ flex: 1, position: "relative", background: P.bg0, overflow: "hidden" }}>
      {/* toolbar */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 46,
          zIndex: 6,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 16px",
          borderBottom: `1px solid ${P.line}`,
          background: `${P.bg0}cc`,
          backdropFilter: "blur(8px)",
        }}
      >
        <Mono c={P.mid}>filter</Mono>
        {Object.entries(SRC)
          .filter(([k]) => k !== "unknown")
          .map(([k, s]) => {
            const active = sourceFilter === k;
            return (
              <span
                key={k}
                onClick={() => onSourceFilter(active ? null : k)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontFamily: P.mono,
                  fontSize: 11,
                  color: active ? P.hi : P.mid,
                  padding: "4px 9px",
                  borderRadius: 6,
                  border: `1px solid ${active ? P.accent : P.line}`,
                  background: active ? P.accentDim : "transparent",
                  cursor: "pointer",
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.color }} />
                {s.label}
              </span>
            );
          })}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <Mono c={P.mid}>layout</Mono>
          {(["force", "cluster"] as LayoutMode[]).map((m) => (
            <span
              key={m}
              onClick={() => setLayout(m)}
              style={{
                fontFamily: P.mono,
                fontSize: 11,
                color: layout === m ? P.accent : P.mid,
                padding: "4px 9px",
                borderRadius: 6,
                background: layout === m ? P.accentDim : "transparent",
                cursor: "pointer",
              }}
            >
              {m}
            </span>
          ))}
        </div>
      </div>

      <svg
        width={size.w}
        height={size.h}
        onWheel={onWheel}
        onPointerDown={onBgDown}
        onPointerMove={onBgMove}
        onPointerUp={onBgUp}
        style={{ display: "block", cursor: panRef.current ? "grabbing" : "grab" }}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {sim.links.map((l, i) => {
            const dim = highlightIds && !(highlightIds.has(l.source.id) && highlightIds.has(l.target.id));
            return (
              <line
                key={i}
                x1={l.source.x}
                y1={l.source.y}
                x2={l.target.x}
                y2={l.target.y}
                stroke={P.line}
                strokeWidth={1}
                opacity={dim ? 0.25 : 0.7}
              />
            );
          })}
          {sim.nodes.map((n) => {
            const r = nodeRadius(n.overall);
            const selected = n.id === selectedId;
            const dim = highlightIds && !highlightIds.has(n.id);
            const showLabel = selected || hover === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: "pointer" }}
                opacity={dim ? 0.3 : 1}
                onPointerDown={(e) => onNodeDown(e, n)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(n.id);
                }}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover((h) => (h === n.id ? null : h))}
              >
                <circle
                  r={r}
                  fill={srcColor(n.source_kind)}
                  stroke={selected ? P.hi : P.bg0}
                  strokeWidth={selected ? 2 : 1.5}
                />
                {showLabel && (
                  <text
                    x={r + 5}
                    y={4}
                    fontFamily={P.sans}
                    fontSize={11}
                    fill={P.hi}
                    style={{ pointerEvents: "none" }}
                  >
                    {n.title.length > 42 ? n.title.slice(0, 42) + "…" : n.title}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* zoom controls */}
      <div
        style={{
          position: "absolute",
          bottom: 16,
          right: 16,
          display: "flex",
          flexDirection: "column",
          border: `1px solid ${P.line}`,
          borderRadius: 8,
          overflow: "hidden",
          background: P.bg1,
          zIndex: 6,
        }}
      >
        {[["+", 1.2], ["−", 1 / 1.2]].map(([s, f], i) => (
          <div
            key={s as string}
            onClick={() => zoomBy(f as number)}
            style={{
              width: 30,
              height: 30,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: P.mono,
              fontSize: 15,
              color: P.mid,
              cursor: "pointer",
              borderBottom: i === 0 ? `1px solid ${P.line}` : "none",
            }}
          >
            {s}
          </div>
        ))}
      </div>

      {/* count chip */}
      <div
        style={{
          position: "absolute",
          bottom: 16,
          left: 16,
          zIndex: 6,
          background: `${P.bg1}dd`,
          border: `1px solid ${P.line}`,
          borderRadius: 8,
          padding: "7px 12px",
        }}
      >
        <Mono>
          {sim.nodes.length} notes · {sim.links.length} links · {graph?.counts.clusters ?? 0} clusters
        </Mono>
      </div>
    </div>
  );
}
