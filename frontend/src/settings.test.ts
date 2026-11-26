// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { groupConversationsByDate, type SavedConversation } from './chatStorage';
import { DEFAULT_SETTINGS, SETTINGS_KEY, applyTheme, loadSettings, saveSettings } from './settings';

const NOW = new Date('2026-11-25T15:00:00');

function conv(id: string, iso: string): SavedConversation {
  return {
    id,
    threadId: `thread-${id}`,
    title: id,
    messages: [],
    evidence: null,
    steps: [],
    updatedAt: iso,
  };
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe('groupConversationsByDate', () => {
  it('buckets chats into Today / Yesterday / Previous 7 days / Older and drops empty groups', () => {
    const groups = groupConversationsByDate(
      [
        conv('a', '2026-11-25T09:00:00'),
        conv('b', '2026-11-24T23:30:00'),
        conv('c', '2026-11-20T10:00:00'),
        conv('d', '2026-10-01T10:00:00'),
      ],
      NOW,
    );
    expect(groups.map((g) => g.label)).toEqual([
      'Today',
      'Yesterday',
      'Previous 7 days',
      'Older',
    ]);
    expect(groups.map((g) => g.items[0].id)).toEqual(['a', 'b', 'c', 'd']);
  });

  it('omits groups with no chats and treats bad dates as Older', () => {
    const groups = groupConversationsByDate([conv('x', 'not-a-date')], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('Older');
  });
});

describe('settings', () => {
  it('falls back to defaults on empty or corrupt storage', () => {
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);
    localStorage.setItem(SETTINGS_KEY, '{broken');
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);
  });

  it('round-trips strictly UI preferences and purges legacy fake profile/chat keys', () => {
    localStorage.setItem('agentic_rag.active_user.v1', 'dorothy');
    localStorage.setItem('agentic_rag.chats.v1.dorothy', '[{"id":"old"}]');

    saveSettings({ theme: 'dark', showDetailsByDefault: true, sidebarCollapsed: true });
    expect(loadSettings()).toEqual({
      theme: 'dark',
      showDetailsByDefault: true,
      sidebarCollapsed: true,
    });
    expect(localStorage.getItem('agentic_rag.active_user.v1')).toBeNull();
    expect(localStorage.getItem('agentic_rag.chats.v1.dorothy')).toBeNull();

    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ theme: 'neon', displayName: 'FakeProfile', sidebarCollapsed: 'yes' }),
    );
    expect(loadSettings()).toEqual({
      theme: 'system',
      showDetailsByDefault: false,
      sidebarCollapsed: false,
    });
  });

  it('applyTheme sets the data-theme attribute', () => {
    expect(applyTheme('dark')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(applyTheme('light')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
