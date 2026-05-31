import { useEffect, useState } from "react";
import { api } from "../api";
import { P } from "../theme";
import type { MaintenanceSettings, Proposal } from "../types";
import { Backdrop } from "./AskOverlay";
import { Spinner } from "./Spinner";

const SETTING_FIELDS: { key: keyof MaintenanceSettings; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: "link_threshold", label: "link threshold", min: 0, max: 1, step: 0.01, hint: "min cosine for an auto 'related' link (higher = stricter)" },
  { key: "max_auto_links", label: "max auto links", min: 0, max: 20, step: 1, hint: "cap on automatic links per note" },
  { key: "max_links_per_note", label: "max links / note", min: 1, max: 30, step: 1, hint: "cap on total links (LLM + auto)" },
  { key: "dup_threshold", label: "dup threshold", min: 0, max: 1, step: 0.01, hint: "min cosine to propose a merge" },
];

function MaintenanceSettingsPanel() {
  const [settings, setSettings] = useState<MaintenanceSettings | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.maintenanceSettings().then(setSettings).catch(() => {});
  }, []);

  const set = (key: keyof MaintenanceSettings, value: number) => {
    setSaved(false);
    setSettings((s) => (s ? { ...s, [key]: value } : s));
  };

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const next = await api.saveMaintenanceSettings(settings);
      setSettings(next);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginBottom: 16, border: `1px solid ${P.line}`, borderRadius: 8, background: P.bg2 }}>
      <div onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", cursor: "pointer" }}>
        <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none" }}>
          <path d="M3 2l4 3-4 3" fill="none" stroke={P.lo} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, textTransform: "uppercase", letterSpacing: 1 }}>maintenance settings</span>
        <span style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 10, color: P.faint }}>thresholds</span>
      </div>
      {open && settings && (
        <div style={{ padding: "4px 12px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
          {SETTING_FIELDS.map((f) => (
            <div key={f.key} style={{ display: "flex", alignItems: "center", gap: 10 }} title={f.hint}>
              <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, width: 120 }}>{f.label}</span>
              <input
                type="range"
                min={f.min}
                max={f.max}
                step={f.step}
                value={settings[f.key]}
                onChange={(e) => set(f.key, Number(e.target.value))}
                style={{ flex: 1, accentColor: P.accent }}
              />
              <span style={{ fontFamily: P.mono, fontSize: 11, color: P.hi, width: 38, textAlign: "right" }}>
                {f.step < 1 ? settings[f.key].toFixed(2) : settings[f.key]}
              </span>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button disabled={saving} onClick={save} style={btnStyle(P.accent, saving)}>
              {saving ? <Spinner size={12} /> : "Save"}
            </button>
            {saved && <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>saved ✓ — applies on next maintenance run</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export function ProposalsOverlay({
  proposals,
  loading,
  busyId,
  onClose,
  onApprove,
  onReject,
}: {
  proposals: Proposal[];
  loading: boolean;
  busyId: string | null;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>/proposals</span>
        <span style={{ fontFamily: P.sans, fontSize: 15, color: P.hi }}>Graph maintenance review</span>
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      <MaintenanceSettingsPanel />

      {loading ? (
        <Spinner label="Loading proposals…" />
      ) : proposals.length === 0 ? (
        <div style={{ fontFamily: P.sans, fontSize: 13.5, color: P.lo }}>
          No pending proposals. The worker creates them during scheduled graph maintenance.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {proposals.map((p) => (
            <div
              key={p.id}
              style={{
                padding: "10px 12px",
                borderRadius: 8,
                background: P.bg2,
                border: `1px solid ${P.line}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontFamily: P.mono, fontSize: 10, color: P.accent, textTransform: "uppercase", letterSpacing: 1.2 }}>
                  {p.kind}
                </span>
                <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint }}>{p.id}</span>
              </div>
              <div style={{ fontFamily: P.sans, fontSize: 13, color: P.hi, lineHeight: 1.5 }}>{p.description}</div>
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <button
                  disabled={busyId === p.id}
                  onClick={() => onApprove(p.id)}
                  style={btnStyle(P.accent, busyId === p.id)}
                >
                  {busyId === p.id ? <Spinner size={12} /> : "✓ Approve"}
                </button>
                <button
                  disabled={busyId === p.id}
                  onClick={() => onReject(p.id)}
                  style={btnStyle(P.lo, busyId === p.id)}
                >
                  ✗ Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Backdrop>
  );
}

function btnStyle(color: string, disabled: boolean): React.CSSProperties {
  return {
    fontFamily: P.mono,
    fontSize: 11,
    color,
    background: "transparent",
    border: `1px solid ${P.line}`,
    borderRadius: 6,
    padding: "5px 12px",
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1,
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  };
}
