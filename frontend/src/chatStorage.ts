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
  user?: { login?: string };
  [key: string]: unknown;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
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

const USER_KEY = 'agentic_rag.active_user.v1';
const CHATS_PREFIX = 'agentic_rag.chats.v1.';
const MAX_SAVED_CHATS = 50;

export function normalizeUserHandle(raw: string): string {
  const cleaned = raw.trim().toLowerCase().replace(/[^a-z0-9._@-]/g, '');
  return cleaned || 'dorothy';
}

export function loadActiveUser(): string {
  try {
    const stored = localStorage.getItem(USER_KEY);
    return stored ? normalizeUserHandle(stored) : 'dorothy';
  } catch {
    return 'dorothy';
  }
}

export function saveActiveUser(handle: string): string {
  const normalized = normalizeUserHandle(handle);
  try {
    localStorage.setItem(USER_KEY, normalized);
  } catch {
    /* ignore quota / private mode errors */
  }
  return normalized;
}

function storageKeyForUser(handle: string): string {
  return `${CHATS_PREFIX}${normalizeUserHandle(handle)}`;
}

export function loadConversations(handle: string): SavedConversation[] {
  try {
    const raw = localStorage.getItem(storageKeyForUser(handle));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is SavedConversation =>
        item &&
        typeof item === 'object' &&
        typeof item.id === 'string' &&
        typeof item.title === 'string' &&
        Array.isArray(item.messages),
    );
  } catch {
    return [];
  }
}

export function saveConversations(handle: string, conversations: SavedConversation[]): void {
  try {
    localStorage.setItem(
      storageKeyForUser(handle),
      JSON.stringify(conversations.slice(0, MAX_SAVED_CHATS)),
    );
  } catch {
    /* ignore quota errors */
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
  const without = list.filter((item) => item.id !== updated.id);
  return [updated, ...without].slice(0, MAX_SAVED_CHATS);
}

export function deleteConversation(list: SavedConversation[], id: string): SavedConversation[] {
  return list.filter((item) => item.id !== id);
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
  for (const msg of conv.messages) {
    lines.push(`### ${msg.role === 'user' ? 'You' : 'Assistant'}`);
    lines.push('');
    lines.push(msg.content);
    lines.push('');
  }
  if (conv.evidence && conv.evidence.length > 0) {
    lines.push('---', '', '### Retrieved Evidence (Raw MCP Records)', '', '```json');
    lines.push(JSON.stringify(conv.evidence, null, 2));
    lines.push('```', '');
  }
  return lines.join('\n');
}
