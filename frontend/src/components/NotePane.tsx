import { useState } from "react";
import { P } from "../theme";
import type { NoteDetail } from "../types";
import { SourceBadge } from "./SourceBadge";
import { Spinner } from "./Spinner";
import { NoteSkeleton } from "./Skeleton";
import { ResizeHandle } from "./ResizeHandle";

const REVIEW_STATUSES = ["unreviewed", "reviewed", "archived"] as const;

const SCORE_ABBR: Record<string, string> = {
  novelty: "nov",
  relevance: "rel",
  credibility: "cre",
  actionability: "act",
  interest: "int",
};

function fmtScore(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

function strField(s: Record<string, unknown>, k: string): string {
  const v = s[k];
  return typeof v === "string" ? v : "";
}
function listField(s: Record<string, unknown>, k: string): string[] {
  const v = s[k];
  return Array.isArray(v) ? v.map((x) => String(x)).filter(Boolean) : [];
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4 }}>
      {children}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.1s", flexShrink: 0 }}>
      <path d="M3 2l4 3-4 3" fill="none" stroke={P.lo} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Section({ title, defaultOpen, action, children }: { title: string; defaultOpen?: boolean; action?: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div style={{ borderTop: `1px solid ${P.line}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 0" }}>
        <div onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flex: 1 }}>
          <Chevron open={open} />
          <Label>{title}</Label>
        </div>
        {action}
      </div>
      {open && <div style={{ paddingBottom: 14 }}>{children}</div>}
    </div>
  );
}

function TextBlock({ children }: { children: string }) {
  return <p style={{ fontFamily: P.sans, fontSize: 13.5, lineHeight: 1.6, color: P.mid, margin: 0 }}>{children}</p>;
}

function Bullets({ items }: { items: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {items.map((c, i) => (
        <div key={i} style={{ display: "flex", gap: 9 }}>
          <span style={{ color: P.lo, lineHeight: 1.5 }}>•</span>
          <span style={{ fontFamily: P.sans, fontSize: 12.5, lineHeight: 1.5, color: P.mid }}>{c}</span>
        </div>
      ))}
    </div>
  );
}

export function NotePane({
  note,
  loading,
  busy,
  reprocessing,
  open,
  onToggle,
  width,
  onResize,
  onSelectRelated,
  onShowRelated,
  onReprocess,
  onDelete,
  onEditTags,
  onEditTitle,
  onSetStatus,
  onSelectTag,
  onSetJobFlag,
}: {
  note: NoteDetail | null;
  loading: boolean;
  busy: boolean;
  reprocessing: boolean;
  open: boolean;
  onToggle: () => void;
  width: number;
  onResize: (w: number) => void;
  onSelectRelated: (id: string) => void;
  onShowRelated: (id: string) => void;
  onReprocess: (id: string) => void;
  onDelete: (id: string) => void;
  onEditTags: (id: string, tags: string[]) => void;
  onEditTitle: (id: string, title: string) => void;
  onSetStatus: (id: string, status: string) => void;
  onSelectTag: (tag: string) => void;
  onSetJobFlag: (id: string, value: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const wrap = (children: React.ReactNode) => (
    <div
      style={{
        position: "relative",
        width,
        flexShrink: 0,
        borderLeft: `1px solid ${P.line}`,
        background: P.bg1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <ResizeHandle side="right" width={width} onResize={onResize} />
      <div style={{ display: "flex", alignItems: "center", height: 28, padding: "0 10px", flexShrink: 0 }}>
        <span onClick={onToggle} title="Collapse" style={{ cursor: "pointer", padding: 4 }}>
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M5 3l4 4-4 4" fill="none" stroke={P.lo} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </span>
      </div>
      {children}
    </div>
  );

  if (!open) {
    return (
      <div style={{ width: 32, flexShrink: 0, borderLeft: `1px solid ${P.line}`, background: P.bg1, display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 10 }}>
        <span onClick={onToggle} title="Show note" style={{ cursor: "pointer", padding: 6 }}>
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M9 3L5 7l4 4" fill="none" stroke={P.mid} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </span>
      </div>
    );
  }

  if (loading || reprocessing) return wrap(<NoteSkeleton />);
  if (!note)
    return wrap(
      <div style={{ padding: 24, fontFamily: P.sans, fontSize: 13, color: P.faint }}>
        Select a node to inspect a note.
      </div>,
    );

  const s = note.structured_summary;
  const summary = strField(s, "quick_summary") || note.summary;
  const claims = listField(s, "key_claims");
  const captured = note.date_saved?.slice(0, 10) ?? "";
  const overall = note.scores.overall;
  const restScores = ["novelty", "relevance", "credibility", "actionability", "interest"].filter((k) => note.scores[k] != null);
  const overallColor = overall == null ? P.mid : overall >= 7.5 ? P.pdf : overall >= 5 ? P.accent : P.arxiv;

  const detailed = strField(s, "detailed_summary");
  const whyMatters = strField(s, "why_it_matters");
  const personal = strField(s, "personal_relevance");
  const technical = listField(s, "technical_details");
  const limitations = listField(s, "limitations");
  const projectIdeas = listField(s, "project_ideas");

  const startEdit = () => {
    setDraft(note.tags.join(", "));
    setEditing(true);
  };
  const saveEdit = () => {
    const tags = draft.split(",").map((t) => t.trim()).filter(Boolean);
    onEditTags(note.id, tags);
    setEditing(false);
  };

  const startTitleEdit = () => {
    setTitleDraft(note.title);
    setTitleEditing(true);
  };
  const saveTitleEdit = () => {
    const next = titleDraft.trim();
    if (next && next !== note.title) onEditTitle(note.id, next);
    setTitleEditing(false);
  };

  return wrap(
    <>
      <div style={{ padding: "8px 20px 16px", borderBottom: `1px solid ${P.line}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <SourceBadge kind={note.source_kind} />
          <a
            href={note.source_url}
            target="_blank"
            rel="noreferrer"
            style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }}
          >
            {note.source_url.replace(/^https?:\/\//, "")}
          </a>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
            <span
              onClick={() => !busy && onSetJobFlag(note.id, !note.job_relevant)}
              title={note.job_relevant ? "Flagged as job-relevant — click to unflag" : "Flag as relevant to your job"}
              style={{ fontSize: 14, lineHeight: 1, color: note.job_relevant ? "#ffd66e" : P.lo, cursor: "pointer" }}
            >
              {note.job_relevant ? "★" : "☆"}
            </span>
            <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint }}>captured {captured}</span>
            <span onClick={() => onShowRelated(note.id)} title="Highlight related notes in the graph" style={{ fontFamily: P.mono, fontSize: 11, color: P.accent, cursor: "pointer" }}>related</span>
          </div>
        </div>
        {titleEditing ? (
          <input
            value={titleDraft}
            autoFocus
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={saveTitleEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveTitleEdit();
              if (e.key === "Escape") setTitleEditing(false);
            }}
            style={{ width: "100%", background: P.bg2, border: `1px solid ${P.line}`, borderRadius: 6, padding: "6px 9px", marginBottom: 14, color: P.hi, fontFamily: P.sans, fontSize: 21, fontWeight: 600, lineHeight: 1.25, letterSpacing: -0.2, outline: "none" }}
          />
        ) : (
          <div
            onDoubleClick={startTitleEdit}
            title="Double-click to rename"
            style={{ fontFamily: P.sans, fontSize: 21, fontWeight: 600, lineHeight: 1.25, letterSpacing: -0.2, marginBottom: 14, color: P.hi, cursor: "text" }}
          >
            {note.title}
          </div>
        )}
        {(overall != null || restScores.length > 0) && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
            {overall != null && (
              <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
                <span style={{ fontFamily: P.mono, fontSize: 10, letterSpacing: 1, color: P.faint }}>OVERALL</span>
                <span style={{ fontFamily: P.sans, fontSize: 18, fontWeight: 600, color: overallColor }}>{overall.toFixed(1)}</span>
              </div>
            )}
            {restScores.length > 0 && (
              <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid }}>
                {restScores.map((k) => `${SCORE_ABBR[k]} ${fmtScore(note.scores[k])}`).join("  ·  ")}
              </span>
            )}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 12 }}>
          {REVIEW_STATUSES.map((st) => {
            const active = note.status === st;
            return (
              <span
                key={st}
                onClick={() => !active && !busy && onSetStatus(note.id, st)}
                title="Set review status"
                style={{
                  fontFamily: P.mono,
                  fontSize: 10,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  padding: "3px 8px",
                  borderRadius: 5,
                  cursor: active ? "default" : "pointer",
                  color: active ? P.hi : P.faint,
                  background: active ? P.bg2 : "transparent",
                  border: `1px solid ${active ? P.accent : P.line}`,
                }}
              >
                {st}
              </span>
            );
          })}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "0 20px 16px" }}>
        {summary && <Section title="Summary" defaultOpen><TextBlock>{summary}</TextBlock></Section>}
        {detailed && <Section title="Detailed summary" defaultOpen><TextBlock>{detailed}</TextBlock></Section>}

        {claims.length > 0 && (
          <Section title="Key claims" defaultOpen>
            <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              {claims.map((c, i) => (
                <div key={i} style={{ display: "flex", gap: 9 }}>
                  <span style={{ fontFamily: P.mono, fontSize: 11, color: P.accent, lineHeight: 1.5 }}>{String(i + 1).padStart(2, "0")}</span>
                  <span style={{ fontFamily: P.sans, fontSize: 12.5, lineHeight: 1.5, color: P.hi }}>{c}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {whyMatters && <Section title="Why it matters"><TextBlock>{whyMatters}</TextBlock></Section>}
        {personal && <Section title="Personal relevance"><TextBlock>{personal}</TextBlock></Section>}
        {technical.length > 0 && <Section title="Technical details"><Bullets items={technical} /></Section>}
        {limitations.length > 0 && <Section title="Limitations"><Bullets items={limitations} /></Section>}
        {projectIdeas.length > 0 && <Section title="Project ideas"><Bullets items={projectIdeas} /></Section>}

        {note.related_notes.length > 0 && (
          <Section title="Backlinks" defaultOpen>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {note.related_notes.map((l) => (
                <div
                  key={l.id}
                  onClick={() => onSelectRelated(l.id)}
                  title={l.reason}
                  style={{ display: "flex", alignItems: "center", gap: 9, padding: "7px 9px", borderRadius: 7, background: P.bg2, border: `1px solid ${P.line}`, cursor: "pointer" }}
                >
                  <span style={{ fontFamily: P.sans, fontSize: 12.5, color: P.hi, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.title}</span>
                  <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>→</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        <Section
          title="Tags"
          defaultOpen
          action={
            <span onClick={editing ? saveEdit : startEdit} style={{ fontFamily: P.mono, fontSize: 10, color: P.accent, cursor: "pointer" }}>
              {editing ? "save" : "edit"}
            </span>
          }
        >
          {editing ? (
            <input
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveEdit()}
              placeholder="comma, separated, tags"
              style={{ width: "100%", background: P.bg2, border: `1px solid ${P.line}`, borderRadius: 6, padding: "7px 9px", color: P.hi, fontFamily: P.sans, fontSize: 12.5, outline: "none" }}
            />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {note.tags.map((t) => (
                <span
                  key={t}
                  onClick={() => onSelectTag(t)}
                  title={`Filter notes tagged “${t}”`}
                  style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, padding: "3px 8px", borderRadius: 5, background: P.bg2, border: `1px solid ${P.line}`, cursor: "pointer" }}
                >
                  {t}
                </span>
              ))}
              {note.tags.length === 0 && <span style={{ fontFamily: P.sans, fontSize: 12, color: P.faint }}>No tags.</span>}
            </div>
          )}
        </Section>

        <Section title="Source & metadata">
          <div style={{ display: "flex", flexDirection: "column", gap: 5, fontFamily: P.mono, fontSize: 11, color: P.mid }}>
            <Meta label="url" value={note.source_url} />
            {note.resolved_url !== note.source_url && <Meta label="resolved" value={note.resolved_url} />}
            <Meta label="saved" value={note.date_saved} />
            {note.fetched_at && <Meta label="fetched" value={note.fetched_at} />}
            <Meta label="kind" value={note.source_kind} />
            {note.llm_model && <Meta label="model" value={note.llm_model} />}
            <Meta label="status" value={`fetch:${note.fetch_status} · llm:${note.llm_status} · embed:${note.embedding_status}`} />
            {note.embedding_dimensions != null && <Meta label="dims" value={String(note.embedding_dimensions)} />}
          </div>
        </Section>
      </div>

      <div style={{ padding: "12px 20px", borderTop: `1px solid ${P.line}`, display: "flex", alignItems: "center", gap: 10 }}>
        {busy && <Spinner size={13} />}
        <span onClick={() => !busy && onReprocess(note.id)} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, cursor: "pointer" }}>
          reprocess
        </span>
        <span
          onClick={() => !busy && confirm(`Delete "${note.title}"?`) && onDelete(note.id)}
          style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 11, color: P.arxiv, cursor: "pointer" }}
        >
          delete
        </span>
      </div>
    </>,
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <span style={{ color: P.faint, minWidth: 56 }}>{label}</span>
      <span style={{ color: P.mid, wordBreak: "break-all" }}>{value}</span>
    </div>
  );
}
