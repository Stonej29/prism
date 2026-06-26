import { Check, ExternalLink } from "lucide-react";
import { P, srcColor, srcLabel } from "../theme";
import type { NoteSummary } from "../types";

function scoreColor(overall: number | null): string {
  if (overall == null) return P.lo;
  return overall >= 7.5 ? P.pdf : overall >= 5 ? P.mid : P.lo;
}

const dot = <span style={{ color: P.faint }}>·</span>;

/** A flat feed row: tap the body to read; quiet inline actions, no boxes. */
export function FeedCard({
  note,
  busy,
  onOpen,
  onRead,
}: {
  note: NoteSummary;
  busy: boolean;
  onOpen: () => void;
  onRead: () => void;
}) {
  const read = !!note.date_reviewed;
  return (
    <div style={{ padding: "16px 4px", borderBottom: `1px solid ${P.line}`, opacity: read ? 0.55 : 1 }}>
      <div onClick={onOpen} style={{ cursor: "pointer", display: "flex", gap: 12 }}>
       <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 7 }}>
        {/* Meta line */}
        <div style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: P.mono, fontSize: 12, color: P.lo }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: srcColor(note.source_kind), flexShrink: 0 }} />
          <span>{srcLabel(note.source_kind)}</span>
          {note.purpose && (<>{dot}<span>{note.purpose}</span></>)}
          {note.overall != null && (<>{dot}<span style={{ color: scoreColor(note.overall) }}>{note.overall.toFixed(1)}</span></>)}
          {read && (<><span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4, color: P.pdf }}><Check size={12} /> read</span></>)}
        </div>

        {/* Title */}
        <div style={{ fontFamily: P.sans, fontSize: 16, fontWeight: 600, lineHeight: 1.35, color: P.hi, letterSpacing: -0.1 }}>
          {note.title}
        </div>

        {/* Summary */}
        {note.summary && (
          <div
            style={{
              fontFamily: P.sans,
              fontSize: 14,
              lineHeight: 1.5,
              color: P.mid,
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {note.summary}
          </div>
        )}

        {/* Tags as quiet inline text */}
        {note.tags.length > 0 && (
          <div style={{ fontFamily: P.mono, fontSize: 12, color: P.faint, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {note.tags.slice(0, 4).map((t) => `#${t}`).join("  ")}
          </div>
        )}
       </div>
        {note.thumbnail && (
          <img
            src={note.thumbnail}
            loading="lazy"
            style={{ flexShrink: 0, width: 76, height: 76, objectFit: "cover", borderRadius: 8, border: `1px solid ${P.line}`, background: P.bg2 }}
          />
        )}
      </div>

      {/* Quiet action row */}
      <div style={{ display: "flex", alignItems: "center", gap: 22, marginTop: 10 }}>
        <button
          onClick={onRead}
          disabled={busy || read}
          title={read ? "Already read" : "Mark as read"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            background: "none",
            border: "none",
            padding: 0,
            cursor: busy || read ? "default" : "pointer",
            color: read ? P.pdf : P.lo,
            fontFamily: P.mono,
            fontSize: 12.5,
          }}
        >
          <Check size={15} strokeWidth={2} />
          {read ? "Read" : "Mark read"}
        </button>
        <a
          href={note.source_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="Open original"
          style={{ display: "inline-flex", alignItems: "center", gap: 6, color: P.lo, fontFamily: P.mono, fontSize: 12.5, textDecoration: "none" }}
        >
          <ExternalLink size={15} strokeWidth={2} />
          Open
        </a>
      </div>
    </div>
  );
}
