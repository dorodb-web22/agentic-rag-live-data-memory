import { DragEvent, FormEvent, useEffect, useRef, useState } from 'react';
import { UnauthorizedApiError } from './chatStorage';
import {
  disconnectIntegration,
  getIntegrationConnectUrl,
  updateIntegrationConfig,
  uploadSqliteDatabase,
  type UserIntegrationItem,
} from './integrations';

type Props = {
  open: boolean;
  integrations: UserIntegrationItem[];
  initialProvider?: string | null;
  onRefresh: () => Promise<void> | void;
  onConnectOAuth?: (url: string) => void;
  onUnauthorized?: () => void;
  onClose: () => void;
};

function extractScopeInput(item: UserIntegrationItem): string {
  const cfg = item.config ?? {};
  if (Array.isArray(cfg.repos)) {
    return cfg.repos.map(String).join(', ');
  }
  if (typeof cfg.repo === 'string') return cfg.repo;
  if (typeof cfg.scope === 'string') return cfg.scope;
  if (typeof cfg.query_filter === 'string') return cfg.query_filter;
  return '';
}

function buildConfigPayload(provider: string, rawInput: string): Record<string, unknown> {
  const parts = rawInput
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (provider === 'github') {
    return { repos: parts, repo: parts[0] ?? '' };
  }
  if (provider === 'gmail') {
    return { query_filter: rawInput.trim() };
  }
  if (provider === 'notion') {
    return { root_pages: parts, scope: rawInput.trim() };
  }
  return { scope: rawInput.trim() };
}

function scopePlaceholder(provider: string): string {
  if (provider === 'github') return 'owner/repo1, owner/repo2 (leave blank for all accessible)';
  if (provider === 'gmail') return 'Optional Gmail search filter, e.g. label:work newer_than:90d';
  if (provider === 'notion') return 'Optional page or database filter';
  return 'Optional scope filter';
}

export default function IntegrationsModal({
  open,
  integrations,
  initialProvider = null,
  onRefresh,
  onConnectOAuth,
  onUnauthorized,
  onClose,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [editingProvider, setEditingProvider] = useState<string | null>(initialProvider);
  const [scopeDraft, setScopeDraft] = useState('');
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(null);
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setConfirmDisconnect(null);
      setFeedback(null);
      setEditingProvider(initialProvider);
      if (initialProvider) {
        const target = integrations.find((i) => i.provider === initialProvider);
        if (target) setScopeDraft(extractScopeInput(target));
      }
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initialProvider, integrations]);

  const needsReauthList = integrations.filter((i) => i.status === 'needs_reauth');

  function triggerOAuthConnect(provider: string) {
    const url = getIntegrationConnectUrl(provider);
    if (onConnectOAuth) {
      onConnectOAuth(url);
    } else {
      window.location.assign(url);
    }
  }

  async function handleSaveConfig(event: FormEvent, item: UserIntegrationItem) {
    event.preventDefault();
    setBusyProvider(item.provider);
    setFeedback(null);
    try {
      await updateIntegrationConfig(item.provider, buildConfigPayload(item.provider, scopeDraft));
      await onRefresh();
      setEditingProvider(null);
      setFeedback({ kind: 'ok', text: `Updated ${item.display_name} scope.` });
    } catch (cause) {
      if (cause instanceof UnauthorizedApiError) {
        onClose();
        onUnauthorized?.();
        return;
      }
      setFeedback({
        kind: 'error',
        text: cause instanceof Error ? cause.message : 'Failed to update configuration.',
      });
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleDisconnect(item: UserIntegrationItem) {
    setBusyProvider(item.provider);
    setFeedback(null);
    try {
      await disconnectIntegration(item.provider);
      setConfirmDisconnect(null);
      if (editingProvider === item.provider) setEditingProvider(null);
      await onRefresh();
      setFeedback({ kind: 'ok', text: `Disconnected ${item.display_name}.` });
    } catch (cause) {
      if (cause instanceof UnauthorizedApiError) {
        onClose();
        onUnauthorized?.();
        return;
      }
      setFeedback({
        kind: 'error',
        text: cause instanceof Error ? cause.message : 'Failed to disconnect integration.',
      });
    } finally {
      setBusyProvider(null);
    }
  }

  async function handleSqliteFile(file: File | undefined) {
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.db') && !lower.endsWith('.sqlite') && !lower.endsWith('.sqlite3')) {
      setFeedback({
        kind: 'error',
        text: 'Please choose a valid SQLite file (.db, .sqlite, or .sqlite3).',
      });
      return;
    }
    setBusyProvider('sqlite');
    setFeedback(null);
    try {
      await uploadSqliteDatabase(file);
      await onRefresh();
      setEditingProvider(null);
      setFeedback({ kind: 'ok', text: `Uploaded ${file.name} and connected SQLite.` });
    } catch (cause) {
      if (cause instanceof UnauthorizedApiError) {
        onClose();
        onUnauthorized?.();
        return;
      }
      setFeedback({
        kind: 'error',
        text: cause instanceof Error ? cause.message : 'SQLite upload failed.',
      });
    } finally {
      setBusyProvider(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files?.[0];
    void handleSqliteFile(file);
  }

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog integrations-dialog"
      aria-modal="true"
      aria-labelledby="integrations-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <div className="settings-panel">
        <header className="settings-header">
          <div>
            <h2 id="integrations-title">Integrations Hub</h2>
            <p className="settings-note">
              Connect your tools so the agent can ground answers in your private live data.
            </p>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close integrations"
          >
            ×
          </button>
        </header>

        {needsReauthList.length > 0 && (
          <div className="reauth-banner" role="alert" data-testid="reauth-banner">
            <div>
              <strong>Reconnection required</strong>
              <span>
                {needsReauthList.map((i) => i.display_name).join(', ')} token expired or was
                revoked.
              </span>
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => triggerOAuthConnect(needsReauthList[0].provider)}
            >
              Reconnect {needsReauthList[0].display_name}
            </button>
          </div>
        )}

        {feedback && (
          <div
            className={feedback.kind === 'error' ? 'error-box' : 'toast-banner'}
            role={feedback.kind === 'error' ? 'alert' : 'status'}
          >
            <span>{feedback.text}</span>
          </div>
        )}

        <ul className="integrations-list" aria-label="Available integrations">
          {integrations.map((item) => {
            const isConnected = item.status === 'connected';
            const isNeedsReauth = item.status === 'needs_reauth';
            const isComingSoon = !item.available || item.status === 'coming_soon';
            const isUpload = item.auth_type === 'upload';
            const isBusy = busyProvider === item.provider;
            const isExpanded = editingProvider === item.provider;

            return (
              <li
                key={item.provider}
                className="integration-item"
                data-testid={`integration-row-${item.provider}`}
              >
                <div className="integration-row-main">
                  <span
                    className={`health-dot ${
                      isConnected
                        ? 'health-dot--online'
                        : isNeedsReauth
                          ? 'health-dot--warn'
                          : ''
                    }`}
                    aria-hidden="true"
                  />
                  <div className="integration-info">
                    <div className="integration-title-row">
                      <strong>{item.display_name}</strong>
                      {item.category && <span className="chip-tag">{item.category}</span>}
                      {isComingSoon && <span className="chip-tag">Coming soon</span>}
                      {isConnected && (
                        <span className="state-tag state-tag--open">Connected</span>
                      )}
                      {isNeedsReauth && (
                        <span className="chip-tag chip-tag--warn">Needs reauth</span>
                      )}
                    </div>
                    <p className="integration-desc">
                      {isConnected && item.scope_summary ? item.scope_summary : item.description}
                    </p>
                  </div>

                  <div className="integration-actions">
                    {isComingSoon ? (
                      <button type="button" className="btn btn--ghost" disabled>
                        Coming soon
                      </button>
                    ) : isNeedsReauth ? (
                      <button
                        type="button"
                        className="btn"
                        disabled={isBusy}
                        onClick={() => triggerOAuthConnect(item.provider)}
                      >
                        Reconnect
                      </button>
                    ) : isConnected ? (
                      <>
                        <button
                          type="button"
                          className="btn btn--secondary"
                          disabled={isBusy}
                          onClick={() => {
                            if (isExpanded) {
                              setEditingProvider(null);
                            } else {
                              setEditingProvider(item.provider);
                              setScopeDraft(extractScopeInput(item));
                            }
                          }}
                        >
                          {isUpload ? 'Replace DB' : isExpanded ? 'Done' : 'Configure'}
                        </button>
                        {confirmDisconnect === item.provider ? (
                          <button
                            type="button"
                            className="btn btn--danger"
                            disabled={isBusy}
                            onClick={() => void handleDisconnect(item)}
                          >
                            {isBusy ? 'Removing…' : 'Confirm disconnect'}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn--ghost-danger"
                            disabled={isBusy}
                            onClick={() => setConfirmDisconnect(item.provider)}
                          >
                            Disconnect
                          </button>
                        )}
                      </>
                    ) : isUpload ? (
                      <button
                        type="button"
                        className="btn"
                        disabled={isBusy}
                        onClick={() =>
                          setEditingProvider(isExpanded ? null : item.provider)
                        }
                      >
                        + Connect
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        disabled={isBusy}
                        onClick={() => triggerOAuthConnect(item.provider)}
                      >
                        + Connect
                      </button>
                    )}
                  </div>
                </div>

                {isExpanded && isUpload && (
                  <div
                    className={`sqlite-dropzone${dragActive ? ' sqlite-dropzone--active' : ''}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragActive(true);
                    }}
                    onDragLeave={() => setDragActive(false)}
                    onDrop={onDrop}
                    data-testid="sqlite-dropzone"
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".db,.sqlite,.sqlite3"
                      aria-label="Upload SQLite database file"
                      onChange={(e) => void handleSqliteFile(e.target.files?.[0])}
                    />
                    <p>
                      {isBusy
                        ? 'Uploading SQLite database…'
                        : 'Drag & drop a .db / .sqlite file here, or choose a file above.'}
                    </p>
                  </div>
                )}

                {isExpanded && !isUpload && isConnected && (
                  <form
                    className="integration-config-form"
                    onSubmit={(e) => void handleSaveConfig(e, item)}
                  >
                    <label className="field">
                      <span>Scope configuration</span>
                      <input
                        type="text"
                        value={scopeDraft}
                        placeholder={scopePlaceholder(item.provider)}
                        onChange={(e) => setScopeDraft(e.target.value)}
                      />
                    </label>
                    <div className="settings-actions">
                      <button type="submit" className="btn" disabled={isBusy}>
                        {isBusy ? 'Saving…' : 'Save scope'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => setEditingProvider(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </dialog>
  );
}
