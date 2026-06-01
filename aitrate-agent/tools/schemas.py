"""Pydantic models for all tool inputs and outputs.

These schemas are the contract between the agent and its tools.
They are framework-agnostic — any agent framework can use them.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────


class TSIGrade(str, Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ParameterClass(str, Enum):
    A = "A"  # Set & forget — stable 12+ months
    B = "B"  # Quarterly drift — AI-tune within bounds
    C = "C"  # Regime-coupled — unstable, AI-toggle on/off


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeSource(str, Enum):
    BACKTEST = "backtest"
    LIVE = "live"


class AnomalyType(str, Enum):
    LOW_PROFIT_FACTOR = "PF < 1.3"
    HIGH_MAX_DRAWDOWN = "MDD > 20%"
    HIGH_SL_RATIO = "SL ratio > 40%"
    NEGATIVE_SHARPE = "Sharpe < 0"
    NEGATIVE_NET_PROFIT = "Net profit < -5%"
    FREQUENCY_COLLAPSE = "FREQ_COLLAPSE"
    ELEVATED_LOSS = "ELEV_LOSS"
    UNPROFITABLE = "UNPROF"


# ─── Knowledge Base Tools ────────────────────────────────────────────────────


class FilterInfoRequest(BaseModel):
    """Request for filter information lookup."""

    filter_id: str = Field(
        ..., description="Filter identifier, e.g., 'F19', 'F26'", examples=["F19"]
    )
    strategy: str | None = Field(
        None,
        description="Strategy name, e.g., 'Master Long v14'",
        examples=["Master Long v14"],
    )


class FilterInfoResponse(BaseModel):
    """Response containing filter information."""

    filter_id: str
    name: str
    description: str
    strategy: str
    class_: ParameterClass | None = Field(None, alias="class")
    citation: str = Field(..., description="Source citation handle")
    source_doc: str
    line_number: int | None = None


class ParameterClassRequest(BaseModel):
    """Request for parameter class lookup."""

    parameter_name: str = Field(
        ..., description="Parameter name", examples=["stop_loss_pct"]
    )
    strategy: str | None = None


class ParameterClassResponse(BaseModel):
    """Response containing parameter class information."""

    parameter_name: str
    class_: ParameterClass = Field(..., alias="class")
    baseline: float | None = None
    range_min: float | None = None
    range_max: float | None = None
    rationale: str
    citation: str
    source_doc: str


class StrategySpecRequest(BaseModel):
    """Request for strategy specification lookup."""

    strategy_name: str = Field(
        ..., description="Strategy name", examples=["Master Long v14"]
    )
    aspect: str | None = Field(
        None,
        description="Specific aspect to explain, e.g., 'exit logic', 'entry filters'",
    )


class StrategySpecResponse(BaseModel):
    """Response containing strategy specification."""

    strategy_name: str
    architecture: str  # e.g., "Single-path AND-gate"
    description: str
    filters: list[str]
    exit_mechanisms: list[str]
    parameters_count: int
    citation: str
    source_doc: str


# ─── Backtest Parser Tools ───────────────────────────────────────────────────


class TradeRecord(BaseModel):
    """Normalized trade record from backtest or live data."""

    strategy_id: str
    asset: str
    source: TradeSource
    entry_time: datetime
    exit_time: datetime | None = None
    direction: TradeDirection
    entry_price: float
    exit_price: float | None = None
    quantity: float
    pnl: float | None = None
    pnl_pct: float | None = None
    fees: float = 0.0
    slippage_pct: float | None = None
    entry_method: str | None = None
    exit_reason: str | None = None
    filters_fired: dict | None = None
    parameters: dict | None = None


class BacktestParseRequest(BaseModel):
    """Request to parse a backtest xlsx file."""

    file_path: str = Field(..., description="Path to xlsx file")
    strategy_id: str = Field(..., description="Strategy identifier")
    asset: str = Field(..., description="Asset ticker, e.g., 'TSLA', 'XRPUSDT'")


class BacktestParseResponse(BaseModel):
    """Response from backtest parsing."""

    strategy_id: str
    asset: str
    total_trades: int
    win_rate: float
    net_profit: float
    net_profit_pct: float
    profit_factor: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float
    avg_trade_duration_hours: float | None = None
    trades: list[TradeRecord]
    anomalies: list["Anomaly"]
    citation: str


class Anomaly(BaseModel):
    """Detected anomaly in backtest data."""

    type: AnomalyType
    severity: str = Field(..., description="'warning' or 'critical'")
    value: float
    threshold: float
    description: str
    affected_trades: list[int] | None = None  # Trade indices


# ─── TSI Engine Tools ────────────────────────────────────────────────────────


class TSIScoreRequest(BaseModel):
    """Request for TSI v2.0 CA scoring."""

    trades: list[TradeRecord]
    strategy_id: str
    asset: str
    context_adjusted: bool = Field(
        default=False,
        description="Use v2.0 CA (context-adjusted) scoring",
    )


class TSIScoreComponent(BaseModel):
    """Individual TSI score component."""

    name: str
    weight: float
    raw_value: float
    weighted_score: float
    grade_contribution: str


class TSIScoreResponse(BaseModel):
    """Response from TSI scoring."""

    strategy_id: str
    asset: str
    overall_score: float
    grade: TSIGrade
    components: list[TSIScoreComponent]
    dq_triggers: list[str] = Field(
        default_factory=list,
        description="Data Quality triggers fired",
    )
    citation: str


# ─── Trade DB Reader Tools ───────────────────────────────────────────────────


class TradeDBQueryRequest(BaseModel):
    """Request to query the trade database."""

    strategy_id: str | None = None
    asset: str | None = None
    source: TradeSource | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = Field(default=100, le=1000)


class TradeDBQueryResponse(BaseModel):
    """Response from trade database query."""

    trades: list[TradeRecord]
    total_count: int
    summary: "TradeSummary"


class TradeSummary(BaseModel):
    """Summary statistics for a set of trades."""

    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    max_win: float
    max_loss: float
    profit_factor: float


# ─── Drift Detection Tools ───────────────────────────────────────────────────


class DriftAnalysisRequest(BaseModel):
    """Request for backtest-vs-live drift analysis."""

    strategy_id: str
    asset: str
    backtest_start: datetime
    backtest_end: datetime
    live_start: datetime
    live_end: datetime
    baseline_slippage_pct: float = Field(
        default=0.19,
        description="Baseline slippage per exit (~0.19% from Bar Magnifier)",
    )


class DriftMetric(BaseModel):
    """Individual drift metric comparison."""

    metric_name: str
    backtest_value: float
    live_value: float
    delta: float
    delta_pct: float
    is_significant: bool
    threshold: float


class DriftAnalysisResponse(BaseModel):
    """Response from drift analysis."""

    strategy_id: str
    asset: str
    overall_drift_score: float
    is_drift_detected: bool
    metrics: list[DriftMetric]
    suspected_causes: list[str]
    recommendation: str
    citation: str


# ─── Recommendation Tools ────────────────────────────────────────────────────


class ParameterRecommendationRequest(BaseModel):
    """Request for parameter adjustment recommendation."""

    strategy_id: str
    asset: str
    parameter_name: str
    current_value: float
    context: str | None = Field(
        None, description="Additional context, e.g., 'regime changed to ranging'"
    )


class ParameterRecommendationResponse(BaseModel):
    """Response with parameter adjustment recommendation."""

    strategy_id: str
    parameter_name: str
    parameter_class: ParameterClass
    current_value: float
    recommended_value: float
    range_min: float
    range_max: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    risks: list[str]
    requires_approval: bool = True  # Always True in v1 (shadow mode)
    citation: str
