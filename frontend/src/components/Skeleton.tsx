import { P } from "../theme";

/**
 * A "breathing" placeholder shown while a note is loading or being regenerated,
 * instead of a bare spinner. Bars pulse via a shared CSS keyframe.
 */
export function NoteSkeleton() {
  return (
    <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
      <style>{`@keyframes prismPulse { 0%,100% { opacity: 0.35 } 50% { opacity: 0.85 } }`}</style>
      {/* header: badge + source */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Bar w={54} h={16} r={5} />
        <Bar w={120} h={10} />
        <div style={{ marginLeft: "auto" }}>
          <Bar w={70} h={10} />
        </div>
      </div>
      {/* title */}
      <Bar w="85%" h={20} />
      {/* score row */}
      <div style={{ display: "flex", gap: 8 }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <Bar key={i} w={42} h={22} r={6} />
        ))}
      </div>
      {/* summary lines */}
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {["100%", "96%", "92%", "70%"].map((w, i) => (
          <Bar key={i} w={w} h={11} />
        ))}
      </div>
      {/* tag chips */}
      <div style={{ display: "flex", gap: 6 }}>
        {[48, 64, 40, 56].map((w, i) => (
          <Bar key={i} w={w} h={18} r={5} />
        ))}
      </div>
    </div>
  );
}

function Bar({ w, h, r = 4 }: { w: number | string; h: number; r?: number }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: r,
        background: P.bg2,
        animation: "prismPulse 1.4s ease-in-out infinite",
      }}
    />
  );
}
