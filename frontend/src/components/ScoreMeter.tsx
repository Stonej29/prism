import { P } from "../theme";

export function ScoreMeter({ value, w = 64 }: { value: number | null; w?: number }) {
  const v = value == null ? 0 : Math.max(0, Math.min(10, value));
  const pct = v / 10;
  const color = v >= 7.5 ? P.pdf : v >= 5 ? P.accent : P.arxiv;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
      <div style={{ width: w, height: 4, background: P.bg2, borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct * 100}%`, height: "100%", background: color }} />
      </div>
      <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, minWidth: 22 }}>
        {value == null ? "–" : v.toFixed(1)}
      </span>
    </div>
  );
}
