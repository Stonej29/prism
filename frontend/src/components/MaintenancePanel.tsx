import { useEffect, useState } from "react";
import { api } from "../api";
import { P } from "../theme";
import type { MaintenanceSettings } from "../types";
import { TextAction } from "./TextAction";

const SETTING_FIELDS: { key: keyof MaintenanceSettings; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: "link_threshold", label: "link threshold", min: 0, max: 1, step: 0.01, hint: "Minimum cosine for an automatic related-note link. Higher is stricter." },
  { key: "max_auto_links", label: "auto links", min: 0, max: 20, step: 1, hint: "Maximum automatic links added per note." },
  { key: "max_links_per_note", label: "links / note", min: 1, max: 30, step: 1, hint: "Total per-note cap used when adding auto links; preserved links occupy slots but are not deleted." },
  { key: "dup_threshold", label: "dup threshold", min: 0, max: 1, step: 0.01, hint: "Minimum cosine to create a merge proposal." },
];

export function MaintenancePanel({
  pendingProposals,
  maintaining,
  onRunMaintenance,
  onReviewProposals,
  onOpenLog,
}: {
  pendingProposals: number;
  maintaining: boolean;
  onRunMaintenance: () => void | Promise<void>;
  onReviewProposals: () => void;
  onOpenLog: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<MaintenanceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || settings) return;
    api.maintenanceSettings().then((next) => {
      setSettings(next);
      setDirty(false);
    }).catch(() => {});
  }, [open, settings]);

  const set = (key: keyof MaintenanceSettings, value: number) => {
    setSaved(false);
    setDirty(true);
    setError(null);
    setSettings((s) => (s ? { ...s, [key]: value } : s));
  };

  const persistSettings = async () => {
    if (!settings) return null;
    setSaving(true);
    setError(null);
    try {
      const next = await api.saveMaintenanceSettings(settings);
      setSettings(next);
      setSaved(true);
      setDirty(false);
      return next;
    } catch (e) {
      setError(String(e));
      throw e;
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    try {
      await persistSettings();
    } catch {
      /* error is displayed inline */
    }
  };

  const runMaintenance = async () => {
    if (maintaining || saving) return;
    try {
      if (dirty) await persistSettings();
      await onRunMaintenance();
    } catch {
      /* save failures are displayed inline; maintenance failures are handled by the caller */
    }
  };

  return (
    <div style={{ borderTop: `1px solid ${P.line}` }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", gap: 6, padding: "12px 12px 6px", cursor: "pointer" }}
      >
        <svg width="9" height="9" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none" }}>
          <path d="M3 2l4 3-4 3" fill="none" stroke={P.faint} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span style={{ fontFamily: P.mono, fontSize: 10, letterSpacing: 1.2, color: P.faint, textTransform: "uppercase" }}>Maintenance</span>
        {pendingProposals > 0 && <span style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 10, color: P.mid }}>{pendingProposals} pending</span>}
      </div>
      {open && (
        <div style={{ padding: "0 14px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <TextAction busy={maintaining} disabled={maintaining || saving} title="Save edited thresholds, then run maintenance" onClick={runMaintenance}>run maintenance</TextAction>
            <TextAction onClick={onReviewProposals}>review proposals{pendingProposals > 0 ? ` (${pendingProposals})` : ""}</TextAction>
            <TextAction onClick={onOpenLog}>log</TextAction>
          </div>
          {!settings ? (
            <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>loading thresholds</span>
          ) : (
            <>
              <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, lineHeight: 1.45 }}>
                Thresholds tune auto links only. LLM and manual links are preserved; turn on LLM links in the graph to inspect model suggestions.
              </div>
              {SETTING_FIELDS.map((f) => (
                <div key={f.key} title={f.hint} style={{ display: "grid", gridTemplateColumns: "76px 1fr 38px", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: P.mono, fontSize: 10, color: P.mid }}>{f.label}</span>
                  <input
                    type="range"
                    min={f.min}
                    max={f.max}
                    step={f.step}
                    value={settings[f.key]}
                    onChange={(e) => set(f.key, Number(e.target.value))}
                    style={{ width: "100%", accentColor: P.mid }}
                  />
                  <span style={{ fontFamily: P.mono, fontSize: 10, color: P.hi, textAlign: "right" }}>{f.step < 1 ? settings[f.key].toFixed(2) : settings[f.key]}</span>
                </div>
              ))}
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <TextAction busy={saving} disabled={saving || !dirty} onClick={save}>save settings</TextAction>
                {dirty && !saved && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.mid }}>unsaved</span>}
                {saved && !dirty && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>saved</span>}
                {error && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.arxiv }}>{error}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
