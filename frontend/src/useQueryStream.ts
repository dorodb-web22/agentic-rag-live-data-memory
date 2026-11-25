import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteConversation,
  deriveTitle,
  loadActiveUser,
  loadConversations,
  saveActiveUser,
  saveConversations,
  upsertConversation,
  type ChatMessage,
  type EvidenceRecord,
  type SavedConversation,
} from './chatStorage';
import { mockStream } from './mockStream';
import {
  applyStepEvent,
  closeRunningSteps,
  parseSseFrame,
  splitSseFrames,
  type StreamEvent,
  type TraceStep,
} from './streaming';

export const IS_MOCK_STREAM = import.meta.env.VITE_MOCK_STREAM === 'true';

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
  const [activeUser, setActiveUser] = useState<string>(() => loadActiveUser());
  const [conversations, setConversations] = useState<SavedConversation[]>(() =>
    loadConversations(loadActiveUser()),
  );
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[] | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [answer, setAnswer] = useState('');
  const [traceUrl, setTraceUrl] = useState<string | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [hasThread, setHasThread] = useState(false);

  const threadIdRef = useRef<string | null>(null);
  const convIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const activeUserRef = useRef<string>(activeUser);

  useEffect(() => {
    activeUserRef.current = activeUser;
  }, [activeUser]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Optional URL ?thread=<id> hydration from PostgreSQL backend
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlThread = params.get('thread')?.trim();
    if (!urlThread) return;

    const existing = conversations.find((c) => c.threadId === urlThread);
    if (existing) {
      convIdRef.current = existing.id;
      setActiveConversationId(existing.id);
      threadIdRef.current = existing.threadId;
      setHasThread(Boolean(existing.threadId));
      setMessages(existing.messages);
      setEvidence(existing.evidence);
      setSteps(existing.steps);
      setTraceUrl(existing.traceUrl);
      const lastAssistant = [...existing.messages].reverse().find((m) => m.role === 'assistant');
      setAnswer(lastAssistant?.content ?? '');
      return;
    }

    if (IS_MOCK_STREAM) return;
    fetch(`/threads/${encodeURIComponent(urlThread)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then(
        (
          data: {
            thread_id: string;
            messages: { role: 'user' | 'assistant'; content: string }[];
            evidence?: EvidenceRecord[] | null;
          } | null,
        ) => {
          if (!data || !Array.isArray(data.messages) || data.messages.length === 0) return;
          const now = new Date().toISOString();
          const hydratedMessages: ChatMessage[] = data.messages.map((m) => ({
            id: makeId('msg'),
            role: m.role,
            content: m.content,
            createdAt: now,
          }));
          const firstUser = hydratedMessages.find((m) => m.role === 'user')?.content ?? data.thread_id;
          const conv: SavedConversation = {
            id: makeId('conv'),
            threadId: data.thread_id,
            title: deriveTitle(firstUser),
            messages: hydratedMessages,
            evidence: data.evidence ?? null,
            steps: [],
            updatedAt: now,
          };
          convIdRef.current = conv.id;
          threadIdRef.current = conv.threadId;
          setActiveConversationId(conv.id);
          setHasThread(true);
          setMessages(hydratedMessages);
          setEvidence(conv.evidence);
          const lastAssistant = [...hydratedMessages].reverse().find((m) => m.role === 'assistant');
          setAnswer(lastAssistant?.content ?? '');
          setConversations((prev) => {
            const next = upsertConversation(prev, conv);
            saveConversations(activeUserRef.current, next);
            return next;
          });
        },
      )
      .catch(() => {
        /* ignore offline hydration failure */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useCallback(async (query: string): Promise<boolean> => {
    abortRef.current?.abort();
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
      const source = IS_MOCK_STREAM
        ? mockStream(query, threadIdRef.current, controller.signal)
        : fetchStream(query, threadIdRef.current, controller.signal);
      for await (const event of source) {
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
          createdAt: new Date().toISOString(),
        };
        const completedMessages = [...pendingMessages, assistantMsg];
        messagesRef.current = completedMessages;
        setMessages(completedMessages);

        const finalizedSteps = closeRunningSteps(collectedSteps);
        const convId = convIdRef.current ?? makeId('conv');
        convIdRef.current = convId;
        setActiveConversationId(convId);

        const firstUserText = completedMessages.find((m) => m.role === 'user')?.content ?? query;
        const saved: SavedConversation = {
          id: convId,
          threadId: threadIdRef.current,
          title: deriveTitle(firstUserText),
          messages: completedMessages,
          evidence: finalEvidence,
          steps: finalizedSteps,
          traceUrl: finalTraceUrl,
          updatedAt: new Date().toISOString(),
        };
        setConversations((prev) => {
          const next = upsertConversation(prev, saved);
          saveConversations(activeUserRef.current, next);
          return next;
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
    convIdRef.current = null;
    messagesRef.current = [];
    setActiveConversationId(null);
    setHasThread(false);
    setMessages([]);
    setEvidence(null);
    setSteps([]);
    setAnswer('');
    setTraceUrl(undefined);
    setError('');
    setLoading(false);
  }, []);

  const selectConversation = useCallback(
    (id: string) => {
      const target = conversations.find((c) => c.id === id);
      if (!target) return;
      abortRef.current?.abort();
      abortRef.current = null;
      convIdRef.current = target.id;
      threadIdRef.current = target.threadId;
      messagesRef.current = target.messages;
      setActiveConversationId(target.id);
      setHasThread(Boolean(target.threadId));
      setMessages(target.messages);
      setEvidence(target.evidence);
      setSteps(target.steps);
      setTraceUrl(target.traceUrl);
      const lastAssistant = [...target.messages].reverse().find((m) => m.role === 'assistant');
      setAnswer(lastAssistant?.content ?? '');
      setError('');
      setLoading(false);
    },
    [conversations],
  );

  const removeConversation = useCallback(
    (id: string) => {
      setConversations((prev) => {
        const next = deleteConversation(prev, id);
        saveConversations(activeUserRef.current, next);
        return next;
      });
      if (convIdRef.current === id) {
        reset();
      }
    },
    [reset],
  );

  const switchUser = useCallback(
    (nextHandle: string) => {
      const normalized = saveActiveUser(nextHandle);
      activeUserRef.current = normalized;
      setActiveUser(normalized);
      const loaded = loadConversations(normalized);
      setConversations(loaded);
      reset();
    },
    [reset],
  );

  return {
    activeUser,
    switchUser,
    conversations,
    activeConversationId,
    selectConversation,
    removeConversation,
    messages,
    evidence,
    steps,
    answer,
    traceUrl,
    error,
    loading,
    hasThread,
    activeThreadId: threadIdRef.current,
    submit,
    stop,
    reset,
  };
}
