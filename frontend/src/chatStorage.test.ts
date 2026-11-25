// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import {
  conversationToMarkdown,
  deleteConversation,
  deriveTitle,
  loadActiveUser,
  loadConversations,
  saveActiveUser,
  saveConversations,
  upsertConversation,
  type SavedConversation,
} from './chatStorage';

beforeEach(() => {
  localStorage.clear();
});

const sampleConv: SavedConversation = {
  id: 'conv-1',
  threadId: 'thread-abc123',
  title: 'How much does Enterprise cost?',
  messages: [
    { id: 'm1', role: 'user', content: 'How much does Enterprise cost?', createdAt: '2026-11-25T10:00:00Z' },
    { id: 'm2', role: 'assistant', content: 'Enterprise costs $5,000 [Product-3].', createdAt: '2026-11-25T10:00:02Z' },
  ],
  evidence: [{ id: 3, name: 'Enterprise', price: 5000, category: 'Subscriptions' }],
  steps: [{ id: 's1', node: 'planner', status: 'done', startedAt: '2026-11-25T10:00:00Z', durationMs: 120 }],
  updatedAt: '2026-11-25T10:00:02Z',
};

describe('chatStorage', () => {
  it('persists and isolates chat history per signed-in user handle', () => {
    expect(loadActiveUser()).toBe('dorothy');
    saveConversations('dorothy', [sampleConv]);
    expect(loadConversations('dorothy')).toHaveLength(1);
    expect(loadConversations('alok')).toHaveLength(0);

    saveActiveUser('Alok');
    expect(loadActiveUser()).toBe('alok');
  });

  it('upserts most recent conversation first and deletes cleanly', () => {
    const second: SavedConversation = { ...sampleConv, id: 'conv-2', title: 'Second chat' };
    const list = upsertConversation([sampleConv], second);
    expect(list.map((c) => c.id)).toEqual(['conv-2', 'conv-1']);

    const afterDelete = deleteConversation(list, 'conv-2');
    expect(afterDelete.map((c) => c.id)).toEqual(['conv-1']);
  });

  it('truncates long titles and exports full markdown with evidence', () => {
    expect(deriveTitle('a'.repeat(80)).endsWith('…')).toBe(true);
    const md = conversationToMarkdown(sampleConv);
    expect(md).toContain('# How much does Enterprise cost?');
    expect(md).toContain('thread-abc123');
    expect(md).toContain('[Product-3]');
    expect(md).toContain('"name": "Enterprise"');
  });
});
