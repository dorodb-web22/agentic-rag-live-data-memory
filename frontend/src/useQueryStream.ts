import { useCallback, useRef, useState } from 'react';
import { mockStream } from './mockStream';
import {
  applyStepEvent,
  closeRunningSteps,
  parseSseFrame,
  splitSseFrames,
  type StreamEvent,
  type TraceStep,
} from './streaming';

const USE_MOCK = import.meta.env.VITE_MOCK_STREAM === 'true';

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* fall through to generic message */
  }
  if (response.status === 422) return 'That question could not be processed. Try shortening or rephrasing it.';
  return `The request failed (${response.status}). Please try again.`;
}

async function* fetchStream(
  query: string,
  threadId: string | null,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch('/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query, thread_id: threadId }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(await describeFailure(response));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const [frames, rest] = splitSseFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) yield event;
    }
  }
  const tail = parseSseFrame(buffer);
  if (tail) yield tail;
}

export function useQueryStream() {
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [answer, setAnswer] = useState('');
  const [traceUrl, setTraceUrl] = useState<string | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const threadIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [hasThread, setHasThread] = useState(false);

  const submit = useCallback(async (query: string): Promise<boolean> => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError('');
    setAnswer('');
    setSteps([]);
    setTraceUrl(undefined);

    let answered = false;
    try {
      const source = USE_MOCK
        ? mockStream(query, threadIdRef.current, controller.signal)
        : fetchStream(query, threadIdRef.current, controller.signal);
      for await (const event of source) {
        if (controller.signal.aborted || abortRef.current !== controller) break;
        if (event.type === 'step') setSteps((prev) => applyStepEvent(prev, event.data));
        else if (event.type === 'trace') setTraceUrl(event.data.url);
        else if (event.type === 'answer') {
          answered = true;
          setAnswer(event.data.answer);
          if (event.data.thread_id) {
            threadIdRef.current = event.data.thread_id;
            setHasThread(true);
          }
        } else if (event.type === 'error') setError(event.data.message);
      }
      return !controller.signal.aborted && answered;
    } catch (cause) {
      if (controller.signal.aborted) return false;
      setError(
        cause instanceof TypeError
          ? 'Could not connect to the backend. Check that the local API is running and try again.'
          : cause instanceof Error
            ? cause.message
            : 'Something went wrong. Please try again.',
      );
      return false;
    } finally {
      if (abortRef.current === controller) {
        setSteps((prev) => closeRunningSteps(prev));
        setLoading(false);
      }
    }
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSteps((prev) => closeRunningSteps(prev));
    setLoading(false);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    threadIdRef.current = null;
    setHasThread(false);
    setSteps([]);
    setAnswer('');
    setTraceUrl(undefined);
    setError('');
    setLoading(false);
  }, []);

  return { steps, answer, traceUrl, error, loading, hasThread, submit, stop, reset };
}
