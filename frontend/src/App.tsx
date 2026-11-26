import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react';
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
  type ChatMessage,
  type SavedConversation,
} from './chatStorage';
import EvidencePanel, { recordCitationKey } from './EvidencePanel';
import ExecutionTrace from './ExecutionTrace';
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

const SUGGESTIONS = [
  { label: 'Pricing', text: 'How much does the Enterprise plan cost?' },
  { label: 'Compare', text: 'Compare Starter and Professional pricing' },
  { label: 'Add-ons', text: 'What add-ons are available?' },
  { label: 'Catalog', text: 'List all products in the database' },
];

const DATA_SOURCES = [
  { name: 'SQLite · MCP', detail: 'Products & pricing', badge: 'Read-only' },
  { name: 'GitHub · MCP', detail: 'Issues & pull requests', badge: 'Read-only' },
  { name: 'PostgreSQL', detail: 'Conversation memory', badge: 'Per thread' },
];

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
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string };

type AppProps = {
  onNavigate?: (url: string) => void;
};

export default function App({ onNavigate }: AppProps = {}) {
  const [authState, setAuthState] = useState<AuthGateState>({ status: 'checking' });
  const [signingOut, setSigningOut] = useState(false);
  const [query, setQuery] = useState('');
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    resolveTheme(loadSettings().theme),
  );
  const [health, setHealth] = useState<HealthState>('checking');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [highlightedCitation, setHighlightedCitation] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleUnauthorized = useCallback(() => {
    setAuthState({ status: 'unauthenticated' });
    redirectToLanding(onNavigate);
  }, [onNavigate]);

  const checkSession = useCallback(
    async (signal?: AbortSignal) => {
      setAuthState({ status: 'checking' });
      try {
        const result = await fetchCurrentUser(signal);
        if (signal?.aborted) return;
        if (result.status === 'unauthenticated') {
          setAuthState({ status: 'unauthenticated' });
          redirectToLanding(onNavigate);
          return;
        }
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
    steps,
    traceUrl,
    error,
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
      if (!trimmed || loading) return;
      const completed = await submit(trimmed);
      if (completed) {
        setQuery('');
        if (settings.showDetailsByDefault) setDetailsOpen(true);
      }
    },
    [loading, submit, settings.showDetailsByDefault],
  );

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
          <h1>Sign in required</h1>
          <p>Redirecting you to the landing page to sign in with Google…</p>
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
        placeholder="Ask about your products, issues, or earlier conversation…"
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
          disabled={!query.trim()}
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
        collapsed={settings.sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(true)}
        onHome={reset}
        onNewChat={() => {
          reset();
          composerRef.current?.focus();
        }}
        onSelect={(threadId) => void selectConversation(threadId)}
        onDelete={(threadId) => void removeConversation(threadId)}
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
          {view === 'home' ? (
            <div className="home">
              <h2 className="welcome">
                <span className="welcome-name">Welcome, {firstName}!</span>
                <span className="welcome-sub">How can I help you today?</span>
              </h2>

              <section className="card-grid" aria-label="Suggested questions">
                {SUGGESTIONS.map((s) => (
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
                <h3 className="section-label">Connected data sources</h3>
                <ul className="source-grid">
                  {DATA_SOURCES.map((source) => (
                    <li key={source.name} className="source-card">
                      <span className={`health-dot health-dot--${health}`} aria-hidden="true" />
                      <div>
                        <strong>{source.name}</strong>
                        <span>{source.detail}</span>
                      </div>
                      <span className="chip-tag">{source.badge}</span>
                    </li>
                  ))}
                </ul>
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
                                key={key}
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
                        ? 'Planning which source to use…'
                        : 'Reviewing data and writing the answer…'
                      : 'Working on your answer…'}
                  </span>
                </div>
              )}

              {error && (
                <div className="error-box" role="alert">
                  <strong>We couldn’t get an answer</strong>
                  <span>{error}</span>
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

      <SettingsDialog
        open={settingsOpen}
        user={user}
        settings={settings}
        conversationCount={conversations.length}
        signingOut={signingOut}
        onChange={setSettings}
        onSignOut={() => void handleSignOut()}
        onExportAll={() => void exportAllChats()}
        onClearAll={() => void clearAllConversations()}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
