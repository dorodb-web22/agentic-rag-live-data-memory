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
      if (url === '/api/integrations') {
        return new Response(JSON.stringify({ integrations: [] }), {
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
      if (url === '/api/integrations') {
        return new Response(JSON.stringify({ integrations: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
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

  it('handles HTTP 429 rate limits with countdown banner and retries cleanly after cooldown', async () => {
    let streamCalls = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/auth/me') {
        return new Response(
          JSON.stringify({ id: 'u1', name: 'Dorothy', email: 'dorothy@example.com', picture: null }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/conversations') {
        return new Response(JSON.stringify({ conversations: [] }), { status: 200 });
      }
      if (url === '/api/integrations') {
        return new Response(JSON.stringify({ integrations: [] }), { status: 200 });
      }
      if (url === '/api/health/deep') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
      }
      if (url === '/api/query/stream') {
        streamCalls += 1;
        if (streamCalls === 1) {
          return new Response(
            JSON.stringify({ detail: 'Too many requests from this workspace.' }),
            {
              status: 429,
              headers: {
                'Content-Type': 'application/json',
                'Retry-After': '1',
              },
            },
          );
        }
        const sseBody =
          'event: answer\r\ndata: {"answer":"Recovered answer [GitHub-42].","evidence":[{"source":"github","citation_key":"GitHub-42","number":42,"title":"Rate limit test"}],"thread_id":"t-retry"}\r\n\r\n' +
          'event: done\r\ndata: {}\r\n\r\n';
        return new Response(sseBody, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }
      throw new Error(`Unhandled URL: ${url}`);
    });

    render(<App onNavigate={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Welcome, Dorothy!')).toBeTruthy();
    });

    const input = screen.getByLabelText('Ask a question');
    fireEvent.change(input, { target: { value: 'Check open blockers' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send question' }));

    await waitFor(() => {
      expect(screen.getByTestId('rate-limit-banner')).toBeTruthy();
    });
    expect(screen.getByTestId('rate-limit-banner').textContent).toContain(
      'Too many requests from this workspace.',
    );

    // Wait ~1.1s for the 1s Retry-After countdown to finish
    await waitFor(
      () => {
        expect(screen.getByTestId('rate-limit-countdown').textContent).toContain('Ready to retry');
      },
      { timeout: 2500 },
    );

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(screen.getByText(/Recovered answer/i)).toBeTruthy();
    });
    expect(screen.queryByTestId('rate-limit-banner')).toBeNull();
  });

  it('handles mid-session 401 expiration and renders partial connector failure warnings', async () => {
    let streamCalls = 0;
    const onNavigate = vi.fn();

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/auth/me') {
        return new Response(
          JSON.stringify({ id: 'u1', name: 'Dorothy', email: 'dorothy@example.com', picture: null }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/conversations') {
        return new Response(JSON.stringify({ conversations: [] }), { status: 200 });
      }
      if (url === '/api/integrations') {
        return new Response(JSON.stringify({ integrations: [] }), { status: 200 });
      }
      if (url === '/api/health/deep') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
      }
      if (url === '/api/query/stream') {
        streamCalls += 1;
        if (streamCalls === 1) {
          const sseBody =
            'event: answer\r\ndata: {"answer":"GitHub issue [GitHub-19] is open.","evidence":[{"source":"github","citation_key":"GitHub-19","number":19,"title":"SSO redirect"}],"thread_id":"t-partial","warnings":[{"provider":"gmail","tool":"fetch_gmail","message":"Gmail API timeout"}]}\r\n\r\n' +
            'event: done\r\ndata: {}\r\n\r\n';
          return new Response(sseBody, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          });
        }
        return new Response(JSON.stringify({ detail: 'Session expired' }), { status: 401 });
      }
      throw new Error(`Unhandled URL: ${url}`);
    });

    render(<App onNavigate={onNavigate} />);

    await waitFor(() => {
      expect(screen.getByText('Welcome, Dorothy!')).toBeTruthy();
    });

    // Turn 1: Partial connector failure callout renders alongside grounded GitHub answer
    const input = screen.getByLabelText('Ask a question');
    fireEvent.change(input, { target: { value: 'Cross-check GitHub and Gmail' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send question' }));

    await waitFor(() => {
      expect(screen.getByTestId('partial-connector-warning')).toBeTruthy();
    });
    expect(screen.getByTestId('partial-connector-warning').textContent).toContain(
      'Gmail: Gmail API timeout',
    );
    expect(screen.getByTestId('grounded-badge').textContent).toContain('Grounded in 1 source');

    // Turn 2: Session expires mid-session (401) -> shows Session expired notice & redirects
    fireEvent.change(screen.getByLabelText('Ask a question'), {
      target: { value: 'Follow-up after cookie expiry' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send question' }));

    await waitFor(() => {
      expect(screen.getByTestId('session-expired-notice')).toBeTruthy();
      expect(onNavigate).toHaveBeenCalledWith('/');
    });
  });
});
