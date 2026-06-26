// Palette + fonts. Neutral tokens resolve to CSS custom properties so the whole
// app (Atlas + feed) switches between light and dark by toggling
// `document.documentElement[data-theme]` — see index.html and hooks/useTheme.ts.
// Source-kind hues stay constant; they read fine on both themes.
export const P = {
  bg0: "var(--p-bg0)",
  bg1: "var(--p-bg1)",
  bg2: "var(--p-bg2)",
  line: "var(--p-line)",
  hi: "var(--p-hi)",
  mid: "var(--p-mid)",
  lo: "var(--p-lo)",
  faint: "var(--p-faint)",
  accent: "var(--p-accent)",
  accentDim: "var(--p-accent-dim)",
  arxiv: "#f0776a",
  github: "#a78bfa",
  huggingface: "#f5c542",
  youtube: "#e5484d",
  pdf: "#4ec9a8",
  web: "#5cb8e6",
  unknown: "#6b7280",
  mono: "ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, monospace",
  sans: "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
} as const;

// Map a backend source_kind to a display color + short label.
export const SRC: Record<string, { color: string; label: string }> = {
  paper: { color: P.arxiv, label: "arXiv" },
  github: { color: P.github, label: "GitHub" },
  huggingface: { color: P.huggingface, label: "HF" },
  youtube: { color: P.youtube, label: "YouTube" },
  pdf: { color: P.pdf, label: "PDF" },
  website: { color: P.web, label: "Web" },
  unknown: { color: P.unknown, label: "Other" },
};

export function srcColor(kind: string): string {
  return (SRC[kind] ?? SRC.unknown).color;
}

export function srcLabel(kind: string): string {
  return (SRC[kind] ?? SRC.unknown).label;
}

// Deterministic, well-spread color per topic cluster. Topic owns hue in the
// graph; score uses a neutral ring so it cannot be confused with clusters.
export function topicColor(topic: number): string {
  if (topic < 0) return P.unknown;
  return `hsl(${(topic * 67) % 360} 62% 62%)`;
}
