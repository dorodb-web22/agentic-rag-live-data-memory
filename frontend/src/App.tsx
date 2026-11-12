import { FormEvent, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type EvidenceRecord = {
  id?: number;
  name?: string;
  description?: string;
  price?: number;
  category?: string;
  // GitHub MCP fields
  number?: number;
  title?: string;
  state?: string;
  html_url?: string;
  user?: { login?: string };
  [key: string]: unknown;
};

type QueryResponse = {
  answer: string;
  evidence: EvidenceRecord[] | null;
};

type ChatMessage = { role: 'user' | 'assistant'; content: string };

function StatusPill({ label, status }: { label: string; status: 'online' | 'offline' | 'checking' }) {
  return (
    <div className={`status-pill status-pill--${status}`}>
      <span className="status-pill-dot" aria-hidden="true" />
      <span className="status-pill-label">{label}</span>
      <span className="status-pill-value">
        {status === 'online' ? 'Online' : status === 'offline' ? 'Offline' : '…'}
      </span>
    </div>
  );
}

function SourceBadge({ source, target }: { source: string; target: string }) {
  const isGithub = source.includes('GitHub');
  return (
    <span className={`source-badge ${isGithub ? 'source-badge--github' : 'source-badge--sqlite'}`}>
      <span className="source-badge-icon" aria-hidden="true">{isGithub ? '🐙' : '🗄'}</span>
      {source}: <strong>{target}</strong>
    </span>
  );
}

function ChatBubble({ role, content }: { role: 'user' | 'assistant'; content: string }) {
  return (
    <div className={`chat-bubble chat-bubble--${role}`}>
      <span className="bubble-role-label">{role === 'user' ? 'You' : 'Assistant'}</span>
      {role === 'assistant' ? (
        <div className="markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
              table: ({ node: _node, ...props }) => (
                <div className="table-scroll"><table {...props} /></div>
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="bubble-user-text">{content}</p>
      )}
    </div>
  );
}

function EvidenceCard({ record }: { record: EvidenceRecord }) {
  const isGithub = record.title !== undefined || record.number !== undefined;

  if (isGithub) {
    const isClosed = record.state === 'closed';
    return (
      <div className="evidence-card evidence-card--github">
        <div className="evidence-card-header">
          <span className="evidence-card-id">#{record.number ?? record.id}</span>
          <span className="evidence-card-name">{record.title ?? record.name}</span>
        </div>
        <div className="evidence-card-meta">
          <span className={`state-tag ${isClosed ? 'state-tag--closed' : 'state-tag--open'}`}>
            {record.state || 'issue'}
          </span>
          {record.user?.login && (
            <span className="evidence-card-author">by @{record.user.login}</span>
          )}
        </div>
        {record.description && (
          <p className="evidence-card-desc">{record.description}</p>
        )}
      </div>
    );
  }

  // Default: SQLite Product record
  return (
    <div className="evidence-card evidence-card--sqlite">
      <div className="evidence-card-header">
        <span className="evidence-card-id">#{record.id}</span>
        <span className="evidence-card-name">{record.name}</span>
      </div>
      {record.price !== undefined && (
        <div className="evidence-card-price">${record.price.toLocaleString()}</div>
      )}
      {record.category && (
        <div className="evidence-card-category">{record.category}</div>
      )}
      {record.description && (
        <p className="evidence-card-desc">{record.description}</p>
      )}
    </div>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [evidence, setEvidence] = useState<EvidenceRecord[] | null>(null);
  const [apiStatus, setApiStatus] = useState<'online' | 'offline' | 'checking'>('checking');

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch('/health');
        setApiStatus(res.ok ? 'online' : 'offline');
      } catch {
        setApiStatus('offline');
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || loading) return;

    setLoading(true);
    setError('');
    setEvidence(null);
    try {
      const response = await fetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmedQuery }),
      });
      if (!response.ok) {
        throw new Error(`The request failed (${response.status}). Please try again.`);
      }
      const data = (await response.json()) as QueryResponse;
      if (typeof data.answer !== 'string') {
        throw new Error('The server response did not include an answer. Please try again.');
      }
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: trimmedQuery },
        { role: 'assistant', content: data.answer },
      ]);
      setEvidence(data.evidence ?? null);
      setQuery('');
    } catch (cause) {
      setError(
        cause instanceof TypeError
          ? 'Could not connect to the backend. Check that the local API is running and try again.'
          : cause instanceof Error
            ? cause.message
            : 'Something went wrong. Please try again.',
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="dashboard-shell">
      {/* Top navigation bar */}
      <header className="dashboard-header">
        <div className="header-brand">
          <span className="brand-icon" aria-hidden="true">⬡</span>
          <span className="brand-name">Agentic RAG</span>
          <span className="brand-tag">OJT Project</span>
        </div>
        <div className="header-status-bar">
          <StatusPill label="API" status={apiStatus} />
          <StatusPill label="SQLite MCP" status={apiStatus} />
          <StatusPill label="GitHub MCP" status={apiStatus} />
        </div>
      </header>

      <div className="dashboard-body">
        {/* LEFT PANE — Chat stream */}
        <main className="chat-pane" aria-label="Chat">
          <div className="chat-history" aria-live="polite">
            {messages.map((msg, i) => (
              <ChatBubble key={i} role={msg.role} content={msg.content} />
            ))}
            {loading && (
              <div className="chat-bubble assistant loading-bubble">
                <span className="spinner" aria-hidden="true" />
                <span className="loading-text">Thinking…</span>
              </div>
            )}
            {error && (
              <div className="chat-bubble error-bubble" role="alert">
                <strong>Error:</strong> {error}
              </div>
            )}
          </div>

          {/* Input bar fixed to bottom of chat pane */}
          <form className="chat-input-form" onSubmit={submitQuery}>
            <textarea
              id="query"
              name="query"
              rows={2}
              placeholder="Ask anything about your data sources…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
              disabled={loading}
              required
            />
            <button type="submit" disabled={loading || !query.trim()}>
              {loading ? <><span className="spinner" aria-hidden="true" /> Sending…</> : 'Send'}
            </button>
          </form>
        </main>

        {/* RIGHT PANE — Evidence sidebar */}
        <aside className="evidence-pane" aria-label="Data Sources and Evidence">
          <div className="evidence-header">
            <h2 className="evidence-title">Data Sources & Evidence</h2>
          </div>

          {!evidence && !loading && (
            <div className="evidence-empty">
              <p>No live data retrieved yet. Ask a question about products/pricing (SQLite MCP) or issues/PRs (GitHub MCP) to see live evidence records here.</p>
            </div>
          )}

          {evidence && evidence.length === 0 && (
            <div className="evidence-empty">
              <p className="evidence-empty-text">0 records matched in data sources.</p>
            </div>
          )}

          {evidence && evidence.length > 0 && (
            <div className="evidence-results">
              {/* Dynamic Source Badge based on retrieved payload */}
              {evidence[0].title !== undefined || evidence[0].number !== undefined ? (
                <SourceBadge source="GitHub MCP" target="issues / PRs" />
              ) : (
                <SourceBadge source="SQLite MCP" target="products" />
              )}
              <p className="evidence-count">{evidence.length} record{evidence.length !== 1 ? 's' : ''} retrieved</p>
              {evidence.map((rec, idx) => (
                <EvidenceCard key={rec.id ?? rec.number ?? idx} record={rec} />
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
