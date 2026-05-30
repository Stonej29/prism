import { useState } from "react";
import { P, srcColor } from "../theme";
import type { TreeNode } from "../types";

interface Ctx {
  selectedNoteId: string | null;
  noteKind: Record<string, string>;
  onSelectNote: (id: string) => void;
  onOpenIdea: (id: string) => void;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.1s" }}>
      <path d="M3 2l4 3-4 3" fill="none" stroke={P.lo} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Entry({ node, depth, ctx }: { node: TreeNode; depth: number; ctx: Ctx }) {
  const [open, setOpen] = useState(depth < 1);
  const padLeft = 8 + depth * 13;

  if (node.type === "dir") {
    return (
      <div>
        <div
          onClick={() => setOpen((o) => !o)}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", paddingLeft: padLeft, cursor: "pointer", color: P.mid }}
        >
          <Chevron open={open} />
          <span style={{ fontFamily: P.sans, fontSize: 13, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {node.name}
          </span>
          <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint }}>{node.children?.length ?? 0}</span>
        </div>
        {open && node.children?.map((c) => <Entry key={c.path} node={c} depth={depth + 1} ctx={ctx} />)}
      </div>
    );
  }

  const clickable = !!(node.note_id || node.idea_id);
  const active = !!node.note_id && node.note_id === ctx.selectedNoteId;
  const dot = node.note_id ? srcColor(ctx.noteKind[node.note_id] ?? "unknown") : node.idea_id ? "#ffd66e" : P.faint;
  const label = node.name.replace(/\.md$/, "");

  return (
    <div
      onClick={() => {
        if (node.note_id) ctx.onSelectNote(node.note_id);
        else if (node.idea_id) ctx.onOpenIdea(node.idea_id);
      }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 8px",
        paddingLeft: padLeft + 16,
        cursor: clickable ? "pointer" : "default",
        background: active ? P.accentDim : "transparent",
        color: active ? P.hi : clickable ? P.mid : P.faint,
        borderRadius: 5,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: dot, flexShrink: 0 }} />
      <span style={{ fontFamily: P.sans, fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {label}
      </span>
    </div>
  );
}

export function FileTree({ root, ...ctx }: { root: TreeNode | null } & Ctx) {
  if (!root) return null;
  return (
    <div>
      {(root.children ?? []).map((c) => (
        <Entry key={c.path} node={c} depth={0} ctx={ctx} />
      ))}
    </div>
  );
}
