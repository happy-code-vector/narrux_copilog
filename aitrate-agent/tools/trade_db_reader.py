"""Trade DB reader — read-only queries against the trade_records table.

NO pydantic_ai imports. NO writes. Pure Python + psycopg.
Used by F-05 (drift monitor) to read live trades from Postgres.

NOTE: This connects to the FULL-STACK TEAM's PostgreSQL database,
NOT the Qdrant vector store. The connection string comes from the
full-stack team's config. TODO: integrate with their DB when available.
"""

from __future__ import annotations

from typing import Literal

import structlog

from tools.schemas import TradeRecord

logger = structlog.get_logger(__name__)

# TODO: Replace with the full-stack team's PostgreSQL connection.
# This module needs a psycopg AsyncConnectionPool pointing at their
# trade_records table. For now, all functions return empty results.
_TRADE_DB_AVAILABLE = False


async def get_recent_trades(
    strategy_id: str,
    asset: str,
    source: Literal["backtest", "live"] = "live",
    limit: int = 100,
) -> list[TradeRecord]:
    """Return most recent N trades for a strategy+asset combination."""
    logger.info("get_recent_trades", strategy_id=strategy_id, asset=asset, source=source, limit=limit)

    if not _TRADE_DB_AVAILABLE:
        logger.warning("trade_db_not_available", detail="Full-stack team's DB not connected yet")
        return []

    # TODO: Implement when full-stack team's DB is available
    # async with get_trade_db_conn() as conn:
    #     cur = await conn.execute(...)
    #     rows = await cur.fetchall()
    #     return [TradeRecord(...) for row in rows]

    return []


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
