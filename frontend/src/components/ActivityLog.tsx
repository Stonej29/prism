import { P } from "../theme";
import type { ActivityEntry } from "../types";
import { Backdrop } from "./AskOverlay";
import { Spinner } from "./Spinner";

export function ActivityLog({
  entries,
  loading,
  onClose,
}: {
  entries: ActivityEntry[];
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.mid }}>/log</span>
        <span style={{ fontFamily: P.sans, fontSize: 15, color: P.hi }}>Recent activity</span>
        <span onClick={onClose} style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>
          esc
        </span>
      </div>

      {loading ? (
        <Spinner label="Loading activity..." />
      ) : entries.length === 0 ? (
        <div style={{ fontFamily: P.sans, fontSize: 13.5, color: P.lo }}>No activity recorded for this web process.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {entries.map((entry) => (
            <div key={entry.id} style={{ display: "grid", gridTemplateColumns: "128px 118px 62px 1fr", gap: 10, alignItems: "baseline", padding: "8px 10px", border: `1px solid ${P.line}`, borderRadius: 7, background: P.bg2 }}>
              <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>{formatTime(entry.at)}</span>
              <span style={{ fontFamily: P.mono, fontSize: 10, color: P.mid }}>{entry.action}</span>
              <span style={{ fontFamily: P.mono, fontSize: 10, color: entry.status === "failed" ? P.arxiv : entry.status === "ok" ? P.mid : P.lo }}>{entry.status}</span>
              <span style={{ fontFamily: P.sans, fontSize: 12.5, color: P.hi, lineHeight: 1.35 }}>{entry.message}</span>
            </div>
          ))}
        </div>
      )}
    </Backdrop>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
