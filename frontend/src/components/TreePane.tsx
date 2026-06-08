import { useState } from "react";
import { P, srcColor, srcLabel, topicColor } from "../theme";
import type { GraphPayload, Stats, TagCount, TreeNode, Usage } from "../types";
import { FileTree } from "./FileTree";
import type { OpenFile } from "./FileViewer";
import { ResizeHandle } from "./ResizeHandle";
import { TagManager } from "./TagManager";
import { usePersistentToggle } from "../hooks/usePersistentToggle";

const KNOWN_SOURCES = ["paper", "github", "huggingface", "youtube", "pdf", "website"];
// "Min age" slider stops: window of days to keep (0 = all). Far left = all,
// moving right narrows toward the newest notes.
const AGE_BUCKETS = [0, 365, 180, 90, 30, 14, 7, 3, 1];
const AGE_LABELS = ["all", "1y", "180d", "90d", "30d", "14d", "7d", "3d", "1d"];

function Mono({ children, c = P.mid }: { children: React.ReactNode; c?: string }) {
  return <span style={{ fontFamily: P.mono, fontSize: 11, color: c }}>{children}</span>;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
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

function FilterRow({ label, count, color, glyph, active, onClick }: { label: string; count?: number; color?: string; glyph?: string; active?: boolean; onClick?: (e: React.MouseEvent<HTMLDivElement>) => void }) {
  return (
    <div
      onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 9, padding: "5px 10px", paddingLeft: 14, borderRadius: 6, background: active ? P.accentDim : "transparent", cursor: "pointer", color: active ? P.hi : P.mid }}
    >
      {color ? (
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
      ) : (
        <span style={{ fontFamily: P.mono, fontSize: 11, color: active ? P.hi : P.lo, width: 7, textAlign: "center" }}>{glyph}</span>
      )}
      <span style={{ fontFamily: P.sans, fontSize: 13, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
      {count != null && <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>{count}</span>}
    </div>
  );
}

const additive = (e: React.MouseEvent) => e.ctrlKey || e.metaKey;

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
  sourceFilters,
  tagFilters,
  topicFilters,
  flagFilters,
  minAgeDays,
  minScore,
  usage,
  onSelectNote,
  onOpenIdea,
  onOpenFile,
  onSelectSource,
  onSelectTag,
  onSelectTopic,
  onToggleFlagFilter,
  onClearFilters,
  onMinAgeDays,
  onMinScore,
  onTagsChanged,
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
  sourceFilters: string[];
  tagFilters: string[];
  topicFilters: number[];
  flagFilters: string[];
  minAgeDays: number;
  minScore: number;
  usage: Usage | null;
  onSelectNote: (id: string) => void;
  onOpenIdea: (id: string) => void;
  onOpenFile: (f: OpenFile) => void;
  onSelectSource: (s: string, additive?: boolean) => void;
  onSelectTag: (t: string, additive?: boolean) => void;
  onSelectTopic: (topic: number, additive?: boolean) => void;
  onToggleFlagFilter: (flag: string, additive?: boolean) => void;
  onClearFilters: () => void;
  onMinAgeDays: (v: number) => void;
  onMinScore: (v: number) => void;
  onTagsChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const [managingTags, setManagingTags] = useState(false);
  const [filtersOpen, toggleFilters] = usePersistentToggle("prism.tree.filters", true);

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
  const topicCounts = new Map<number, number>();
  for (const n of graph?.nodes ?? []) {
    counts[n.source_kind] = (counts[n.source_kind] ?? 0) + 1;
    if (n.topic >= 0) topicCounts.set(n.topic, (topicCounts.get(n.topic) ?? 0) + 1);
  }
  const topicOptions = [...topicCounts.entries()]
    .sort(([aTopic, aCount], [bTopic, bCount]) => bCount - aCount || aTopic - bTopic)
    .map(([topic, count]) => ({ topic, count, label: graph?.topic_labels?.[String(topic)] ?? `topic ${topic + 1}` }));
  const indexed = stats?.notes.embedding_indexed ?? 0;
  const healthy = stats?.index_configured && (stats?.notes.embedding_failed ?? 0) === 0;
  const llmHealthy = stats?.llm_configured && (stats?.notes.llm_failed ?? 0) === 0;
  const filtering = query.trim().length > 0;
  const fanoutActive = sourceFilters.length > 0 || tagFilters.length > 0 || topicFilters.length > 0 || flagFilters.length > 0 || minAgeDays > 0 || minScore > 0;

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
            placeholder="Filter files by name..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: P.hi, fontFamily: P.sans, fontSize: 12.5 }}
          />
          {filtering && (
            <span onClick={() => setQuery("")} title="Clear" style={{ fontFamily: P.mono, fontSize: 11, color: P.lo, cursor: "pointer" }}>x</span>
          )}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        <FileTree root={tree} filter={query} selectedNoteId={selectedNoteId} noteKind={noteKind} onSelectNote={onSelectNote} onOpenIdea={onOpenIdea} onOpenFile={onOpenFile} />

        <SectionHead open={filtersOpen} onClick={toggleFilters}>Filters</SectionHead>
        {filtersOpen && (
          <div style={{ padding: "0 4px 8px" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "0 10px 4px 14px" }}>
              <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, flex: 1 }}>Ctrl-click to combine</span>
              {fanoutActive && <span onClick={onClearFilters} style={{ fontFamily: P.mono, fontSize: 10, color: P.mid, cursor: "pointer" }}>clear</span>}
            </div>
            <FilterRow glyph="◇" label="All notes" active={!fanoutActive} onClick={onClearFilters} />
            <FilterRow glyph="★" label="Favorites" count={(graph?.nodes ?? []).filter((n) => n.favorite).length} active={flagFilters.includes("favorite")} onClick={(e) => onToggleFlagFilter("favorite", additive(e))} />
            <FilterRow glyph="?" label="Unreviewed" count={stats?.notes.unreviewed ?? 0} active={flagFilters.includes("unreviewed")} onClick={(e) => onToggleFlagFilter("unreviewed", additive(e))} />
            <FilterRow glyph="!" label="Needs attention" count={(graph?.nodes ?? []).filter((n) => n.failed).length} active={flagFilters.includes("failed")} onClick={(e) => onToggleFlagFilter("failed", additive(e))} />
            <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "8px 12px 4px" }}>BY SOURCE</div>
            {KNOWN_SOURCES.map((kind) => (
              <FilterRow
                key={kind}
                color={srcColor(kind)}
                label={srcLabel(kind)}
                count={counts[kind] ?? 0}
                active={sourceFilters.includes(kind)}
                onClick={(e) => onSelectSource(kind, additive(e))}
              />
            ))}
            {topicOptions.length > 0 && (
              <>
                <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "8px 12px 4px" }}>TOPICS</div>
                {topicOptions.map((t) => (
                  <FilterRow key={t.topic} color={topicColor(t.topic)} label={t.label} count={t.count} active={topicFilters.includes(t.topic)} onClick={(e) => onSelectTopic(t.topic, additive(e))} />
                ))}
              </>
            )}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px 4px" }}>
              <span style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint }}>TAGS</span>
              {tags.length > 0 && (
                <span onClick={() => setManagingTags(true)} title="Delete or merge tags" style={{ fontFamily: P.mono, fontSize: 10, color: P.mid, cursor: "pointer" }}>manage</span>
              )}
            </div>
            {tags.slice(0, 12).map((t) => (
              <FilterRow key={t.tag} glyph="#" label={t.tag} count={t.count} active={tagFilters.includes(t.tag)} onClick={(e) => onSelectTag(t.tag, additive(e))} />
            ))}
            {tags.length === 0 && <div style={{ padding: "4px 14px", fontFamily: P.sans, fontSize: 12, color: P.faint }}>No tags yet.</div>}

            <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "10px 12px 4px" }}>MIN AGE</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 14px 4px" }}>
              <input
                type="range"
                min={0}
                max={AGE_BUCKETS.length - 1}
                step={1}
                value={Math.max(0, AGE_BUCKETS.indexOf(minAgeDays))}
                onChange={(e) => onMinAgeDays(AGE_BUCKETS[Number(e.target.value)])}
                style={{ flex: 1, accentColor: P.mid }}
              />
              <span style={{ fontFamily: P.mono, fontSize: 11, color: minAgeDays > 0 ? P.hi : P.lo, width: 30, textAlign: "right" }}>
                {AGE_LABELS[Math.max(0, AGE_BUCKETS.indexOf(minAgeDays))]}
              </span>
            </div>

            <div style={{ fontFamily: P.mono, fontSize: 9, letterSpacing: 1, color: P.faint, padding: "10px 12px 4px" }}>MIN SCORE</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 14px 4px" }}>
              <input type="range" min={0} max={10} step={1} value={minScore} onChange={(e) => onMinScore(Number(e.target.value))} style={{ flex: 1, accentColor: P.mid }} />
              <span style={{ fontFamily: P.mono, fontSize: 11, color: minScore > 0 ? P.hi : P.lo, width: 30, textAlign: "right" }}>{minScore > 0 ? `>=${minScore}` : "off"}</span>
            </div>
          </div>
        )}
      </div>

      <div style={{ padding: "12px 14px", borderTop: `1px solid ${P.line}`, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }} title={stats?.llm_model ?? "no LLM configured"}>
          <Mono>llm</Mono>
          <Mono c={!stats?.llm_configured ? P.lo : llmHealthy ? P.pdf : P.arxiv}>
            ● {stats?.llm_configured ? (llmHealthy ? "healthy" : `${stats?.notes.llm_failed ?? 0} failed`) : "off"}
          </Mono>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Mono>index</Mono>
          <Mono c={healthy ? P.pdf : P.arxiv}>● {stats?.index_configured ? (healthy ? "healthy" : "errors") : "off"}</Mono>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Mono>{indexed} vecs</Mono>
          <Mono c={P.lo}>{stats?.embedding_model ?? "no model"}</Mono>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }} title={`${usage?.calls ?? 0} calls total · ${usage?.today_calls ?? 0} today`}>
          <Mono>tokens</Mono>
          <Mono c={P.lo}>{fmtTokens(usage?.total_tokens ?? 0)} · today {fmtTokens(usage?.today_total_tokens ?? 0)}</Mono>
        </div>
      </div>

      {managingTags && (
        <TagManager tags={tags} onClose={() => setManagingTags(false)} onChanged={onTagsChanged} />
      )}
    </div>
  );
}
