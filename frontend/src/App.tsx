import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { conversationToMarkdown } from './chatStorage';
import EvidencePanel from './EvidencePanel';
import ExecutionTrace from './ExecutionTrace';
import { linkifyCitations, MAX_QUERY_LENGTH } from './streaming';
import { IS_MOCK_STREAM, useQueryStream } from './useQueryStream';

const EXAMPLES = [
  'How much does the Enterprise plan cost?',
  'Compare Starter and Professional pricing',
  'What add-ons are available?',
];

type HealthState = 'online' | 'offline' | 'mock' | 'checking';

function StatusSticker({ label, status }: { label: string; status: HealthState }) {
  const statusText =
    status === 'mock'
      ? 'Mock'
      : status === 'online'
        ? 'Live'
        : status === 'offline'
          ? 'Offline'
          : '…';
  return (
    <span className={`nav-status nav-status--${status}`}>
      <span className="nav-status-dot" aria-hidden="true" />
      <span>{label}</span>
      <strong>{statusText}</strong>
    </span>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const [apiHealth, setApiHealth] = useState<HealthState>(IS_MOCK_STREAM ? 'mock' : 'checking');
  const [highlightedCitation, setHighlightedCitation] = useState<string | null>(null);
  const [editingUser, setEditingUser] = useState(false);
  const [userDraft, setUserDraft] = useState('');

  const {
    activeUser,
    switchUser,
    conversations,
    activeConversationId,
    selectConversation,
    removeConversation,
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

  useEffect(() => {
    if (IS_MOCK_STREAM) {
      setApiHealth('mock');
      return;
    }
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/health');
        if (!cancelled) setApiHealth(res.ok ? 'online' : 'offline');
      } catch {
        if (!cancelled) setApiHealth('offline');
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
    if (messages.length > 0 && typeof chatEndRef.current?.scrollIntoView === 'function') {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages.length, loading]);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || loading) return;
    const completed = await submit(trimmedQuery);
    if (completed) {
      setQuery('');
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function handleCitationClick(citeKey: string) {
    setHighlightedCitation(citeKey);
    const el = document.getElementById(`evidence-${citeKey}`);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function handleExportActiveChat() {
    const activeConv =
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
    if (!activeConv) return;
    const md = conversationToMarkdown(activeConv);
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `agentic-rag-chat-${(activeConv.threadId ?? activeConv.id).slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleUserSubmit(event: FormEvent) {
    event.preventDefault();
    if (userDraft.trim()) {
      switchUser(userDraft);
    }
    setEditingUser(false);
    setUserDraft('');
  }

  const shortThreadLabel = activeThreadId ? activeThreadId.slice(0, 8).toUpperCase() : 'NEW';

  return (
    <div className="app-root">
      <div className="top-accent-bar" aria-hidden="true" />

      {/* Floating Glass Navbar matching Netlify landing page */}
      <header className="top-nav-wrap">
        <nav className="top-nav" aria-label="Workspace navigation">
          <div className="brand-pill">
            <span className="brand-orb" aria-hidden="true" />
            <span className="brand-wordmark">agentic.rag</span>
          </div>

          <div className="nav-sources" aria-label="Connected data sources">
            <StatusSticker label="API" status={apiHealth} />
            <StatusSticker label="SQLite MCP" status={apiHealth} />
            <StatusSticker label="GitHub MCP" status={apiHealth} />
          </div>

          <div className="nav-actions">
            {messages.length > 0 && (
              <button
                type="button"
                className="pill-btn pill-btn--ghost pill-btn--sm"
                onClick={handleExportActiveChat}
                title="Download conversation & evidence as Markdown"
              >
                Save .md ↓
              </button>
            )}

            {editingUser ? (
              <form className="user-switch-form" onSubmit={handleUserSubmit}>
                <input
                  type="text"
                  className="user-switch-input"
                  value={userDraft}
                  onChange={(e) => setUserDraft(e.target.value)}
                  placeholder="Enter username…"
                  aria-label="Username"
                  autoFocus
                />
                <button type="submit" className="pill-btn pill-btn--dark pill-btn--sm">
                  Sign in
                </button>
              </form>
            ) : (
              <button
                type="button"
                className="user-pill"
                onClick={() => {
                  setUserDraft(activeUser);
                  setEditingUser(true);
                }}
                title="Switch signed-in profile to load that user's saved chat history"
              >
                <span className="user-avatar" aria-hidden="true">
                  {activeUser.slice(0, 1).toUpperCase()}
                </span>
                <span>@{activeUser}</span>
              </button>
            )}
          </div>
        </nav>
      </header>

      {/* Three-column workspace: Chat History | Main Assistant | Trace + Data Sources */}
      <div className="app-layout">
        {/* LEFT RAIL — Persistent Chat History */}
        <aside className="history-sidebar" aria-label="Saved chat history">
          <div className="history-top">
            <div className="history-heading">
              <span className="mono-label">Saved Chats</span>
              <span className="count-pill">{conversations.length}</span>
            </div>
            <button
              type="button"
              className="pill-btn pill-btn--peach pill-btn--full"
              onClick={reset}
              disabled={loading && messages.length === 0}
            >
              + New conversation
            </button>
          </div>

          {conversations.length === 0 ? (
            <p className="history-empty">
              Chats for <strong>@{activeUser}</strong> auto-save here so you can pick right back up
              next time you open the app.
            </p>
          ) : (
            <ul className="history-list" aria-label="Conversation history">
              {conversations.map((conv) => {
                const isSelected = conv.id === activeConversationId;
                return (
                  <li
                    key={conv.id}
                    className={`history-item${isSelected ? ' history-item--active' : ''}`}
                    data-testid="history-item"
                  >
                    <button
                      type="button"
                      className="history-select-btn"
                      onClick={() => selectConversation(conv.id)}
                    >
                      <span className="history-item-title">{conv.title}</span>
                      <span className="history-item-meta">
                        {Math.ceil(conv.messages.length / 2)}{' '}
                        {Math.ceil(conv.messages.length / 2) === 1 ? 'turn' : 'turns'}
                        {conv.threadId ? ` · #${conv.threadId.slice(0, 6)}` : ''}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="history-delete-btn"
                      aria-label={`Delete ${conv.title}`}
                      title="Delete saved chat"
                      onClick={() => removeConversation(conv.id)}
                    >
                      ×
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        {/* CENTER — Grounded Assistant Card */}
        <main className="page-shell">
          <section className="query-card" aria-labelledby="page-title">
            <div className="window-bar">
              <div className="window-dots" aria-hidden="true">
                <span className="win-dot win-dot--peach" />
                <span className="win-dot win-dot--blue" />
              </div>
              <div className="eyebrow">
                <span className="status-dot" />
                <span>PROJECT ASSISTANT · THREAD {shortThreadLabel}</span>
              </div>
            </div>

            {messages.length === 0 ? (
              <div className="hero-greeting">
                <h1 id="page-title">
                  Ask once. Get the <em className="serif-pill">whole</em> answer.
                </h1>
                <p className="intro">
                  Your SQLite catalog, GitHub issues, and persistent memory — searched by an agent
                  that <strong>plans, cites, and remembers</strong>.
                </p>
              </div>
            ) : (
              <div className="compact-header">
                <h1 id="page-title" className="compact-title">
                  Agentic RAG <em className="serif-inline">assistant</em>
                </h1>
              </div>
            )}

            {/* Multi-turn conversation log */}
            {messages.length > 0 && (
              <section
                className="answer-section chat-log"
                aria-labelledby="answer-title"
                aria-live="polite"
              >
                <h2 id="answer-title" className="sr-only">
                  Answer
                </h2>
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`chat-bubble chat-bubble--${msg.role}`}
                    data-testid={`chat-bubble-${msg.role}`}
                  >
                    <span className="bubble-role">
                      {msg.role === 'user' ? `@${activeUser}` : 'agentic.rag'}
                    </span>
                    {msg.role === 'user' ? (
                      <p className="user-bubble-text">{msg.content}</p>
                    ) : (
                      <div className="markdown">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            a: ({ node: _node, href, children, ...props }) =>
                              href?.startsWith('#cite-') ? (
                                <sup
                                  className="cite"
                                  title={`Source: ${href.slice(6)} — click to highlight evidence`}
                                  role="button"
                                  tabIndex={0}
                                  onClick={() => handleCitationClick(href.slice(6))}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.preventDefault();
                                      handleCitationClick(href.slice(6));
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
                    )}
                  </div>
                ))}

                {hasThread && !loading && (
                  <div className="memory-checkpoint" data-testid="memory-badge">
                    Saved to memory · thread #{shortThreadLabel}
                  </div>
                )}
                <div ref={chatEndRef} />
              </section>
            )}

            {loading && (
              <p className="loading-message" role="status">
                <span className="spinner spinner--ink" aria-hidden="true" /> Working on your answer…
              </p>
            )}

            {error && (
              <div className="error-box" role="alert">
                <strong>We couldn’t get an answer</strong>
                <span>{error}</span>
              </div>
            )}

            <form className="composer-form" onSubmit={submitQuery}>
              <label htmlFor="query">Your question</label>
              <textarea
                id="query"
                name="query"
                rows={3}
                placeholder="What would you like to know?"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onKeyDown}
                maxLength={MAX_QUERY_LENGTH}
                disabled={loading}
                required
              />

              {messages.length === 0 && !loading && !query && (
                <div className="examples" aria-label="Example questions">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      className="chip"
                      onClick={() => setQuery(example)}
                    >
                      {example}
                    </button>
                  ))}
                </div>
              )}

              <div className="form-footer">
                <span className="hint">
                  {hasThread ? 'Conversation memory is on · ' : ''}
                  {query.length}/{MAX_QUERY_LENGTH} · ⌘/Ctrl+Enter to send
                </span>
                <span className="actions">
                  {hasThread && !loading && (
                    <button type="button" className="pill-btn pill-btn--ghost" onClick={reset}>
                      New conversation
                    </button>
                  )}
                  {loading ? (
                    <button type="button" className="pill-btn pill-btn--ghost" onClick={stop}>
                      Stop
                    </button>
                  ) : null}
                  <button
                    type="submit"
                    className="pill-btn pill-btn--dark"
                    disabled={loading || !query.trim()}
                  >
                    {loading ? (
                      <>
                        <span className="spinner" aria-hidden="true" /> Asking…
                      </>
                    ) : (
                      'Ask question'
                    )}
                  </button>
                </span>
              </div>
            </form>
          </section>

          <footer className="workspace-footer">
            <span>AGENTIC RAG OVER LIVE DATA &amp; MEMORY</span>
            <span>SQLITE · GITHUB · POSTGRESQL · LANGSMITH</span>
          </footer>
        </main>

        {/* RIGHT RAIL — Execution Trace + Data Sources & Evidence */}
        <div className="inspector-rail">
          <ExecutionTrace steps={steps} traceUrl={traceUrl} />
          <EvidencePanel
            evidence={evidence}
            loading={loading}
            highlightedKey={highlightedCitation}
          />
        </div>
      </div>
    </div>
  );
}
