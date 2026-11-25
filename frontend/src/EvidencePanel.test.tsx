// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import EvidencePanel from './EvidencePanel';

afterEach(cleanup);

describe('EvidencePanel', () => {
  it('renders empty state when no evidence is loaded yet', () => {
    render(<EvidencePanel evidence={null} />);
    expect(screen.getByText(/Live MCP records/i)).toBeTruthy();
  });

  it('renders SQLite product cards and highlights matching citation key', () => {
    const { container } = render(
      <EvidencePanel
        evidence={[
          { id: 1, name: 'Starter', price: 100, category: 'Subscriptions' },
          { id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' },
        ]}
        highlightedKey="Product-3"
      />,
    );
    expect(screen.getByText('SQLite MCP · products')).toBeTruthy();
    expect(screen.getByTestId('evidence-count').textContent).toBe('2 records');
    expect(screen.getByText('$5,000')).toBeTruthy();
    const highlighted = container.querySelector('#evidence-Product-3.evidence-card--highlighted');
    expect(highlighted).not.toBeNull();
  });

  it('renders GitHub MCP issue records with state and author', () => {
    render(
      <EvidencePanel
        evidence={[
          { number: 214, title: 'Add checkpoint pool', state: 'open', user: { login: 'dorothy' } },
        ]}
      />,
    );
    expect(screen.getByText('GitHub MCP · issues / PRs')).toBeTruthy();
    expect(screen.getByText('GitHub-214')).toBeTruthy();
    expect(screen.getByText('by @dorothy')).toBeTruthy();
  });
});
