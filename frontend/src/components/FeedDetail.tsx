import { useEffect, useState } from "react";
import { Check, ChevronLeft, ExternalLink, Pencil } from "lucide-react";
import { api } from "../api";
import { P, srcColor, srcLabel } from "../theme";
import { PURPOSES } from "../types";
import type { NoteDetail } from "../types";
import { ImageGallery } from "./ImageGallery";
import { Spinner } from "./Spinner";

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
    <div style={{ fontFamily: P.mono, fontSize: 11, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4, marginBottom: 8 }}>
      {children}
    </div>
  );
}
function Para({ children }: { children: string }) {
  return <p style={{ fontFamily: P.sans, fontSize: 15, lineHeight: 1.65, color: P.mid, margin: 0 }}>{children}</p>;
}
function Bullets({ items }: { items: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {items.map((c, i) => (
        <div key={i} style={{ display: "flex", gap: 9 }}>
          <span style={{ color: P.lo, lineHeight: 1.5 }}>•</span>
          <span style={{ fontFamily: P.sans, fontSize: 14, lineHeight: 1.55, color: P.mid }}>{c}</span>
        </div>
      ))}
    </div>
  );
}
function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Label>{label}</Label>
      {children}
    </div>
  );
}

/**
 * Full-screen reader for a single note's PRISM summary (mobile feed).
 * Fetches the full NoteDetail, renders the generated summary, and lets the
 * reader mark it read, edit its classification (title/purpose/tags), or jump
 * to the original source. Edits persist via the same REST endpoints the Atlas
 * UI uses; `onChanged` lets the feed list reflect them without a full reload.
 */
export function FeedDetail({
  noteId,
  onClose,
  onRead,
  onChanged,
}: {
  noteId: string;
  onClose: () => void;
  onRead: (id: string) => void;
  onChanged?: (note: NoteDetail) => void;
}) {
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [tagsDraft, setTagsDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setEditing(false);
    api
      .note(noteId)
      .then((n) => {
        if (cancelled) return;
        setNote(n);
        setTitleDraft(n.title);
        setTagsDraft(n.tags.join(", "));
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  function applyUpdate(updated: NoteDetail) {
    setNote(updated);
    setTitleDraft(updated.title);
    setTagsDraft(updated.tags.join(", "));
    onChanged?.(updated);
  }

  async function run(fn: () => Promise<NoteDetail>) {
    setSaving(true);
    setError(null);
    try {
      applyUpdate(await fn());
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function savePurpose(p: string | null) {
    if (!note || saving) return;
    await run(() => api.setPurpose(note.id, p));
  }
  async function saveTitle() {
    if (!note) return;
    const t = titleDraft.trim();
    if (!t || t === note.title) return;
    await run(() => api.editTitle(note.id, t));
  }
  async function saveTags() {
    if (!note) return;
    const tags = tagsDraft.split(",").map((x) => x.trim()).filter(Boolean);
    if (tags.join("|") === note.tags.join("|")) return;
    await run(() => api.editTags(note.id, tags));
  }

  const s = note?.structured_summary ?? {};
  const detailed = strField(s, "detailed_summary");
  const quick = strField(s, "quick_summary") || note?.summary || "";
  const claims = listField(s, "key_claims");
  const whyMatters = strField(s, "why_it_matters");
  const personal = strField(s, "personal_relevance");
  const technical = listField(s, "technical_details");
  const limitations = listField(s, "limitations");
  const projectIdeas = listField(s, "project_ideas");
  const read = !!note?.date_reviewed;

  const inputStyle: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    background: P.bg1,
    border: `1px solid ${P.line}`,
    borderRadius: 8,
    padding: "10px 12px",
    color: P.hi,
    fontFamily: P.sans,
    fontSize: 15,
    outline: "none",
  };

  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 25, background: P.bg0, display: "flex", flexDirection: "column" }}>
      {/* Header bar */}
      <div style={{ flexShrink: 0, height: 52, display: "flex", alignItems: "center", gap: 10, padding: "0 10px", borderBottom: `1px solid ${P.line}`, background: P.bg0 }}>
        <button
          onClick={onClose}
          title="Back"
          style={{ display: "inline-flex", alignItems: "center", minHeight: 44, minWidth: 44, justifyContent: "center", background: "transparent", border: "none", color: P.mid, cursor: "pointer" }}
        >
          <ChevronLeft size={22} />
        </button>
        {note && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontFamily: P.mono, fontSize: 12.5, color: P.lo }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: srcColor(note.source_kind) }} />
            {srcLabel(note.source_kind)}
          </span>
        )}
        {note && (
          <button
            onClick={() => setEditing((e) => !e)}
            title={editing ? "Done editing" : "Edit note"}
            style={{
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              minHeight: 44,
              padding: "0 10px",
              background: "transparent",
              border: "none",
              color: editing ? P.accent : P.lo,
              fontFamily: P.mono,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <Pencil size={16} strokeWidth={2} />
            {editing ? "Done" : "Edit"}
          </button>
        )}
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch", padding: "18px 18px 96px" }}>
        {error && (
          <div style={{ fontFamily: P.sans, fontSize: 13.5, color: P.arxiv, maxWidth: 720, margin: "0 auto 14px" }}>{error}</div>
        )}
        {!note && !error ? (
          <div style={{ paddingTop: 40, display: "flex", justifyContent: "center" }}>
            <Spinner label="Loading…" />
          </div>
        ) : note ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 720, margin: "0 auto" }}>
            {editing && (
              <div style={{ display: "flex", flexDirection: "column", gap: 18, padding: 16, background: P.bg1, border: `1px solid ${P.line}`, borderRadius: 12 }}>
                <div>
                  <Label>Title</Label>
                  <textarea
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    onBlur={saveTitle}
                    rows={2}
                    style={{ ...inputStyle, resize: "vertical", lineHeight: 1.4 }}
                  />
                </div>
                <div>
                  <Label>Purpose</Label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
                    {PURPOSES.map((pp) => {
                      const active = note.purpose === pp;
                      return (
                        <button
                          key={pp}
                          onClick={() => savePurpose(active ? null : pp)}
                          disabled={saving}
                          style={{
                            fontFamily: P.mono,
                            fontSize: 12,
                            letterSpacing: 0.4,
                            padding: "7px 12px",
                            borderRadius: 7,
                            cursor: saving ? "default" : "pointer",
                            color: active ? P.hi : P.lo,
                            background: active ? P.bg2 : "transparent",
                            border: `1px solid ${active ? P.accent : P.line}`,
                          }}
                        >
                          {pp}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <Label>Tags</Label>
                  <input
                    value={tagsDraft}
                    onChange={(e) => setTagsDraft(e.target.value)}
                    onBlur={saveTags}
                    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                    placeholder="comma, separated, tags"
                    style={{ ...inputStyle, fontFamily: P.mono, fontSize: 13 }}
                  />
                </div>
              </div>
            )}

            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12, fontFamily: P.mono, fontSize: 12.5, color: P.lo }}>
                {note.scores.overall != null && <span style={{ color: P.mid }}>{note.scores.overall.toFixed(1)}</span>}
                {note.reading_minutes != null && (<>{note.scores.overall != null && <span style={{ color: P.faint }}>·</span>}<span>~{note.reading_minutes} min</span></>)}
                {note.purpose && (<><span style={{ color: P.faint }}>·</span><span>{note.purpose}</span></>)}
              </div>
              <h1 style={{ fontFamily: P.sans, fontSize: 24, fontWeight: 700, lineHeight: 1.25, color: P.hi, margin: 0, letterSpacing: -0.3 }}>
                {note.title}
              </h1>
            </div>

            {quick && <Para>{quick}</Para>}
            {note.images && note.images.length > 0 && (
              <Block label={`Images (${note.images.length})`}><ImageGallery images={note.images} /></Block>
            )}
            {whyMatters && <Block label="Why it matters"><Para>{whyMatters}</Para></Block>}
            {detailed && <Block label="Detailed summary"><Para>{detailed}</Para></Block>}
            {claims.length > 0 && <Block label="Key claims"><Bullets items={claims} /></Block>}
            {personal && <Block label="Personal relevance"><Para>{personal}</Para></Block>}
            {projectIdeas.length > 0 && <Block label="Project ideas"><Bullets items={projectIdeas} /></Block>}
            {technical.length > 0 && <Block label="Technical details"><Bullets items={technical} /></Block>}
            {limitations.length > 0 && <Block label="Limitations"><Bullets items={limitations} /></Block>}

            {note.tags.length > 0 && (
              <div style={{ fontFamily: P.mono, fontSize: 13, color: P.faint, lineHeight: 1.7 }}>
                {note.tags.map((t) => `#${t}`).join("  ")}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Sticky action footer — quiet inline actions */}
      {note && (
        <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 28, padding: "14px 18px", borderTop: `1px solid ${P.line}`, background: P.bg0 }}>
          <button
            onClick={() => onRead(note.id)}
            disabled={read}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              minHeight: 44,
              background: "none",
              border: "none",
              padding: 0,
              color: read ? P.pdf : P.accent,
              fontFamily: P.mono,
              fontSize: 14,
              cursor: read ? "default" : "pointer",
            }}
          >
            <Check size={17} strokeWidth={2} />
            {read ? "Read" : "Mark read"}
          </button>
          <a
            href={note.source_url}
            target="_blank"
            rel="noreferrer"
            style={{ display: "inline-flex", alignItems: "center", gap: 8, minHeight: 44, color: P.mid, fontFamily: P.mono, fontSize: 14, textDecoration: "none" }}
          >
            <ExternalLink size={16} strokeWidth={2} />
            Open original
          </a>
        </div>
      )}
    </div>
  );
}
