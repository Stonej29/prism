import { P, srcColor } from "../theme";
import type { TreeNode } from "../types";
import type { OpenFile } from "./FileViewer";
import { usePersistentToggle } from "../hooks/usePersistentToggle";

interface Ctx {
  selectedNoteId: string | null;
  noteKind: Record<string, string>;
  filter: string;
  onSelectNote: (id: string) => void;
  onOpenIdea: (id: string) => void;
  onOpenFile: (f: OpenFile) => void;
}

// Prune the tree to nodes whose name (or a descendant's) matches the filter.
function prune(node: TreeNode, q: string): TreeNode | null {
  if (!q) return node;
  const self = node.name.toLowerCase().includes(q);
  if (node.type === "file") return self ? node : null;
  const kids = (node.children ?? []).map((c) => prune(c, q)).filter((c): c is TreeNode => c !== null);
  if (self || kids.length) return { ...node, children: self ? node.children : kids };
  return null;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.1s" }}>
      <path d="M3 2l4 3-4 3" fill="none" stroke={P.lo} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Entry({ node, depth, ctx }: { node: TreeNode; depth: number; ctx: Ctx }) {
  // Sections start folded (it's a lot at a glance); the user's choice per folder
  // is remembered across reloads. While filtering, force everything open.
  const [openState, toggleOpen] = usePersistentToggle(`prism.tree.dir:${node.path}/${node.name}`, false);
  const open = ctx.filter ? true : openState;
  const padLeft = 8 + depth * 13;

  if (node.type === "dir") {
    return (
      <div>
        <div
          onClick={toggleOpen}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", paddingLeft: padLeft, cursor: "pointer", color: P.mid }}
        >
          <Chevron open={open} />
          <span style={{ fontFamily: P.sans, fontSize: 13, flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{node.name}</span>
          <span style={{ fontFamily: P.mono, fontSize: 10, color: P.faint }}>{node.children?.length ?? 0}</span>
        </div>
        {open && node.children?.map((c) => <Entry key={c.path + c.name} node={c} depth={depth + 1} ctx={ctx} />)}
      </div>
    );
  }

  const active = !!node.note_id && node.note_id === ctx.selectedNoteId;
  const dot = node.note_id ? srcColor(ctx.noteKind[node.note_id] ?? "unknown") : node.idea_id ? "#ffd66e" : P.faint;
  // Hide the leading YYYY-MM-DD- date prefix from note/idea filenames in the UI
  // (the date stays in the filename + frontmatter); keep folder names as-is.
  const label = node.note_id || node.idea_id
    ? node.name.replace(/\.md$/, "").replace(/^\d{4}-\d{2}-\d{2}-/, "")
    : node.name.replace(/\.md$/, "");

  const onClick = () => {
    if (node.note_id) ctx.onSelectNote(node.note_id);
    else if (node.idea_id) ctx.onOpenIdea(node.idea_id);
    else ctx.onOpenFile({ root: node.root ?? "vault", path: node.path, name: node.name });
  };

  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 8px",
        paddingLeft: padLeft + 16,
        cursor: "pointer",
        background: active ? P.accentDim : "transparent",
        color: active ? P.hi : node.note_id || node.idea_id ? P.mid : P.lo,
        borderRadius: 5,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: dot, flexShrink: 0 }} />
      <span style={{ fontFamily: P.sans, fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
    </div>
  );
}

export function FileTree({ root, ...ctx }: { root: TreeNode | null } & Ctx) {
  if (!root) return null;
  const children = (root.children ?? [])
    .map((c) => prune(c, ctx.filter.toLowerCase()))
    .filter((c): c is TreeNode => c !== null);
  return (
    <div>
      {children.map((c) => (
        <Entry key={c.path + c.name} node={c} depth={0} ctx={ctx} />
      ))}
      {ctx.filter && children.length === 0 && (
        <div style={{ padding: "6px 14px", fontFamily: P.sans, fontSize: 12, color: P.faint }}>No matches.</div>
      )}
    </div>
  );
}
