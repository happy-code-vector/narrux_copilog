"""Backtest xlsx parser — parses TradingView exports into normalized trade records.

NO framework imports. Pure Python + pandas + Pydantic.
"""

import structlog
import pandas as pd
from pathlib import Path

from tools.schemas import (
    Anomaly,
    AnomalyType,
    BacktestParseRequest,
    BacktestParseResponse,
    TradeDirection,
    TradeRecord,
    TradeSource,
)

logger = structlog.get_logger(__name__)


# ─── Column Mapping ──────────────────────────────────────────────────────────
# TradingView backtest export column names (may vary by export format)
# Adjust these mappings based on actual xlsx structure

COLUMN_MAP = {
    "time": ["Time", "Date", "Entry Time", "Entry Date"],
    "direction": ["Direction", "Side", "Type", "Trade Type"],
    "entry_price": ["Entry Price", "Open Price", "Entry"],
    "exit_price": ["Exit Price", "Close Price", "Exit"],
    "quantity": ["Qty", "Quantity", "Size", "Position Size"],
    "pnl": ["PnL", "Profit", "Net Profit", "Profit/Loss"],
    "pnl_pct": ["PnL %", "Profit %", "Return %", "Net %"],
    "exit_reason": ["Exit Reason", "Close Reason", "Exit Type"],
}


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find the first matching column name from candidates."""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _normalize_direction(value: str) -> TradeDirection:
    """Normalize direction string to TradeDirection enum."""
    value_lower = value.lower().strip()
    if value_lower in ("long", "buy", "l"):
        return TradeDirection.LONG
    elif value_lower in ("short", "sell", "s"):
        return TradeDirection.SHORT
    raise ValueError(f"Unknown trade direction: {value}")


def _detect_anomalies(
    trades: list[TradeRecord], net_profit_pct: float, max_drawdown_pct: float, profit_factor: float
) -> list[Anomaly]:
    """Detect anomalies in backtest results."""
    anomalies: list[Anomaly] = []

    # Profit Factor < 1.3
    if profit_factor < 1.3:
        anomalies.append(
            Anomaly(
                type=AnomalyType.LOW_PROFIT_FACTOR,
                severity="warning" if profit_factor >= 1.0 else "critical",
                value=profit_factor,
                threshold=1.3,
                description=f"Profit factor {profit_factor:.2f} is below 1.3 threshold",
            )
        )

    # Max Drawdown > 20%
    if max_drawdown_pct > 20.0:
        anomalies.append(
            Anomaly(
                type=AnomalyType.HIGH_MAX_DRAWDOWN,
                severity="critical",
                value=max_drawdown_pct,
                threshold=20.0,
                description=f"Max drawdown {max_drawdown_pct:.1f}% exceeds 20% threshold",
            )
        )

    # SL ratio > 40% (stop-loss exits as % of total)
    sl_exits = sum(1 for t in trades if t.exit_reason and "stop" in t.exit_reason.lower())
    if trades:
        sl_ratio = sl_exits / len(trades) * 100
        if sl_ratio > 40.0:
            anomalies.append(
                Anomaly(
                    type=AnomalyType.HIGH_SL_RATIO,
                    severity="warning",
                    value=sl_ratio,
                    threshold=40.0,
                    description=f"Stop-loss exit ratio {sl_ratio:.1f}% exceeds 40% threshold",
                )
            )

    # Net profit < -5%
    if net_profit_pct < -5.0:
        anomalies.append(
            Anomaly(
                type=AnomalyType.NEGATIVE_NET_PROFIT,
                severity="critical",
                value=net_profit_pct,
                threshold=-5.0,
                description=f"Net profit {net_profit_pct:.1f}% is below -5% threshold",
            )
        )

    return anomalies


async def parse_backtest(request: BacktestParseRequest) -> BacktestParseResponse:
    """Parse a TradingView backtest xlsx export.

    Args:
        request: Parse request with file path, strategy ID, and asset.

    Returns:
        Parsed backtest data with trade records and anomaly detection.

    Raises:
        FileNotFoundError: If xlsx file doesn't exist.
        ValueError: If xlsx format is invalid.
    """
    logger.info(
        "parsing_backtest",
        file_path=request.file_path,
        strategy_id=request.strategy_id,
        asset=request.asset,
    )

    file_path = Path(request.file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Backtest file not found: {request.file_path}")

    # Read xlsx
    df = pd.read_excel(file_path, engine="openpyxl")
    logger.info("backtest_loaded", rows=len(df), columns=list(df.columns))

    # Find columns
    time_col = _find_column(df, COLUMN_MAP["time"])
    direction_col = _find_column(df, COLUMN_MAP["direction"])
    entry_price_col = _find_column(df, COLUMN_MAP["entry_price"])
    exit_price_col = _find_column(df, COLUMN_MAP["exit_price"])
    quantity_col = _find_column(df, COLUMN_MAP["quantity"])
    pnl_col = _find_column(df, COLUMN_MAP["pnl"])
    pnl_pct_col = _find_column(df, COLUMN_MAP["pnl_pct"])
    exit_reason_col = _find_column(df, COLUMN_MAP["exit_reason"])

    if not all([time_col, direction_col, entry_price_col]):
        raise ValueError(
            f"Required columns not found. Available: {list(df.columns)}. "
            f"Expected at least: Time/Date, Direction/Side, Entry Price"
        )

    # Parse trades
    trades: list[TradeRecord] = []
    for idx, row in df.iterrows():
        try:
            trade = TradeRecord(
                strategy_id=request.strategy_id,
                asset=request.asset,
                source=TradeSource.BACKTEST,
                entry_time=pd.to_datetime(row[time_col]),
                direction=_normalize_direction(str(row[direction_col])),
                entry_price=float(row[entry_price_col]),
                exit_price=float(row[exit_price_col]) if exit_price_col and pd.notna(row.get(exit_price_col)) else None,
                quantity=float(row[quantity_col]) if quantity_col and pd.notna(row.get(quantity_col)) else 1.0,
                pnl=float(row[pnl_col]) if pnl_col and pd.notna(row.get(pnl_col)) else None,
                pnl_pct=float(row[pnl_pct_col]) if pnl_pct_col and pd.notna(row.get(pnl_pct_col)) else None,
                exit_reason=str(row[exit_reason_col]) if exit_reason_col and pd.notna(row.get(exit_reason_col)) else None,
            )
            trades.append(trade)
        except Exception as e:
            logger.warning("trade_parse_error", row=idx, error=str(e))
            continue

    if not trades:
        raise ValueError("No valid trades found in backtest file")

    # Calculate summary statistics
    winning_trades = [t for t in trades if t.pnl and t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl and t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades if t.pnl)
    total_pnl_pct = sum(t.pnl_pct for t in trades if t.pnl_pct)
    gross_wins = sum(t.pnl for t in winning_trades if t.pnl)
    gross_losses = abs(sum(t.pnl for t in losing_trades if t.pnl))

    win_rate = len(winning_trades) / len(trades) if trades else 0.0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    # Calculate max drawdown (simplified — peak-to-trough)
    cumulative_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        if t.pnl:
            cumulative_pnl += t.pnl
            peak = max(peak, cumulative_pnl)
            dd = (peak - cumulative_pnl) / (peak if peak > 0 else 1) * 100
            max_dd = max(max_dd, dd)

    # Detect anomalies
    anomalies = _detect_anomalies(trades, total_pnl_pct, max_dd, profit_factor)

    logger.info(
        "backtest_parsed",
        total_trades=len(trades),
        win_rate=f"{win_rate:.2%}",
        profit_factor=f"{profit_factor:.2f}",
        anomalies=len(anomalies),
    )

    return BacktestParseResponse(
        strategy_id=request.strategy_id,
        asset=request.asset,
        total_trades=len(trades),
        win_rate=win_rate,
        net_profit=total_pnl,
        net_profit_pct=total_pnl_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        trades=trades,
        anomalies=anomalies,
        citation=f"Backtest export: {file_path.name}",
    )
