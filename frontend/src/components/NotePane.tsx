import { useState } from "react";
import { P } from "../theme";
import type { NoteDetail } from "../types";
import { ScoreMeter } from "./ScoreMeter";
import { SourceBadge } from "./SourceBadge";
import { Spinner } from "./Spinner";

const PANEL = 392;
const SCORE_ORDER = ["novelty", "relevance", "credibility", "actionability", "interest", "overall"];

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4 }}>
      {children}
    </span>
  );
}

function strField(s: Record<string, unknown>, k: string): string {
  const v = s[k];
  return typeof v === "string" ? v : "";
}

function listField(s: Record<string, unknown>, k: string): string[] {
  const v = s[k];
  return Array.isArray(v) ? v.map((x) => String(x)).filter(Boolean) : [];
}

export function NotePane({
  note,
  loading,
  busy,
  onSelectRelated,
  onReprocess,
  onDelete,
  onEditTags,
}: {
  note: NoteDetail | null;
  loading: boolean;
  busy: boolean;
  onSelectRelated: (id: string) => void;
  onReprocess: (id: string) => void;
  onDelete: (id: string) => void;
  onEditTags: (id: string, tags: string[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const wrap = (children: React.ReactNode) => (
    <div
      style={{
        width: PANEL,
        flexShrink: 0,
        borderLeft: `1px solid ${P.line}`,
        background: P.bg1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      {children}
    </div>
  );

  if (loading) return wrap(<div style={{ padding: 24 }}><Spinner label="Loading note…" /></div>);
  if (!note)
    return wrap(
      <div style={{ padding: 24, fontFamily: P.sans, fontSize: 13, color: P.faint }}>
        Select a node to inspect a note.
      </div>,
    );

  const s = note.structured_summary;
  const summary = strField(s, "quick_summary") || note.summary;
  const claims = listField(s, "key_claims").slice(0, 6);
  const captured = note.date_saved?.slice(0, 10) ?? "";
  const scores = SCORE_ORDER.filter((k) => note.scores[k] != null);

  const startEdit = () => {
    setDraft(note.tags.join(", "));
    setEditing(true);
  };
  const saveEdit = () => {
    const tags = draft.split(",").map((t) => t.trim()).filter(Boolean);
    onEditTags(note.id, tags);
    setEditing(false);
  };

  return wrap(
    <>
      <div style={{ padding: "18px 20px 14px", borderBottom: `1px solid ${P.line}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <SourceBadge kind={note.source_kind} />
          <a
            href={note.source_url}
            target="_blank"
            rel="noreferrer"
            style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}
          >
            {note.source_url.replace(/^https?:\/\//, "")}
          </a>
          <span style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 10, color: P.faint }}>captured {captured}</span>
        </div>
        <div style={{ fontFamily: P.sans, fontSize: 21, fontWeight: 600, lineHeight: 1.25, letterSpacing: -0.2, marginBottom: 14, color: P.hi }}>
          {note.title}
        </div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {scores.map((k) => (
            <div key={k}>
              <Label>{k}</Label>
              <div style={{ marginTop: 4 }}>
                <ScoreMeter value={note.scores[k]} w={56} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <Label>Summary</Label>
          <p style={{ fontFamily: P.sans, fontSize: 13.5, lineHeight: 1.6, color: P.mid, margin: "8px 0 0" }}>{summary}</p>
        </div>

        {claims.length > 0 && (
          <div>
            <Label>Key claims</Label>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 7 }}>
              {claims.map((c, i) => (
                <div key={i} style={{ display: "flex", gap: 9 }}>
                  <span style={{ fontFamily: P.mono, fontSize: 11, color: P.accent, lineHeight: 1.5 }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontFamily: P.sans, fontSize: 12.5, lineHeight: 1.5, color: P.hi }}>{c}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {note.related_notes.length > 0 && (
          <div>
            <Label>Backlinks</Label>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
              {note.related_notes.map((l) => (
                <div
                  key={l.id}
                  onClick={() => onSelectRelated(l.id)}
                  title={l.reason}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 9,
                    padding: "7px 9px",
                    borderRadius: 7,
                    background: P.bg2,
                    border: `1px solid ${P.line}`,
                    cursor: "pointer",
                  }}
                >
                  <span style={{ fontFamily: P.sans, fontSize: 12.5, color: P.hi, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {l.title}
                  </span>
                  <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>→</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <Label>Tags</Label>
            <span onClick={editing ? saveEdit : startEdit} style={{ fontFamily: P.mono, fontSize: 10, color: P.accent, cursor: "pointer" }}>
              {editing ? "save" : "edit"}
            </span>
          </div>
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
                <span key={t} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, padding: "3px 8px", borderRadius: 5, background: P.bg2, border: `1px solid ${P.line}` }}>
                  {t}
                </span>
              ))}
              {note.tags.length === 0 && <span style={{ fontFamily: P.sans, fontSize: 12, color: P.faint }}>No tags.</span>}
            </div>
          )}
        </div>
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
