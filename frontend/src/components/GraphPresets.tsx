import { useEffect, useState } from "react";
import { P } from "../theme";

// A saved/built-in graph "view" = a snapshot of the fan-out filters. Persisted in
// localStorage (single-user app — no backend needed). Built-ins are keyed on purpose.
export interface GraphView {
  name?: string;
  purposeFilters?: string[];
  sourceFilters?: string[];
  tagFilters?: string[];
  flagFilters?: string[];
  minScore?: number;
  minAgeDays?: number;
}

const BUILTINS: GraphView[] = [
  { name: "Research", purposeFilters: ["Thesis", "Dataset"] },
  { name: "Work", purposeFilters: ["Work"] },
  { name: "Self-host", purposeFilters: ["Self-Host"] },
  { name: "All", purposeFilters: [] },
];

const STORAGE_KEY = "prism.graphViews";

function loadSaved(): GraphView[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function GraphPresets({
  current,
  onApply,
}: {
  current: GraphView;
  onApply: (view: GraphView) => void;
}) {
  const [saved, setSaved] = useState<GraphView[]>(loadSaved);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch {
      /* ignore quota / disabled storage */
    }
  }, [saved]);

  const saveCurrent = () => {
    const name = window.prompt("Name this view:");
    if (!name) return;
    setSaved((prev) => [...prev.filter((v) => v.name !== name), { ...current, name }]);
  };

  const remove = (name: string) => setSaved((prev) => prev.filter((v) => v.name !== name));

  const chip = (label: string, onClick: () => void, onRemove?: () => void) => (
    <span
      key={label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontFamily: P.mono,
        fontSize: 10,
        padding: "2px 7px",
        borderRadius: 5,
        cursor: "pointer",
        color: P.mid,
        border: `1px solid ${P.line}`,
        background: "transparent",
      }}
    >
      <span onClick={onClick}>{label}</span>
      {onRemove && (
        <span onClick={onRemove} title="Delete view" style={{ color: P.faint }}>×</span>
      )}
    </span>
  );

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "2px 12px 4px" }}>
      {BUILTINS.map((v) => chip(v.name ?? "view", () => onApply(v)))}
      {saved.map((v) => chip(v.name ?? "view", () => onApply(v), () => remove(v.name ?? "view")))}
      {chip("+ save", saveCurrent)}
    </div>
  );
}
