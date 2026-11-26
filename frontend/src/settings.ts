export type ThemeMode = 'light' | 'dark' | 'system';

export type Settings = {
  theme: ThemeMode;
  showDetailsByDefault: boolean;
  sidebarCollapsed: boolean;
};

export const DEFAULT_SETTINGS: Settings = {
  theme: 'system',
  showDetailsByDefault: false,
  sidebarCollapsed: false,
};

export const SETTINGS_KEY = 'agentic_rag.settings.v1';

const LEGACY_USER_KEY = 'agentic_rag.active_user.v1';
const LEGACY_CHATS_PREFIX = 'agentic_rag.chats.v1.';

export function purgeLegacyLocalChatState(): void {
  try {
    localStorage.removeItem(LEGACY_USER_KEY);
    const toRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && key.startsWith(LEGACY_CHATS_PREFIX)) {
        toRemove.push(key);
      }
    }
    for (const key of toRemove) {
      localStorage.removeItem(key);
    }
  } catch {
    /* ignore quota / private-mode errors */
  }
}

export function loadSettings(): Settings {
  purgeLegacyLocalChatState();
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      theme: parsed.theme === 'light' || parsed.theme === 'dark' ? parsed.theme : 'system',
      showDetailsByDefault: parsed.showDetailsByDefault === true,
      sidebarCollapsed: parsed.sidebarCollapsed === true,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: Settings): void {
  try {
    const clean: Settings = {
      theme: settings.theme,
      showDetailsByDefault: settings.showDetailsByDefault,
      sidebarCollapsed: settings.sidebarCollapsed,
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(clean));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

export function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'light' || mode === 'dark') return mode;
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'light';
}

export function applyTheme(mode: ThemeMode): 'light' | 'dark' {
  const resolved = resolveTheme(mode);
  document.documentElement.dataset.theme = resolved;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', resolved === 'dark' ? '#1c1d1f' : '#e9e8f8');
  return resolved;
}
