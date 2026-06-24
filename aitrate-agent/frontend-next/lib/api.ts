import type { ChatResponse, KBStats, HealthResponse, BacktestResult, PortfolioResult } from './types';

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

export async function uploadBacktest(
  file: File,
  strategyId: string = 'unknown',
  asset: string = 'unknown',
  capitalBasis: number = 100000,
): Promise<BacktestResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('strategy_id', strategyId);
  formData.append('asset', asset);
  formData.append('capital_basis', String(capitalBasis));

  const resp = await fetch(`${API_BASE}/chat/backtest`, {
    method: 'POST',
    body: formData,
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  return resp.json();
}

export async function uploadPortfolio(
  files: File[],
  capitalBasis: number = 100000,
): Promise<PortfolioResult> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('capital_basis', String(capitalBasis));

  const resp = await fetch(`${API_BASE}/chat/portfolio`, {
    method: 'POST',
    body: formData,
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  return resp.json();
}
