"""Pydantic contracts for all tool inputs and outputs.

NO pydantic_ai imports. NO fastapi imports. Pure pydantic v2 + stdlib only.
These schemas are the contract between the agent and its tools.
"""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────


class ParameterClass(str, Enum):
    """Parameter governance classes.

    A = Set & Forget: stable 12+ months, never propose on single-backtest evidence.
    B = Quarterly drift: require ≥3 backtests before proposing change.
    C = Regime-coupled: ALL volume-based, always flag as non-stationary.
    """

    A = "A"
    B = "B"
    C = "C"


class TSIGrade(str, Enum):
    """TSI grade → leverage cap (fixed, non-negotiable).

    S → 3.0x, A → 2.0x, B → 1.5x, C → 1.0x, D → 0x
    """

    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    abstain = "abstain"


class FunctionID(str, Enum):
    F01 = "F-01"
    F02 = "F-02"
    F03 = "F-03"
    F04 = "F-04"
    F05 = "F-05"


class AlertFormat(str, Enum):
    alpha_json = "alpha_json"
    sentinel_csv = "sentinel_csv"


class DocumentScope(str, Enum):
    governance = "governance"
    strategy = "strategy"
    filter_glossary = "filter_glossary"
    parameter_master = "parameter_master"
    process = "process"
    report_template = "report_template"
    playbook = "playbook"


# ─── Knowledge Base ──────────────────────────────────────────────────────────


class KBDocument(BaseModel):
    """Knowledge base document metadata."""

    doc_id: str
    doc_version: str
    title: str
    scope: DocumentScope
    strategy: str | None = None
    volume: str | None = None
    module_id: str | None = None
    owner: str = "NARRUX"
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    supersedes: str | None = None
    deprecated: bool = False

    @field_validator("doc_id")
    @classmethod
    def validate_doc_id(cls, v: str) -> str:
        """Ensure doc_id is snake_case."""
        if " " in v:
            raise ValueError("doc_id must be snake_case (no spaces)")
        return v


class KBChunk(BaseModel):
    """Knowledge base chunk with optional embedding."""

    chunk_id: str
    doc_id: str
    doc_version: str
    content: str
    token_count: int
    embedding: list[float] | None = None
    metadata: dict = Field(default_factory=dict)


# ─── Citations ───────────────────────────────────────────────────────────────


class Citation(BaseModel):
    """A validated citation pointing to a specific KB chunk."""

    doc_id: str
    doc_version: str
    chunk_id: str
    source_type: Literal["spec", "pine", "playbook", "filter_glossary", "param_master", "handbook"]
    citation_handle: str
    relevance_score: float
    excerpt: str = Field(max_length=300)


# ─── Trade Records ───────────────────────────────────────────────────────────


class TradeRecord(BaseModel):
    """Normalized trade record from backtest or live data.

    pnl_pct is calculated against NARRUX capital basis (order_size × 1.10),
    NOT TradingView initial_capital.
    """

    trade_id: UUID = Field(default_factory=uuid4)
    strategy_id: str
    asset: str
    timeframe: str
    source: Literal["backtest", "live"]
    execution_mode: Literal["CLOSED", "INTRABAR"]
    side: Literal["long", "short"]
    entry_time: datetime
    exit_time: datetime | None = None
    entry_price: float
    exit_price: float | None = None
    size: float
    pnl: float | None = None
    pnl_pct: float | None = None
    mae: float = 0.0
    mfe: float = 0.0
    entry_method: str | None = None
    exit_reason: str = ""
    filters_fired: list[str] = Field(default_factory=list)
    regime_label: str | None = None
    params_hash: str | None = None
    capital_basis: float | None = None


class BacktestSummary(BaseModel):
    """Summary statistics from a backtest."""

    strategy_id: str
    asset: str
    timeframe: str
    period_start: datetime
    period_end: datetime
    total_trades: int
    win_rate: float
    profit_factor: float
    net_pnl: float
    net_pnl_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    stop_loss_count: int
    stop_loss_ratio: float  # flag if >0.40
    capital_basis: float
    calc_on_order_fills: bool  # MUST be false
    process_orders_on_close: bool
    execution_mode: str

    @field_validator("stop_loss_ratio")
    @classmethod
    def flag_high_sl_ratio(cls, v: float) -> float:
        if v > 0.40:
            # Flagged — validator will raise in output_validator.py
            pass
        return v


class RawTrade(BaseModel):
    """One row from the xlsx trade log (Type='Exit' rows only).

    Used by backtest_parser.py and tsi_engine.py.
    """

    open_time: datetime
    close_time: datetime
    side: Literal["long", "short"]
    net_pnl: float
    net_pnl_pct: float  # against capital_basis — NOT TV initial_capital
    entry_price: float | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    partial_count: int = 1


# ─── TSI ─────────────────────────────────────────────────────────────────────


class PeriodMetrics(BaseModel):
    """Per-period metrics from TSI v2.0 CA §6. One instance per time window."""

    period: str  # "12mo" | "6mo" | "3mo" | "1mo" | "7d"
    n: int  # logical trade count (post-aggregation, not partial rows)
    win_rate: float  # logical-trade basis
    profit_factor: float
    mdd_pct: float  # continuous equity model (never reset per window)
    sharpe_ann: float  # annualised using sqrt(tpy), NOT sqrt(252)
    sortino_ann: float
    trades_per_day: float
    composite: float  # 0–100 period composite score
    insufficient_sample: bool  # True when n < 5; excluded from σ


class TSIResult(BaseModel):
    """TSI v2.0 CA scoring result — complete output per §1.2."""

    strategy_id: str
    asset: str
    period_start: datetime
    period_end: datetime
    capital_basis: float

    # Component sub-scores (for F-03 presentation)
    components: dict[str, float]  # {"sharpe": 0.73, "pf": 0.91, ...} — period-weighted
    weighted_composite: float  # pre-stability score (debugging + cross-check)
    stability: float  # 0–100
    sigma_periods: float  # stdev across eligible period composites
    trend_drop: float
    catastrophic_floor: bool  # True = recent regime failure detected
    final_tsi: float  # = weighted_composite × (0.5 + 0.5 × stability/100)
    grade: TSIGrade  # derived from final_tsi via tier thresholds
    leverage_cap: float  # S=3.0, A=2.0, B=1.5, C=1.0, D=0.0
    weight_cap_pct: float | None  # S=None, A=15, B=8, C=3-6, D=0
    dq_triggers: list[str]  # ["PF12<1.3", "Sharpe1<0", "Net1<-5%", "MDD>20%"]
    period_metrics: list[PeriodMetrics]  # one per window, always 5 entries
    diagnostics: dict  # cat floor source, tier floor, relief applied
    computed_from_raw_csv: bool = False
    reconstruction_tolerance: float | None = None  # ±2–3 if not from raw CSV

    def leverage_cap_for_grade(self) -> float:
        """Return the correct leverage cap for the grade."""
        caps = {"S": 3.0, "A": 2.0, "B": 1.5, "C": 1.0, "D": 0.0}
        return caps.get(self.grade.value, 0.0)


# ─── Robustness Analysis ────────────────────────────────────────────────────


class WorstWindowResult(BaseModel):
    """Worst-window robustness analysis."""

    window_size: int = 30
    worst_composite: float
    worst_period_start: datetime
    worst_period_end: datetime
    full_sample_composite: float
    drop_points: float  # how much worse than full sample
    n_windows_tested: int


class FragileTradeResult(BaseModel):
    """Leave-K-out fragile trade dependency analysis."""

    k: int
    removed_pnl: list[float]
    tsi_without: float
    tsi_full: float
    tsi_drop: float
    fragile: bool  # True if drop > 10 points


class TSIPnLCrossCheck(BaseModel):
    """TSI vs P&L trend alignment check."""

    aligned: bool
    tsi_trend: str  # "rising" | "falling" | "flat"
    pnl_trend: str  # "rising" | "falling" | "flat"
    artifact_flag: bool  # True if TSI rising but P&L flat/falling
    note: str


class RobustnessResult(BaseModel):
    """Complete robustness analysis output."""

    raw_sharpe: float
    dsr: float
    dsr_inflation_pct: float
    n_trials: int
    worst_window: WorstWindowResult
    fragile_trade: list[FragileTradeResult]
    tsi_pnl_crosscheck: TSIPnLCrossCheck
    overall_robust: bool  # True if no critical flags


# ─── Drift Analysis ─────────────────────────────────────────────────────────


class ExitQualityFlag(BaseModel):
    """A single exit flagged for poor quality."""

    trade_index: int
    close_time: datetime
    side: str
    net_pnl: float
    mfe: float  # max favorable excursion
    mae: float  # max adverse excursion
    mfe_capture_pct: float  # how much of MFE was captured
    issue: str  # "low_capture" | "reversal" | "wide_stop"


class DriftAnalysisResult(BaseModel):
    """Exit quality and drift estimation from backtest data."""

    avg_exit_quality: float  # avg MFE capture % across all exits
    worst_exits: list[ExitQualityFlag]
    exits_flagged: int
    total_exits: int
    drift_estimate_pct: float
    baseline_pct: float = 0.19  # Bar Magnifier baseline
    above_baseline: bool


# ─── Portfolio Metrics ───────────────────────────────────────────────────────


class PortfolioResult(BaseModel):
    """Portfolio-level correlation and diversification analysis."""

    strategies: list[str]
    correlation_matrix: dict[str, dict[str, float]]  # {sym_a: {sym_b: rho}}
    avg_pairwise_rho: float
    min_pairwise_rho: float
    max_pairwise_rho: float
    diversification_ratio: float  # 1 / (1 + avg_rho)
    kill_zone_active: bool
    triggering_pairs: list[str]  # pairs with rho >= 0.30 AND tail >= 20%
    n_strategies: int


# ─── Recommendations ─────────────────────────────────────────────────────────


class Recommendation(BaseModel):
    """Parameter adjustment recommendation."""

    parameter_name: str
    parameter_class: ParameterClass
    current_value: float
    recommended_value: float
    within_bounds: bool  # MUST be True or rejected
    bounds: tuple[float, float] | None = None
    evidence_backtest_count: int = 0
    regime_label: str | None = None
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    expected_impact: str
    risk_notes: str
    governance_check_passed: bool = False


# ─── Drift Monitoring ────────────────────────────────────────────────────────


class DriftStatus(str, Enum):
    stable = "stable"
    watch = "watch"
    breach = "breach"


class DriftReport(BaseModel):
    """Drift monitoring report comparing live vs backtest performance."""

    strategy_id: str
    asset: str
    window_trades: int
    avg_exit_slippage_pct: float
    rolling_drift_pct: float
    drift_status: DriftStatus
    breach_threshold_pct: float = 0.4
    stop_loss_ratio: float
    tsi_grade_current: TSIGrade | None = None
    tsi_grade_previous: TSIGrade | None = None
    grade_transition: str | None = None
    flags: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    authority_role: Literal["veto", "override", "advisory"] = "advisory"


# ─── Agent Response ──────────────────────────────────────────────────────────


class AgentResponse(BaseModel):
    """Structured response from the agent."""

    response_id: UUID = Field(default_factory=uuid4)
    function_id: FunctionID
    content: str
    citations: list[Citation] = Field(default_factory=list)
    structured_output: dict | None = None
    confidence: ConfidenceLevel
    validator_results: dict = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Webhook Alerts ──────────────────────────────────────────────────────────


class AlphaWebhookAlert(BaseModel):
    """Alpha v15.9.1 webhook alert (JSON format)."""

    symbol: str
    side: str
    action: str
    qty: float
    price: float | None = None
    position_size: float | None = None
    htf_bias: str | None = None
    reason: str | None = None
    level: float | None = None


class SentinelWebhookAlert(BaseModel):
    """Sentinel v1.9 webhook alert (CSV format)."""

    raw: str
    bot_name: str
    side: str
    action: str
    qty: float | None = None
    reason: str | None = None
    level: float | None = None

    @classmethod
    def from_csv(cls, payload: str) -> "SentinelWebhookAlert":
        """Parse CSV positional string: botName,side,action[,key=value...]

        Example: NARRUX_SENTINEL,long,entry,qty=1.5
        """
        parts = payload.strip().split(",")
        if len(parts) < 3:
            raise ValueError(f"Sentinel payload needs ≥3 fields, got {len(parts)}")

        bot_name = parts[0]
        side = parts[1]
        action = parts[2]

        kwargs: dict = {"raw": payload, "bot_name": bot_name, "side": side, "action": action}

        for part in parts[3:]:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                if key == "qty":
                    kwargs["qty"] = float(value)
                elif key == "reason":
                    kwargs["reason"] = value
                elif key == "level":
                    kwargs["level"] = float(value)

        return cls(**kwargs)


def parse_webhook_alert(payload: str) -> AlphaWebhookAlert | SentinelWebhookAlert:
    """Parse a webhook alert — branches on payload shape.

    This routing MUST be in code, not just documentation.
    Alpha v15.9.1: JSON object
    Sentinel v1.9: CSV positional string
    """
    stripped = payload.strip()
    if stripped.startswith("{"):
        import json

        data = json.loads(stripped)
        return AlphaWebhookAlert(**data)
    else:
        return SentinelWebhookAlert.from_csv(stripped)


# ─── Audit ───────────────────────────────────────────────────────────────────


class AuditEntry(BaseModel):
    """Audit log entry — one per agent response."""

    entry_id: UUID = Field(default_factory=uuid4)
    response_id: UUID
    user_id: str
    function_id: str
    prompt_template_version: str
    system_prompt_hash: str
    user_message: str
    retrieval_query: str
    retrieval_results: list[Citation] = Field(default_factory=list)
    rerank_scores: list[float] = Field(default_factory=list)
    llm_model: str
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_usd: float = 0.0
    raw_llm_response: str
    parsed_response: AgentResponse
    validator_log: dict = Field(default_factory=dict)
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
