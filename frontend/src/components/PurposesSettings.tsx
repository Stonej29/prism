import { useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { P } from "../theme";
import type { Purpose } from "../types";
import { TextAction } from "./TextAction";
import { usePurposes } from "../hooks/usePurposes";

const inputStyle: React.CSSProperties = {
  background: P.bg2,
  border: `1px solid ${P.line}`,
  borderRadius: 6,
  padding: "6px 9px",
  color: P.hi,
  fontFamily: P.sans,
  fontSize: 12.5,
  outline: "none",
  boxSizing: "border-box",
};

// One purpose row: name is fixed; the "what belongs here" description is editable
// inline and saved on blur (so the AI classifier gets the updated hint).
function PurposeRow({ purpose, onSaved, onDelete, busy }: { purpose: Purpose; onSaved: () => void; onDelete: () => void; busy: boolean }) {
  const [desc, setDesc] = useState(purpose.description);
  const dirty = desc !== purpose.description;
  const save = async () => {
    if (!dirty) return;
    await api.updatePurpose(purpose.name, desc.trim());
    onSaved();
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
      <span style={{ fontFamily: P.mono, fontSize: 11, color: P.hi, minWidth: 92, flexShrink: 0 }}>{purpose.name}</span>
      <input
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        placeholder="what belongs here…"
        style={{ ...inputStyle, flex: 1 }}
      />
      <span
        onClick={() => { if (!busy) onDelete(); }}
        title={`Delete “${purpose.name}”`}
        style={{ cursor: busy ? "default" : "pointer", color: P.faint, display: "inline-flex" }}
      >
        <Trash2 size={14} />
      </span>
    </div>
  );
}

export function PurposesSettings({ onReviewProposals }: { onReviewProposals: () => void }) {
  const { purposes, reload } = usePurposes();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState<string | null>(null);
  const [scanCreated, setScanCreated] = useState(0);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    if (!name.trim() || busy) return;
    await run(() => api.addPurpose(name.trim(), desc.trim()));
    setName("");
    setDesc("");
  };

  const scanNow = async () => {
    setScanning(true);
    setScanMsg(null);
    setError(null);
    try {
      const r = await api.scanPurposes();
      setScanMsg(r.message);
      setScanCreated(r.created);
    } catch (e) {
      setError(String(e));
    } finally {
      setScanning(false);
    }
  };

  return (
    <div>
      <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 10 }}>
        Purpose is your primary way to sort notes. The AI classifies each note into one of these
        categories using its description, and learns from your corrections. Add your own — the
        description tells the AI what belongs there.
      </div>

      {purposes.map((p) => (
        <PurposeRow
          key={p.name}
          purpose={p}
          busy={busy}
          onSaved={reload}
          onDelete={() => run(() => api.deletePurpose(p.name))}
        />
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New purpose"
          style={{ ...inputStyle, minWidth: 92, width: 110, flexShrink: 0 }}
        />
        <input
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void add(); }}
          placeholder="what belongs here…"
          style={{ ...inputStyle, flex: 1 }}
        />
        <TextAction busy={busy} disabled={busy || !name.trim()} onClick={add}>add</TextAction>
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 14 }}>
        <TextAction busy={scanning} disabled={scanning} onClick={scanNow} title="Re-classify existing notes against the current categories; you approve each change">
          scan notes for re-classification
        </TextAction>
        {scanMsg && (
          <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>
            {scanMsg}
            {scanCreated > 0 && (
              <> · <span onClick={onReviewProposals} style={{ color: P.accent, cursor: "pointer" }}>review</span></>
            )}
          </span>
        )}
      </div>
      {error && <div style={{ fontFamily: P.mono, fontSize: 10, color: P.arxiv, marginTop: 8 }}>{error}</div>}
    </div>
  );
}
