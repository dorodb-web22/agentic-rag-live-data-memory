// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { groupConversationsByDate, type SavedConversation } from './chatStorage';
import { DEFAULT_SETTINGS, SETTINGS_KEY, applyTheme, loadSettings, saveSettings } from './settings';

const NOW = new Date('2026-11-25T15:00:00');

function conv(id: string, iso: string): SavedConversation {
  return { id, threadId: null, title: id, messages: [], evidence: null, steps: [], updatedAt: iso };
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
    expect(groups.map((g) => g.label)).toEqual(['Today', 'Yesterday', 'Previous 7 days', 'Older']);
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

  it('round-trips valid settings and sanitizes unknown values', () => {
    saveSettings({ theme: 'dark', displayName: 'Dorothy', showDetailsByDefault: true });
    expect(loadSettings()).toEqual({ theme: 'dark', displayName: 'Dorothy', showDetailsByDefault: true });
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ theme: 'neon', displayName: 5 }));
    expect(loadSettings().theme).toBe('system');
    expect(loadSettings().displayName).toBe('');
  });

  it('applyTheme sets the data-theme attribute', () => {
    expect(applyTheme('dark')).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(applyTheme('light')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
