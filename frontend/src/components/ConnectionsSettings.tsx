import { useEffect, useState, type CSSProperties } from "react";
import { api, type SettingsConfig, type SettingsUpdate } from "../api";
import { P } from "../theme";
import { TextAction } from "./TextAction";

const input: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: P.bg2,
  border: `1px solid ${P.line}`,
  borderRadius: 6,
  padding: "8px 10px",
  color: P.hi,
  fontFamily: P.mono,
  fontSize: 12,
  outline: "none",
};
const lockedInput: CSSProperties = { ...input, color: P.lo, background: P.bg1 };
const fieldLabel: CSSProperties = { fontFamily: P.mono, fontSize: 10, color: P.faint, letterSpacing: 0.6, marginBottom: 4 };

function LockTag({ source }: { source: "env" | "store" | "unset" }) {
  if (source !== "env") return null;
  return <span style={{ fontFamily: P.mono, fontSize: 9.5, color: P.faint }}>set via environment — locked</span>;
}

// A text field (base URL / model) with env-lock handling.
function TextField({
  label, value, locked, source, onChange,
}: { label: string; value: string; locked: boolean; source: "env" | "store" | "unset"; onChange: (v: string) => void }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={fieldLabel}>{label}</div>
        <LockTag source={source} />
      </div>
      <input
        style={locked ? lockedInput : input}
        value={value}
        disabled={locked}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

// A secret field (API key / token): never pre-filled; shows configured state.
function SecretField({
  label, configured, locked, source, value, onChange,
}: { label: string; configured: boolean; locked: boolean; source: "env" | "store" | "unset"; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={fieldLabel}>{label}</div>
        <LockTag source={source} />
      </div>
      <input
        style={locked ? lockedInput : input}
        type="password"
        value={value}
        disabled={locked}
        autoComplete="off"
        spellCheck={false}
        placeholder={locked ? "managed via environment" : configured ? "configured — leave blank to keep" : "not set"}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: ok ? P.pdf : P.faint }} />;
}

export function ConnectionsSettings() {
  const [cfg, setCfg] = useState<SettingsConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Editable drafts. Text fields seed from the loaded config; secret inputs
  // start blank (blank == "leave unchanged" on save).
  const [llmBase, setLlmBase] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [embBase, setEmbBase] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [embKey, setEmbKey] = useState("");

  const load = (c: SettingsConfig) => {
    setCfg(c);
    setLlmBase(c.llm.base_url.value);
    setLlmModel(c.llm.model.value);
    setEmbBase(c.embedding.base_url.value);
    setEmbModel(c.embedding.model.value);
    setLlmKey("");
    setEmbKey("");
  };

  useEffect(() => {
    api.getSettings().then(load).catch((e) => setError(String(e)));
  }, []);

  if (error) return <span style={{ fontFamily: P.mono, fontSize: 11, color: P.arxiv }}>{error}</span>;
  if (!cfg) return <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>loading…</span>;

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    const body: SettingsUpdate = {};
    // Only send non-locked fields; secrets only when a new value was typed.
    if (!cfg.llm.base_url.locked) body.llm_base_url = llmBase;
    if (!cfg.llm.model.locked) body.llm_model = llmModel;
    if (!cfg.llm.api_key.locked && llmKey) body.llm_api_key = llmKey;
    if (!cfg.embedding.base_url.locked) body.embedding_base_url = embBase;
    if (!cfg.embedding.model.locked) body.embedding_model = embModel;
    if (!cfg.embedding.api_key.locked && embKey) body.embedding_api_key = embKey;
    try {
      const next = await api.saveSettings(body);
      load(next);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 12 }}>
        API keys are stored privately on the server and never shown again. Changes apply to the web app immediately;
        the Telegram bot picks them up on its next restart.
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
        <StatusDot ok={cfg.llm.configured} />
        <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid }}>LLM (note summaries, ideas, ask)</span>
      </div>
      <TextField label="base url" value={llmBase} locked={cfg.llm.base_url.locked} source={cfg.llm.base_url.source} onChange={setLlmBase} />
      <TextField label="model" value={llmModel} locked={cfg.llm.model.locked} source={cfg.llm.model.source} onChange={setLlmModel} />
      <SecretField label="api key" configured={cfg.llm.api_key.configured} locked={cfg.llm.api_key.locked} source={cfg.llm.api_key.source} value={llmKey} onChange={setLlmKey} />

      <div style={{ display: "flex", alignItems: "center", gap: 7, margin: "16px 0 8px" }}>
        <StatusDot ok={cfg.embedding.configured} />
        <span style={{ fontFamily: P.mono, fontSize: 11, color: P.mid }}>Embeddings (semantic search, related, graph)</span>
      </div>
      <TextField label="base url" value={embBase} locked={cfg.embedding.base_url.locked} source={cfg.embedding.base_url.source} onChange={setEmbBase} />
      <TextField label="model" value={embModel} locked={cfg.embedding.model.locked} source={cfg.embedding.model.source} onChange={setEmbModel} />
      <SecretField label="api key" configured={cfg.embedding.api_key.configured} locked={cfg.embedding.api_key.locked} source={cfg.embedding.api_key.source} value={embKey} onChange={setEmbKey} />

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 6 }}>
        <TextAction busy={saving} disabled={saving} onClick={save}>save connections</TextAction>
        {saved && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>saved</span>}
      </div>
    </div>
  );
}
