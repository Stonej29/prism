import { useEffect, useMemo, useRef, useState } from "react";
import { P, scoreColor } from "../theme";
import type { GraphPayload, MaintenanceEvent, MaintenanceStatus } from "../types";
import { nodeRadius, useGraphSimulation, type SimNode } from "../hooks/useGraphSimulation";
import { convexHull, expandHull, roundedPath } from "../lib/hull";

function Mono({ children, s = 11, c = P.mid }: { children: React.ReactNode; s?: number; c?: string }) {
  return <span style={{ fontFamily: P.mono, fontSize: s, color: c }}>{children}</span>;
}

// Deterministic, well-spread colour per topic cluster for the hull overlay.
function topicColor(topic: number): string {
  if (topic < 0) return P.line;
  return `hsl(${(topic * 67) % 360} 60% 62%)`;
}

function edgeKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`;
}

// Guard against a non-finite coordinate reaching the SVG: a single NaN in a
// <g transform> blanks the entire group (the "black graph" bug).
function finite(n: number, fallback = 0): number {
  return Number.isFinite(n) ? n : fallback;
}

function eventNodeIds(event: MaintenanceEvent): string[] {
  const ids: string[] = [];
  if (event.note_id) ids.push(event.note_id);
  if (event.source) ids.push(event.source);
  if (event.target) ids.push(event.target);
  if (event.keep) ids.push(event.keep);
  if (event.remove) ids.push(event.remove);
  return ids;
}

export function GraphPane({
  graph,
  sourceFilters,
  tagFilters,
  flagFilters,
  minAgeDays,
  minScore,
  selectedId,
  highlightIds,
  onSelect,
  onDeselect,
  onClearHighlight,
  onClearFilters,
  leftPanelWidth,
  processingNodeIds,
  maintenanceStatus,
  maintenanceEvents = [],
}: {
  graph: GraphPayload | null;
  sourceFilters: string[];
  tagFilters: string[];
  flagFilters: string[];
  minAgeDays: number;
  minScore: number;
  selectedId: string | null;
  highlightIds: Set<string> | null;
  onSelect: (id: string) => void;
  onDeselect: () => void;
  onClearHighlight: () => void;
  onClearFilters: () => void;
  leftPanelWidth: number;
  processingNodeIds?: Record<string, string>;
  maintenanceStatus?: MaintenanceStatus | null;
  maintenanceEvents?: MaintenanceEvent[];
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [repaintKey, setRepaintKey] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const transformRef = useRef(transform);
  transformRef.current = transform;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    // Ignore transient 0-size measurements and retry after tab/window return;
    // otherwise some browsers can leave the SVG painted as a blank dark rect.
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) {
        setSize({ w, h });
        return true;
      }
      return false;
    };
    const measureSoon = () => {
      if (!measure()) requestAnimationFrame(() => requestAnimationFrame(measure));
    };
    const ro = new ResizeObserver(measureSoon);
    ro.observe(el);
    measureSoon();
    window.addEventListener("resize", measureSoon);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measureSoon);
    };
  }, []);

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    // "Minimum age" slider: keep only notes saved within the last `minAgeDays`
    // days (far left = 0 = show everything from the beginning).
    const minAgeCutoff = Date.now() - minAgeDays * 86400000;
    const passes = (n: GraphPayload["nodes"][number]) => {
      if (sourceFilters.length > 0 && !sourceFilters.includes(n.source_kind)) return false;
      if (tagFilters.length > 0 && !tagFilters.some((tag) => n.tags.includes(tag))) return false;
      if (flagFilters.includes("favorite") && !n.favorite) return false;
      if (flagFilters.includes("unreviewed") && n.status !== "unreviewed") return false;
      if (flagFilters.includes("failed") && !n.failed) return false;
      if (minAgeDays > 0) {
        const saved = Date.parse(n.date_saved ?? "");
        if (!Number.isFinite(saved) || saved < minAgeCutoff) return false;
      }
      if (minScore > 0 && !(n.overall != null && n.overall >= minScore)) return false;
      return true;
    };
    const hasFilters = sourceFilters.length > 0 || tagFilters.length > 0 || flagFilters.length > 0 || minAgeDays > 0 || minScore > 0;
    if (!hasFilters) return { nodes: graph.nodes, edges: graph.edges };
    const keep = new Set(graph.nodes.filter(passes).map((n) => n.id));
    return {
      nodes: graph.nodes.filter((n) => keep.has(n.id)),
      edges: graph.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [graph, sourceFilters, tagFilters, flagFilters, minAgeDays, minScore]);

  const { sim, tick, simRef } = useGraphSimulation(nodes, edges, size.w, size.h);

  // Toggleable topic "hulls": dashed regions + labels behind the nodes. Pure
  // overlay — never touches the force simulation. Persisted across reloads.
  const [showHulls, setShowHulls] = useState(() => {
    try { return localStorage.getItem("prism.graph.hulls") === "1"; } catch { return false; }
  });
  const toggleHulls = () =>
    setShowHulls((v) => {
      const next = !v;
      try { localStorage.setItem("prism.graph.hulls", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });

  const hulls = useMemo(() => {
    if (!showHulls) return [] as { topic: number; d: string; cx: number; cy: number; label: string }[];
    const groups = new Map<number, SimNode[]>();
    for (const n of sim.nodes) {
      if (n.topic < 0) continue;
      const g = groups.get(n.topic);
      if (g) g.push(n);
      else groups.set(n.topic, [n]);
    }
    const out: { topic: number; d: string; cx: number; cy: number; label: string }[] = [];
    for (const [topic, members] of groups) {
      if (members.length < 2) continue;
      const hull = expandHull(convexHull(members.map((m) => ({ x: m.x, y: m.y }))), 30);
      const cx = hull.reduce((s, p) => s + p.x, 0) / hull.length;
      const cy = Math.min(...hull.map((p) => p.y)) - 8;
      out.push({ topic, d: roundedPath(hull), cx, cy, label: graph?.topic_labels?.[String(topic)] ?? `topic ${topic + 1}` });
    }
    return out;
    // tick drives recompute as the layout settles; sim.nodes mutates in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showHulls, tick, graph, sim.nodes]);

  // Entrance animation for newly added nodes (e.g. just-saved notes).
  const seenRef = useRef<Set<string>>(new Set());
  const [entering, setEntering] = useState<Set<string>>(new Set());
  useEffect(() => {
    const fresh = nodes.filter((n) => !seenRef.current.has(n.id)).map((n) => n.id);
    if (fresh.length === 0) return;
    fresh.forEach((id) => seenRef.current.add(id));
    setEntering((prev) => new Set([...prev, ...fresh]));
    const t = setTimeout(() => {
      setEntering((prev) => {
        const next = new Set(prev);
        fresh.forEach((id) => next.delete(id));
        return next;
      });
    }, 700);
    return () => clearTimeout(t);
  }, [nodes]);

  // Returning from another app/tab can leave the SVG blank or the simulation's
  // rAF loop paused; re-measure the container and nudge the layout so it repaints.
  useEffect(() => {
    const onReturn = () => {
      if (document.visibilityState !== "visible") return;
      const el = wrapRef.current;
      const measure = () => {
        if (el && el.clientWidth > 0 && el.clientHeight > 0) {
          setSize({ w: el.clientWidth, h: el.clientHeight });
          setRepaintKey((k) => k + 1);
        }
      };
      measure();
      requestAnimationFrame(() => requestAnimationFrame(measure));
      simRef.current?.alpha(0.12).restart();
    };
    window.addEventListener("focus", onReturn);
    window.addEventListener("pageshow", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      window.removeEventListener("pageshow", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [simRef]);

  const recentMaintenanceEvents = maintenanceEvents.slice(-80);
  const latestMaintenancePhase = [...recentMaintenanceEvents].reverse().find((e) => e.kind === "phase");
  const maintenanceNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const event of recentMaintenanceEvents) {
      for (const id of eventNodeIds(event)) ids.add(id);
    }
    return ids;
  }, [recentMaintenanceEvents]);
  const maintenanceEdgeEvents = useMemo(
    () => recentMaintenanceEvents.filter((e) => (e.kind === "edge_added" || e.kind === "edge_removed") && e.source && e.target),
    [recentMaintenanceEvents],
  );
  const simNodeById = useMemo(() => new Map(sim.nodes.map((n) => [n.id, n])), [sim.nodes]);

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
    const pan = panRef.current;
    if (!pan) return;
    const dx = e.clientX - pan.sx;
    const dy = e.clientY - pan.sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) movedRef.current = true;
    // Capture pan locally: the setTransform updater runs later, by which point
    // panRef.current may be null (pointerup) — dereferencing it there crashes
    // the render and blanks the graph.
    setTransform((t) => ({ ...t, x: pan.ox + dx, y: pan.oy + dy }));
  };
  const onBgUp = () => (panRef.current = null);
  const onBgClick = () => {
    if (!movedRef.current) onDeselect();
  };

  const filterCount = sourceFilters.length + tagFilters.length + flagFilters.length + (minAgeDays > 0 ? 1 : 0) + (minScore > 0 ? 1 : 0);

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
      <style>{`
        @keyframes prism-maintenance-node-pulse {
          0% { opacity: 0.95; transform: scale(0.85); }
          100% { opacity: 0; transform: scale(2.2); }
        }
        @keyframes prism-maintenance-edge-pulse {
          0% { opacity: 0.95; stroke-width: 3; }
          100% { opacity: 0; stroke-width: 1; }
        }
        @keyframes prism-node-working {
          0%, 100% { fill: var(--node-color); opacity: 1; }
          48%, 58% { fill: #6f7780; opacity: 0.58; }
        }
        .prism-maintenance-node-pulse {
          transform-box: fill-box;
          transform-origin: center;
          animation: prism-maintenance-node-pulse 1.8s ease-out forwards;
          pointer-events: none;
        }
        .prism-maintenance-edge-pulse {
          animation: prism-maintenance-edge-pulse 1.8s ease-out forwards;
          pointer-events: none;
        }
        .prism-node-working {
          animation: prism-node-working 1.25s ease-in-out infinite;
        }
      `}</style>

      {/* toolbar */}
      <div
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          zIndex: 6,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 16px",
          background: `${P.bg0}cc`,
          borderBottomLeftRadius: 8,
          backdropFilter: "blur(8px)",
        }}
      >
        <span
          onClick={toggleHulls}
          title="Outline topic regions behind the graph"
          style={{ fontFamily: P.mono, fontSize: 11, color: showHulls ? P.hi : P.mid, cursor: "pointer" }}
        >
          hulls
        </span>
      </div>

      <svg
        key={repaintKey}
        width={size.w}
        height={size.h}
        onPointerDown={onBgDown}
        onPointerMove={onBgMove}
        onPointerUp={onBgUp}
        onClick={onBgClick}
        style={{ display: "block", cursor: panRef.current ? "grabbing" : "grab" }}
      >
        <style>{`@keyframes prismNodeEnter { from { opacity: 0; transform: scale(0.3); } to { opacity: 1; transform: scale(1); } }`}</style>
        <g transform={`translate(${finite(transform.x)},${finite(transform.y)}) scale(${finite(transform.k, 1)})`}>
          {hulls.map((h) => (
            <g key={`hull-${h.topic}`} style={{ pointerEvents: "none" }}>
              <path d={h.d} fill={topicColor(h.topic)} fillOpacity={0.06} stroke={topicColor(h.topic)} strokeOpacity={0.5} strokeWidth={1.2} strokeDasharray="6 5" />
              <text x={h.cx} y={h.cy} textAnchor="middle" fontFamily={P.mono} fontSize={11} fill={topicColor(h.topic)} opacity={0.9}>
                {h.label}
              </text>
            </g>
          ))}
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
          {maintenanceEdgeEvents.map((event) => {
            const source = event.source;
            const target = event.target;
            if (!source || !target) return null;
            const a = simNodeById.get(source);
            const b = simNodeById.get(target);
            if (!a || !b) return null;
            const removed = event.kind === "edge_removed";
            return (
              <line
                key={`${event.seq}-${edgeKey(source, target)}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={removed ? P.arxiv : P.accent}
                strokeDasharray={removed ? "5 4" : "none"}
                className="prism-maintenance-edge-pulse"
              />
            );
          })}
          {sim.nodes.map((n) => {
            const r = nodeRadius(n.degree);
            const selected = n.id === selectedId;
            const lit = !!highlightIds && highlightIds.has(n.id);
            const dim = !!highlightIds && !lit;
            const archived = n.status === "archived";
            const showLabel = selected || lit || hover === n.id;
            const maintenancePulse = maintenanceNodeIds.has(n.id);
            const processing = !!processingNodeIds?.[n.id];
            const nodeColor = scoreColor(n.overall);
            return (
              <g
                key={n.id}
                transform={`translate(${finite(n.x)},${finite(n.y)})`}
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
                {maintenancePulse && (
                  <circle
                    r={r + 7}
                    fill="none"
                    stroke={P.accent}
                    strokeWidth={1.6}
                    className="prism-maintenance-node-pulse"
                  />
                )}
                <circle
                  r={r}
                  fill={nodeColor}
                  stroke={processing ? "#8d949b" : selected ? P.hi : lit ? P.hi : P.bg0}
                  strokeWidth={processing ? 2.2 : selected ? 2 : lit ? 1.8 : 1.5}
                  className={processing ? "prism-node-working" : undefined}
                  style={processing ? ({ "--node-color": nodeColor } as React.CSSProperties) : entering.has(n.id) ? { animation: "prismNodeEnter 650ms ease-out", transformBox: "fill-box", transformOrigin: "center" } : undefined}
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
            {sim.nodes.length} notes · {sim.links.length} links · {new Set(nodes.map((n) => n.topic)).size} topics
          </Mono>
        </div>
        <div title="Node colour = overall score; node size = number of semantic links" style={{ display: "flex", alignItems: "center", gap: 8, background: `${P.bg1}dd`, border: `1px solid ${P.line}`, borderRadius: 8, padding: "7px 12px" }}>
          <Mono c={P.faint}>score</Mono>
          <span style={{ width: 44, height: 7, borderRadius: 4, background: `linear-gradient(90deg, ${scoreColor(1)}, ${scoreColor(5.5)}, ${scoreColor(10)})` }} />
          <Mono c={P.faint}>size = links</Mono>
        </div>
        {filterCount > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: `${P.bg1}dd`, border: `1px solid ${P.line}`, borderRadius: 8, padding: "7px 12px" }}>
            <Mono c={P.mid}>{filterCount} filter{filterCount === 1 ? "" : "s"}</Mono>
            <span onClick={onClearFilters} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, cursor: "pointer" }}>clear filters</span>
          </div>
        )}
        {maintenanceStatus && maintenanceStatus.status !== "idle" && (
          <div style={{ background: maintenanceStatus.status === "running" ? P.accentDim : `${P.bg1}dd`, border: `1px solid ${maintenanceStatus.status === "failed" ? P.arxiv : maintenanceStatus.status === "running" ? P.accent : P.line}`, borderRadius: 8, padding: "7px 12px" }}>
            <Mono c={maintenanceStatus.status === "failed" ? P.arxiv : maintenanceStatus.status === "running" ? P.accent : P.mid}>
              maintenance {maintenanceStatus.status} · {maintenanceStatus.event_count} events{latestMaintenancePhase?.phase ? ` · ${latestMaintenancePhase.phase}` : ""}
            </Mono>
          </div>
        )}
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
