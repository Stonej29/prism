import { P, srcColor, srcLabel } from "../theme";

export function SourceBadge({ kind, size = 11 }: { kind: string; size?: number }) {
  const color = srcColor(kind);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: P.mono,
        fontSize: size,
        color: P.mid,
        padding: "3px 8px",
        borderRadius: 5,
        border: `1px solid ${P.line}`,
        background: P.bg2,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
      {srcLabel(kind)}
    </span>
  );
}
