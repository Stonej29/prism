import { useState } from "react";
import { P } from "../theme";
import { Omnibar } from "./Omnibar";
import { Lightbulb, type IdeaStatus } from "./Lightbulb";
import { Spinner } from "./Spinner";

export function TopBar({
  busy,
  saving,
  ideaStatus,
  pendingProposals,
  unreviewed,
  ingesting,
  maintaining,
  onAsk,
  onFind,
  onSave,
  onLightbulb,
  onInbox,
  onProposals,
  onPullFeeds,
  onRunMaintenance,
}: {
  busy: boolean;
  saving: boolean;
  ideaStatus: IdeaStatus;
  pendingProposals: number;
  unreviewed: number;
  ingesting: boolean;
  maintaining: boolean;
  onAsk: (q: string) => void;
  onFind: (q: string) => void;
  onSave: (url: string) => void;
  onLightbulb: () => void;
  onInbox: () => void;
  onProposals: () => void;
  onPullFeeds: () => void;
  onRunMaintenance: () => void;
}) {
  const [saveOpen, setSaveOpen] = useState(false);
  const [url, setUrl] = useState("");

  const submitSave = () => {
    const u = url.trim();
    if (u) {
      onSave(u);
      setUrl("");
      setSaveOpen(false);
    }
  };

  return (
    <div
      style={{
        height: 52,
        flexShrink: 0,
        borderBottom: `1px solid ${P.line}`,
        background: P.bg1,
        display: "flex",
        alignItems: "center",
        padding: "0 16px",
        gap: 16,
        position: "relative",
        zIndex: 30,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{ width: 18, height: 18, position: "relative" }}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              transform: "rotate(45deg)",
              background: `linear-gradient(135deg, ${P.accent}, ${P.github})`,
              borderRadius: 3,
            }}
          />
        </div>
        <span style={{ fontFamily: P.mono, fontWeight: 600, letterSpacing: 2, fontSize: 14, color: P.hi }}>
          PRISM
        </span>
      </div>

      <Omnibar busy={busy} onAsk={onAsk} onFind={onFind} />

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          onClick={() => !ingesting && onPullFeeds()}
          title="Pull configured feeds now"
          style={iconBtnStyle(ingesting, ingesting)}
        >
          {ingesting ? <Spinner size={14} /> : "⭳"}
        </span>
        <span
          onClick={() => !maintaining && onRunMaintenance()}
          title="Run graph maintenance now (links, tags, merge proposals)"
          style={iconBtnStyle(maintaining, maintaining)}
        >
          {maintaining ? <Spinner size={14} /> : "⚙"}
        </span>
        <span
          onClick={onInbox}
          title="Highlight unreviewed notes in the graph"
          style={{ ...iconBtnStyle(false, unreviewed > 0), position: "relative" }}
        >
          📥
          {unreviewed > 0 && (
            <span
              style={{
                position: "absolute",
                top: -6,
                right: -6,
                minWidth: 15,
                height: 15,
                padding: "0 3px",
                borderRadius: 8,
                background: P.accent,
                color: P.bg0,
                fontFamily: P.mono,
                fontSize: 9,
                fontWeight: 700,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {unreviewed}
            </span>
          )}
        </span>
        <span
          onClick={onProposals}
          title="Review graph maintenance proposals"
          style={{ ...iconBtnStyle(false, pendingProposals > 0), position: "relative" }}
        >
          ⚑
          {pendingProposals > 0 && (
            <span
              style={{
                position: "absolute",
                top: -6,
                right: -6,
                minWidth: 15,
                height: 15,
                padding: "0 3px",
                borderRadius: 8,
                background: P.accent,
                color: P.bg0,
                fontFamily: P.mono,
                fontSize: 9,
                fontWeight: 700,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {pendingProposals}
            </span>
          )}
        </span>
        <Lightbulb status={ideaStatus} onClick={onLightbulb} />
        <span
          onClick={() => !saving && setSaveOpen((o) => !o)}
          title={saving ? "Saving…" : "Save a URL"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 30,
            height: 30,
            borderRadius: 7,
            border: `1px solid ${saving || saveOpen ? P.accent : P.line}`,
            background: saving || saveOpen ? P.accentDim : P.bg2,
            color: saving || saveOpen ? P.accent : P.mid,
            cursor: saving ? "default" : "pointer",
            fontFamily: P.mono,
            fontSize: 18,
            lineHeight: 1,
          }}
        >
          {saving ? <Spinner size={14} /> : "+"}
        </span>
      </div>

      {saveOpen && (
        <div
          style={{
            position: "absolute",
            top: 56,
            right: 16,
            zIndex: 31,
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: P.bg1,
            border: `1px solid ${P.line}`,
            borderRadius: 8,
            padding: "8px 10px",
            boxShadow: "0 16px 40px rgba(0,0,0,0.45)",
            width: 380,
          }}
        >
          <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>url</span>
          <input
            autoFocus
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitSave();
              if (e.key === "Escape") setSaveOpen(false);
            }}
            placeholder="https://…  (runs fetch → LLM → index)"
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: P.hi, fontFamily: P.sans, fontSize: 13 }}
          />
          {saving ? <Spinner size={13} /> : (
            <span onClick={submitSave} style={{ fontFamily: P.mono, fontSize: 11, color: P.accent, cursor: "pointer" }}>
              save
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function iconBtnStyle(busy: boolean, accent: boolean): React.CSSProperties {
  const lit = busy || accent;
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 30,
    height: 30,
    borderRadius: 7,
    border: `1px solid ${lit ? P.accent : P.line}`,
    background: lit ? P.accentDim : P.bg2,
    color: lit ? P.accent : P.mid,
    cursor: busy ? "default" : "pointer",
    fontFamily: P.mono,
    fontSize: 15,
    lineHeight: 1,
  };
}
