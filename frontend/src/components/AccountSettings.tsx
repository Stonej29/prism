import { useEffect, useState, type CSSProperties } from "react";
import { api } from "../api";
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
const fieldLabel: CSSProperties = { fontFamily: P.mono, fontSize: 10, color: P.faint, letterSpacing: 0.6, marginBottom: 4 };

const MIN_PASSWORD = 8;

export function AccountSettings({ onLogout }: { onLogout: () => void }) {
  const [authRequired, setAuthRequired] = useState(false);
  const [envLocked, setEnvLocked] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.authStatus().then((s) => { setAuthRequired(s.auth_required); setEnvLocked(s.env_locked); }).catch(() => {});
  }, []);

  if (!authRequired) {
    return (
      <span style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo }}>
        Login is disabled on this (loopback) instance.
      </span>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== next;
  const tooShort = next.length > 0 && next.length < MIN_PASSWORD;
  const disabled = busy || !current || next.length < MIN_PASSWORD || next !== confirm;

  const submit = async () => {
    if (disabled) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(current, next);
      setCurrent(""); setNext(""); setConfirm("");
      setDone(true);
      setTimeout(() => setDone(false), 2500);
    } catch (e) {
      setError(String(e).replace(/^Error:\s*\d+:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {envLocked ? (
        <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 12 }}>
          Credentials are managed via environment variables, so they can’t be changed here.
        </div>
      ) : (
        <>
          <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 12 }}>Change your login password.</div>
          <div style={{ marginBottom: 10 }}>
            <div style={fieldLabel}>current password</div>
            <input style={input} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={fieldLabel}>new password</div>
            <input style={input} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            {tooShort && <div style={{ marginTop: 4, fontFamily: P.mono, fontSize: 9.5, color: P.lo }}>at least {MIN_PASSWORD} characters</div>}
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={fieldLabel}>confirm new password</div>
            <input style={input} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {mismatch && <div style={{ marginTop: 4, fontFamily: P.mono, fontSize: 9.5, color: P.arxiv }}>passwords don’t match</div>}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 4 }}>
            <TextAction busy={busy} disabled={disabled} onClick={submit}>change password</TextAction>
            {done && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>updated</span>}
            {error && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.arxiv }}>{error}</span>}
          </div>
        </>
      )}

      <div style={{ borderTop: `1px solid ${P.line}`, marginTop: 14, paddingTop: 12 }}>
        <TextAction danger onClick={onLogout}>log out</TextAction>
      </div>
    </div>
  );
}
