import { useEffect, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdge, GraphNode } from "../types";

export interface SimNode extends GraphNode, SimulationNodeDatum {
  x: number;
  y: number;
}

export interface SimLink extends SimulationLinkDatum<SimNode> {
  source: SimNode;
  target: SimNode;
  reason: string;
}

export type LayoutMode = "force" | "cluster";

interface SimState {
  nodes: SimNode[];
  links: SimLink[];
}

/**
 * Runs a d3-force simulation for layout only (no DOM mutation). React renders
 * the SVG; each tick bumps a counter (throttled by the sim's own rAF cadence)
 * so the consumer re-reads node positions from the returned arrays.
 */
export function useGraphSimulation(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
  layout: LayoutMode,
): { sim: SimState; tick: number; simRef: React.MutableRefObject<Simulation<SimNode, undefined> | null> } {
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const stateRef = useRef<SimState>({ nodes: [], links: [] });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!width || !height) return;

    // Preserve positions of nodes that already exist across re-runs.
    const prev = new Map(stateRef.current.nodes.map((n) => [n.id, n]));
    const simNodes: SimNode[] = nodes.map((n) => {
      const old = prev.get(n.id);
      return { ...n, x: old?.x ?? width / 2 + (Math.random() - 0.5) * 80, y: old?.y ?? height / 2 + (Math.random() - 0.5) * 80 };
    });
    const byId = new Map(simNodes.map((n) => [n.id, n]));
    const simLinks = edges
      .map((e) => ({ source: byId.get(e.source)!, target: byId.get(e.target)!, reason: e.reason }))
      .filter((l) => l.source && l.target);

    stateRef.current = { nodes: simNodes, links: simLinks };

    const sim = forceSimulation(simNodes)
      .force("charge", forceManyBody().strength(-220))
      .force("link", forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(90).strength(0.5))
      .force("collide", forceCollide<SimNode>().radius((d) => nodeRadius(d.overall) + 6))
      .force("center", forceCenter(width / 2, height / 2));

    if (layout === "cluster") {
      const clusters = [...new Set(simNodes.map((n) => n.cluster))];
      const centroid = (c: string) => {
        const i = clusters.indexOf(c);
        const angle = (i / Math.max(clusters.length, 1)) * Math.PI * 2;
        const radius = Math.min(width, height) * 0.3;
        return { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius };
      };
      sim
        .force("x", forceX<SimNode>((d) => centroid(d.cluster).x).strength(0.25))
        .force("y", forceY<SimNode>((d) => centroid(d.cluster).y).strength(0.25))
        .force("charge", forceManyBody().strength(-120));
    }

    let frame = 0;
    sim.on("tick", () => {
      frame = (frame + 1) % 2;
      if (frame === 0) setTick((t) => t + 1);
    });
    sim.on("end", () => setTick((t) => t + 1));

    simRef.current = sim;
    setTick((t) => t + 1);

    return () => {
      sim.stop();
    };
    // NOTE: width/height are intentionally omitted — a resize (e.g. folding a panel)
    // must NOT re-run the layout. The effect captures the current size when it re-runs
    // on a data/layout change, which is the only time we want to re-lay-out.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, layout]);

  return { sim: stateRef.current, tick, simRef };
}

export function nodeRadius(overall: number | null): number {
  const v = overall ?? 5;
  return 5 + (Math.max(1, Math.min(10, v)) / 10) * 9;
}
