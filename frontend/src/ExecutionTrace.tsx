import { NODE_LABELS, type TraceStep } from './streaming';

type Props = { steps: TraceStep[]; traceUrl?: string };

function formatDuration(ms?: number): string {
  if (ms === undefined) return '';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export default function ExecutionTrace({ steps, traceUrl }: Props) {
  return (
    <aside className="trace-sidebar" aria-label="Execution trace">
      <h2>Execution Trace</h2>
      {steps.length === 0 ? (
        <p className="trace-empty">Agent steps will appear here when you ask a question.</p>
      ) : (
        <ol className="trace-list" aria-live="polite">
          {steps.map((step) => (
            <li key={step.id} className={`trace-step ${step.status}`} data-testid="trace-step">
              <span className="trace-icon" aria-hidden="true">
                {step.status === 'running' ? <span className="spinner trace-spinner" /> : '✓'}
              </span>
              <span className="trace-text">
                <strong>{NODE_LABELS[step.node].label}</strong>
                <small>{NODE_LABELS[step.node].detail}</small>
              </span>
              <span className="trace-duration">
                {step.status === 'running' ? 'running…' : formatDuration(step.durationMs)}
              </span>
            </li>
          ))}
        </ol>
      )}
      {traceUrl && (
        <a className="trace-link" href={traceUrl} target="_blank" rel="noopener noreferrer">
          View in LangSmith →
        </a>
      )}
    </aside>
  );
}
