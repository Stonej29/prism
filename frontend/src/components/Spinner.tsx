import { P } from "../theme";

export function Spinner({ size = 16, label, color = P.accent }: { size?: number; label?: string; color?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9 }}>
      <span
        style={{
          width: size,
          height: size,
          border: `2px solid ${P.line}`,
          borderTopColor: color,
          borderRadius: "50%",
          display: "inline-block",
          animation: "prism-spin 0.7s linear infinite",
        }}
      />
      {label && <span style={{ fontFamily: P.mono, fontSize: 12, color: P.mid }}>{label}</span>}
      <style>{`@keyframes prism-spin { to { transform: rotate(360deg); } }`}</style>
    </span>
  );
}
