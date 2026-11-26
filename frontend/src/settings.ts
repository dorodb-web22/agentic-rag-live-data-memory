export type ThemeMode = 'light' | 'dark' | 'system';

export type Settings = {
  theme: ThemeMode;
  displayName: string;
  showDetailsByDefault: boolean;
};

export const DEFAULT_SETTINGS: Settings = {
  theme: 'system',
  displayName: '',
  showDetailsByDefault: false,
};

export const SETTINGS_KEY = 'agentic_rag.settings.v1';

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      theme: parsed.theme === 'light' || parsed.theme === 'dark' ? parsed.theme : 'system',
      displayName: typeof parsed.displayName === 'string' ? parsed.displayName.slice(0, 40) : '',
      showDetailsByDefault: parsed.showDetailsByDefault === true,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: Settings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
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
