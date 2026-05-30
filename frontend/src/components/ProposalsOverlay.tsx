import { P } from "../theme";
import type { Proposal } from "../types";
import { Backdrop } from "./AskOverlay";
import { Spinner } from "./Spinner";

export function ProposalsOverlay({
  proposals,
  loading,
  busyId,
  runningJob,
  onClose,
  onApprove,
  onReject,
  onRunIngest,
  onRunTraverse,
}: {
  proposals: Proposal[];
  loading: boolean;
  busyId: string | null;
  runningJob: "ingest" | "traverse" | null;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRunIngest: () => void;
  onRunTraverse: () => void;
}) {
  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>/proposals</span>
        <span style={{ fontFamily: P.sans, fontSize: 15, color: P.hi }}>Graph maintenance review</span>
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button disabled={runningJob !== null} onClick={onRunIngest} style={runStyle(runningJob === "ingest")}>
          {runningJob === "ingest" ? <Spinner size={12} /> : "↻"} Pull feeds now
        </button>
        <button disabled={runningJob !== null} onClick={onRunTraverse} style={runStyle(runningJob === "traverse")}>
          {runningJob === "traverse" ? <Spinner size={12} /> : "⤬"} Run maintenance now
        </button>
      </div>

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

function runStyle(active: boolean): React.CSSProperties {
  return {
    fontFamily: P.mono,
    fontSize: 11,
    color: active ? P.accent : P.mid,
    background: active ? P.accentDim : P.bg2,
    border: `1px solid ${active ? P.accent : P.line}`,
    borderRadius: 6,
    padding: "6px 12px",
    cursor: active ? "default" : "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  };
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
