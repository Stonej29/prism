import { useEffect, useRef, useState } from "react";
import { Lightbulb, Plus, Settings } from "lucide-react";
import { P } from "../theme";
import { Omnibar } from "./Omnibar";
import type { IdeaStatus } from "./Lightbulb";
import { Logo } from "./Logo";
import { IconButton } from "./IconButton";
import { TextAction } from "./TextAction";

export function TopBar({
  busy,
  saving,
  ideaStatus,
  onAsk,
  onFind,
  onSave,
  onLightbulb,
  onOpenSettings,
}: {
  busy: boolean;
  saving: boolean;
  ideaStatus: IdeaStatus;
  onAsk: (q: string) => void;
  onFind: (q: string) => void;
  onSave: (url: string) => void;
  onLightbulb: () => void;
  onOpenSettings: () => void;
}) {
  const [saveOpen, setSaveOpen] = useState(false);
  const [url, setUrl] = useState("");
  const actionsRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  // Close the URL popover when clicking anywhere outside it (or the action bar).
  useEffect(() => {
    if (!saveOpen) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (popRef.current?.contains(t) || actionsRef.current?.contains(t)) return;
      setSaveOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [saveOpen]);

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
        <Logo size={20} />
        <span style={{ fontFamily: P.mono, fontWeight: 600, letterSpacing: 2, fontSize: 14, color: P.hi }}>
          PRISM
        </span>
      </div>

      <Omnibar busy={busy} onAsk={onAsk} onFind={onFind} />

      <div ref={actionsRef} style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <IconButton
          icon={Lightbulb}
          busy={ideaStatus === "loading"}
          color={ideaStatus === "ready" ? "#ffd66e" : undefined}
          title={ideaStatus === "ready" ? "Idea ready — click to view" : "Generate an idea"}
          onClick={onLightbulb}
        />
        <IconButton icon={Plus} busy={saving} title={saving ? "Saving…" : "Save a URL"} onClick={() => setSaveOpen((o) => !o)} />
        <IconButton icon={Settings} title="Settings — profile, feeds, maintenance" onClick={onOpenSettings} />
      </div>

      {saveOpen && (
        <div
          ref={popRef}
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
