import { useEffect, useRef, useState } from "react";
import { P } from "../theme";
import { Spinner } from "./Spinner";

export function Omnibar({ busy, onAsk }: { busy: boolean; onAsk: (q: string) => void }) {
  const [value, setValue] = useState("");
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
    if (q) {
      onAsk(q);
      setValue("");
    }
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
        padding: "0 12px",
      }}
    >
      <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>/ask</span>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="Ask a question grounded in your notes…"
        style={{
          flex: 1,
          background: "transparent",
          border: "none",
          outline: "none",
          color: P.hi,
          fontFamily: P.sans,
          fontSize: 13,
        }}
      />
      {busy ? (
        <Spinner size={13} />
      ) : (
        <span
          style={{
            fontFamily: P.mono,
            fontSize: 10,
            color: P.faint,
            border: `1px solid ${P.line}`,
            borderRadius: 4,
            padding: "2px 5px",
          }}
        >
          ⌘K
        </span>
      )}
    </div>
  );
}
