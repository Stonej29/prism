import { useState } from "react";
import { P, srcColor, srcLabel } from "../theme";
import type { GraphPayload, Stats, TagCount, TreeNode } from "../types";
import { FileTree } from "./FileTree";
import type { OpenFile } from "./FileViewer";
import { ResizeHandle } from "./ResizeHandle";

const KNOWN_SOURCES = ["paper", "github", "huggingface", "youtube", "pdf", "website"];

function Mono({ children, c = P.mid }: { children: React.ReactNode; c?: string }) {
  return <span style={{ fontFamily: P.mono, fontSize: 11, color: c }}>{children}</span>;
}

function SectionHead({ children, open, onClick }: { children: React.ReactNode; open?: boolean; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontFamily: P.mono,
        fontSize: 10,
        letterSpacing: 1.2,
        color: P.faint,
        textTransform: "uppercase",
        padding: "12px 12px 6px",
        cursor: onClick ? "pointer" : "default",
      }}
    >
      {onClick && (
        <svg width="9" height="9" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none" }}>
          <path d="M3 2l4 3-4 3" fill="none" stroke={P.faint} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {children}
    </div>
  );
}

function FilterRow({ label, count, color, glyph, active, onClick }: { label: string; count?: number; color?: string; glyph?: string; active?: boolean; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 9, padding: "5px 10px", paddingLeft: 14, borderRadius: 6, background: active ? P.accentDim : "transparent", cursor: "pointer", color: active ? P.hi : P.mid }}
    >
      {color ? (
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
      ) : (
        <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo, width: 7, textAlign: "center" }}>{glyph}</span>
      )}
      <span style={{ fontFamily: P.sans, fontSize: 13, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
      {count != null && <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>{count}</span>}
    </div>
  );
}

export function TreePane({
  open,
  onToggle,
  width,
  onResize,
  tree,
  noteKind,
  selectedNoteId,
  graph,
  tags,
  stats,
  sourceFilter,
  activeTag,
  onSelectNote,
  onOpenIdea,
  onOpenFile,
  onSelectSource,
  onSelectTag,
  onJob,
}: {
  open: boolean;
  onToggle: () => void;
  width: number;
  onResize: (w: number) => void;
  tree: TreeNode | null;
  noteKind: Record<string, string>;
  selectedNoteId: string | null;
  graph: GraphPayload | null;
  tags: TagCount[];
  stats: Stats | null;
  sourceFilter: string | null;
  activeTag: string | null;
  onSelectNote: (id: string) => void;
  onOpenIdea: (id: string) => void;
  onOpenFile: (f: OpenFile) => void;
  onSelectSource: (s: string | null) => void;
  onSelectTag: (t: string) => void;
  onJob: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);

  if (!open) {
    return (
      <div style={{ width: 32, flexShrink: 0, borderRight: `1px solid ${P.line}`, background: P.bg1, display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 10 }}>
        <span onClick={onToggle} title="Show explorer" style={{ cursor: "pointer", padding: 6 }}>
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M5 3l4 4-4 4" fill="none" stroke={P.mid} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </span>
      </div>
    );
  }

  const counts: Record<string, number> = {};
  for (const n of graph?.nodes ?? []) counts[n.source_kind] = (counts[n.source_kind] ?? 0) + 1;
  const indexed = stats?.notes.embedding_indexed ?? 0;
  const healthy = stats?.index_configured && (stats?.notes.embedding_failed ?? 0) === 0;
  const filtering = query.trim().length > 0;

  return (
    <div style={{ position: "relative", width, flexShrink: 0, borderRight: `1px solid ${P.line}`, background: P.bg1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <ResizeHandle side="left" width={width} onResize={onResize} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px 6px" }}>
        <span style={{ fontFamily: P.mono, fontSize: 10, letterSpacing: 1.2, color: P.faint, textTransform: "uppercase" }}>Explorer</span>
        <span onClick={onToggle} title="Collapse" style={{ cursor: "pointer" }}>
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M9 3L5 7l4 4" fill="none" stroke={P.lo} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </span>
      </div>

      <div style={{ padding: "2px 12px 8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, height: 32, background: filtering ? P.accentDim : P.bg2, border: `1px solid ${filtering ? P.accent : P.line}`, borderRadius: 7, padding: "0 10px" }}>
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke={P.lo} strokeWidth="1.5"><circle cx="5.5" cy="5.5" r="4" /><path d="M9 9l3 3" strokeLinecap="round" /></svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter files by name…"
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: P.hi, fontFamily: P.sans, fontSize: 12.5 }}
          />
          {filtering && (
            <span onClick={() => setQuery("")} title="Clear" style={{ fontFamily: P.mono, fontSize: 11, color: P.lo, cursor: "pointer" }}>×</span>
          )}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        <FileTree root={tree} filter={query} selectedNoteId={selectedNoteId} noteKind={noteKind} onSelectNote={onSelectNote} onOpenIdea={onOpenIdea} onOpenFile={onOpenFile} />

        <SectionHead open={filtersOpen} onClick={() => setFiltersOpen((o) => !o)}>Filters</SectionHead>
        {filtersOpen && (
          <div style={{ padding: "0 4px 8px" }}>
            <FilterRow glyph="◇" label="All notes" active={!sourceFilter && !activeTag} onClick={() => onSelectSource(null)} />
            <FilterRow glyph="★" label="Job-relevant" count={(graph?.nodes ?? []).filter((n) => n.job_relevant).length} onClick={onJob} />
            <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "8px 12px 4px" }}>BY SOURCE</div>
            {KNOWN_SOURCES.map((kind) => (
              <FilterRow
                key={kind}
                color={srcColor(kind)}
                label={srcLabel(kind)}
                count={counts[kind] ?? 0}
                active={sourceFilter === kind}
                onClick={() => onSelectSource(sourceFilter === kind ? null : kind)}
              />
            ))}
            <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "8px 12px 4px" }}>TAGS</div>
            {tags.slice(0, 12).map((t) => (
              <FilterRow key={t.tag} glyph="≈" label={t.tag} count={t.count} active={activeTag === t.tag} onClick={() => onSelectTag(t.tag)} />
            ))}
            {tags.length === 0 && <div style={{ padding: "4px 14px", fontFamily: P.sans, fontSize: 12, color: P.faint }}>No tags yet.</div>}
          </div>
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
