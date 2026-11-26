// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import EvidencePanel from './EvidencePanel';

afterEach(cleanup);

describe('EvidencePanel', () => {
  it('renders empty state when no evidence is loaded yet', () => {
    render(<EvidencePanel evidence={null} />);
    expect(screen.getByText(/Live records from your connected sources/i)).toBeTruthy();
  });

  it('renders SQLite product and structured table cards and highlights matching citation key', () => {
    const { container } = render(
      <EvidencePanel
        evidence={[
          { id: 1, name: 'Starter', price: 100, category: 'Subscriptions' },
          { id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' },
          { source: 'sqlite', table: 'orders', row: { rowid: 9, customer: 'Acme', total: 12000 } },
        ]}
        highlightedKey="Product-3"
      />,
    );
    expect(screen.getByText('SQLite · tables')).toBeTruthy();
    expect(screen.getByTestId('evidence-count').textContent).toBe('3 records');
    expect(screen.getByText('$5,000')).toBeTruthy();
    expect(screen.getByText('SQL-orders-9')).toBeTruthy();
    const highlighted = container.querySelector('#evidence-Product-3.evidence-card--highlighted');
    expect(highlighted).not.toBeNull();
  });

  it('renders multi-source GitHub, Gmail, and Notion cards with external links', () => {
    render(
      <EvidencePanel
        evidence={[
          {
            source: 'github',
            citation_key: 'GitHub-214',
            number: 214,
            title: 'Add checkpoint pool',
            state: 'open',
            author: 'dorothy',
            body_excerpt: 'Async pool setup',
            url: 'https://github.com/dorodb-web22/repo/issues/214',
          },
          {
            source: 'gmail',
            citation_key: 'Gmail-18f3a9',
            message_id: '18f3a9',
            subject: 'Launch sign-off',
            sender: 'alok@example.com',
            date: '2026-11-26',
            snippet: 'All checks green',
            url: 'https://mail.google.com/mail/u/0/#inbox/18f3a9',
          },
          {
            source: 'notion',
            citation_key: 'Notion-9b2c1d',
            page_id: '9b2c1d',
            title: 'Architecture Spec',
            last_edited: '2026-11-26',
            excerpt: 'Multi-tenant isolation rules',
            url: 'https://www.notion.so/9b2c1d',
          },
        ]}
      />,
    );
    expect(screen.getByText('GitHub · issues / PRs')).toBeTruthy();
    expect(screen.getByText('Gmail · threads')).toBeTruthy();
    expect(screen.getByText('Notion · pages')).toBeTruthy();

    expect(screen.getByText('GitHub-214')).toBeTruthy();
    expect(screen.getByText('by @dorothy')).toBeTruthy();
    expect(screen.getByText('Gmail-18f3a9')).toBeTruthy();
    expect(screen.getByText(/From alok@example.com/)).toBeTruthy();
    expect(screen.getByText('Notion-9b2c1d')).toBeTruthy();

    const links = screen.getAllByTestId('evidence-external-link');
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      'https://github.com/dorodb-web22/repo/issues/214',
      'https://mail.google.com/mail/u/0/#inbox/18f3a9',
      'https://www.notion.so/9b2c1d',
    ]);
  });
});
