"""Trade DB reader — read-only queries against the trade_records table.

NO pydantic_ai imports. NO writes. Pure Python + psycopg.
Used by F-05 (drift monitor) to read live trades from Postgres.
"""

from __future__ import annotations

from typing import Literal

import structlog

from retrieval.vector_store import get_conn
from tools.schemas import TradeRecord

logger = structlog.get_logger(__name__)


async def get_recent_trades(
    strategy_id: str,
    asset: str,
    source: Literal["backtest", "live"] = "live",
    limit: int = 100,
) -> list[TradeRecord]:
    """Return most recent N trades for a strategy+asset combination."""
    logger.info("get_recent_trades", strategy_id=strategy_id, asset=asset, source=source, limit=limit)

    async with get_conn() as conn:
        cur = await conn.execute(
            """
            SELECT trade_id, strategy_id, asset, timeframe, source, execution_mode,
                   side, entry_time, exit_time, entry_price, exit_price, size,
                   pnl, pnl_pct, mae, mfe, entry_method, exit_reason,
                   filters_fired, regime_label, params_hash, capital_basis
            FROM trade_records
            WHERE strategy_id = %s AND asset = %s AND source = %s
            ORDER BY entry_time DESC
            LIMIT %s
            """,
            (strategy_id, asset, source, limit),
        )
        rows = await cur.fetchall()

    trades = []
    for row in rows:
        trades.append(
            TradeRecord(
                trade_id=row["trade_id"],
                strategy_id=row["strategy_id"],
                asset=row["asset"],
                timeframe=row["timeframe"] or "",
                source=row["source"],
                execution_mode=row["execution_mode"] or "CLOSED",
                side=row["side"],
                entry_time=row["entry_time"],
                exit_time=row["exit_time"],
                entry_price=float(row["entry_price"]),
                exit_price=float(row["exit_price"]) if row["exit_price"] else None,
                size=float(row["size"]) if row["size"] else 0,
                pnl=float(row["pnl"]) if row["pnl"] else None,
                pnl_pct=float(row["pnl_pct"]) if row["pnl_pct"] else None,
                mae=float(row["mae"]) if row["mae"] else 0,
                mfe=float(row["mfe"]) if row["mfe"] else 0,
                entry_method=row["entry_method"],
                exit_reason=row["exit_reason"] or "",
                filters_fired=row["filters_fired"] or [],
                regime_label=row["regime_label"],
                params_hash=row["params_hash"],
                capital_basis=float(row["capital_basis"]) if row["capital_basis"] else None,
            )
        )

    return trades


async def get_rolling_window(
    strategy_id: str,
    asset: str,
    n_trades: int = 20,
    source: Literal["live"] = "live",
) -> list[TradeRecord]:
    """Return the last N live trades for drift analysis."""
    return await get_recent_trades(strategy_id, asset, source=source, limit=n_trades)


async def get_stop_loss_ratio(
    strategy_id: str,
    asset: str,
    n_trades: int = 20,
) -> float:
    """SL count / total trades for last N live trades. >0.40 = emergency brake."""
    trades = await get_recent_trades(strategy_id, asset, source="live", limit=n_trades)

    if not trades:
        return 0.0

    sl_count = sum(1 for t in trades if "stop loss" in t.exit_reason.lower())
    ratio = sl_count / len(trades)

    logger.info("stop_loss_ratio", strategy_id=strategy_id, asset=asset, ratio=ratio, trades=len(trades))
    return ratio
