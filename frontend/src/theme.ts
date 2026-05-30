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
