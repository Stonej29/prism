import { useState } from "react";
import { P } from "../theme";
import type { TagCount } from "../types";
import { api } from "../api";
import { Backdrop } from "./AskOverlay";
import { TextAction } from "./TextAction";

// Tag cleanup: delete an over-broad tag globally, or merge one tag into another
// across all notes. Two-step merge: pick a source, then click the target row.
export function TagManager({ tags, onClose, onChanged }: { tags: TagCount[]; onClose: () => void; onChanged: () => void }) {
  const [mergeSource, setMergeSource] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");

  const run = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      onChanged();
    } finally {
      setBusy(false);
      setMergeSource(null);
    }
  };

  const shown = tags.filter((t) => t.tag.includes(filter.trim().toLowerCase()));

  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{ fontFamily: P.mono, fontSize: 13, letterSpacing: 1, color: P.hi }}>Manage tags</span>
        <span onClick={onClose} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, cursor: "pointer" }}>close</span>
      </div>

      <div style={{ fontFamily: P.sans, fontSize: 12, color: P.faint, marginBottom: 12 }}>
        {mergeSource
          ? `Merging "${mergeSource}" → click the tag to fold it into, or cancel.`
          : "Delete a broad tag globally, or merge one tag into another."}
      </div>

      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter tags..."
        style={{ width: "100%", boxSizing: "border-box", background: P.bg2, border: `1px solid ${P.line}`, borderRadius: 6, padding: "7px 9px", color: P.hi, fontFamily: P.sans, fontSize: 12.5, outline: "none", marginBottom: 10 }}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: "48vh", overflowY: "auto" }}>
        {shown.map((t) => {
          const isSource = mergeSource === t.tag;
          return (
            <div
              key={t.tag}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 9px", borderRadius: 7, background: isSource ? P.accentDim : P.bg2, border: `1px solid ${isSource ? P.accent : P.line}` }}
            >
              <span style={{ fontFamily: P.mono, fontSize: 12.5, color: P.hi, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>#{t.tag}</span>
              <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>{t.count}</span>
              {mergeSource ? (
                isSource ? (
                  <TextAction onClick={() => setMergeSource(null)}>cancel</TextAction>
                ) : (
                  <TextAction busy={busy} onClick={() => run(() => api.mergeTags(mergeSource, t.tag))}>← merge here</TextAction>
                )
              ) : (
                <>
                  <TextAction onClick={() => setMergeSource(t.tag)}>merge</TextAction>
                  <TextAction danger busy={busy} onClick={() => run(() => api.deleteTag(t.tag))}>delete</TextAction>
                </>
              )}
            </div>
          );
        })}
        {shown.length === 0 && <div style={{ fontFamily: P.sans, fontSize: 12, color: P.faint, padding: "6px 9px" }}>No tags.</div>}
      </div>
    </Backdrop>
  );
}
