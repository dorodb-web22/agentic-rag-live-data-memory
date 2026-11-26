import { FormEvent, useEffect, useRef, useState } from 'react';
import type { Settings, ThemeMode } from './settings';

type Props = {
  open: boolean;
  settings: Settings;
  activeUser: string;
  conversationCount: number;
  onChange: (next: Settings) => void;
  onSwitchUser: (handle: string) => void;
  onExportAll: () => void;
  onClearAll: () => void;
  onClose: () => void;
};

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

export default function SettingsDialog({
  open,
  settings,
  activeUser,
  conversationCount,
  onChange,
  onSwitchUser,
  onExportAll,
  onClearAll,
  onClose,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [profileDraft, setProfileDraft] = useState(activeUser);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setProfileDraft(activeUser);
      setConfirmClear(false);
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, activeUser]);

  function submitProfile(event: FormEvent) {
    event.preventDefault();
    if (profileDraft.trim() && profileDraft.trim() !== activeUser) onSwitchUser(profileDraft);
  }

  return (
    <dialog
      ref={ref}
      className="settings-dialog"
      aria-labelledby="settings-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="settings-panel">
        <header className="settings-header">
          <h2 id="settings-title">Settings</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close settings">
            ×
          </button>
        </header>

        <section className="settings-section">
          <h3>Appearance</h3>
          <div className="segmented" role="radiogroup" aria-label="Theme">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={settings.theme === option.value}
                className={`segment${settings.theme === option.value ? ' segment--active' : ''}`}
                onClick={() => onChange({ ...settings, theme: option.value })}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>

        <section className="settings-section">
          <h3>Profile</h3>
          <label className="field">
            <span>Display name</span>
            <input
              type="text"
              value={settings.displayName}
              maxLength={40}
              placeholder={activeUser}
              onChange={(e) => onChange({ ...settings, displayName: e.target.value })}
            />
          </label>
          <form className="field field--inline" onSubmit={submitProfile}>
            <label>
              <span>Signed in as (chat history is kept per profile)</span>
              <input
                type="text"
                value={profileDraft}
                onChange={(e) => setProfileDraft(e.target.value)}
              />
            </label>
            <button type="submit" className="btn btn--secondary">
              Switch
            </button>
          </form>
        </section>

        <section className="settings-section">
          <h3>Workspace</h3>
          <label className="toggle-row">
            <span>
              Show sources &amp; trace panel automatically
              <small>Opens the details panel whenever an answer arrives.</small>
            </span>
            <input
              type="checkbox"
              role="switch"
              checked={settings.showDetailsByDefault}
              onChange={(e) => onChange({ ...settings, showDetailsByDefault: e.target.checked })}
            />
          </label>
        </section>

        <section className="settings-section">
          <h3>Data &amp; privacy</h3>
          <p className="settings-note">
            Saved chats live in this browser only. Agent memory for a conversation is stored
            server-side in PostgreSQL under its thread ID. The agent has read-only access to
            connected data sources.
          </p>
          <div className="settings-actions">
            <button
              type="button"
              className="btn btn--secondary"
              onClick={onExportAll}
              disabled={conversationCount === 0}
            >
              Export all chats
            </button>
            {confirmClear ? (
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => {
                  onClearAll();
                  setConfirmClear(false);
                }}
              >
                Confirm: delete {conversationCount} chat{conversationCount === 1 ? '' : 's'}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--ghost-danger"
                onClick={() => setConfirmClear(true)}
                disabled={conversationCount === 0}
              >
                Clear all chats
              </button>
            )}
          </div>
        </section>
      </div>
    </dialog>
  );
}
