import { useEffect, useRef, useState } from "react";
import { P } from "../theme";
import { Spinner } from "./Spinner";

export type Command = "ask" | "find" | "idea" | "save";

export interface Dispatch {
  kind: Command;
  text: string;
}

const URL_RE = /^https?:\/\/\S+$/i;

function parse(raw: string): Dispatch | null {
  const value = raw.trim();
  if (!value) return null;
  const m = value.match(/^\/(ask|find|idea|save)\s*(.*)$/is);
  if (m) return { kind: m[1].toLowerCase() as Command, text: m[2].trim() };
  if (URL_RE.test(value)) return { kind: "save", text: value };
  return { kind: "find", text: value };
}

export function Omnibar({ busy, onDispatch }: { busy: boolean; onDispatch: (d: Dispatch) => void }) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const parsed = parse(value);

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
    const d = parse(value);
    if (d) {
      onDispatch(d);
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
      <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>
        {parsed ? `/${parsed.kind}` : "/"}
      </span>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="Ask, find, save a URL, or /idea a topic…"
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
