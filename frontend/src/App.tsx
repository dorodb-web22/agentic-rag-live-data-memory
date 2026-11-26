import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { conversationToMarkdown, type SavedConversation } from './chatStorage';
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
import { IS_MOCK_STREAM, useQueryStream } from './useQueryStream';

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

export default function App() {
  const [query, setQuery] = useState('');
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    resolveTheme(loadSettings().theme),
  );
  const [health, setHealth] = useState<HealthState>(IS_MOCK_STREAM ? 'mock' : 'checking');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [highlightedCitation, setHighlightedCitation] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const {
    activeUser,
    switchUser,
    conversations,
    activeConversationId,
    selectConversation,
    removeConversation,
    clearAllConversations,
    messages,
    evidence,
    steps,
    traceUrl,
    error,
    loading,
    hasThread,
    activeThreadId,
    submit,
    stop,
    reset,
  } = useQueryStream();

  const chatEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const displayName = settings.displayName.trim() || activeUser;
  const view: 'home' | 'chat' = messages.length > 0 || loading ? 'chat' : 'home';

  // ---- theme ----
  useEffect(() => {
    setResolvedTheme(applyTheme(settings.theme));
    saveSettings(settings);
    if (settings.theme !== 'system' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setResolvedTheme(applyTheme('system'));
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [settings]);

  // ---- backend health ----
  useEffect(() => {
    if (IS_MOCK_STREAM) {
      setHealth('mock');
      return;
    }
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/health');
        if (!cancelled) setHealth(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setHealth('offline');
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

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

  function openCitation(citeKey: string) {
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
    const conv: SavedConversation | null =
      conversations.find((c) => c.id === activeConversationId) ??
      (messages.length > 0
        ? {
            id: 'unsaved',
            threadId: activeThreadId,
            title: messages[0].content.slice(0, 48),
            messages,
            evidence,
            steps,
            traceUrl,
            updatedAt: new Date().toISOString(),
          }
        : null);
    if (!conv) return;
    downloadFile(
      `agentic-rag-chat-${(conv.threadId ?? conv.id).slice(0, 8)}.md`,
      conversationToMarkdown(conv),
      'text/markdown;charset=utf-8',
    );
  }

  function exportAllChats() {
    downloadFile(
      `agentic-rag-all-chats-${activeUser}.json`,
      JSON.stringify(conversations, null, 2),
      'application/json;charset=utf-8',
    );
  }

  function toggleQuickTheme() {
    setSettings((prev) => ({ ...prev, theme: resolvedTheme === 'dark' ? 'light' : 'dark' }));
  }

  const lastAssistantId = [...messages].reverse().find((m) => m.role === 'assistant')?.id;
  const activeTitle =
    conversations.find((c) => c.id === activeConversationId)?.title ?? 'New chat';
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
        displayName={displayName}
        conversations={conversations}
        activeConversationId={activeConversationId}
        activeView={view}
        health={health}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(true)}
        onHome={reset}
        onNewChat={() => {
          reset();
          composerRef.current?.focus();
        }}
        onSelect={selectConversation}
        onDelete={removeConversation}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            {sidebarCollapsed && (
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
                <span className="welcome-name">Welcome, {displayName}!</span>
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
              {messages.map((msg) => (
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
                                  onClick={() => openCitation(href.slice(6))}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.preventDefault();
                                      openCitation(href.slice(6));
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
                        {msg.id === lastAssistantId && evidence && evidence.length > 0 && (
                          <span className="grounded" data-testid="grounded-badge">
                            ✓ Grounded in {evidence.length} source{evidence.length === 1 ? '' : 's'}
                          </span>
                        )}
                        {msg.id === lastAssistantId &&
                          evidence?.map((rec, idx) => {
                            const key = recordCitationKey(rec, idx);
                            return (
                              <button
                                key={key}
                                type="button"
                                className="source-chip"
                                onClick={() => openCitation(key)}
                              >
                                {key}
                              </button>
                            );
                          })}
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
              ))}

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
        settings={settings}
        activeUser={activeUser}
        conversationCount={conversations.length}
        onChange={setSettings}
        onSwitchUser={switchUser}
        onExportAll={exportAllChats}
        onClearAll={clearAllConversations}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
