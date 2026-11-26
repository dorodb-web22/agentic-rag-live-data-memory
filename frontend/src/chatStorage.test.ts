// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  conversationToMarkdown,
  deleteConversation,
  deleteConversationRemote,
  deriveTitle,
  fetchConversationDetail,
  fetchConversations,
  UnauthorizedApiError,
  upsertConversation,
  type SavedConversation,
} from './chatStorage';

afterEach(() => {
  vi.restoreAllMocks();
});

const sampleConv: SavedConversation = {
  id: 'conv-1',
  threadId: 'thread-abc123',
  title: 'How much does Enterprise cost?',
  messages: [
    {
      id: 'm1',
      role: 'user',
      content: 'How much does Enterprise cost?',
      createdAt: '2026-11-25T10:00:00Z',
    },
    {
      id: 'm2',
      role: 'assistant',
      content: 'Enterprise costs $5,000 [Product-3].',
      evidence: [{ id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' }],
      traceUrl: 'https://smith.langchain.com/r/run-1',
      createdAt: '2026-11-25T10:00:02Z',
    },
  ],
  evidence: [{ id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' }],
  steps: [],
  traceUrl: 'https://smith.langchain.com/r/run-1',
  updatedAt: '2026-11-25T10:00:02Z',
};

describe('chatStorage (server-backed)', () => {
  it('fetches conversations list with credentials included', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          conversations: [
            {
              id: 'c-1',
              thread_id: 'thread-1',
              title: 'Enterprise pricing',
              updated_at: '2026-11-26T09:00:00Z',
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const list = await fetchConversations();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/conversations',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    );
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({
      id: 'c-1',
      threadId: 'thread-1',
      title: 'Enterprise pricing',
      updatedAt: '2026-11-26T09:00:00Z',
    });
  });

  it('hydrates full conversation detail preserving every turn evidence and trace_url', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          thread_id: 'thread-1',
          title: 'Multi-turn chat',
          messages: [
            {
              id: 'm1',
              role: 'user',
              content: 'Enterprise price?',
              evidence: null,
              trace_url: null,
              created_at: '2026-11-26T09:00:00Z',
            },
            {
              id: 'm2',
              role: 'assistant',
              content: 'Costs $5,000 [Product-3].',
              evidence: [{ id: 3, name: 'Enterprise', price: 5000 }],
              trace_url: 'https://smith.langchain.com/r/turn-1',
              created_at: '2026-11-26T09:00:01Z',
            },
            {
              id: 'm3',
              role: 'user',
              content: 'Open issues?',
              evidence: null,
              trace_url: null,
              created_at: '2026-11-26T09:01:00Z',
            },
            {
              id: 'm4',
              role: 'assistant',
              content: 'Issue [GitHub-19] is open.',
              evidence: [{ number: 19, title: 'Fix concurrency', state: 'open' }],
              trace_url: 'https://smith.langchain.com/r/turn-2',
              created_at: '2026-11-26T09:01:02Z',
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const detail = await fetchConversationDetail('thread-1');
    expect(detail.messages).toHaveLength(4);
    expect(detail.messages[1].evidence).toEqual([{ id: 3, name: 'Enterprise', price: 5000 }]);
    expect(detail.messages[1].traceUrl).toBe('https://smith.langchain.com/r/turn-1');
    expect(detail.messages[3].evidence).toEqual([
      { number: 19, title: 'Fix concurrency', state: 'open' },
    ]);
    expect(detail.messages[3].traceUrl).toBe('https://smith.langchain.com/r/turn-2');
    expect(detail.evidence).toEqual([{ number: 19, title: 'Fix concurrency', state: 'open' }]);
    expect(detail.traceUrl).toBe('https://smith.langchain.com/r/turn-2');
  });

  it('throws UnauthorizedApiError on 401 and sends DELETE with credentials', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockResolvedValueOnce(new Response('{"ok":true}', { status: 200 }));

    await expect(fetchConversations()).rejects.toBeInstanceOf(UnauthorizedApiError);

    await deleteConversationRemote('thread-xyz');
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/conversations/thread-xyz',
      expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
    );
  });

  it('upserts by threadId without duplicating and deletes cleanly', () => {
    const updatedSameThread: SavedConversation = {
      ...sampleConv,
      id: 'server-id-1',
      title: 'Updated title',
    };
    const afterSameThread = upsertConversation([sampleConv], updatedSameThread);
    expect(afterSameThread).toHaveLength(1);
    expect(afterSameThread[0].title).toBe('Updated title');

    const second: SavedConversation = {
      ...sampleConv,
      id: 'conv-2',
      threadId: 'thread-def456',
      title: 'Second chat',
    };
    const list = upsertConversation(afterSameThread, second);
    expect(list.map((c) => c.threadId)).toEqual(['thread-def456', 'thread-abc123']);

    const afterDelete = deleteConversation(list, 'thread-def456');
    expect(afterDelete.map((c) => c.threadId)).toEqual(['thread-abc123']);
  });

  it('truncates long titles and exports full markdown with per-turn evidence and trace URL', () => {
    expect(deriveTitle('a'.repeat(80)).endsWith('…')).toBe(true);
    const md = conversationToMarkdown(sampleConv);
    expect(md).toContain('# How much does Enterprise cost?');
    expect(md).toContain('thread-abc123');
    expect(md).toContain('[Product-3]');
    expect(md).toContain('https://smith.langchain.com/r/run-1');
    expect(md).toContain('"name": "Enterprise"');
  });
});
