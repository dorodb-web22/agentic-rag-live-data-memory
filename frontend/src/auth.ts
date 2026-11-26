export type AuthUser = {
  id: string;
  name: string;
  email: string;
  picture: string | null;
};

export function getLandingUrl(override?: string): string {
  const raw = override ?? (import.meta.env.VITE_LANDING_URL as string | undefined);
  if (typeof raw === 'string' && raw.trim().length > 0) {
    return raw.trim();
  }
  return '/';
}

export function getFirstName(user: AuthUser): string {
  const trimmedName = user.name?.trim() ?? '';
  if (trimmedName) {
    return trimmedName.split(/\s+/)[0];
  }
  const emailLocal = user.email?.split('@')[0]?.trim();
  return emailLocal || 'there';
}

export function redirectToLanding(navigate?: (url: string) => void): boolean {
  const target = getLandingUrl();
  if (navigate) {
    navigate(target);
    return true;
  }
  if (typeof window === 'undefined') return false;
  try {
    const resolved = new URL(target, window.location.origin).href;
    if (resolved === window.location.href) {
      return false;
    }
  } catch {
    /* proceed with replace */
  }
  window.location.replace(target);
  return true;
}

export async function fetchCurrentUser(
  signal?: AbortSignal,
): Promise<{ status: 'authenticated'; user: AuthUser } | { status: 'unauthenticated' }> {
  const response = await fetch('/api/auth/me', {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (response.status === 401) {
    return { status: 'unauthenticated' };
  }

  if (!response.ok) {
    throw new Error(`Authentication check failed (${response.status}).`);
  }

  const data = (await response.json()) as Partial<AuthUser>;
  if (!data || typeof data.id !== 'string' || typeof data.email !== 'string') {
    throw new Error('Invalid user profile returned by /api/auth/me.');
  }

  return {
    status: 'authenticated',
    user: {
      id: data.id,
      name: typeof data.name === 'string' && data.name.trim() ? data.name.trim() : data.email,
      email: data.email,
      picture: typeof data.picture === 'string' && data.picture.trim() ? data.picture.trim() : null,
    },
  };
}

export async function logoutCurrentUser(): Promise<void> {
  await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
}
