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

export interface WorstWindowResult {
  window_size: number;
  worst_composite: number;
  worst_period_start: string;
  worst_period_end: string;
  full_sample_composite: number;
  drop_points: number;
  n_windows_tested: number;
}

export interface FragileTradeResult {
  k: number;
  removed_pnl: number[];
  tsi_without: number;
  tsi_full: number;
  tsi_drop: number;
  fragile: boolean;
}

export interface TSIPnLCrossCheck {
  aligned: boolean;
  tsi_trend: string;
  pnl_trend: string;
  artifact_flag: boolean;
  note: string;
}

export interface RobustnessResult {
  raw_sharpe: number;
  dsr: number;
  dsr_inflation_pct: number;
  n_trials: number;
  overall_robust: boolean;
  worst_window: WorstWindowResult;
  fragile_trade: FragileTradeResult[];
  tsi_pnl_crosscheck: TSIPnLCrossCheck;
}

export interface ExitQualityFlag {
  trade_index: number;
  close_time: string;
  side: string;
  net_pnl: number;
  mfe: number;
  mae: number;
  mfe_capture_pct: number;
  issue: string;
}

export interface DriftAnalysisResult {
  avg_exit_quality: number;
  exits_flagged: number;
  total_exits: number;
  drift_estimate_pct: number;
  baseline_pct: number;
  above_baseline: boolean;
  worst_exits: ExitQualityFlag[];
}

export interface PortfolioResult {
  strategies: string[];
  correlation_matrix: Record<string, Record<string, number>>;
  avg_pairwise_rho: number;
  min_pairwise_rho: number;
  max_pairwise_rho: number;
  diversification_ratio: number;
  kill_zone_active: boolean;
  triggering_pairs: string[];
  n_strategies: number;
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
  robustness: RobustnessResult;
  drift: DriftAnalysisResult;
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
