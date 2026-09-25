const API_BASE = '';

export async function askQuestion(question, sessionId = 'demo-session-1') {
  const response = await fetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question, session_id: sessionId }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Network request failed' }));
    throw new Error(err.detail || 'Failed to communicate with RAG agent');
  }

  return response.json();
}

export async function fetchSessionFacts(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/facts`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.facts || [];
}

export async function fetchSessionHistory(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/history`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.history || [];
}

export async function clearSessionMemory(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  return response.ok;
}

export async function fetchSampleQueries() {
  try {
    const response = await fetch(`${API_BASE}/sample-queries`);
    if (response.ok) {
      return await response.json();
    }
  } catch (e) {
    console.warn("Could not fetch sample queries from backend:", e);
  }
  return [
    { id: 'q1', title: 'Quarterly Changes & Blockers', question: 'What changed in Project X this quarter and what\'s blocked?' },
    { id: 'q2', title: 'Blocked Tasks & Owners', question: 'What tasks are blocked and who owns them?' },
    { id: 'q3', title: 'Launch Risk Summary', question: 'Summarize the launch risk discussion and compliance status.' },
    { id: 'q4', title: 'Security & Auth Focus', question: 'Based on our conversation, what security and auth items need immediate attention?' }
  ];
}

export async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return await res.json();
  } catch {
    return { status: 'offline' };
  }
}
