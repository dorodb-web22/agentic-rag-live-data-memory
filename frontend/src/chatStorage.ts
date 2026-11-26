import type { TraceStep } from './streaming';

export type EvidenceRecord = {
  id?: number;
  name?: string;
  description?: string;
  price?: number;
  category?: string;
  // GitHub MCP fields
  number?: number;
  title?: string;
  state?: string;
  html_url?: string;
  url?: string;
  user?: { login?: string };
  [key: string]: unknown;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  evidence?: EvidenceRecord[] | null;
  traceUrl?: string | null;
  createdAt: string;
};

export type SavedConversation = {
  id: string;
  threadId: string | null;
  title: string;
  messages: ChatMessage[];
  evidence: EvidenceRecord[] | null;
  steps: TraceStep[];
  traceUrl?: string;
  updatedAt: string;
};

export type ServerConversationSummary = {
  id: string;
  thread_id: string;
  title: string;
  updated_at: string;
};

export type ServerConversationMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  evidence: EvidenceRecord[] | null;
  trace_url: string | null;
  created_at: string;
};

export type ServerConversationDetail = {
  thread_id: string;
  title: string;
  messages: ServerConversationMessage[];
};

export class UnauthorizedApiError extends Error {
  constructor(message = 'Session expired. Please sign in again.') {
    super(message);
    this.name = 'UnauthorizedApiError';
  }
}

export function deriveTitle(firstQuery: string): string {
  const trimmed = firstQuery.trim().replace(/\s+/g, ' ');
  if (!trimmed) return 'Untitled conversation';
  return trimmed.length > 52 ? `${trimmed.slice(0, 51)}…` : trimmed;
}

export function upsertConversation(
  list: SavedConversation[],
  updated: SavedConversation,
): SavedConversation[] {
  const without = list.filter((item) => {
    if (updated.threadId && item.threadId === updated.threadId) return false;
    return item.id !== updated.id;
  });
  return [updated, ...without];
}

export function deleteConversation(
  list: SavedConversation[],
  idOrThreadId: string,
): SavedConversation[] {
  return list.filter((item) => item.threadId !== idOrThreadId && item.id !== idOrThreadId);
}

export function mapConversationSummary(raw: ServerConversationSummary): SavedConversation {
  return {
    id: raw.id || raw.thread_id,
    threadId: raw.thread_id,
    title: raw.title || 'Untitled conversation',
    messages: [],
    evidence: null,
    steps: [],
    updatedAt: raw.updated_at,
  };
}

export function mapConversationDetail(
  detail: ServerConversationDetail,
  existingId?: string,
  existingUpdatedAt?: string,
): SavedConversation {
  const messages: ChatMessage[] = (detail.messages ?? []).map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    evidence: m.evidence ?? null,
    traceUrl: m.trace_url ?? null,
    createdAt: m.created_at,
  }));

  const reverseAssistants = [...messages].reverse().filter((m) => m.role === 'assistant');
  const latestWithEvidence = reverseAssistants.find(
    (m) => Array.isArray(m.evidence) && m.evidence.length > 0,
  );
  const latestWithTrace = reverseAssistants.find((m) => Boolean(m.traceUrl));
  const lastMsg = messages[messages.length - 1];

  return {
    id: existingId ?? detail.thread_id,
    threadId: detail.thread_id,
    title: detail.title || deriveTitle(messages.find((m) => m.role === 'user')?.content ?? ''),
    messages,
    evidence: latestWithEvidence?.evidence ?? reverseAssistants[0]?.evidence ?? null,
    steps: [],
    traceUrl: latestWithTrace?.traceUrl ?? undefined,
    updatedAt: existingUpdatedAt ?? lastMsg?.createdAt ?? new Date().toISOString(),
  };
}

export async function fetchConversations(signal?: AbortSignal): Promise<SavedConversation[]> {
  const response = await fetch('/api/conversations', {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (!response.ok) {
    throw new Error(`Failed to load conversations (${response.status}).`);
  }
  const body = (await response.json()) as { conversations?: ServerConversationSummary[] };
  if (!Array.isArray(body.conversations)) return [];
  return body.conversations.map(mapConversationSummary);
}

export async function fetchConversationDetail(
  threadId: string,
  signal?: AbortSignal,
): Promise<SavedConversation> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(threadId)}`, {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (!response.ok) {
    throw new Error(`Failed to load conversation (${response.status}).`);
  }
  const detail = (await response.json()) as ServerConversationDetail;
  return mapConversationDetail(detail);
}

export async function deleteConversationRemote(threadId: string): Promise<void> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (response.status === 401) throw new UnauthorizedApiError();
  if (!response.ok && response.status !== 404) {
    throw new Error(`Failed to delete conversation (${response.status}).`);
  }
}

export type HistoryGroup = { label: string; items: SavedConversation[] };

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Group conversations (already sorted newest-first) into Today / Yesterday / Previous 7 days / Older. */
export function groupConversationsByDate(
  list: SavedConversation[],
  now: Date = new Date(),
): HistoryGroup[] {
  const today = startOfDay(now);
  const DAY = 24 * 60 * 60 * 1000;
  const buckets: HistoryGroup[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ];
  for (const conv of list) {
    const parsed = Date.parse(conv.updatedAt);
    const age = Number.isFinite(parsed) ? today - startOfDay(new Date(parsed)) : Infinity;
    if (age <= 0) buckets[0].items.push(conv);
    else if (age <= DAY) buckets[1].items.push(conv);
    else if (age <= 7 * DAY) buckets[2].items.push(conv);
    else buckets[3].items.push(conv);
  }
  return buckets.filter((b) => b.items.length > 0);
}

export function conversationToMarkdown(conv: SavedConversation): string {
  const lines: string[] = [
    `# ${conv.title}`,
    '',
    `- **Saved:** ${conv.updatedAt}`,
    ...(conv.threadId ? [`- **Thread ID:** \`${conv.threadId}\``] : []),
    '',
    '---',
    '',
  ];
  let exportedTurnEvidence = false;
  for (const msg of conv.messages) {
    lines.push(`### ${msg.role === 'user' ? 'You' : 'Assistant'}`);
    lines.push('');
    lines.push(msg.content);
    lines.push('');
    if (msg.role === 'assistant' && msg.traceUrl) {
      lines.push(`- **Execution Trace:** ${msg.traceUrl}`);
      lines.push('');
    }
    if (msg.role === 'assistant' && msg.evidence && msg.evidence.length > 0) {
      exportedTurnEvidence = true;
      lines.push('#### Supporting Evidence', '', '```json');
      lines.push(JSON.stringify(msg.evidence, null, 2));
      lines.push('```', '');
    }
  }
  if (!exportedTurnEvidence && conv.evidence && conv.evidence.length > 0) {
    lines.push('---', '', '### Retrieved Evidence (Raw MCP Records)', '', '```json');
    lines.push(JSON.stringify(conv.evidence, null, 2));
    lines.push('```', '');
  }
  return lines.join('\n');
}
