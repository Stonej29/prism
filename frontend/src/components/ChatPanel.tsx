import { useEffect, useRef, useState } from "react";
import { Send, Trash2, X } from "lucide-react";
import { api } from "../api";
import { P } from "../theme";
import type { ChatMessage } from "../types";
import { Spinner } from "./Spinner";

/**
 * Conversation with an LLM grounded in a single note. Loads any persisted
 * history on mount, sends turns to POST /notes/{id}/chat, and shows the full
 * reply once it returns (no streaming). Shared by the PC NotePane (rendered in
 * a Backdrop modal) and the mobile FeedDetail (`fullscreen`).
 */
export function ChatPanel({
  noteId,
  noteTitle,
  onClose,
  fullscreen = false,
}: {
  noteId: string;
  noteTitle: string;
  onClose: () => void;
  fullscreen?: boolean;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .chatHistory(noteId)
      .then((r) => !cancelled && setMessages(r.messages))
      .catch(() => {})
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  // Auto-scroll to the newest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, sending]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setError(null);
    setSending(true);
    // Optimistically show the user's turn while we wait for the reply.
    const optimistic: ChatMessage = { role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, optimistic]);
    setInput("");
    try {
      const r = await api.chat(noteId, text);
      setMessages(r.messages);
      if (!r.ok) setError(r.message || "Chat failed.");
    } catch (e) {
      setError(String(e));
      setInput(text); // restore what they typed so it isn't lost
      setMessages((prev) => prev.filter((m) => m !== optimistic));
    } finally {
      setSending(false);
    }
  }

  async function clear() {
    if (sending) return;
    try {
      await api.clearChat(noteId);
      setMessages([]);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  const container: React.CSSProperties = fullscreen
    ? { position: "absolute", inset: 0, zIndex: 40, background: P.bg0, display: "flex", flexDirection: "column" }
    : { display: "flex", flexDirection: "column", height: "min(72vh, 680px)", width: "100%" };

  return (
    <div style={container}>
      {/* Header */}
      <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 10, padding: "0 6px 0 2px", height: 48, borderBottom: `1px solid ${P.line}` }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent, flexShrink: 0 }}>chat</span>
        <span style={{ fontFamily: P.sans, fontSize: 14, color: P.hi, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {noteTitle}
        </span>
        {messages.length > 0 && (
          <button
            onClick={clear}
            title="Clear conversation"
            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 40, minHeight: 40, background: "transparent", border: "none", color: P.lo, cursor: "pointer" }}
          >
            <Trash2 size={16} />
          </button>
        )}
        <button
          onClick={onClose}
          title="Close"
          style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 40, minHeight: 40, background: "transparent", border: "none", color: P.mid, cursor: "pointer" }}
        >
          <X size={18} />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch", padding: "16px 4px", display: "flex", flexDirection: "column", gap: 14 }}>
        {loaded && messages.length === 0 && !sending && (
          <div style={{ margin: "auto", textAlign: "center", maxWidth: 320, fontFamily: P.sans, fontSize: 13.5, color: P.lo, lineHeight: 1.6 }}>
            Ask anything about this note — summaries, follow-ups, or how it connects to your work.
          </div>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}
        {sending && (
          <div style={{ alignSelf: "flex-start", padding: "4px 2px" }}>
            <Spinner label="Thinking…" />
          </div>
        )}
      </div>

      {error && (
        <div style={{ flexShrink: 0, fontFamily: P.sans, fontSize: 12.5, color: P.arxiv, padding: "0 4px 8px" }}>{error}</div>
      )}

      {/* Composer */}
      <div style={{ flexShrink: 0, display: "flex", alignItems: "flex-end", gap: 8, padding: "10px 4px", borderTop: `1px solid ${P.line}` }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Message this note…"
          rows={1}
          style={{
            flex: 1,
            resize: "none",
            maxHeight: 140,
            boxSizing: "border-box",
            background: P.bg1,
            border: `1px solid ${P.line}`,
            borderRadius: 10,
            padding: "10px 12px",
            color: P.hi,
            fontFamily: P.sans,
            fontSize: 14,
            lineHeight: 1.5,
            outline: "none",
          }}
        />
        <button
          onClick={send}
          disabled={!input.trim() || sending}
          title="Send"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 40,
            height: 40,
            flexShrink: 0,
            borderRadius: 10,
            border: "none",
            background: input.trim() && !sending ? P.accent : P.bg2,
            color: input.trim() && !sending ? "#0b0e13" : P.faint,
            cursor: input.trim() && !sending ? "pointer" : "default",
          }}
        >
          <Send size={17} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start", gap: 4 }}>
      <span style={{ fontFamily: P.mono, fontSize: 9.5, letterSpacing: 1, textTransform: "uppercase", color: P.faint, padding: "0 4px" }}>
        {isUser ? "you" : "assistant"}
      </span>
      <div
        style={{
          maxWidth: "88%",
          padding: "10px 13px",
          borderRadius: 12,
          background: isUser ? P.accentDim : P.bg2,
          border: `1px solid ${P.line}`,
          fontFamily: P.sans,
          fontSize: 14,
          lineHeight: 1.6,
          color: P.hi,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {message.content}
      </div>
    </div>
  );
}
