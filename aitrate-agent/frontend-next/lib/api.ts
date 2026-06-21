import type { ChatResponse, KBStats, HealthResponse } from './types';

const API_BASE = '/api';

export async function sendChatMessage(
  message: string,
  functionId: string = 'F-01',
  userId: string = 'frontend-user'
): Promise<ChatResponse> {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      function_id: functionId,
      message,
      user_id: userId,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  return resp.json();
}

export async function fetchKBStats(): Promise<KBStats | null> {
  try {
    const resp = await fetch(`${API_BASE}/health/kb-stats`);
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}

export async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const resp = await fetch(`${API_BASE}/health`);
    if (!resp.ok) return null;
    return resp.json();
  } catch {
    return null;
  }
}
