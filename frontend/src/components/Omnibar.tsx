import { useEffect, useRef, useState } from "react";
import { P } from "../theme";
import { Spinner } from "./Spinner";

type Mode = "ask" | "find";

function ModeIcon({ mode }: { mode: Mode }) {
  if (mode === "ask") {
    return (
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke={P.accent} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5.5 6a2.5 2.5 0 1 1 3.2 2.4c-.5.2-.7.6-.7 1.1V10" />
        <circle cx="8" cy="12.5" r="0.6" fill={P.accent} stroke="none" />
      </svg>
    );
  }
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke={P.accent} strokeWidth="1.6" strokeLinecap="round">
      <circle cx="7" cy="7" r="4.2" />
      <path d="M10.5 10.5l3 3" />
    </svg>
  );
}

export function Omnibar({ busy, onAsk, onFind }: { busy: boolean; onAsk: (q: string) => void; onFind: (q: string) => void }) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<Mode>("ask");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = () => {
    if (busy) return;
    const q = value.trim();
    if (!q) return;
    if (mode === "ask") onAsk(q);
    else onFind(q);
    setValue("");
  };

  return (
    <div
      style={{
        flex: 1,
        maxWidth: 600,
        margin: "0 auto",
        display: "flex",
        alignItems: "center",
        gap: 10,
        height: 34,
        background: P.bg2,
        border: `1px solid ${P.line}`,
        borderRadius: 8,
        padding: "0 10px 0 6px",
      }}
    >
      <span
        onClick={() => setMode((m) => (m === "ask" ? "find" : "ask"))}
        title={mode === "ask" ? "Ask mode — click for Find" : "Find mode — click for Ask"}
        style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", width: 28, height: 28, borderRadius: 6, background: P.accentDim }}
      >
        <ModeIcon mode={mode} />
      </span>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder={mode === "ask" ? "Ask a question grounded in your notes…" : "Find the best-matching note…"}
        style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: P.hi, fontFamily: P.sans, fontSize: 13 }}
      />
      {busy ? (
        <Spinner size={13} />
      ) : (
        <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, border: `1px solid ${P.line}`, borderRadius: 4, padding: "2px 5px" }}>⌘K</span>
      )}
    </div>
  );
}
