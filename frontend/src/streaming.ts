// Pure helpers for the /api/query/stream SSE contract (no React, easy to unit test).

export type TraceNode = 'planner' | 'worker' | 'tools';

export type TraceStep = {
  id: string;
  node: TraceNode;
  status: 'running' | 'done';
  startedAt: string;
  endedAt?: string;
  durationMs?: number;
};

export type ConnectorWarning = {
  tool?: string;
  provider?: string;
  message: string;
};

export type StreamEvent =
  | { type: 'step'; data: { node: string; status: 'start' | 'end'; timestamp: string } }
  | { type: 'trace'; data: { url: string } }
  | {
      type: 'answer';
      data: {
        answer: string;
        evidence: Record<string, unknown>[] | null;
        thread_id: string | null;
        warnings?: ConnectorWarning[];
      };
    }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: Record<string, never> };

const KNOWN_NODES: readonly string[] = ['planner', 'worker', 'tools'];
const KNOWN_EVENTS: readonly string[] = ['step', 'trace', 'answer', 'error', 'done'];

/** Parse one SSE frame ("event: x\ndata: {...}"). Returns null for unknown/malformed frames. */
export function parseSseFrame(frame: string): StreamEvent | null {
  let type = '';
  const dataLines: string[] = [];
  for (const rawLine of frame.split(/\r?\n/)) {
    if (rawLine.startsWith(':')) continue;
    if (rawLine.startsWith('event:')) type = rawLine.slice(6).trim();
    else if (rawLine.startsWith('data:')) dataLines.push(rawLine.slice(5).trimStart());
  }
  if (!KNOWN_EVENTS.includes(type) || dataLines.length === 0) return null;
  try {
    const data = JSON.parse(dataLines.join('\n'));
    if (data === null || typeof data !== 'object') return null;
    return { type, data } as StreamEvent;
  } catch {
    return null;
  }
}

/** Incrementally split a text buffer into complete SSE frames; returns [frames, remainder]. */
export function splitSseFrames(buffer: string): [string[], string] {
  const parts = buffer.split(/\r?\n\r?\n/);
  const remainder = parts.pop() ?? '';
  return [parts.filter((p) => p.trim().length > 0), remainder];
}

let counter = 0;
function newId(): string {
  counter += 1;
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `step-${counter}`;
}

/** Fold a `step` event into the steps list (immutable). */
export function applyStepEvent(
  steps: TraceStep[],
  data: { node: string; status: 'start' | 'end'; timestamp: string },
): TraceStep[] {
  if (!KNOWN_NODES.includes(data.node)) return steps;
  const node = data.node as TraceNode;

  if (data.status === 'start') {
    if (steps.some((s) => s.node === node && s.status === 'running')) return steps;
    return [...steps, { id: newId(), node, status: 'running', startedAt: data.timestamp }];
  }

  // status === 'end': close the matching running step, or synthesize one if `start` was missed.
  const idx = steps.findIndex((s) => s.node === node && s.status === 'running');
  if (idx === -1) {
    return [
      ...steps,
      { id: newId(), node, status: 'done', startedAt: data.timestamp, endedAt: data.timestamp, durationMs: 0 },
    ];
  }
  const current = steps[idx];
  const duration = Math.max(0, Date.parse(data.timestamp) - Date.parse(current.startedAt));
  const next = steps.slice();
  next[idx] = {
    ...current,
    status: 'done',
    endedAt: data.timestamp,
    durationMs: Number.isFinite(duration) ? duration : undefined,
  };
  return next;
}

/** Mark any still-running steps as done (used when the stream ends or errors). */
export function closeRunningSteps(steps: TraceStep[]): TraceStep[] {
  return steps.map((s) => (s.status === 'running' ? { ...s, status: 'done' as const } : s));
}

export const NODE_LABELS: Record<TraceNode, { label: string; detail: string }> = {
  planner: { label: 'Planning', detail: 'Selecting connected tools & arguments' },
  tools: { label: 'Retrieving', detail: 'Querying connected tools in parallel' },
  worker: { label: 'Synthesizing', detail: 'Validating citations & writing answer' },
};

/** Turn `[GitHub-12]` / `[Gmail-abc]` / `[Notion-xyz]` / `[SQL-tbl-1]` / `[Product-3]` markers into markdown links (`#cite-...`). */
export function linkifyCitations(markdown: string): string {
  return markdown.replace(
    /\[((?:GitHub|Gmail|Notion|SQL|Product|SQLite)-[A-Za-z0-9_\-]+)\](?!\()/g,
    '[$1](#cite-$1)',
  );
}

export const MAX_QUERY_LENGTH = 2000;
