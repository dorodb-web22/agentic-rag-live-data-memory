import type { EvidenceRecord } from './chatStorage';

type Props = {
  evidence: EvidenceRecord[] | null;
  loading?: boolean;
  highlightedKey?: string | null;
};

export function recordCitationKey(record: EvidenceRecord, index: number): string {
  if (record.title !== undefined || record.number !== undefined) {
    return `GitHub-${record.number ?? record.id ?? index + 1}`;
  }
  return `Product-${record.id ?? `row${index + 1}`}`;
}

function SourceBadge({ isGithub }: { isGithub: boolean }) {
  return (
    <span className={`source-badge ${isGithub ? 'source-badge--github' : 'source-badge--sqlite'}`}>
      <span className="source-badge-dot" aria-hidden="true" />
      {isGithub ? 'GitHub MCP · issues / PRs' : 'SQLite MCP · products'}
    </span>
  );
}

export default function EvidencePanel({ evidence, loading = false, highlightedKey = null }: Props) {
  const isGithubPayload =
    Boolean(evidence && evidence.length > 0) &&
    (evidence![0].title !== undefined || evidence![0].number !== undefined);

  return (
    <section className="inspector-card evidence-panel" aria-label="Data Sources and Evidence">
      <div className="inspector-header">
        <h2>Data Sources &amp; Evidence</h2>
        {evidence && evidence.length > 0 && (
          <span className="count-pill" data-testid="evidence-count">
            {evidence.length} {evidence.length === 1 ? 'record' : 'records'}
          </span>
        )}
      </div>

      {!evidence && !loading && (
        <p className="inspector-empty">
          Live MCP records from <strong>SQLite</strong> (products &amp; pricing) and{' '}
          <strong>GitHub</strong> (issues &amp; PRs) appear here with every grounded answer.
        </p>
      )}

      {!evidence && loading && (
        <p className="inspector-empty">Querying connected MCP data sources…</p>
      )}

      {evidence && evidence.length === 0 && (
        <p className="inspector-empty">0 matching records returned from connected data sources.</p>
      )}

      {evidence && evidence.length > 0 && (
        <div className="evidence-results">
          <SourceBadge isGithub={isGithubPayload} />
          <div className="evidence-list">
            {evidence.map((rec, idx) => {
              const citeKey = recordCitationKey(rec, idx);
              const isHighlighted = highlightedKey === citeKey;
              const isGithub = rec.title !== undefined || rec.number !== undefined;

              if (isGithub) {
                const isClosed = rec.state === 'closed';
                return (
                  <article
                    key={citeKey}
                    id={`evidence-${citeKey}`}
                    data-testid="evidence-card"
                    className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                  >
                    <div className="evidence-card-top">
                      <span className="evidence-cite-tag">{citeKey}</span>
                      <span className={`state-tag ${isClosed ? 'state-tag--closed' : 'state-tag--open'}`}>
                        {rec.state || 'open'}
                      </span>
                    </div>
                    <div className="evidence-card-name">{rec.title ?? rec.name}</div>
                    {rec.user?.login && (
                      <div className="evidence-card-meta">by @{rec.user.login}</div>
                    )}
                    {typeof rec.description === 'string' && rec.description && (
                      <p className="evidence-card-desc">{rec.description}</p>
                    )}
                  </article>
                );
              }

              return (
                <article
                  key={citeKey}
                  id={`evidence-${citeKey}`}
                  data-testid="evidence-card"
                  className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                >
                  <div className="evidence-card-top">
                    <span className="evidence-cite-tag">{citeKey}</span>
                    {typeof rec.price === 'number' && (
                      <span className="evidence-card-price">${rec.price.toLocaleString()}</span>
                    )}
                  </div>
                  <div className="evidence-card-name">{rec.name}</div>
                  {rec.category && <div className="evidence-card-category">{rec.category}</div>}
                  {typeof rec.description === 'string' && rec.description && (
                    <p className="evidence-card-desc">{rec.description}</p>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
