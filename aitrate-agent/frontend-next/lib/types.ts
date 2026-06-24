export interface CitationResponse {
  doc_id: string;
  citation_handle: string;
  relevance_score: number;
}

export interface ChatResponse {
  response_id: string;
  function_id: string;
  content: string;
  citations: CitationResponse[];
  confidence: 'high' | 'medium' | 'low' | 'abstain';
  validator_results: Record<string, unknown>;
}

export interface KBStats {
  total_chunks: number;
  active_docs: number;
  deprecated_docs: number;
}

export interface HealthResponse {
  status: string;
  kb_stats?: KBStats;
  detail?: string;
}

export interface BacktestPeriodMetric {
  period: string;
  n: number;
  win_rate: number;
  profit_factor: number;
  mdd_pct: number;
  composite: number;
  insufficient_sample: boolean;
}

export interface BacktestResult {
  summary: {
    total_trades: number;
    win_rate: number;
    profit_factor: number;
    net_pnl: number;
    max_drawdown_pct: number;
    stop_loss_ratio: number;
  };
  tsi: {
    final_tsi: number;
    grade: string;
    leverage_cap: number;
    stability: number;
    catastrophic_floor: boolean;
    dq_triggers: string[];
    period_metrics: BacktestPeriodMetric[];
  };
  trades_parsed: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  timestamp: Date;
  functionId?: string;
  citations?: CitationResponse[];
  confidence?: string;
}
