import { useState, type CSSProperties, type FormEvent } from "react";
import { api } from "../api";
import { P } from "../theme";
import { Logo } from "./Logo";

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: P.bg0,
  border: `1px solid ${P.line}`,
  borderRadius: 8,
  color: P.hi,
  fontFamily: P.sans,
  fontSize: 14,
  padding: "10px 12px",
  outline: "none",
};

const labelStyle: CSSProperties = {
  display: "block",
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: 0.6,
  color: P.mid,
  marginBottom: 6,
};

const MIN_PASSWORD = 8;

export function Login({ needsSetup, onAuthenticated }: { needsSetup: boolean; onAuthenticated: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tooShort = needsSetup && password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = needsSetup && confirm.length > 0 && confirm !== password;
  const disabled =
    busy || !username || !password || (needsSetup && (password.length < MIN_PASSWORD || confirm !== password));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (disabled) return;
    setBusy(true);
    setError(null);
    try {
      const res = needsSetup
        ? await api.setupAccount(username, password)
        : await api.login(username, password);
      if (res.authenticated) onAuthenticated();
      else setError(needsSetup ? "Could not create the account." : "Invalid username or password.");
    } catch (err) {
      setError(
        needsSetup
          ? `Could not create the account. ${String(err).replace(/^Error:\s*\d+:\s*/, "")}`.trim()
          : "Invalid username or password.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: P.bg0,
        color: P.hi,
        fontFamily: P.sans,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: 320,
          background: P.bg1,
          border: `1px solid ${P.line}`,
          borderRadius: 14,
          padding: "30px 28px 26px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Logo size={26} />
          <span style={{ fontSize: 19, fontWeight: 600, letterSpacing: 0.5 }}>PRISM</span>
        </div>
        <p style={{ margin: "0 0 22px", fontSize: 13, color: P.mid }}>
          {needsSetup ? "Create your owner account to secure this vault." : "Sign in to your vault."}
        </p>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle} htmlFor="prism-username">Username</label>
          <input
            id="prism-username"
            style={inputStyle}
            value={username}
            autoFocus
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div style={{ marginBottom: needsSetup ? 14 : 18 }}>
          <label style={labelStyle} htmlFor="prism-password">Password</label>
          <input
            id="prism-password"
            type="password"
            style={inputStyle}
            value={password}
            autoComplete={needsSetup ? "new-password" : "current-password"}
            onChange={(e) => setPassword(e.target.value)}
          />
          {tooShort && (
            <div style={{ marginTop: 6, fontSize: 11.5, color: P.lo }}>At least {MIN_PASSWORD} characters.</div>
          )}
        </div>
        {needsSetup && (
          <div style={{ marginBottom: 18 }}>
            <label style={labelStyle} htmlFor="prism-confirm">Confirm password</label>
            <input
              id="prism-confirm"
              type="password"
              style={inputStyle}
              value={confirm}
              autoComplete="new-password"
              onChange={(e) => setConfirm(e.target.value)}
            />
            {mismatch && (
              <div style={{ marginTop: 6, fontSize: 11.5, color: P.arxiv }}>Passwords don’t match.</div>
            )}
          </div>
        )}

        {error && <div style={{ marginBottom: 14, fontSize: 12.5, color: P.arxiv }}>{error}</div>}

        <button
          type="submit"
          disabled={disabled}
          style={{
            width: "100%",
            background: disabled ? P.bg2 : P.accent,
            color: disabled ? P.mid : "#0a0c10",
            border: "none",
            borderRadius: 8,
            padding: "10px 12px",
            fontFamily: P.sans,
            fontSize: 14,
            fontWeight: 600,
            cursor: disabled ? "default" : "pointer",
          }}
        >
          {busy ? (needsSetup ? "Creating…" : "Signing in…") : needsSetup ? "Create account" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
