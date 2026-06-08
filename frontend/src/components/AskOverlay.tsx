import { P } from "../theme";
import type { AskResult } from "../types";
import { Spinner } from "./Spinner";

export function AskOverlay({
  question,
  result,
  loading,
  onClose,
  onSelectSource,
}: {
  question: string;
  result: AskResult | null;
  loading: boolean;
  onClose: () => void;
  onSelectSource: (id: string) => void;
}) {
  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>/ask</span>
        <span style={{ fontFamily: P.sans, fontSize: 15, color: P.hi }}>{question}</span>
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      {loading ? (
        <Spinner label="Searching notes and answering…" />
      ) : !result ? null : !result.ok ? (
        <div style={{ fontFamily: P.sans, fontSize: 13.5, color: P.arxiv }}>{result.message}</div>
      ) : (
        <>
          <p style={{ fontFamily: P.sans, fontSize: 14, lineHeight: 1.65, color: P.hi, whiteSpace: "pre-wrap", margin: 0 }}>
            {result.answer}
          </p>
          {result.sources.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.4 }}>
                Sources
              </span>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {result.sources.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => onSelectSource(c.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 9,
                      padding: "8px 10px",
                      borderRadius: 7,
                      background: P.bg2,
                      border: `1px solid ${P.line}`,
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ fontFamily: P.sans, fontSize: 12.5, color: P.hi, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.title}
                    </span>
                    <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>{c.score.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Backdrop>
  );
}

export function Backdrop({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 20,
        background: "rgba(5,7,10,0.55)",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: 80,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 640,
          maxWidth: "90%",
          maxHeight: "75%",
          overflowY: "auto",
          background: P.bg1,
          border: `1px solid ${P.line}`,
          borderRadius: 12,
          padding: "20px 24px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
