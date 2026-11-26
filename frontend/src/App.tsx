import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  fetchCurrentUser,
  getFirstName,
  getLandingUrl,
  logoutCurrentUser,
  redirectToLanding,
  type AuthUser,
} from './auth';
import {
  conversationToMarkdown,
  UnauthorizedApiError,
  type ChatMessage,
  type SavedConversation,
} from './chatStorage';
import EvidencePanel, { recordCitationKey } from './EvidencePanel';
import ExecutionTrace from './ExecutionTrace';
import {
  buildSuggestedPrompts,
  fetchIntegrations,
  getIntegrationConnectUrl,
  type UserIntegrationItem,
} from './integrations';
import IntegrationsModal from './IntegrationsModal';
import SettingsDialog from './SettingsDialog';
import Sidebar, { type HealthState } from './Sidebar';
import {
  applyTheme,
  loadSettings,
  resolveTheme,
  saveSettings,
  type Settings,
} from './settings';
import { linkifyCitations, MAX_QUERY_LENGTH } from './streaming';
import { useQueryStream } from './useQueryStream';

function downloadFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type AuthGateState =
  | { status: 'checking' }
  | { status: 'authenticated'; user: AuthUser }
  | { status: 'unauthenticated'; expired?: boolean }
  | { status: 'error'; message: string };

const PROVIDER_LABELS: Record<string, string> = {
  github: 'GitHub',
  gmail: 'Gmail',
  notion: 'Notion',
  sqlite: 'SQLite',
  google_sheets: 'Google Sheets',
  google_calendar: 'Google Calendar',
};

function formatConnectorLabel(raw?: string): string {
  if (!raw) return 'Connector';
  const normalized = raw.trim().toLowerCase();
  return PROVIDER_LABELS[normalized] ?? raw;
}

type AppProps = {
  onNavigate?: (url: string) => void;
};

export default function App({ onNavigate }: AppProps = {}) {
  const [authState, setAuthState] = useState<AuthGateState>({ status: 'checking' });
  const wasAuthenticatedRef = useRef(false);
  const [signingOut, setSigningOut] = useState(false);
  const [query, setQuery] = useState('');
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    resolveTheme(loadSettings().theme),
  );
  const [health, setHealth] = useState<HealthState>('checking');
  const [integrations, setIntegrations] = useState<UserIntegrationItem[]>([]);
  const [integrationsLoading, setIntegrationsLoading] = useState(false);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);
  const [focusedProvider, setFocusedProvider] = useState<string | null>(null);
  const [connectedToast, setConnectedToast] = useState<string | null>(null);
  const [oauthErrorToast, setOauthErrorToast] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [highlightedCitation, setHighlightedCitation] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleUnauthorized = useCallback(() => {
    const expired = wasAuthenticatedRef.current;
    wasAuthenticatedRef.current = false;
    setAuthState({ status: 'unauthenticated', expired });
    redirectToLanding(onNavigate);
  }, [onNavigate]);

  const checkSession = useCallback(
    async (signal?: AbortSignal) => {
      setAuthState({ status: 'checking' });
      try {
        const result = await fetchCurrentUser(signal);
        if (signal?.aborted) return;
        if (result.status === 'unauthenticated') {
          wasAuthenticatedRef.current = false;
          setAuthState({ status: 'unauthenticated', expired: false });
          redirectToLanding(onNavigate);
          return;
        }
        wasAuthenticatedRef.current = true;
        setAuthState({ status: 'authenticated', user: result.user });
      } catch (cause) {
        if (signal?.aborted) return;
        setAuthState({
          status: 'error',
          message:
            cause instanceof Error
              ? cause.message
              : 'Could not verify your session. Check that the API is running.',
        });
      }
    },
    [onNavigate],
  );

  useEffect(() => {
    const controller = new AbortController();
    void checkSession(controller.signal);
    return () => controller.abort();
  }, [checkSession]);

  const isAuthenticated = authState.status === 'authenticated';

  const refreshIntegrations = useCallback(
    async (signal?: AbortSignal) => {
      setIntegrationsLoading(true);
      try {
        const items = await fetchIntegrations(signal);
        if (!signal?.aborted) {
          setIntegrations(items);
        }
      } catch (cause) {
        if (signal?.aborted) return;
        if (cause instanceof UnauthorizedApiError) {
          handleUnauthorized();
        }
      } finally {
        if (!signal?.aborted) {
          setIntegrationsLoading(false);
        }
      }
    },
    [handleUnauthorized],
  );

  // Load registry-driven per-user integrations & handle ?connected=<provider> toast
  useEffect(() => {
    if (!isAuthenticated) return;
    const controller = new AbortController();

    const params = new URLSearchParams(window.location.search);
    const connectedProvider = params.get('connected')?.trim();
    const oauthErr = params.get('error')?.trim();
    const oauthErrProv = params.get('provider')?.trim();
    let dirtyUrl = false;

    if (connectedProvider) {
      setConnectedToast(connectedProvider);
      params.delete('connected');
      dirtyUrl = true;
    }
    if (oauthErr) {
      const provLabel = formatConnectorLabel(oauthErrProv);
      setOauthErrorToast(
        oauthErr === 'access_denied'
          ? `${provLabel} authorization was cancelled.`
          : `Could not complete ${provLabel} connection (${oauthErr}). Please try again.`,
      );
      params.delete('error');
      params.delete('provider');
      dirtyUrl = true;
    }
    if (dirtyUrl) {
      const qs = params.toString();
      const nextUrl = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`;
      window.history.replaceState({}, '', nextUrl);
    }

    void refreshIntegrations(controller.signal);
    return () => controller.abort();
  }, [isAuthenticated, refreshIntegrations]);

  const {
    conversations,
    activeThreadId,
    selectConversation,
    removeConversation,
    clearAllConversations,
    hydrateAllConversations,
    inspectTurn,
    messages,
    evidence,
    warnings,
    steps,
    traceUrl,
    error,
    rateLimitMessage,
    rateLimitSecondsLeft,
    lastFailedQuery,
    dismissRateLimit,
    retryLastQuery,
    loading,
    loadingThread,
    hasThread,
    submit,
    stop,
    reset,
  } = useQueryStream({
    enabled: isAuthenticated,
    onUnauthorized: handleUnauthorized,
  });

  const chatEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const view: 'home' | 'chat' =
    messages.length > 0 || loading || loadingThread ? 'chat' : 'home';

  const suggestedCards = useMemo(() => buildSuggestedPrompts(integrations, 4), [integrations]);
  const connectedCount = useMemo(
    () => integrations.filter((i) => i.status === 'connected').length,
    [integrations],
  );
  const needsReauthItems = useMemo(
    () => integrations.filter((i) => i.status === 'needs_reauth'),
    [integrations],
  );

  const connectedToastLabel = useMemo(() => {
    if (!connectedToast) return null;
    const match = integrations.find((i) => i.provider === connectedToast);
    return match?.display_name ?? connectedToast;
  }, [connectedToast, integrations]);

  // ---- theme & persisted UI preferences ----
  useEffect(() => {
    setResolvedTheme(applyTheme(settings.theme));
    saveSettings(settings);
    if (settings.theme !== 'system' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setResolvedTheme(applyTheme('system'));
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [settings]);

  // ---- live /api/health/deep status ----
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/api/health/deep', { credentials: 'include' });
        if (!cancelled) setHealth(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setHealth('offline');
      }
    };
    void check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (typeof chatEndRef.current?.scrollIntoView === 'function') {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages.length, loading]);

  // auto-grow composer
  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [query]);

  const ask = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading || rateLimitSecondsLeft > 0) return;
      const completed = await submit(trimmed);
      if (completed) {
        setQuery('');
        if (settings.showDetailsByDefault) setDetailsOpen(true);
      } else {
        setQuery((prev) => prev || trimmed);
      }
    },
    [loading, rateLimitSecondsLeft, submit, settings.showDetailsByDefault],
  );

  function openIntegrationsHub(provider: string | null = null) {
    setFocusedProvider(provider);
    setIntegrationsOpen(true);
  }

  function connectOAuth(provider: string) {
    const url = getIntegrationConnectUrl(provider);
    if (onNavigate) {
      onNavigate(url);
    } else {
      window.location.assign(url);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(query);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask(query);
    }
  }

  function openCitation(citeKey: string, msg?: ChatMessage) {
    if (msg) {
      inspectTurn(msg.evidence ?? null, msg.traceUrl ?? null);
    }
    setHighlightedCitation(citeKey);
    setDetailsOpen(true);
    requestAnimationFrame(() => {
      const el = document.getElementById(`evidence-${citeKey}`);
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }

  async function copyMessage(id: string, content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  function exportActiveChat() {
    const existing = activeThreadId
      ? conversations.find((c) => c.threadId === activeThreadId)
      : undefined;
    const conv: SavedConversation | null =
      messages.length > 0
        ? {
            id: existing?.id ?? activeThreadId ?? 'unsaved',
            threadId: activeThreadId,
            title: existing?.title ?? messages[0].content.slice(0, 48),
            messages,
            evidence,
            steps,
            traceUrl,
            updatedAt: existing?.updatedAt ?? new Date().toISOString(),
          }
        : (existing ?? null);
    if (!conv) return;
    downloadFile(
      `agentic-rag-chat-${(conv.threadId ?? conv.id).slice(0, 8)}.md`,
      conversationToMarkdown(conv),
      'text/markdown;charset=utf-8',
    );
  }

  async function exportAllChats() {
    if (authState.status !== 'authenticated') return;
    const hydrated = await hydrateAllConversations();
    const safeEmail = authState.user.email.split('@')[0] || 'account';
    downloadFile(
      `agentic-rag-all-chats-${safeEmail}.json`,
      JSON.stringify(hydrated, null, 2),
      'application/json;charset=utf-8',
    );
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logoutCurrentUser();
    } catch {
      /* proceed with client redirect even if network fails */
    } finally {
      setSigningOut(false);
      setSettingsOpen(false);
      setAuthState({ status: 'unauthenticated' });
      redirectToLanding(onNavigate);
    }
  }

  function toggleQuickTheme() {
    setSettings((prev) => ({ ...prev, theme: resolvedTheme === 'dark' ? 'light' : 'dark' }));
  }

  function setSidebarCollapsed(collapsed: boolean) {
    setSettings((prev) => ({ ...prev, sidebarCollapsed: collapsed }));
  }

  if (authState.status === 'checking') {
    return (
      <div className="auth-gate" role="status" data-testid="auth-checking">
        <div className="auth-gate-card">
          <div>
            <span className="spinner" aria-hidden="true" />
          </div>
          <h1>Loading your workspace…</h1>
          <p>Verifying your Google session.</p>
        </div>
      </div>
    );
  }

  if (authState.status === 'unauthenticated') {
    return (
      <div className="auth-gate" data-testid="auth-unauthenticated">
        <div className="auth-gate-card">
          <h1>{authState.expired ? 'Session expired' : 'Sign in required'}</h1>
          <p data-testid={authState.expired ? 'session-expired-notice' : undefined}>
            {authState.expired
              ? 'Your Google session expired. Redirecting you to the landing page to sign in again…'
              : 'Redirecting you to the landing page to sign in with Google…'}
          </p>
          <div className="auth-gate-actions">
            <a className="btn" href={getLandingUrl()}>
              Continue to landing page
            </a>
          </div>
        </div>
      </div>
    );
  }

  if (authState.status === 'error') {
    return (
      <div className="auth-gate" role="alert" data-testid="auth-error">
        <div className="auth-gate-card">
          <h1>Could not verify session</h1>
          <p>{authState.message}</p>
          <div className="auth-gate-actions">
            <button type="button" className="btn" onClick={() => void checkSession()}>
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  const user = authState.user;
  const firstName = getFirstName(user);
  const lastAssistantId = [...messages].reverse().find((m) => m.role === 'assistant')?.id;
  const activeTitle =
    (activeThreadId
      ? conversations.find((c) => c.threadId === activeThreadId)?.title
      : undefined) ?? 'New chat';
  const evidenceCount = evidence?.length ?? 0;

  const composer = (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={composerRef}
        id="query"
        name="query"
        rows={1}
        aria-label="Ask a question"
        placeholder="Ask across your connected GitHub, Gmail, Notion, or SQLite data…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
        maxLength={MAX_QUERY_LENGTH}
        disabled={loading}
      />
      {loading ? (
        <button type="button" className="send-btn send-btn--stop" onClick={stop} aria-label="Stop">
          ■
        </button>
      ) : (
        <button
          type="submit"
          className="send-btn"
          disabled={!query.trim() || rateLimitSecondsLeft > 0}
          aria-label="Send question"
        >
          ↑
        </button>
      )}
    </form>
  );

  return (
    <div className="app-shell">
      <Sidebar
        user={user}
        conversations={conversations}
        activeThreadId={activeThreadId}
        activeView={view}
        health={health}
        connectedIntegrationsCount={connectedCount}
        needsReauthCount={needsReauthItems.length}
        collapsed={settings.sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(true)}
        onHome={reset}
        onNewChat={() => {
          reset();
          composerRef.current?.focus();
        }}
        onSelect={(threadId) => void selectConversation(threadId)}
        onDelete={(threadId) => void removeConversation(threadId)}
        onOpenIntegrations={() => openIntegrationsHub(null)}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            {settings.sidebarCollapsed && (
              <button
                type="button"
                className="icon-btn"
                onClick={() => setSidebarCollapsed(false)}
                aria-label="Expand sidebar"
                title="Expand sidebar"
              >
                »
              </button>
            )}
            <h1 className="topbar-title">{view === 'home' ? 'Home' : activeTitle}</h1>
            {hasThread && view === 'chat' && (
              <span className="memory-pill" data-testid="memory-badge">
                Memory on
              </span>
            )}
          </div>
          <div className="topbar-right">
            {messages.length > 0 && (
              <button type="button" className="btn btn--ghost" onClick={exportActiveChat}>
                Export
              </button>
            )}
            <button
              type="button"
              className={`btn btn--ghost${detailsOpen ? ' btn--pressed' : ''}`}
              onClick={() => setDetailsOpen((v) => !v)}
              aria-pressed={detailsOpen}
            >
              Sources &amp; trace
              {evidenceCount > 0 && <span className="badge">{evidenceCount}</span>}
            </button>
            <button
              type="button"
              className="icon-btn"
              onClick={toggleQuickTheme}
              aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
              title="Toggle light / dark"
            >
              {resolvedTheme === 'dark' ? '☀' : '☾'}
            </button>
          </div>
        </header>

        <main className="stage" aria-live="polite">
          {connectedToastLabel && (
            <div className="toast-banner toast-banner--stage" role="status" data-testid="connected-toast">
              <span>✓ {connectedToastLabel} connected to your workspace.</span>
              <button
                type="button"
                className="icon-btn"
                aria-label="Dismiss notification"
                onClick={() => setConnectedToast(null)}
              >
                ×
              </button>
            </div>
          )}

          {oauthErrorToast && (
            <div className="error-box error-box--stage" role="alert" data-testid="oauth-error-banner">
              <div className="banner-row">
                <span>{oauthErrorToast}</span>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="Dismiss OAuth error"
                  onClick={() => setOauthErrorToast(null)}
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {rateLimitMessage && (
            <div className="reauth-banner reauth-banner--stage rate-limit-banner" role="alert" data-testid="rate-limit-banner">
              <div>
                <strong>Rate limit reached:</strong>{' '}
                <span>{rateLimitMessage}</span>
                <span className="chip-tag chip-tag--warn" data-testid="rate-limit-countdown">
                  {rateLimitSecondsLeft > 0 ? `Retry in ${rateLimitSecondsLeft}s` : 'Ready to retry'}
                </span>
              </div>
              <div className="banner-actions">
                {lastFailedQuery && (
                  <button
                    type="button"
                    className="btn btn--xs"
                    disabled={rateLimitSecondsLeft > 0 || loading}
                    onClick={() => void retryLastQuery()}
                  >
                    Retry
                  </button>
                )}
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="Dismiss rate limit notice"
                  onClick={dismissRateLimit}
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {needsReauthItems.length > 0 && (
            <div className="reauth-banner reauth-banner--stage" role="alert" data-testid="stage-reauth-banner">
              <div>
                <strong>Reconnection needed:</strong>{' '}
                <span>
                  {needsReauthItems.map((i) => i.display_name).join(', ')} needs re-authorization.
                </span>
              </div>
              <button
                type="button"
                className="btn btn--xs"
                onClick={() => connectOAuth(needsReauthItems[0].provider)}
              >
                Reconnect
              </button>
            </div>
          )}

          {view === 'home' ? (
            <div className="home">
              <h2 className="welcome">
                <span className="welcome-name">Welcome, {firstName}!</span>
                <span className="welcome-sub">How can I help you today?</span>
              </h2>

              <section className="card-grid" aria-label="Suggested questions">
                {suggestedCards.map((s) => (
                  <button
                    key={s.text}
                    type="button"
                    className="suggest-card"
                    onClick={() => void ask(s.text)}
                  >
                    <span className="suggest-label">{s.label}</span>
                    <span className="suggest-text">{s.text}</span>
                  </button>
                ))}
              </section>

              <section className="sources-section" aria-label="Connected data sources">
                <div className="section-header-row">
                  <h3 className="section-label">
                    {connectedCount > 0
                      ? `Integrations · ${connectedCount} connected`
                      : 'Connect your data sources'}
                  </h3>
                  <button
                    type="button"
                    className="text-btn"
                    onClick={() => openIntegrationsHub(null)}
                  >
                    Manage integrations
                  </button>
                </div>

                {integrationsLoading && integrations.length === 0 ? (
                  <p className="history-empty">Loading available integrations…</p>
                ) : integrations.length === 0 ? (
                  <div className="empty-sources-card" data-testid="home-sources-empty">
                    <div>
                      <strong>Connect your first tool</strong>
                      <span>
                        Link GitHub, Gmail, Notion, or upload a SQLite database so answers are
                        grounded in your live private workspace.
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn--xs"
                      onClick={() => openIntegrationsHub(null)}
                    >
                      + Connect tools
                    </button>
                  </div>
                ) : (
                  <ul className="source-grid">
                    {integrations.map((source) => {
                      const isConnected = source.status === 'connected';
                      const isNeedsReauth = source.status === 'needs_reauth';
                      const isComingSoon = !source.available || source.status === 'coming_soon';

                      return (
                        <li
                          key={source.provider}
                          className={`source-card${
                            isConnected ? ' source-card--interactive' : ''
                          }${isComingSoon ? ' source-card--coming-soon' : ''}`}
                          data-testid={`home-source-${source.provider}`}
                          onClick={
                            isConnected
                              ? () => openIntegrationsHub(source.provider)
                              : undefined
                          }
                        >
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
                          <div>
                            <strong>{source.display_name}</strong>
                            <span>
                              {isConnected && source.scope_summary
                                ? source.scope_summary
                                : source.description}
                            </span>
                          </div>
                          {isComingSoon ? (
                            <span className="chip-tag">Coming soon</span>
                          ) : isNeedsReauth ? (
                            <button
                              type="button"
                              className="btn btn--xs"
                              onClick={(e) => {
                                e.stopPropagation();
                                connectOAuth(source.provider);
                              }}
                            >
                              Reconnect
                            </button>
                          ) : isConnected ? (
                            <span className="chip-tag">Connected</span>
                          ) : (
                            <button
                              type="button"
                              className="btn btn--xs"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (source.auth_type === 'upload') {
                                  openIntegrationsHub(source.provider);
                                } else {
                                  connectOAuth(source.provider);
                                }
                              }}
                            >
                              + Connect
                            </button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </div>
          ) : (
            <div className="conversation">
              {loadingThread && messages.length === 0 && (
                <div className="message message--assistant message--pending" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <span>Loading conversation…</span>
                </div>
              )}

              {messages.map((msg) => {
                const msgEvidence =
                  msg.evidence !== undefined
                    ? msg.evidence
                    : msg.id === lastAssistantId
                      ? evidence
                      : null;
                const msgTraceUrl =
                  msg.traceUrl !== undefined
                    ? msg.traceUrl
                    : msg.id === lastAssistantId
                      ? (traceUrl ?? null)
                      : null;
                const msgWarnings =
                  msg.warnings !== undefined
                    ? msg.warnings
                    : msg.id === lastAssistantId
                      ? warnings
                      : null;

                return (
                  <article
                    key={msg.id}
                    className={`message message--${msg.role}`}
                    data-testid={`chat-bubble-${msg.role}`}
                  >
                    {msg.role === 'user' ? (
                      <p className="message-text">{msg.content}</p>
                    ) : (
                      <>
                        {msgWarnings && msgWarnings.length > 0 && (
                          <div
                            className="partial-warning-card"
                            role="status"
                            data-testid="partial-connector-warning"
                          >
                            <div className="partial-warning-body">
                              <strong>
                                Partial source issue ({msgWarnings
                                  .map((w) => formatConnectorLabel(w.provider || w.tool))
                                  .join(', ')})
                              </strong>
                              <span>
                                {msgWarnings
                                  .map(
                                    (w) =>
                                      `${formatConnectorLabel(w.provider || w.tool)}: ${w.message}`,
                                  )
                                  .join(' · ')}{' '}
                                — answered using your remaining healthy sources.
                              </span>
                            </div>
                            <button
                              type="button"
                              className="btn btn--xs"
                              onClick={() =>
                                openIntegrationsHub(msgWarnings[0]?.provider ?? null)
                              }
                            >
                              Check integration
                            </button>
                          </div>
                        )}
                        <div className="markdown">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              a: ({ node: _node, href, children, ...props }) =>
                                href?.startsWith('#cite-') ? (
                                  <sup
                                    className="cite"
                                    role="button"
                                    tabIndex={0}
                                    title={`Source: ${href.slice(6)} — click to view`}
                                    onClick={() => openCitation(href.slice(6), msg)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        openCitation(href.slice(6), msg);
                                      }
                                    }}
                                  >
                                    {children}
                                  </sup>
                                ) : (
                                  <a {...props} href={href} target="_blank" rel="noopener noreferrer">
                                    {children}
                                  </a>
                                ),
                              table: ({ node: _node, ...props }) => (
                                <div className="table-scroll">
                                  <table {...props} />
                                </div>
                              ),
                            }}
                          >
                            {linkifyCitations(msg.content)}
                          </ReactMarkdown>
                        </div>
                        <footer className="message-meta">
                          {msgEvidence && msgEvidence.length > 0 && (
                            <span className="grounded" data-testid="grounded-badge">
                              ✓ Grounded in {msgEvidence.length} source
                              {msgEvidence.length === 1 ? '' : 's'}
                            </span>
                          )}
                          {msgEvidence?.map((rec, idx) => {
                            const key = recordCitationKey(rec, idx);
                            return (
                              <button
                                key={`${key}-${idx}`}
                                type="button"
                                className="source-chip"
                                onClick={() => openCitation(key, msg)}
                              >
                                {key}
                              </button>
                            );
                          })}
                          {msgTraceUrl && (
                            <a
                              className="source-chip"
                              href={msgTraceUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={() => inspectTurn(msgEvidence, msgTraceUrl)}
                              data-testid="turn-trace-link"
                            >
                              Trace ↗
                            </a>
                          )}
                          <button
                            type="button"
                            className="text-btn"
                            onClick={() => void copyMessage(msg.id, msg.content)}
                          >
                            {copiedId === msg.id ? 'Copied' : 'Copy'}
                          </button>
                        </footer>
                      </>
                    )}
                  </article>
                );
              })}

              {loading && (
                <div className="message message--assistant message--pending" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <span>
                    {steps.length > 0 && steps[steps.length - 1].status === 'running'
                      ? steps[steps.length - 1].node === 'planner'
                        ? 'Planning which connected tools to invoke…'
                        : steps[steps.length - 1].node === 'tools'
                          ? 'Querying connected tools in parallel…'
                          : 'Synthesizing answer and validating citations…'
                      : 'Working on your answer…'}
                  </span>
                </div>
              )}

              {error && (
                <div className="error-box" role="alert">
                  <div className="banner-row">
                    <div className="error-box-copy">
                      <strong>We couldn’t get an answer</strong>
                      <span>{error}</span>
                    </div>
                    {lastFailedQuery && !loading && (
                      <button
                        type="button"
                        className="btn btn--xs"
                        onClick={() => void retryLastQuery()}
                      >
                        Try again
                      </button>
                    )}
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          )}
        </main>

        <div className="composer-wrap">
          {composer}
          <p className="composer-note">
            Answers come from your connected data and include citations. Check important details
            against the source records.
            {query.length > MAX_QUERY_LENGTH * 0.8 && (
              <span className="count-warn">
                {' '}
                {query.length}/{MAX_QUERY_LENGTH}
              </span>
            )}
          </p>
        </div>
      </div>

      <aside
        className={`details-drawer${detailsOpen ? ' details-drawer--open' : ''}`}
        aria-label="Sources and execution trace"
        aria-hidden={!detailsOpen}
      >
        <div className="drawer-header">
          <h2>Details</h2>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setDetailsOpen(false)}
            aria-label="Close details"
          >
            ×
          </button>
        </div>
        <ExecutionTrace steps={steps} traceUrl={traceUrl} />
        <EvidencePanel evidence={evidence} loading={loading} highlightedKey={highlightedCitation} />
      </aside>
      {detailsOpen && (
        <button
          type="button"
          className="drawer-scrim"
          aria-label="Close details"
          onClick={() => setDetailsOpen(false)}
        />
      )}

      <IntegrationsModal
        open={integrationsOpen}
        integrations={integrations}
        initialProvider={focusedProvider}
        onRefresh={() => refreshIntegrations()}
        onUnauthorized={handleUnauthorized}
        onConnectOAuth={(url) => {
          if (onNavigate) onNavigate(url);
          else window.location.assign(url);
        }}
        onClose={() => {
          setIntegrationsOpen(false);
          setFocusedProvider(null);
        }}
      />

      <SettingsDialog
        open={settingsOpen}
        user={user}
        settings={settings}
        conversationCount={conversations.length}
        connectedIntegrationsCount={connectedCount}
        signingOut={signingOut}
        onChange={setSettings}
        onSignOut={() => void handleSignOut()}
        onOpenIntegrations={() => openIntegrationsHub(null)}
        onExportAll={() => void exportAllChats()}
        onClearAll={() => void clearAllConversations()}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
