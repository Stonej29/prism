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
  onDeselect,
  onClearHighlight,
  leftPanelWidth,
}: {
  graph: GraphPayload | null;
  sourceFilter: string | null;
  onSourceFilter: (s: string | null) => void;
  selectedId: string | null;
  highlightIds: Set<string> | null;
  onSelect: (id: string) => void;
  onDeselect: () => void;
  onClearHighlight: () => void;
  leftPanelWidth: number;
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
    // Ignore transient 0-size measurements (e.g. when the tab/window is
    // backgrounded or the layout briefly collapses). Setting the SVG to 0×0
    // blanks it to the bare background and it stays dark until a reload.
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) setSize({ w, h });
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
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

  // Returning from another app/tab can leave the SVG blank or the simulation's
  // rAF loop paused; re-measure the container and nudge the layout so it repaints.
  useEffect(() => {
    const onReturn = () => {
      if (document.visibilityState !== "visible") return;
      const el = wrapRef.current;
      if (el && el.clientWidth > 0 && el.clientHeight > 0) {
        setSize({ w: el.clientWidth, h: el.clientHeight });
      }
      simRef.current?.alpha(0.05).restart();
    };
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [simRef]);

  // Keep nodes screen-stable when the LEFT panel folds (its width change moves the
  // graph's left origin); compensate the pan so the graph doesn't appear to jump.
  const prevLeftRef = useRef(leftPanelWidth);
  useEffect(() => {
    const delta = prevLeftRef.current - leftPanelWidth;
    prevLeftRef.current = leftPanelWidth;
    if (delta !== 0) setTransform((t) => ({ ...t, x: t.x + delta }));
  }, [leftPanelWidth]);

  // ---- zoom (native non-passive wheel so only the graph zooms, never the page) ----
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const t = transformRef.current;
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      const k = Math.max(0.25, Math.min(4, t.k * factor));
      const x = px - ((px - t.x) / t.k) * k;
      const y = py - ((py - t.y) / t.k) * k;
      setTransform({ k, x, y });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // ---- pan (and distinguish a click from a drag for deselect) ----
  const panRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const movedRef = useRef(false);
  const onBgDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    movedRef.current = false;
    panRef.current = { sx: e.clientX, sy: e.clientY, ox: transform.x, oy: transform.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onBgMove = (e: React.PointerEvent) => {
    if (!panRef.current) return;
    const dx = e.clientX - panRef.current.sx;
    const dy = e.clientY - panRef.current.sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) movedRef.current = true;
    setTransform((t) => ({ ...t, x: panRef.current!.ox + dx, y: panRef.current!.oy + dy }));
  };
  const onBgUp = () => (panRef.current = null);
  const onBgClick = () => {
    if (!movedRef.current) onDeselect();
  };

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
    <div
      ref={wrapRef}
      style={{ flex: 1, position: "relative", background: P.bg0, overflow: "hidden", touchAction: "none", overscrollBehavior: "contain" }}
    >
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
          {([["force", "force"], ["topic", "topics"], ["link", "links"]] as [LayoutMode, string][]).map(([m, label]) => (
            <span
              key={m}
              onClick={() => setLayout(m)}
              title={m === "topic" ? "Group by embedding similarity" : m === "link" ? "Group by related-note links" : "Force-directed"}
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
              {label}
            </span>
          ))}
        </div>
      </div>

      <svg
        width={size.w}
        height={size.h}
        onPointerDown={onBgDown}
        onPointerMove={onBgMove}
        onPointerUp={onBgUp}
        onClick={onBgClick}
        style={{ display: "block", cursor: panRef.current ? "grabbing" : "grab" }}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {sim.links.map((l, i) => {
            const active = !!highlightIds;
            const on = active && highlightIds.has(l.source.id) && highlightIds.has(l.target.id);
            return (
              <line
                key={i}
                x1={l.source.x}
                y1={l.source.y}
                x2={l.target.x}
                y2={l.target.y}
                stroke={on ? P.hi : P.line}
                strokeWidth={on ? 1.5 : 1}
                opacity={active ? (on ? 0.95 : 0.05) : 0.7}
              />
            );
          })}
          {sim.nodes.map((n) => {
            const r = nodeRadius(n.overall);
            const selected = n.id === selectedId;
            const lit = !!highlightIds && highlightIds.has(n.id);
            const dim = !!highlightIds && !lit;
            const archived = n.status === "archived";
            const showLabel = selected || lit || hover === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: "pointer" }}
                opacity={dim ? 0.12 : archived ? 0.4 : 1}
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
                  stroke={selected ? P.hi : lit ? P.hi : P.bg0}
                  strokeWidth={selected ? 2 : lit ? 1.8 : 1.5}
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

      {/* count / highlight chip */}
      <div style={{ position: "absolute", bottom: 16, left: 16, zIndex: 6, display: "flex", gap: 8 }}>
        <div style={{ background: `${P.bg1}dd`, border: `1px solid ${P.line}`, borderRadius: 8, padding: "7px 12px" }}>
          <Mono>
            {sim.nodes.length} notes · {sim.links.length} links ·{" "}
            {new Set(nodes.map((n) => (layout === "link" ? n.community : n.topic))).size}{" "}
            {layout === "link" ? "communities" : "topics"}
          </Mono>
        </div>
        {highlightIds && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: P.accentDim, border: `1px solid ${P.accent}`, borderRadius: 8, padding: "7px 12px" }}>
            <Mono c={P.accent}>≈ {highlightIds.size} highlighted</Mono>
            <span onClick={onClearHighlight} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, cursor: "pointer" }}>clear</span>
          </div>
        )}
      </div>
    </div>
  );
}
