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
  degree: number;
}

export interface SimLink extends SimulationLinkDatum<SimNode> {
  source: SimNode;
  target: SimNode;
  reason: string;
  origin: string;
}

interface SimState {
  nodes: SimNode[];
  links: SimLink[];
}

/**
 * Runs a d3-force simulation for layout only (no DOM mutation). React renders
 * the SVG; each tick bumps a counter (throttled by the sim's own rAF cadence)
 * so the consumer re-reads node positions from the returned arrays.
 *
 * Layout is always topic-grouped (the only mode). Node size encodes semantic
 * connectivity (link degree), so hubs read large at a glance.
 */
export function useGraphSimulation(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
): { sim: SimState; tick: number; simRef: React.MutableRefObject<Simulation<SimNode, undefined> | null> } {
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const stateRef = useRef<SimState>({ nodes: [], links: [] });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!width || !height) return;

    // Semantic-link degree per node → drives node size.
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }

    // Preserve positions of nodes that already exist across re-runs.
    const prev = new Map(stateRef.current.nodes.map((n) => [n.id, n]));
    const simNodes: SimNode[] = nodes.map((n) => {
      const old = prev.get(n.id);
      return {
        ...n,
        degree: degree.get(n.id) ?? 0,
        x: old?.x ?? width / 2 + (Math.random() - 0.5) * 80,
        y: old?.y ?? height / 2 + (Math.random() - 0.5) * 80,
      };
    });
    const byId = new Map(simNodes.map((n) => [n.id, n]));
    const simLinks = edges
      .map((e) => ({ source: byId.get(e.source)!, target: byId.get(e.target)!, reason: e.reason, origin: e.origin }))
      .filter((l) => l.source && l.target);

    stateRef.current = { nodes: simNodes, links: simLinks };

    const groups = [...new Set(simNodes.map((n) => n.topic))];
    const centroid = (topic: number) => {
      const i = groups.indexOf(topic);
      const angle = (i / Math.max(groups.length, 1)) * Math.PI * 2;
      const radius = Math.min(width, height) * 0.3;
      return { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius };
    };

    const sim = forceSimulation(simNodes)
      .velocityDecay(0.6) // more friction → nodes glide to new positions instead of snapping
      .alphaDecay(0.015) // ease in over a longer, gentler settle
      .force("charge", forceManyBody().strength(-120))
      .force("link", forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(90).strength(0.5))
      .force("collide", forceCollide<SimNode>().radius((d) => nodeRadius(d.degree) + 6))
      .force("center", forceCenter(width / 2, height / 2))
      .force("x", forceX<SimNode>((d) => centroid(d.topic).x).strength(0.12))
      .force("y", forceY<SimNode>((d) => centroid(d.topic).y).strength(0.12));

    let frame = 0;
    sim.on("tick", () => {
      // Self-heal NaN/Infinity positions. If the force sim ever blows up (e.g.
      // coincident nodes under strong charge), a single non-finite value would
      // otherwise propagate to every node and render the whole SVG blank until a
      // full page reload. Reset the offending node instead so it recovers live.
      for (const n of simNodes) {
        if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) {
          n.x = width / 2 + (Math.random() - 0.5) * 80;
          n.y = height / 2 + (Math.random() - 0.5) * 80;
          n.vx = 0;
          n.vy = 0;
        }
      }
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
  }, [nodes, edges]);

  return { sim: stateRef.current, tick, simRef };
}

// Node size encodes semantic connectivity (link degree). Saturates past ~12
// links so a few mega-hubs don't dwarf everything else.
export function nodeRadius(degree: number): number {
  return 5 + (Math.min(Math.max(degree, 0), 12) / 12) * 11;
}
