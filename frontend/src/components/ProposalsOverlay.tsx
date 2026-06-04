import { P } from "../theme";
import type { Proposal } from "../types";
import { Backdrop } from "./AskOverlay";
import { Spinner } from "./Spinner";
import { TextAction } from "./TextAction";

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
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.mid }}>/proposals</span>
        <span style={{ fontFamily: P.sans, fontSize: 15, color: P.hi }}>Graph maintenance review</span>
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      {loading ? (
        <Spinner label="Loading proposals..." />
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
                <span style={{ fontFamily: P.mono, fontSize: 10, color: P.mid, textTransform: "uppercase", letterSpacing: 1.2 }}>
                  {p.kind}
                </span>
                <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint }}>{p.id}</span>
              </div>
              <div style={{ fontFamily: P.sans, fontSize: 13, color: P.hi, lineHeight: 1.5 }}>{p.description}</div>
              <div style={{ display: "flex", gap: 12, marginTop: 10 }}>
                <TextAction busy={busyId === p.id} disabled={busyId === p.id} onClick={() => onApprove(p.id)}>approve</TextAction>
                <TextAction disabled={busyId === p.id} onClick={() => onReject(p.id)}>reject</TextAction>
              </div>
            </div>
          ))}
        </div>
      )}
    </Backdrop>
  );
}
