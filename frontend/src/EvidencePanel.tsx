import type { EvidenceRecord } from './chatStorage';

type Props = {
  evidence: EvidenceRecord[] | null;
  loading?: boolean;
  highlightedKey?: string | null;
};

export type EvidenceSourceKind = 'github' | 'gmail' | 'notion' | 'sqlite';

export function detectEvidenceSource(record: EvidenceRecord): EvidenceSourceKind {
  const src = typeof record.source === 'string' ? record.source.toLowerCase() : '';
  if (src === 'github') return 'github';
  if (src === 'gmail') return 'gmail';
  if (src === 'notion') return 'notion';
  if (src === 'sqlite') return 'sqlite';

  if (record.message_id !== undefined || record.sender !== undefined || record.subject !== undefined) {
    return 'gmail';
  }
  if (record.page_id !== undefined || record.last_edited !== undefined) {
    return 'notion';
  }
  if (record.number !== undefined || (record.title !== undefined && record.state !== undefined)) {
    return 'github';
  }
  return 'sqlite';
}

function cleanCitationBracket(raw: string): string {
  return raw.trim().replace(/^\[/, '').replace(/\]$/, '');
}

export function recordCitationKey(record: EvidenceRecord, index: number): string {
  if (typeof record.citation_key === 'string' && record.citation_key.trim()) {
    return cleanCitationBracket(record.citation_key);
  }
  const kind = detectEvidenceSource(record);
  if (kind === 'github') {
    return `GitHub-${record.number ?? record.id ?? index + 1}`;
  }
  if (kind === 'gmail') {
    const shortId = String(record.message_id ?? record.id ?? index + 1).slice(0, 12);
    return `Gmail-${shortId}`;
  }
  if (kind === 'notion') {
    const shortId = String(record.page_id ?? record.id ?? index + 1)
      .replace(/-/g, '')
      .slice(0, 12);
    return `Notion-${shortId}`;
  }
  if (typeof record.table === 'string' && record.table.trim()) {
    const rowObj =
      record.row && typeof record.row === 'object'
        ? (record.row as Record<string, unknown>)
        : record;
    const rid = rowObj.rowid ?? rowObj.id ?? index + 1;
    return `SQL-${record.table.trim()}-${rid}`;
  }
  return `Product-${record.id ?? `row${index + 1}`}`;
}

const SOURCE_BADGE_META: Record<EvidenceSourceKind, { label: string; className: string }> = {
  github: { label: 'GitHub · issues / PRs', className: 'source-badge--github' },
  gmail: { label: 'Gmail · threads', className: 'source-badge--gmail' },
  notion: { label: 'Notion · pages', className: 'source-badge--notion' },
  sqlite: { label: 'SQLite · tables', className: 'source-badge--sqlite' },
};

function ExternalRecordLink({ url, label }: { url?: unknown; label: string }) {
  if (typeof url !== 'string' || !url.trim()) return null;
  const href = url.trim();
  if (!href.startsWith('https://') && !href.startsWith('http://')) return null;
  return (
    <a
      className="evidence-ext-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="evidence-external-link"
    >
      {label} ↗
    </a>
  );
}

export default function EvidencePanel({ evidence, loading = false, highlightedKey = null }: Props) {
  const presentKinds: EvidenceSourceKind[] = [];
  if (evidence && evidence.length > 0) {
    for (const rec of evidence) {
      const k = detectEvidenceSource(rec);
      if (!presentKinds.includes(k)) presentKinds.push(k);
    }
  }

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
          Live records from your connected sources (<strong>GitHub</strong>, <strong>Gmail</strong>,{' '}
          <strong>Notion</strong>, and <strong>SQLite</strong>) appear here with every grounded
          answer.
        </p>
      )}

      {!evidence && loading && (
        <p className="inspector-empty">Querying your connected data sources…</p>
      )}

      {evidence && evidence.length === 0 && (
        <p className="inspector-empty">0 matching records returned from connected data sources.</p>
      )}

      {evidence && evidence.length > 0 && (
        <div className="evidence-results">
          <div className="source-badge-group">
            {presentKinds.map((kind) => (
              <span
                key={kind}
                className={`source-badge ${SOURCE_BADGE_META[kind].className}`}
              >
                <span className="source-badge-dot" aria-hidden="true" />
                {SOURCE_BADGE_META[kind].label}
              </span>
            ))}
          </div>

          <div className="evidence-list">
            {evidence.map((rec, idx) => {
              const citeKey = recordCitationKey(rec, idx);
              const isHighlighted = highlightedKey === citeKey;
              const kind = detectEvidenceSource(rec);

              if (kind === 'github') {
                const stateStr = typeof rec.state === 'string' ? rec.state : 'open';
                const isClosed = stateStr === 'closed';
                const author =
                  (typeof rec.author === 'string' && rec.author) ||
                  (rec.user && typeof rec.user === 'object' ? rec.user.login : undefined);
                const excerpt =
                  (typeof rec.body_excerpt === 'string' && rec.body_excerpt) ||
                  (typeof rec.description === 'string' && rec.description) ||
                  '';
                const linkUrl = rec.url ?? rec.html_url;

                return (
                  <article
                    key={`${citeKey}-${idx}`}
                    id={`evidence-${citeKey}`}
                    data-testid="evidence-card"
                    className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                  >
                    <div className="evidence-card-top">
                      <span className="evidence-cite-tag">{citeKey}</span>
                      <span
                        className={`state-tag ${isClosed ? 'state-tag--closed' : 'state-tag--open'}`}
                      >
                        {stateStr}
                      </span>
                    </div>
                    <div className="evidence-card-name">{String(rec.title ?? rec.name ?? citeKey)}</div>
                    {author && <div className="evidence-card-meta">by @{author}</div>}
                    {excerpt && <p className="evidence-card-desc">{excerpt}</p>}
                    <ExternalRecordLink url={linkUrl} label="Open on GitHub" />
                  </article>
                );
              }

              if (kind === 'gmail') {
                const subject = typeof rec.subject === 'string' ? rec.subject : 'Email thread';
                const sender = typeof rec.sender === 'string' ? rec.sender : '';
                const date = typeof rec.date === 'string' ? rec.date : '';
                const snippet = typeof rec.snippet === 'string' ? rec.snippet : '';

                return (
                  <article
                    key={`${citeKey}-${idx}`}
                    id={`evidence-${citeKey}`}
                    data-testid="evidence-card"
                    className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                  >
                    <div className="evidence-card-top">
                      <span className="evidence-cite-tag">{citeKey}</span>
                      <span className="chip-tag">Gmail</span>
                    </div>
                    <div className="evidence-card-name">{subject}</div>
                    {(sender || date) && (
                      <div className="evidence-card-meta">
                        {sender ? `From ${sender}` : ''}
                        {sender && date ? ' · ' : ''}
                        {date}
                      </div>
                    )}
                    {snippet && <p className="evidence-card-desc">{snippet}</p>}
                    <ExternalRecordLink url={rec.url} label="Open in Gmail" />
                  </article>
                );
              }

              if (kind === 'notion') {
                const title = typeof rec.title === 'string' ? rec.title : 'Notion page';
                const lastEdited = typeof rec.last_edited === 'string' ? rec.last_edited : '';
                const excerpt = typeof rec.excerpt === 'string' ? rec.excerpt : '';

                return (
                  <article
                    key={`${citeKey}-${idx}`}
                    id={`evidence-${citeKey}`}
                    data-testid="evidence-card"
                    className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                  >
                    <div className="evidence-card-top">
                      <span className="evidence-cite-tag">{citeKey}</span>
                      <span className="chip-tag">Notion</span>
                    </div>
                    <div className="evidence-card-name">{title}</div>
                    {lastEdited && (
                      <div className="evidence-card-meta">Last edited {lastEdited}</div>
                    )}
                    {excerpt && <p className="evidence-card-desc">{excerpt}</p>}
                    <ExternalRecordLink url={rec.url} label="Open in Notion" />
                  </article>
                );
              }

              // SQLite (structured { table, row } OR legacy product row)
              const rowData =
                rec.row && typeof rec.row === 'object'
                  ? (rec.row as Record<string, unknown>)
                  : (rec as Record<string, unknown>);
              const tableName = typeof rec.table === 'string' ? rec.table : null;
              const priceVal = typeof rowData.price === 'number' ? rowData.price : undefined;
              const primaryName =
                typeof rowData.name === 'string'
                  ? rowData.name
                  : typeof rowData.title === 'string'
                    ? rowData.title
                    : tableName
                      ? `${tableName} row`
                      : citeKey;

              const extraEntries = Object.entries(rowData).filter(
                ([k, v]) =>
                  !['source', 'citation_key', 'name', 'title', 'price', 'category', 'description'].includes(k) &&
                  v !== null &&
                  v !== undefined &&
                  typeof v !== 'object',
              );

              return (
                <article
                  key={`${citeKey}-${idx}`}
                  id={`evidence-${citeKey}`}
                  data-testid="evidence-card"
                  className={`evidence-card${isHighlighted ? ' evidence-card--highlighted' : ''}`}
                >
                  <div className="evidence-card-top">
                    <span className="evidence-cite-tag">{citeKey}</span>
                    {priceVal !== undefined ? (
                      <span className="evidence-card-price">${priceVal.toLocaleString()}</span>
                    ) : (
                      tableName && <span className="chip-tag">{tableName}</span>
                    )}
                  </div>
                  <div className="evidence-card-name">{primaryName}</div>
                  {typeof rowData.category === 'string' && rowData.category && (
                    <div className="evidence-card-category">{rowData.category}</div>
                  )}
                  {typeof rowData.description === 'string' && rowData.description && (
                    <p className="evidence-card-desc">{rowData.description}</p>
                  )}
                  {extraEntries.length > 0 && !rowData.description && (
                    <dl className="evidence-kv-list">
                      {extraEntries.slice(0, 5).map(([k, v]) => (
                        <div key={k} className="evidence-kv-row">
                          <dt>{k}</dt>
                          <dd>{String(v)}</dd>
                        </div>
                      ))}
                    </dl>
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
