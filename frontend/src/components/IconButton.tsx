import type { LucideIcon } from "lucide-react";
import { P } from "../theme";

// Compact icon button used across the top bar and note actions. Keeps a text
// `title` for accessibility/tooltips. `danger` tints destructive actions; `busy`
// dims + disables while an action is in flight.
export function IconButton({
  icon: Icon,
  title,
  onClick,
  busy = false,
  disabled = false,
  danger = false,
  size = 16,
  color,
}: {
  icon: LucideIcon;
  title: string;
  onClick: () => void;
  busy?: boolean;
  disabled?: boolean;
  danger?: boolean;
  size?: number;
  color?: string;
}) {
  const inactive = busy || disabled;
  const base = color ?? (danger ? P.arxiv : P.mid);
  const hover = color ?? (danger ? P.arxiv : P.hi);
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={inactive}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 30,
        height: 30,
        padding: 0,
        background: "transparent",
        border: "none",
        borderRadius: 7,
        color: base,
        cursor: inactive ? "default" : "pointer",
        opacity: inactive ? 0.5 : 1,
        transition: "color 0.12s, background 0.12s",
      }}
      onMouseEnter={(e) => { if (!inactive) e.currentTarget.style.color = hover; e.currentTarget.style.background = P.bg2; }}
      onMouseLeave={(e) => { e.currentTarget.style.color = base; e.currentTarget.style.background = "transparent"; }}
    >
      <Icon size={size} strokeWidth={1.75} className={busy ? "prism-spin" : undefined} />
    </button>
  );
}
