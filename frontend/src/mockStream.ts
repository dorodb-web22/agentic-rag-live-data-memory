// Local-only mock of the /query/stream contract. Enabled with VITE_MOCK_STREAM=true.
// Lets the UI be developed without the backend streaming endpoint.
import type { EvidenceRecord } from './chatStorage';
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

function buildMockPayload(query: string): { answer: string; evidence: EvidenceRecord[] } {
  const lowered = query.toLowerCase();
  if (lowered.includes('compare') || (lowered.includes('starter') && lowered.includes('professional'))) {
    return {
      answer:
        'The **Starter** tier costs **$100/mo** [Product-1] for small teams, while the **Professional** tier costs **$500/mo** [Product-2] with expanded collaboration and analytics.',
      evidence: [
        {
          id: 1,
          name: 'Starter',
          price: 100,
          category: 'Subscriptions',
          description: 'Core workspace for individuals and early teams.',
        },
        {
          id: 2,
          name: 'Professional',
          price: 500,
          category: 'Subscriptions',
          description: 'Team-scale workflows, SSO, and priority indexing.',
        },
      ],
    };
  }
  if (lowered.includes('add-on') || lowered.includes('addon') || lowered.includes('support') || lowered.includes('storage')) {
    return {
      answer:
        'Two add-ons are available in the catalog: **Add-on Storage** at **$50/mo** [Product-4] and **Premium Support** at **$250/mo** [Product-5] with 24/7 SLA coverage.',
      evidence: [
        {
          id: 4,
          name: 'Add-on Storage',
          price: 50,
          category: 'Add-ons',
          description: 'Extra 500 GB encrypted vector & document storage.',
        },
        {
          id: 5,
          name: 'Premium Support',
          price: 250,
          category: 'Add-ons',
          description: '24/7 dedicated engineering support and 1-hour SLA.',
        },
      ],
    };
  }
  return {
    answer: `For "${query}": the **Enterprise** plan costs **$5,000/mo** [Product-3], including unlimited seats, dedicated PostgreSQL memory, and custom MCP connectors.`,
    evidence: [
      {
        id: 3,
        name: 'Enterprise',
        price: 5000,
        category: 'Subscriptions',
        description: 'Unlimited seats, custom MCP connectors, and dedicated SLA.',
      },
    ],
  };
}

let mockSeq = 1;

export async function* mockStream(
  query: string,
  threadId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const ts = () => new Date().toISOString();
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'planner', status: 'start', timestamp: ts() } };
  await sleep(450, signal);
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'planner', status: 'end', timestamp: ts() } };
  yield { type: 'step', data: { node: 'worker', status: 'start', timestamp: ts() } };
  await sleep(950, signal);
  if (signal?.aborted) return;
  yield { type: 'step', data: { node: 'worker', status: 'end', timestamp: ts() } };
  const payload = buildMockPayload(query);
  const resolvedThread = threadId ?? `mock-thread-${mockSeq++}`;
  yield {
    type: 'answer',
    data: {
      answer: payload.answer,
      evidence: payload.evidence,
      thread_id: resolvedThread,
    },
  };
  yield { type: 'done', data: {} };
}
