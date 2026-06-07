import { useEffect, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api } from "../api";
import { P } from "../theme";
import { Backdrop } from "./AskOverlay";

export interface OpenFile {
  root: string;
  path: string;
  name: string;
}

function ext(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

export function FileViewer({ file, onClose }: { file: OpenFile; onClose: () => void }) {
  const kind = ext(file.name);
  const url = api.fileUrl(file.root, file.path);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const isPdf = kind === "pdf";
  const isImage = ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(kind);
  const isText = !isPdf && !isImage;

  useEffect(() => {
    if (!isText) return;
    setText(null);
    setErr(null);
    api.fileText(file.root, file.path).then(setText).catch((e) => setErr(String(e)));
  }, [file.root, file.path, isText]);

  let body: React.ReactNode;
  if (isPdf) {
    body = <iframe src={url} title={file.name} style={{ width: "100%", height: "70vh", border: "none", borderRadius: 8, background: "#fff" }} />;
  } else if (isImage) {
    body = <img src={url} alt={file.name} style={{ maxWidth: "100%", borderRadius: 8 }} />;
  } else if (err) {
    body = <div style={{ fontFamily: P.sans, fontSize: 13, color: P.arxiv }}>{err}</div>;
  } else if (text == null) {
    body = <div style={{ fontFamily: P.mono, fontSize: 12, color: P.mid }}>Loading…</div>;
  } else if (kind === "md") {
    body = (
      <div
        style={{ fontFamily: P.sans, fontSize: 13.5, lineHeight: 1.6, color: P.hi }}
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(text) as string) }}
      />
    );
  } else {
    body = (
      <pre style={{ fontFamily: P.mono, fontSize: 12, lineHeight: 1.55, color: P.mid, whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
        {text}
      </pre>
    );
  }

  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontFamily: P.mono, fontSize: 12, color: P.accent }}>file</span>
        <span style={{ fontFamily: P.sans, fontSize: 14, color: P.hi, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file.name}</span>
        <a href={url} target="_blank" rel="noreferrer" style={{ marginLeft: "auto", fontFamily: P.mono, fontSize: 11, color: P.lo, textDecoration: "none" }}>
          open raw ↗
        </a>
        <span onClick={onClose} style={{ fontFamily: P.mono, fontSize: 12, color: P.lo, cursor: "pointer" }}>esc</span>
      </div>
      {body}
    </Backdrop>
  );
}
