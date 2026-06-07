// Palette + fonts for the Atlas dark theme. Mirrors the concept's `P` object.
export const P = {
  bg0: "#0a0c10",
  bg1: "#0f1217",
  bg2: "#161a21",
  line: "#232830",
  hi: "#e6e9ef",
  mid: "#9aa3b2",
  lo: "#6b7280",
  faint: "#4b5563",
  accent: "#6ea8fe",
  accentDim: "rgba(110,168,254,0.14)",
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

// Map an overall score (1–10) to a cool→warm color: low = cool blue,
// high = warm amber. Unscored notes render neutral grey. Used as the graph's
// node color encoding (source kind stays as the small dot in the file tree).
export function scoreColor(overall: number | null): string {
  if (overall == null) return P.unknown;
  const v = Math.min(Math.max(overall, 1), 10);
  const t = (v - 1) / 9; // 0..1
  const hue = 210 - t * 175; // 210° blue → 35° amber
  return `hsl(${Math.round(hue)} 70% 60%)`;
}
