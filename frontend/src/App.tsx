import { FormEvent, useRef, useState } from 'react';

type QueryResponse = { answer: string };

export default function App() {
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const answerRef = useRef<HTMLParagraphElement>(null);

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || loading) return;

    setLoading(true);
    setError('');
    setAnswer('');
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
      setAnswer(data.answer);
      requestAnimationFrame(() => answerRef.current?.focus());
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
                <p ref={answerRef} tabIndex={-1}>{answer}</p>
              )}
            </div>
          </section>
        )}
      </section>
      <footer>Powered by your local agent</footer>
    </main>
  );
}
