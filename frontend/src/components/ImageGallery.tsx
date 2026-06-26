import { useState } from "react";
import { P } from "../theme";
import type { NoteImage } from "../types";
import { Lightbox } from "./Lightbox";

/** Responsive thumbnail grid; tap a thumbnail to open the full-screen lightbox. */
export function ImageGallery({ images }: { images: NoteImage[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!images.length) return null;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))", gap: 8 }}>
        {images.map((img, i) => (
          <button
            key={img.url}
            onClick={() => setOpen(i)}
            style={{ padding: 0, border: `1px solid ${P.line}`, borderRadius: 8, overflow: "hidden", cursor: "pointer", background: P.bg2, aspectRatio: "1 / 1" }}
          >
            <img src={img.url} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
          </button>
        ))}
      </div>
      {open != null && <Lightbox images={images} index={open} onClose={() => setOpen(null)} />}
    </>
  );
}
