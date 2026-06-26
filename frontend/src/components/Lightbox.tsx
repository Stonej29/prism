import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { P } from "../theme";
import type { NoteImage } from "../types";

/** Full-screen image viewer. Tap backdrop / X / Esc to close; ‹ › or arrow keys to page. */
export function Lightbox({ images, index, onClose }: { images: NoteImage[]; index: number; onClose: () => void }) {
  const [i, setI] = useState(index);
  const go = useCallback((d: number) => setI((p) => (p + d + images.length) % images.length), [images.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose]);

  const img = images[i];
  const multi = images.length > 1;
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(0,0,0,0.92)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <button onClick={onClose} title="Close" style={iconBtn({ top: 14, right: 14 })}>
        <X size={22} />
      </button>
      {multi && (
        <button onClick={(e) => { e.stopPropagation(); go(-1); }} title="Previous" style={iconBtn({ left: 8, top: "50%" }, true)}>
          <ChevronLeft size={28} />
        </button>
      )}
      <img
        src={img.url}
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "94vw", maxHeight: "90vh", objectFit: "contain", borderRadius: 6 }}
      />
      {multi && (
        <button onClick={(e) => { e.stopPropagation(); go(1); }} title="Next" style={iconBtn({ right: 8, top: "50%" }, true)}>
          <ChevronRight size={28} />
        </button>
      )}
      {multi && (
        <div style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", fontFamily: P.mono, fontSize: 12, color: "rgba(255,255,255,0.7)" }}>
          {i + 1} / {images.length}
        </div>
      )}
    </div>
  );
}

function iconBtn(pos: Record<string, number | string>, center = false): React.CSSProperties {
  return {
    position: "fixed",
    ...pos,
    transform: center ? "translateY(-50%)" : undefined,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 44,
    height: 44,
    borderRadius: 999,
    background: "rgba(0,0,0,0.4)",
    border: "none",
    color: "#fff",
    cursor: "pointer",
  };
}
