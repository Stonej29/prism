import { P } from "../theme";
import { Omnibar, type Dispatch } from "./Omnibar";

function TopBtn({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        fontFamily: P.mono,
        fontSize: 11,
        color: P.mid,
        padding: "5px 10px",
        border: `1px solid ${P.line}`,
        borderRadius: 6,
        cursor: "pointer",
      }}
    >
      {children}
    </span>
  );
}

export function TopBar({ busy, onDispatch }: { busy: boolean; onDispatch: (d: Dispatch) => void }) {
  return (
    <div
      style={{
        height: 52,
        flexShrink: 0,
        borderBottom: `1px solid ${P.line}`,
        background: P.bg1,
        display: "flex",
        alignItems: "center",
        padding: "0 16px",
        gap: 16,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{ width: 18, height: 18, position: "relative" }}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              transform: "rotate(45deg)",
              background: `linear-gradient(135deg, ${P.accent}, ${P.github})`,
              borderRadius: 3,
            }}
          />
        </div>
        <span style={{ fontFamily: P.mono, fontWeight: 600, letterSpacing: 2, fontSize: 14, color: P.hi }}>
          PRISM
        </span>
      </div>
      <Omnibar busy={busy} onDispatch={onDispatch} />
      <div style={{ display: "flex", gap: 8 }}>
        <TopBtn onClick={() => onDispatch({ kind: "idea", text: "" })}>/idea</TopBtn>
      </div>
    </div>
  );
}
