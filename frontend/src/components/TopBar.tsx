import { useState } from "react";
import { P } from "../theme";
import { Omnibar } from "./Omnibar";
import type { IdeaStatus } from "./Lightbulb";
import { TextAction } from "./TextAction";

export function TopBar({
  busy,
  saving,
  ideaStatus,
  ingesting,
  onAsk,
  onFind,
  onSave,
  onLightbulb,
  onPullFeeds,
}: {
  busy: boolean;
  saving: boolean;
  ideaStatus: IdeaStatus;
  ingesting: boolean;
  onAsk: (q: string) => void;
  onFind: (q: string) => void;
  onSave: (url: string) => void;
  onLightbulb: () => void;
  onPullFeeds: () => void;
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

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <TextAction busy={ingesting} disabled={ingesting} title="Pull configured feeds now" onClick={onPullFeeds}>feeds</TextAction>
        <TextAction busy={ideaStatus === "loading"} disabled={ideaStatus === "loading"} title="Generate or open an idea" onClick={onLightbulb}>idea</TextAction>
        <TextAction busy={saving} disabled={saving} title={saving ? "Saving" : "Save a URL"} onClick={() => setSaveOpen((o) => !o)}>save url</TextAction>
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
          <span style={{ fontFamily: P.mono, fontSize: 12, color: P.mid }}>url</span>
          <input
            autoFocus
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitSave();
              if (e.key === "Escape") setSaveOpen(false);
            }}
            placeholder="https://..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: P.hi, fontFamily: P.sans, fontSize: 13 }}
          />
          <TextAction busy={saving} disabled={saving} onClick={submitSave}>save</TextAction>
        </div>
      )}
    </div>
  );
}
