import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteConversation,
  deleteConversationRemote,
  deriveTitle,
  fetchConversationDetail,
  fetchConversations,
  UnauthorizedApiError,
  upsertConversation,
  type ChatMessage,
  type EvidenceRecord,
  type SavedConversation,
} from './chatStorage';
import {
  applyStepEvent,
  closeRunningSteps,
  parseSseFrame,
  splitSseFrames,
  type StreamEvent,
  type TraceStep,
} from './streaming';

let localIdSeq = 0;
function makeId(prefix: string): string {
  localIdSeq += 1;
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? `${prefix}-${crypto.randomUUID()}`
    : `${prefix}-${Date.now()}-${localIdSeq}`;
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* fall through to generic message */
  }
  if (response.status === 422) {
    return 'That question could not be processed. Try shortening or rephrasing it.';
  }
  if (response.status === 429) {
    return 'Rate limit reached. Please wait a moment and try again.';
  }
  return `The request failed (${response.status}). Please try again.`;
}

async function* fetchStream(
  query: string,
  threadId: string | null,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch('/api/query/stream', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query, thread_id: threadId }),
    signal,
  });
  if (response.status === 401) {
    throw new UnauthorizedApiError();
  }
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

export type UseQueryStreamOptions = {
  enabled?: boolean;
  onUnauthorized?: () => void;
};

export function useQueryStream(options: UseQueryStreamOptions = {}) {
  const { enabled = true, onUnauthorized } = options;

  const [conversations, setConversations] = useState<SavedConversation[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[] | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [answer, setAnswer] = useState('');
  const [traceUrl, setTraceUrl] = useState<string | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [hasThread, setHasThread] = useState(false);

  const threadIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const conversationsRef = useRef<SavedConversation[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);
  const onUnauthorizedRef = useRef(onUnauthorized);

  useEffect(() => {
    onUnauthorizedRef.current = onUnauthorized;
  }, [onUnauthorized]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const selectConversation = useCallback(async (threadId: string) => {
    if (!threadId) return;
    abortRef.current?.abort();
    abortRef.current = null;
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;

    threadIdRef.current = threadId;
    setActiveThreadId(threadId);
    setHasThread(true);
    setError('');
    setLoading(false);

    const cached = conversationsRef.current.find((c) => c.threadId === threadId);
    if (cached && cached.messages.length > 0) {
      messagesRef.current = cached.messages;
      setMessages(cached.messages);
      setEvidence(cached.evidence);
      setSteps(cached.steps);
      setTraceUrl(cached.traceUrl);
      const lastAssistant = [...cached.messages].reverse().find((m) => m.role === 'assistant');
      setAnswer(lastAssistant?.content ?? '');
    } else {
      setLoadingThread(true);
    }

    try {
      const hydrated = await fetchConversationDetail(threadId, controller.signal);
      if (controller.signal.aborted || threadIdRef.current !== threadId) return;
      const merged: SavedConversation = {
        ...hydrated,
        id: cached?.id ?? hydrated.id,
        updatedAt: cached?.updatedAt ?? hydrated.updatedAt,
      };
      messagesRef.current = merged.messages;
      setMessages(merged.messages);
      setEvidence(merged.evidence);
      setSteps([]);
      setTraceUrl(merged.traceUrl);
      const lastAssistant = [...merged.messages].reverse().find((m) => m.role === 'assistant');
      setAnswer(lastAssistant?.content ?? '');
      setConversations((prev) =>
        prev.some((c) => c.threadId === threadId)
          ? prev.map((c) => (c.threadId === threadId ? merged : c))
          : upsertConversation(prev, merged),
      );
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof UnauthorizedApiError) {
        onUnauthorizedRef.current?.();
        return;
      }
      if (!cached || cached.messages.length === 0) {
        setError(cause instanceof Error ? cause.message : 'Failed to load conversation.');
      }
    } finally {
      if (detailAbortRef.current === controller) {
        setLoadingThread(false);
      }
    }
  }, []);

  // Load server-persisted conversations on sign-in, and hydrate optional ?thread=<id>
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();

    fetchConversations(controller.signal)
      .then((list) => {
        if (controller.signal.aborted) return;
        setConversations(list);
        const params = new URLSearchParams(window.location.search);
        const urlThread = params.get('thread')?.trim();
        if (urlThread) {
          void selectConversation(urlThread);
        }
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        if (cause instanceof UnauthorizedApiError) {
          onUnauthorizedRef.current?.();
        }
      });

    return () => {
      controller.abort();
    };
  }, [enabled, selectConversation]);

  const submit = useCallback(async (query: string): Promise<boolean> => {
    abortRef.current?.abort();
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError('');
    setAnswer('');
    setSteps([]);
    setTraceUrl(undefined);

    const priorMessages = messagesRef.current;
    const userMsg: ChatMessage = {
      id: makeId('msg'),
      role: 'user',
      content: query,
      createdAt: new Date().toISOString(),
    };
    const pendingMessages = [...priorMessages, userMsg];
    messagesRef.current = pendingMessages;
    setMessages(pendingMessages);

    let answered = false;
    let finalAnswer = '';
    let finalEvidence: EvidenceRecord[] | null = null;
    let finalTraceUrl: string | undefined;
    let collectedSteps: TraceStep[] = [];

    try {
      for await (const event of fetchStream(query, threadIdRef.current, controller.signal)) {
        if (controller.signal.aborted || abortRef.current !== controller) break;
        if (event.type === 'step') {
          collectedSteps = applyStepEvent(collectedSteps, event.data);
          setSteps(collectedSteps);
        } else if (event.type === 'trace') {
          finalTraceUrl = event.data.url;
          setTraceUrl(event.data.url);
        } else if (event.type === 'answer') {
          answered = true;
          finalAnswer = event.data.answer;
          finalEvidence = (event.data.evidence as EvidenceRecord[] | null) ?? null;
          setAnswer(finalAnswer);
          setEvidence(finalEvidence);
          if (event.data.thread_id) {
            threadIdRef.current = event.data.thread_id;
            setActiveThreadId(event.data.thread_id);
            setHasThread(true);
          }
        } else if (event.type === 'error') {
          setError(event.data.message);
        }
      }

      if (!controller.signal.aborted && answered) {
        const assistantMsg: ChatMessage = {
          id: makeId('msg'),
          role: 'assistant',
          content: finalAnswer,
          evidence: finalEvidence,
          traceUrl: finalTraceUrl ?? null,
          createdAt: new Date().toISOString(),
        };
        const completedMessages = [...pendingMessages, assistantMsg];
        messagesRef.current = completedMessages;
        setMessages(completedMessages);

        const finalizedSteps = closeRunningSteps(collectedSteps);
        const resolvedThread = threadIdRef.current;
        if (resolvedThread) {
          setActiveThreadId(resolvedThread);
          setHasThread(true);
        }

        const existing = resolvedThread
          ? conversationsRef.current.find((c) => c.threadId === resolvedThread)
          : undefined;
        const firstUserText = completedMessages.find((m) => m.role === 'user')?.content ?? query;
        const saved: SavedConversation = {
          id: existing?.id ?? resolvedThread ?? makeId('conv'),
          threadId: resolvedThread,
          title: existing?.title ?? deriveTitle(firstUserText),
          messages: completedMessages,
          evidence: finalEvidence,
          steps: finalizedSteps,
          traceUrl: finalTraceUrl,
          updatedAt: new Date().toISOString(),
        };
        setConversations((prev) => upsertConversation(prev, saved));

        // Sync canonical server list (id, title, updated_at) in background
        void fetchConversations()
          .then((remoteList) => {
            setConversations((prev) => {
              const byThread = new Map(prev.map((c) => [c.threadId, c]));
              return remoteList.map((remote) => {
                const local = byThread.get(remote.threadId);
                return local && local.messages.length > 0
                  ? { ...remote, messages: local.messages, evidence: local.evidence, steps: local.steps, traceUrl: local.traceUrl }
                  : remote;
              });
            });
          })
          .catch(() => {
            /* ignore background list refresh errors */
          });

        return true;
      }

      // Rolled back user bubble if aborted or errored before an answer arrived
      messagesRef.current = priorMessages;
      setMessages(priorMessages);
      return false;
    } catch (cause) {
      messagesRef.current = priorMessages;
      setMessages(priorMessages);
      if (controller.signal.aborted) return false;
      if (cause instanceof UnauthorizedApiError) {
        onUnauthorizedRef.current?.();
        return false;
      }
      setError(
        cause instanceof TypeError
          ? 'Could not connect to the backend. Check that the API is running and try again.'
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
    detailAbortRef.current?.abort();
    detailAbortRef.current = null;
    threadIdRef.current = null;
    messagesRef.current = [];
    setActiveThreadId(null);
    setHasThread(false);
    setMessages([]);
    setEvidence(null);
    setSteps([]);
    setAnswer('');
    setTraceUrl(undefined);
    setError('');
    setLoading(false);
    setLoadingThread(false);
  }, []);

  const inspectTurn = useCallback(
    (turnEvidence: EvidenceRecord[] | null | undefined, turnTraceUrl?: string | null) => {
      if (turnEvidence !== undefined) {
        setEvidence(turnEvidence);
      }
      setTraceUrl(turnTraceUrl ?? undefined);
    },
    [],
  );

  const removeConversation = useCallback(
    async (threadId: string) => {
      setConversations((prev) => deleteConversation(prev, threadId));
      if (threadIdRef.current === threadId) {
        reset();
      }
      try {
        await deleteConversationRemote(threadId);
      } catch (cause) {
        if (cause instanceof UnauthorizedApiError) {
          onUnauthorizedRef.current?.();
          return;
        }
        try {
          const fresh = await fetchConversations();
          setConversations(fresh);
        } catch {
          /* ignore */
        }
      }
    },
    [reset],
  );

  const clearAllConversations = useCallback(async () => {
    const threadIds = conversationsRef.current
      .map((c) => c.threadId)
      .filter((id): id is string => Boolean(id));
    setConversations([]);
    reset();
    const results = await Promise.allSettled(
      threadIds.map((threadId) => deleteConversationRemote(threadId)),
    );
    if (results.some((r) => r.status === 'rejected' && r.reason instanceof UnauthorizedApiError)) {
      onUnauthorizedRef.current?.();
    }
  }, [reset]);

  const hydrateAllConversations = useCallback(async (): Promise<SavedConversation[]> => {
    const current = conversationsRef.current;
    const hydrated = await Promise.all(
      current.map(async (conv) => {
        if (conv.messages.length > 0 || !conv.threadId) return conv;
        try {
          const full = await fetchConversationDetail(conv.threadId);
          return { ...full, id: conv.id, updatedAt: conv.updatedAt };
        } catch {
          return conv;
        }
      }),
    );
    return hydrated;
  }, []);

  return {
    conversations,
    activeThreadId,
    selectConversation,
    removeConversation,
    clearAllConversations,
    hydrateAllConversations,
    inspectTurn,
    messages,
    evidence,
    steps,
    answer,
    traceUrl,
    error,
    loading,
    loadingThread,
    hasThread,
    submit,
    stop,
    reset,
  };
}
