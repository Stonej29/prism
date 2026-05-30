import { useRef } from "react";
import { P } from "../theme";

// A thin draggable strip on a panel's inner edge. `side` is which edge of the
// graph it borders: a left panel's handle sits on its right edge ("left"),
// a right panel's handle on its left edge ("right").
export function ResizeHandle({ side, width, onResize }: { side: "left" | "right"; width: number; onResize: (w: number) => void }) {
  const start = useRef<{ x: number; w: number } | null>(null);

  const onDown = (e: React.PointerEvent) => {
    start.current = { x: e.clientX, w: width };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    const dx = e.clientX - start.current.x;
    onResize(start.current.w + (side === "left" ? dx : -dx));
  };
  const onUp = (e: React.PointerEvent) => {
    start.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
  };

  return (
    <div
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      title="Drag to resize"
      style={{
        position: "absolute",
        top: 0,
        bottom: 0,
        [side === "left" ? "right" : "left"]: -3,
        width: 6,
        cursor: "col-resize",
        zIndex: 8,
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = `${P.accent}55`)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    />
  );
}
