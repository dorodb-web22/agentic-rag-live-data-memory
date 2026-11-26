import { useEffect, useRef, useState } from 'react';
import type { AuthUser } from './auth';
import type { Settings, ThemeMode } from './settings';

type Props = {
  open: boolean;
  user: AuthUser;
  settings: Settings;
  conversationCount: number;
  signingOut?: boolean;
  onChange: (next: Settings) => void;
  onSignOut: () => void;
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
  user,
  settings,
  conversationCount,
  signingOut = false,
  onChange,
  onSignOut,
  onExportAll,
  onClearAll,
  onClose,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [avatarError, setAvatarError] = useState(false);

  useEffect(() => {
    setAvatarError(false);
  }, [user.picture]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setConfirmClear(false);
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const initial = (user.name || user.email || '?').trim().slice(0, 1).toUpperCase();
  const showPicture = Boolean(user.picture) && !avatarError;

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
          <h3>Account</h3>
          <div className="account-card">
            {showPicture ? (
              <img
                className="avatar avatar--img avatar--lg"
                src={user.picture!}
                alt={user.name}
                referrerPolicy="no-referrer"
                onError={() => setAvatarError(true)}
              />
            ) : (
              <span className="avatar avatar--lg" aria-hidden="true">
                {initial}
              </span>
            )}
            <div className="account-details">
              <strong>{user.name}</strong>
              <span>{user.email}</span>
            </div>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={onSignOut}
              disabled={signingOut}
            >
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
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
            Your chat history and conversation memory are stored privately in your account on
            PostgreSQL and sync across devices. The agent has read-only access to connected data
            sources.
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
