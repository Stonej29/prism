import { P, srcColor, srcLabel } from "../theme";
import type { GraphPayload, Stats, TagCount } from "../types";

const RAIL = 264;
const KNOWN_SOURCES = ["paper", "github", "pdf", "website"];

function TreeHead({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: P.mono,
        fontSize: 10,
        letterSpacing: 1.2,
        color: P.faint,
        textTransform: "uppercase",
        padding: "14px 12px 6px",
      }}
    >
      {children}
    </div>
  );
}

function TreeRow({
  label,
  count,
  color,
  glyph,
  active,
  indent = 0,
  onClick,
}: {
  label: string;
  count?: number | null;
  color?: string;
  glyph?: string;
  active?: boolean;
  indent?: number;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "6px 10px",
        paddingLeft: 12 + indent,
        borderRadius: 6,
        background: active ? P.accentDim : "transparent",
        cursor: "pointer",
        color: active ? P.hi : P.mid,
      }}
    >
      {color ? (
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
      ) : (
        <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo, width: 7, textAlign: "center" }}>{glyph}</span>
      )}
      <span style={{ fontFamily: P.sans, fontSize: 13, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {label}
      </span>
      {count != null && <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>{count}</span>}
    </div>
  );
}

function Mono({ children, c = P.mid }: { children: React.ReactNode; c?: string }) {
  return <span style={{ fontFamily: P.mono, fontSize: 11, color: c }}>{children}</span>;
}

export function TreePane({
  graph,
  tags,
  stats,
  sourceFilter,
  activeTag,
  onSelectSource,
  onSelectTag,
}: {
  graph: GraphPayload | null;
  tags: TagCount[];
  stats: Stats | null;
  sourceFilter: string | null;
  activeTag: string | null;
  onSelectSource: (s: string | null) => void;
  onSelectTag: (t: string) => void;
}) {
  const counts: Record<string, number> = {};
  for (const n of graph?.nodes ?? []) counts[n.source_kind] = (counts[n.source_kind] ?? 0) + 1;
  const total = graph?.nodes.length ?? 0;
  const indexed = stats?.notes.embedding_indexed ?? 0;
  const healthy = stats?.index_configured && (stats?.notes.embedding_failed ?? 0) === 0;

  return (
    <div
      style={{
        width: RAIL,
        flexShrink: 0,
        borderRight: `1px solid ${P.line}`,
        background: P.bg1,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ flex: 1, overflowY: "auto", padding: "2px 8px" }}>
        <TreeHead>Library</TreeHead>
        <TreeRow glyph="◇" label="All notes" count={total} active={!sourceFilter && !activeTag} onClick={() => onSelectSource(null)} />

        <TreeHead>By source</TreeHead>
        {KNOWN_SOURCES.map((kind) => (
          <TreeRow
            key={kind}
            color={srcColor(kind)}
            label={`${srcLabel(kind)} ${kind === "paper" ? "papers" : kind === "github" ? "repos" : kind === "pdf" ? "files" : "sites"}`}
            count={counts[kind] ?? 0}
            active={sourceFilter === kind}
            onClick={() => onSelectSource(sourceFilter === kind ? null : kind)}
          />
        ))}

        <TreeHead>Tags</TreeHead>
        {tags.slice(0, 14).map((t) => (
          <TreeRow
            key={t.tag}
            glyph="≈"
            label={t.tag}
            count={t.count}
            active={activeTag === t.tag}
            onClick={() => onSelectTag(t.tag)}
          />
        ))}
        {tags.length === 0 && (
          <div style={{ padding: "6px 12px", fontFamily: P.sans, fontSize: 12, color: P.faint }}>No tags yet.</div>
        )}
      </div>

      <div style={{ padding: "12px 14px", borderTop: `1px solid ${P.line}`, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Mono>index</Mono>
          <Mono c={healthy ? P.pdf : P.arxiv}>● {stats?.index_configured ? (healthy ? "healthy" : "errors") : "off"}</Mono>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Mono>{indexed} vecs</Mono>
          <Mono c={P.lo}>{stats?.embedding_model ?? "no model"}</Mono>
        </div>
      </div>
    </div>
  );
}
