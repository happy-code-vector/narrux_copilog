"""Trade database reader — read-only queries against unified trade DB.

Uses asyncpg directly (no ORM).
"""

import structlog
import asyncpg

from tools.schemas import (
    TradeDBQueryRequest,
    TradeDBQueryResponse,
    TradeRecord,
    TradeSummary,
    TradeSource,
)

logger = structlog.get_logger(__name__)


def _row_to_schema(row: asyncpg.Record) -> TradeRecord:
    """Convert database row to Pydantic schema."""
    return TradeRecord(
        strategy_id=row["strategy_id"],
        asset=row["asset"],
        source=TradeSource(row["source"]),
        entry_time=row["entry_time"],
        exit_time=row["exit_time"],
        direction=row["direction"],
        entry_price=row["entry_price"],
        exit_price=row["exit_price"],
        quantity=row["quantity"],
        pnl=row["pnl"],
        pnl_pct=row["pnl_pct"],
        fees=row["fees"] or 0.0,
        slippage_pct=row["slippage_pct"],
        entry_method=row["entry_method"],
        exit_reason=row["exit_reason"],
        filters_fired=row["filters_fired"],
        parameters=row["parameters"],
    )


def _compute_summary(trades: list[TradeRecord]) -> TradeSummary:
    """Compute summary statistics for a list of trades."""
    if not trades:
        return TradeSummary(
            total_trades=0,
            win_count=0,
            loss_count=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_pnl=0.0,
            max_win=0.0,
            max_loss=0.0,
            profit_factor=0.0,
        )

    winning = [t for t in trades if t.pnl and t.pnl > 0]
    losing = [t for t in trades if t.pnl and t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades if t.pnl)
    gross_wins = sum(t.pnl for t in winning if t.pnl)
    gross_losses = abs(sum(t.pnl for t in losing if t.pnl))

    return TradeSummary(
        total_trades=len(trades),
        win_count=len(winning),
        loss_count=len(losing),
        win_rate=len(winning) / len(trades) if trades else 0.0,
        total_pnl=total_pnl,
        avg_pnl=total_pnl / len(trades) if trades else 0.0,
        max_win=max((t.pnl for t in winning if t.pnl), default=0.0),
        max_loss=min((t.pnl for t in losing if t.pnl), default=0.0),
        profit_factor=gross_wins / gross_losses if gross_losses > 0 else 0.0,
    )


async def query_trade_db(
    request: TradeDBQueryRequest,
    conn: asyncpg.Connection,
) -> TradeDBQueryResponse:
    """Query the trade database (read-only)."""
    logger.info(
        "querying_trade_db",
        strategy_id=request.strategy_id,
        asset=request.asset,
        source=request.source,
    )

    # Build query dynamically
    conditions = []
    params = []
    idx = 1

    if request.strategy_id:
        conditions.append(f"strategy_id = ${idx}")
        params.append(request.strategy_id)
        idx += 1
    if request.asset:
        conditions.append(f"asset = ${idx}")
        params.append(request.asset)
        idx += 1
    if request.source:
        conditions.append(f"source = ${idx}")
        params.append(request.source.value)
        idx += 1
    if request.start_date:
        conditions.append(f"entry_time >= ${idx}")
        params.append(request.start_date)
        idx += 1
    if request.end_date:
        conditions.append(f"entry_time <= ${idx}")
        params.append(request.end_date)
        idx += 1

    where_clause = " AND ".join(conditions) if conditions else "true"

    # Main query with limit
    sql = f"""
        SELECT * FROM trade_records
        WHERE {where_clause}
        ORDER BY entry_time DESC
        LIMIT ${idx}
    """
    params.append(request.limit)

    rows = await conn.fetch(sql, *params)
    trades = [_row_to_schema(row) for row in rows]

    # Count query
    count_sql = f"SELECT COUNT(*) as cnt FROM trade_records WHERE {where_clause}"
    count_row = await conn.fetchrow(count_sql, *params[:-1])  # Exclude limit param
    total_count = count_row["cnt"] if count_row else 0

    summary = _compute_summary(trades)

    logger.info(
        "trade_db_queried",
        returned=len(trades),
        total=total_count,
        win_rate=f"{summary.win_rate:.2%}",
    )

    return TradeDBQueryResponse(
        trades=trades,
        total_count=total_count,
        summary=summary,
    )
