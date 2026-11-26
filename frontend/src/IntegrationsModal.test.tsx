// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { buildSuggestedPrompts, type UserIntegrationItem } from './integrations';

const SAMPLE_REGISTRY: UserIntegrationItem[] = [
  {
    provider: 'github',
    display_name: 'GitHub',
    category: 'Developer',
    description: 'Issues & pull requests',
    auth_type: 'oauth',
    available: true,
    status: 'connected',
    scope_summary: 'dorodb-web22/agentic-rag-live-data-memory',
    config: { repos: ['dorodb-web22/agentic-rag-live-data-memory'] },
    suggested_prompts: ['Which GitHub issues are open right now?'],
    connected_at: '2026-11-26T09:00:00Z',
  },
  {
    provider: 'gmail',
    display_name: 'Gmail',
    category: 'Communication',
    description: 'Search threads and messages',
    auth_type: 'oauth',
    available: true,
    status: 'needs_reauth',
    scope_summary: null,
    config: {},
    suggested_prompts: ['Summarize recent launch emails'],
    connected_at: null,
  },
  {
    provider: 'notion',
    display_name: 'Notion',
    category: 'Docs',
    description: 'Workspace pages and databases',
    auth_type: 'oauth',
    available: true,
    status: 'disconnected',
    scope_summary: null,
    config: {},
    suggested_prompts: ['Check Notion for Q4 launch checklist'],
    connected_at: null,
  },
  {
    provider: 'sqlite',
    display_name: 'Upload SQLite',
    category: 'Database',
    description: 'Upload a .db or .sqlite file',
    auth_type: 'upload',
    available: true,
    status: 'disconnected',
    scope_summary: null,
    config: {},
    suggested_prompts: ['List tables in my uploaded database'],
    connected_at: null,
  },
  {
    provider: 'google_sheets',
    display_name: 'Google Sheets',
    category: 'Spreadsheets',
    description: 'Live spreadsheet tables',
    auth_type: 'oauth',
    available: false,
    status: 'coming_soon',
    scope_summary: null,
    config: {},
    suggested_prompts: [],
    connected_at: null,
  },
  {
    provider: 'google_calendar',
    display_name: 'Google Calendar',
    category: 'Schedule',
    description: 'Upcoming meetings & schedules',
    auth_type: 'oauth',
    available: false,
    status: 'coming_soon',
    scope_summary: null,
    config: {},
    suggested_prompts: [],
    connected_at: null,
  },
];

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/');
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Integrations Registry & Modal UI', () => {
  it('builds dynamic suggested prompts from connected tools or onboarding fallbacks', () => {
    const onboarding = buildSuggestedPrompts([]);
    expect(onboarding).toHaveLength(4);
    expect(onboarding[0].label).toBe('Getting started');

    const personalized = buildSuggestedPrompts(SAMPLE_REGISTRY);
    expect(personalized).toHaveLength(4);
    expect(personalized[0]).toMatchObject({
      label: 'GitHub',
      text: 'Which GitHub issues are open right now?',
    });
  });

  it('renders connected, + Connect, Reconnect, Coming soon cards, ?connected toast, and Modal actions', async () => {
    window.history.replaceState({}, '', '/?connected=github');

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
      if (url === '/api/conversations') {
        return new Response(JSON.stringify({ conversations: [] }), { status: 200 });
      }
      if (url === '/api/health/deep') {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
      }
      if (url === '/api/integrations' && (!init?.method || init.method === 'GET')) {
        return new Response(JSON.stringify({ integrations: SAMPLE_REGISTRY }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/integrations/github/config' && init?.method === 'PATCH') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      if (url === '/api/integrations/sqlite/upload' && init?.method === 'POST') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      if (url === '/api/integrations/github' && init?.method === 'DELETE') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      throw new Error(`Unhandled fetch: ${init?.method ?? 'GET'} ${url}`);
    });

    const onNavigate = vi.fn();
    render(<App onNavigate={onNavigate} />);

    // ?connected=github toast appears and personalized GitHub prompt renders
    await waitFor(() => {
      expect(screen.getByTestId('connected-toast').textContent).toContain('GitHub connected');
      expect(screen.getByText('Which GitHub issues are open right now?')).toBeTruthy();
    });

    // Reconnect banner for Gmail (needs_reauth) + Coming soon badges for Sheets/Calendar
    expect(screen.getByTestId('stage-reauth-banner')).toBeTruthy();
    expect(screen.getByTestId('home-source-google_sheets').textContent).toContain('Coming soon');
    expect(screen.getByTestId('home-source-google_calendar').textContent).toContain('Coming soon');

    // Clicking Notion's + Connect triggers OAuth redirect URL
    const notionCard = screen.getByTestId('home-source-notion');
    const connectNotionBtn = notionCard.querySelector('button');
    expect(connectNotionBtn).not.toBeNull();
    fireEvent.click(connectNotionBtn!);
    expect(onNavigate).toHaveBeenCalledWith('/api/integrations/notion/connect');

    // Open Integrations Hub from Sidebar
    fireEvent.click(screen.getByTestId('sidebar-integrations-btn'));
    await waitFor(() => {
      expect(screen.getByText('Integrations Hub')).toBeTruthy();
    });

    // Configure GitHub scope (PATCH /api/integrations/github/config)
    const ghRow = screen.getByTestId('integration-row-github');
    fireEvent.click(ghRow.querySelector('button')!); // Configure
    const scopeInput = ghRow.querySelector('input[type="text"]') as HTMLInputElement;
    fireEvent.change(scopeInput, { target: { value: 'dorodb-web22/repo-a, dorodb-web22/repo-b' } });
    fireEvent.submit(ghRow.querySelector('form')!);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/integrations/github/config',
        expect.objectContaining({ method: 'PATCH', credentials: 'include' }),
      );
    });

    // Upload SQLite .db file (POST /api/integrations/sqlite/upload)
    const sqliteRow = screen.getByTestId('integration-row-sqlite');
    fireEvent.click(sqliteRow.querySelector('button')!); // + Connect opens dropzone
    const fileInput = screen.getByLabelText('Upload SQLite database file') as HTMLInputElement;
    const fakeDbFile = new File(['SQLite format 3'], 'analytics.db', {
      type: 'application/octet-stream',
    });
    fireEvent.change(fileInput, { target: { files: [fakeDbFile] } });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/integrations/sqlite/upload',
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      );
    });

    // Disconnect GitHub with two-step confirmation (DELETE /api/integrations/github)
    const disconnectBtn = Array.from(ghRow.querySelectorAll('button')).find(
      (b) => b.textContent === 'Disconnect',
    )!;
    fireEvent.click(disconnectBtn);
    const confirmDisconnectBtn = Array.from(ghRow.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Confirm disconnect'),
    )!;
    fireEvent.click(confirmDisconnectBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/integrations/github',
        expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
      );
    });
  });
});
