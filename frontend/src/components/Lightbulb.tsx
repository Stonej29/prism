import { P } from "../theme";

export type IdeaStatus = "idle" | "loading" | "ready";

// Top-bar lightbulb: click to generate an idea in the background; it pulses while
// working and glows when ready, then opens the idea popup on click.
export function Lightbulb({ status, onClick }: { status: IdeaStatus; onClick: () => void }) {
  const lit = status === "ready";
  const loading = status === "loading";
  const color = lit ? "#ffd66e" : loading ? P.accent : P.mid;

  return (
    <span
      onClick={() => !loading && onClick()}
      title={lit ? "Idea ready — click to view" : loading ? "Generating idea…" : "Generate an idea"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 30,
        height: 30,
        borderRadius: 7,
        border: `1px solid ${lit ? "#ffd66e55" : P.line}`,
        background: lit ? "#ffd66e1a" : P.bg2,
        cursor: loading ? "default" : "pointer",
        animation: loading ? "prism-pulse 1.1s ease-in-out infinite" : undefined,
      }}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 18h6" />
        <path d="M10 22h4" />
        <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2z" />
        {lit && <circle cx="12" cy="9" r="2.2" fill="#ffd66e" stroke="none" />}
      </svg>
      <style>{`@keyframes prism-pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.45 } }`}</style>
    </span>
  );
}
