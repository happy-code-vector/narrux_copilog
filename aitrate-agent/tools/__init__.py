"""Tool layer — pure Python implementations, no framework imports.

All tools follow the pattern:
- Accept a Pydantic request model
- Return a Pydantic response model
- Are async functions
- Log to structlog
"""

from tools.schemas import (
    Anomaly,
    AnomalyType,
    BacktestParseRequest,
    BacktestParseResponse,
    DriftAnalysisRequest,
    DriftAnalysisResponse,
    DriftMetric,
    FilterInfoRequest,
    FilterInfoResponse,
    ParameterClass,
    ParameterClassRequest,
    ParameterClassResponse,
    ParameterRecommendationRequest,
    ParameterRecommendationResponse,
    StrategySpecRequest,
    StrategySpecResponse,
    TradeDBQueryRequest,
    TradeDBQueryResponse,
    TradeDirection,
    TradeRecord,
    TradeSource,
    TradeSummary,
    TSIGrade,
    TSIScoreComponent,
    TSIScoreRequest,
    TSIScoreResponse,
)

__all__ = [
    "Anomaly",
    "AnomalyType",
    "BacktestParseRequest",
    "BacktestParseResponse",
    "DriftAnalysisRequest",
    "DriftAnalysisResponse",
    "DriftMetric",
    "FilterInfoRequest",
    "FilterInfoResponse",
    "ParameterClass",
    "ParameterClassRequest",
    "ParameterClassResponse",
    "ParameterRecommendationRequest",
    "ParameterRecommendationResponse",
    "StrategySpecRequest",
    "StrategySpecResponse",
    "TradeDBQueryRequest",
    "TradeDBQueryResponse",
    "TradeDirection",
    "TradeRecord",
    "TradeSource",
    "TSIGrade",
    "TSIScoreComponent",
    "TSIScoreRequest",
    "TSIScoreResponse",
    "TradeSummary",
]
