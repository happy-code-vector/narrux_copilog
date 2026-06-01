"""Trade database reader — read-only queries against unified trade DB.

NO framework imports. Pure Python + SQLAlchemy + Pydantic.
"""

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TradeRecord as TradeRecordDB
from tools.schemas import (
    TradeDBQueryRequest,
    TradeDBQueryResponse,
    TradeRecord,
    TradeSummary,
    TradeSource,
)

logger = structlog.get_logger(__name__)


def _db_to_schema(trade: TradeRecordDB) -> TradeRecord:
    """Convert database model to Pydantic schema."""
    return TradeRecord(
        strategy_id=trade.strategy_id,
        asset=trade.asset,
        source=TradeSource(trade.source),
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        direction=trade.direction,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        quantity=trade.quantity,
        pnl=trade.pnl,
        pnl_pct=trade.pnl_pct,
        fees=trade.fees,
        slippage_pct=trade.slippage_pct,
        entry_method=trade.entry_method,
        exit_reason=trade.exit_reason,
        filters_fired=trade.filters_fired,
        parameters=trade.parameters,
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
    session: AsyncSession,
) -> TradeDBQueryResponse:
    """Query the trade database (read-only).

    Args:
        request: Query parameters.
        session: Async database session.

    Returns:
        Matching trades with summary statistics.
    """
    logger.info(
        "querying_trade_db",
        strategy_id=request.strategy_id,
        asset=request.asset,
        source=request.source,
    )

    # Build query
    query = select(TradeRecordDB)

    if request.strategy_id:
        query = query.where(TradeRecordDB.strategy_id == request.strategy_id)
    if request.asset:
        query = query.where(TradeRecordDB.asset == request.asset)
    if request.source:
        query = query.where(TradeRecordDB.source == request.source.value)
    if request.start_date:
        query = query.where(TradeRecordDB.entry_time >= request.start_date)
    if request.end_date:
        query = query.where(TradeRecordDB.entry_time <= request.end_date)

    query = query.order_by(TradeRecordDB.entry_time.desc()).limit(request.limit)

    # Execute
    result = await session.execute(query)
    db_trades = result.scalars().all()

    # Convert to schema
    trades = [_db_to_schema(t) for t in db_trades]
    summary = _compute_summary(trades)

    # Get total count (without limit)
    count_query = select(func.count(TradeRecordDB.id))
    if request.strategy_id:
        count_query = count_query.where(TradeRecordDB.strategy_id == request.strategy_id)
    if request.asset:
        count_query = count_query.where(TradeRecordDB.asset == request.asset)
    if request.source:
        count_query = count_query.where(TradeRecordDB.source == request.source.value)

    total_result = await session.execute(count_query)
    total_count = total_result.scalar() or 0

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
