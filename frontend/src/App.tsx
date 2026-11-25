import { FormEvent, KeyboardEvent, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ExecutionTrace from './ExecutionTrace';
import { linkifyCitations, MAX_QUERY_LENGTH } from './streaming';
import { useQueryStream } from './useQueryStream';

const EXAMPLES = [
  'How much does the Enterprise plan cost?',
  'Compare Starter and Professional pricing',
  'What add-ons are available?',
];

export default function App() {
  const [query, setQuery] = useState('');
  const { steps, answer, traceUrl, error, loading, hasThread, submit, stop, reset } = useQueryStream();
  const answerRef = useRef<HTMLDivElement>(null);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || loading) return;
    await submit(trimmedQuery);
    setQuery('');
    requestAnimationFrame(() => answerRef.current?.focus());
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="app-layout">
    <main className="page-shell">
      <section className="query-card" aria-labelledby="page-title">
        <div className="eyebrow"><span className="status-dot" /> BASIC AGENT QUERY</div>
        <h1 id="page-title">Agentic RAG Assistant</h1>
        <p className="intro">Ask a question and get a response from your assistant.</p>

        <form onSubmit={submitQuery}>
          <label htmlFor="query">Your question</label>
          <textarea
            id="query"
            name="query"
            rows={4}
            placeholder="What would you like to know?"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_QUERY_LENGTH}
            disabled={loading}
            required
          />
          {!answer && !loading && !query && (
            <div className="examples" aria-label="Example questions">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="chip" onClick={() => setQuery(example)}>
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
                <button type="button" className="secondary" onClick={reset}>New conversation</button>
              )}
              {loading ? (
                <button type="button" className="secondary" onClick={stop}>Stop</button>
              ) : null}
              <button type="submit" disabled={loading || !query.trim()}>
                {loading ? <><span className="spinner" aria-hidden="true" /> Asking…</> : 'Ask question'}
              </button>
            </span>
          </div>
        </form>

        {loading && <p className="loading-message" role="status">Working on your answer…</p>}
        {error && <div className="error-box" role="alert"><strong>We couldn’t get an answer</strong><span>{error}</span></div>}
        {(answer || loading) && (
          <section className="answer-section" aria-labelledby="answer-title" aria-live="polite">
            <h2 id="answer-title">Answer</h2>
            <div className={`answer-box${loading ? ' answer-pending' : ''}`}>
              {loading ? <span className="answer-placeholder">Your response will appear here.</span> : (
                <div ref={answerRef} className="markdown" tabIndex={-1}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node: _node, href, children, ...props }) =>
                        href?.startsWith('#cite-') ? (
                          <sup className="cite" title={`Source: ${href.slice(6)}`}>{children}</sup>
                        ) : (
                          <a {...props} href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                        ),
                      table: ({ node: _node, ...props }) => (
                        <div className="table-scroll"><table {...props} /></div>
                      ),
                    }}
                  >
                    {linkifyCitations(answer)}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </section>
        )}
      </section>
      <footer>Powered by your local agent</footer>
    </main>
    <ExecutionTrace steps={steps} traceUrl={traceUrl} />
    </div>
  );
}
