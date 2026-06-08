import { useEffect, useState } from "react";
import { api } from "../api";
import { P } from "../theme";
import { Backdrop } from "./AskOverlay";
import { MaintenancePanel } from "./MaintenancePanel";
import { TextAction } from "./TextAction";
import { ConnectionsSettings } from "./ConnectionsSettings";
import { AccountSettings } from "./AccountSettings";

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: `1px solid ${P.line}`, padding: "14px 0" }}>
      <div style={{ fontFamily: P.mono, fontSize: 10, letterSpacing: 1.2, color: P.faint, textTransform: "uppercase", marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}

// One place for everything that isn't day-to-day knowledge exploration: the
// editable profile, manual feed pulls, and graph maintenance / proposals / log.
export function SettingsOverlay({
  onClose,
  onPullFeeds,
  ingesting,
  pendingProposals,
  maintaining,
  onRunMaintenance,
  onReviewProposals,
  onOpenLog,
  onLogout,
}: {
  onClose: () => void;
  onPullFeeds: () => void;
  ingesting: boolean;
  pendingProposals: number;
  maintaining: boolean;
  onRunMaintenance: () => void | Promise<void>;
  onReviewProposals: () => void;
  onOpenLog: () => void;
  onLogout: () => void;
}) {
  const [profile, setProfile] = useState<string | null>(null);
  const [profileDirty, setProfileDirty] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  useEffect(() => {
    api.getProfile().then((r) => setProfile(r.content)).catch((e) => setProfileError(String(e)));
  }, []);

  const saveProfile = async () => {
    if (profile == null || savingProfile) return;
    setSavingProfile(true);
    setProfileError(null);
    try {
      const r = await api.saveProfile(profile);
      setProfile(r.content);
      setProfileDirty(false);
      setProfileSaved(true);
    } catch (e) {
      setProfileError(String(e));
    } finally {
      setSavingProfile(false);
    }
  };

  return (
    <Backdrop onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontFamily: P.mono, fontSize: 13, letterSpacing: 1, color: P.hi }}>Settings</span>
        <span onClick={onClose} style={{ fontFamily: P.mono, fontSize: 11, color: P.mid, cursor: "pointer" }}>close</span>
      </div>

      <SettingsSection title="Connections">
        <ConnectionsSettings />
      </SettingsSection>

      <SettingsSection title="Profile">
        <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 8 }}>
          The personal profile fed to the LLM when summarizing notes and generating ideas.
        </div>
        {profile == null ? (
          <span style={{ fontFamily: P.mono, fontSize: 11, color: P.lo }}>loading…</span>
        ) : (
          <>
            <textarea
              value={profile}
              onChange={(e) => { setProfile(e.target.value); setProfileDirty(true); setProfileSaved(false); }}
              spellCheck={false}
              style={{ width: "100%", boxSizing: "border-box", minHeight: 220, resize: "vertical", background: P.bg2, border: `1px solid ${P.line}`, borderRadius: 6, padding: "9px 11px", color: P.hi, fontFamily: P.mono, fontSize: 12, lineHeight: 1.5, outline: "none" }}
            />
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8 }}>
              <TextAction busy={savingProfile} disabled={savingProfile || !profileDirty} onClick={saveProfile}>save profile</TextAction>
              {profileDirty && !profileSaved && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.mid }}>unsaved</span>}
              {profileSaved && !profileDirty && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.lo }}>saved</span>}
              {profileError && <span style={{ fontFamily: P.mono, fontSize: 10, color: P.arxiv }}>{profileError}</span>}
            </div>
          </>
        )}
      </SettingsSection>

      <SettingsSection title="Feeds">
        <div style={{ fontFamily: P.sans, fontSize: 11.5, color: P.lo, marginBottom: 8 }}>
          Feeds pull automatically on a schedule (background worker). Trigger one now if you don't want to wait.
        </div>
        <TextAction busy={ingesting} disabled={ingesting} onClick={onPullFeeds}>pull feeds now</TextAction>
      </SettingsSection>

      <MaintenancePanel
        defaultOpen
        pendingProposals={pendingProposals}
        maintaining={maintaining}
        onRunMaintenance={onRunMaintenance}
        onReviewProposals={onReviewProposals}
        onOpenLog={onOpenLog}
      />

      <SettingsSection title="Account">
        <AccountSettings onLogout={onLogout} />
      </SettingsSection>
    </Backdrop>
  );
}
