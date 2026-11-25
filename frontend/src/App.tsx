import { FormEvent, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ExecutionTrace from './ExecutionTrace';
import { useQueryStream } from './useQueryStream';

export default function App() {
  const [query, setQuery] = useState('');
  const { steps, answer, traceUrl, error, loading, submit } = useQueryStream();
  const answerRef = useRef<HTMLDivElement>(null);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || loading) return;
    await submit(trimmedQuery);
    requestAnimationFrame(() => answerRef.current?.focus());
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
            disabled={loading}
            required
          />
          <div className="form-footer">
            <span className="hint">Your question is sent to the local assistant.</span>
            <button type="submit" disabled={loading || !query.trim()}>
              {loading ? <><span className="spinner" aria-hidden="true" /> Asking…</> : 'Ask question'}
            </button>
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
                      a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                      table: ({ node: _node, ...props }) => (
                        <div className="table-scroll"><table {...props} /></div>
                      ),
                    }}
                  >
                    {answer}
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
