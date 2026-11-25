// Local-only mock of the /query/stream contract. Enabled with VITE_MOCK_STREAM=true.
// Lets the UI be developed without the backend streaming endpoint.
import type { StreamEvent } from './streaming';

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function* mockStream(
  query: string,
  threadId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const ts = () => new Date().toISOString();
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'planner', status: 'start', timestamp: ts() } };
  await sleep(500, signal);
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'planner', status: 'end', timestamp: ts() } };
  yield { type: 'step', data: { node: 'worker', status: 'start', timestamp: ts() } };
  await sleep(1200, signal);
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'worker', status: 'end', timestamp: ts() } };
  yield {
    type: 'answer',
    data: {
      answer: `Mock answer for "${query}": the Enterprise plan costs $5000 [Product-3].`,
      evidence: [{ id: 3, name: 'Enterprise', price: 5000 }],
      thread_id: threadId ?? 'mock-thread',
    },
  };
  yield { type: 'done', data: {} };
}
