// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App — Auth Gate, Personalization & Server-Side History', () => {
  it('redirects to landing page when GET /api/auth/me returns 401', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 }),
    );
    const onNavigate = vi.fn();

    render(<App onNavigate={onNavigate} />);

    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith('/');
    });
    expect(screen.queryByText(/Demo mode/i)).toBeNull();
  });

  it('renders Google user identity, live /api/health/deep status, and signs out via POST /api/auth/logout', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/auth/me') {
        expect(init?.credentials).toBe('include');
        return new Response(
          JSON.stringify({
            id: 'user-1',
            name: 'Dorothy Barma',
            email: 'dorothy@example.com',
            picture: 'https://lh3.googleusercontent.com/a/dorothy-photo',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/conversations') {
        return new Response(JSON.stringify({ conversations: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/health/deep') {
        return new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/auth/logout') {
        expect(init?.method).toBe('POST');
        expect(init?.credentials).toBe('include');
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`Unhandled fetch URL: ${url}`);
    });

    const onNavigate = vi.fn();
    render(<App onNavigate={onNavigate} />);

    await waitFor(() => {
      expect(screen.getByText('Welcome, Dorothy!')).toBeTruthy();
    });

    expect(screen.getByTestId('user-avatar-img').getAttribute('src')).toBe(
      'https://lh3.googleusercontent.com/a/dorothy-photo',
    );
    expect(screen.getAllByText('dorothy@example.com').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/Demo mode/i)).toBeNull();

    await waitFor(() => {
      expect(screen.getByTestId('health-status').textContent).toContain('Connected');
    });

    // Open Settings and verify real Sign out (no local Switch profile form)
    fireEvent.click(screen.getByRole('button', { name: /Settings/i }));
    expect(screen.queryByText(/Switch/i)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Sign out/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/auth/logout',
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      );
      expect(onNavigate).toHaveBeenCalledWith('/');
    });
  });

  it('loads server conversations, preserves per-turn evidence & trace URLs on reopen, and deletes via API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/auth/me') {
        return new Response(
          JSON.stringify({
            id: 'user-1',
            name: 'Dorothy Barma',
            email: 'dorothy@example.com',
            picture: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/health/deep') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
      }
      if (url === '/api/conversations' && (!init?.method || init.method === 'GET')) {
        return new Response(
          JSON.stringify({
            conversations: [
              {
                id: 'conv-server-1',
                thread_id: 'thread-server-1',
                title: 'Pricing & GitHub check',
                updated_at: '2026-11-26T10:00:00Z',
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/conversations/thread-server-1' && (!init?.method || init.method === 'GET')) {
        return new Response(
          JSON.stringify({
            thread_id: 'thread-server-1',
            title: 'Pricing & GitHub check',
            messages: [
              {
                id: 'm1',
                role: 'user',
                content: 'Enterprise price?',
                evidence: null,
                trace_url: null,
                created_at: '2026-11-26T09:58:00Z',
              },
              {
                id: 'm2',
                role: 'assistant',
                content: 'Enterprise costs $5,000 [Product-3].',
                evidence: [{ id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' }],
                trace_url: 'https://smith.langchain.com/r/turn-1',
                created_at: '2026-11-26T09:58:02Z',
              },
              {
                id: 'm3',
                role: 'user',
                content: 'Any open issues?',
                evidence: null,
                trace_url: null,
                created_at: '2026-11-26T09:59:58Z',
              },
              {
                id: 'm4',
                role: 'assistant',
                content: 'Issue [GitHub-214] is open.',
                evidence: [{ number: 214, title: 'Add checkpoint pool', state: 'open' }],
                trace_url: 'https://smith.langchain.com/r/turn-2',
                created_at: '2026-11-26T10:00:00Z',
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/conversations/thread-server-1' && init?.method === 'DELETE') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      throw new Error(`Unhandled fetch: ${init?.method ?? 'GET'} ${url}`);
    });

    render(<App onNavigate={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Pricing & GitHub check')).toBeTruthy();
    });

    // Reopen saved chat from sidebar
    fireEvent.click(screen.getByText('Pricing & GitHub check'));

    await waitFor(() => {
      expect(screen.getAllByTestId('grounded-badge')).toHaveLength(2);
    });

    // Both turns retain their trace links and source chips
    const traceLinks = screen.getAllByTestId('turn-trace-link');
    expect(traceLinks).toHaveLength(2);
    expect(traceLinks[0].getAttribute('href')).toBe('https://smith.langchain.com/r/turn-1');
    expect(traceLinks[1].getAttribute('href')).toBe('https://smith.langchain.com/r/turn-2');

    // Clicking Turn 1's inline citation pill loads Turn 1's evidence & trace URL into Details panel
    const product3Buttons = screen.getAllByRole('button', { name: 'Product-3' });
    expect(product3Buttons.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(product3Buttons[0]);
    await waitFor(() => {
      expect(screen.getByText('$5,000')).toBeTruthy();
      expect(screen.getByText(/View in LangSmith/).getAttribute('href')).toBe(
        'https://smith.langchain.com/r/turn-1',
      );
    });

    // Delete conversation calls DELETE /api/conversations/{thread_id}
    fireEvent.click(screen.getByRole('button', { name: /Delete chat: Pricing & GitHub check/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/conversations/thread-server-1',
        expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
      );
    });
  });
});
