import { buildRateLimitError, UnauthorizedApiError } from './chatStorage';

export type IntegrationStatus = 'connected' | 'disconnected' | 'needs_reauth' | 'coming_soon';
export type IntegrationAuthType = 'oauth' | 'upload';

export type UserIntegrationItem = {
  provider: string;
  display_name: string;
  category: string;
  description: string;
  auth_type: IntegrationAuthType;
  available: boolean;
  status: IntegrationStatus;
  scope_summary: string | null;
  config: Record<string, unknown> | null;
  suggested_prompts: string[];
  connected_at: string | null;
};

export type SuggestedPromptCard = {
  label: string;
  text: string;
  provider?: string;
};

export const ONBOARDING_SUGGESTIONS: SuggestedPromptCard[] = [
  {
    label: 'Getting started',
    text: 'What data sources can I connect to personalize my workspace?',
  },
  {
    label: 'Cross-source RAG',
    text: 'How can you cross-check my GitHub issues, Gmail threads, and Notion docs together?',
  },
  {
    label: 'Grounded citations',
    text: 'How do inline citations verify facts against my connected tools?',
  },
  {
    label: 'SQLite databases',
    text: 'What kinds of questions can I ask after uploading a SQLite database?',
  },
];

export function buildSuggestedPrompts(
  integrations: UserIntegrationItem[],
  maxCards = 4,
): SuggestedPromptCard[] {
  const connected = integrations.filter(
    (item) =>
      item.status === 'connected' &&
      Array.isArray(item.suggested_prompts) &&
      item.suggested_prompts.length > 0,
  );

  if (connected.length === 0) {
    return ONBOARDING_SUGGESTIONS.slice(0, maxCards);
  }

  // Round-robin across connected integrations so multi-tool users get balanced prompts
  const cards: SuggestedPromptCard[] = [];
  const seen = new Set<string>();
  let depth = 0;
  while (cards.length < maxCards) {
    let addedAtDepth = false;
    for (const item of connected) {
      if (depth < item.suggested_prompts.length) {
        const promptText = item.suggested_prompts[depth]?.trim();
        if (promptText && !seen.has(promptText)) {
          seen.add(promptText);
          cards.push({
            label: item.display_name,
            text: promptText,
            provider: item.provider,
          });
          addedAtDepth = true;
          if (cards.length >= maxCards) break;
        }
      }
    }
    if (!addedAtDepth) break;
    depth += 1;
  }

  // Pad with onboarding prompts if connected integrations provided fewer than maxCards prompts
  for (const fallback of ONBOARDING_SUGGESTIONS) {
    if (cards.length >= maxCards) break;
    if (!seen.has(fallback.text)) {
      seen.add(fallback.text);
      cards.push(fallback);
    }
  }

  return cards;
}

export function getIntegrationConnectUrl(provider: string): string {
  return `/api/integrations/${encodeURIComponent(provider)}/connect`;
}

export async function fetchIntegrations(signal?: AbortSignal): Promise<UserIntegrationItem[]> {
  const response = await fetch('/api/integrations', {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (response.status === 429) throw await buildRateLimitError(response);
  if (!response.ok) {
    throw new Error(`Failed to load integrations (${response.status}).`);
  }
  const body = (await response.json()) as { integrations?: UserIntegrationItem[] };
  return Array.isArray(body.integrations) ? body.integrations : [];
}

export async function updateIntegrationConfig(
  provider: string,
  config: Record<string, unknown>,
): Promise<void> {
  const response = await fetch(`/api/integrations/${encodeURIComponent(provider)}/config`, {
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ config }),
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (response.status === 429) throw await buildRateLimitError(response);
  if (!response.ok) {
    let detail = `Failed to update ${provider} configuration (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}

export async function uploadSqliteDatabase(file: File): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch('/api/integrations/sqlite/upload', {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    body: form,
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (response.status === 429) throw await buildRateLimitError(response);
  if (!response.ok) {
    let detail = `SQLite upload failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}

export async function disconnectIntegration(provider: string): Promise<void> {
  const response = await fetch(`/api/integrations/${encodeURIComponent(provider)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (response.status === 429) throw await buildRateLimitError(response);
  if (!response.ok && response.status !== 404) {
    throw new Error(`Failed to disconnect ${provider} (${response.status}).`);
  }
}
