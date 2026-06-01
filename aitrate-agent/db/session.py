"""Database connection management — asyncpg + pgvector.

Simplified: no ORM, no migrations, direct PostgreSQL connection.
"""

import asyncpg
from pgvector.asyncpg import register_vector

from config.settings import get_settings

settings = get_settings()

# Connection pool (initialized on startup)
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the asyncpg connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=5,
            max_size=20,
        )
    return _pool


async def get_connection() -> asyncpg.Connection:
    """Get a connection from the pool."""
    pool = await get_pool()
    return await pool.acquire()


async def release_connection(conn: asyncpg.Connection):
    """Release a connection back to the pool."""
    pool = await get_pool()
    await pool.release(conn)


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ─── Table Creation ──────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Audit log — append-only, never update, never delete
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    function_id VARCHAR(20) NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    citations JSONB,
    tools_called JSONB,
    model_used VARCHAR(100) NOT NULL,
    latency_ms INTEGER NOT NULL,
    token_usage JSONB,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_log_function_id ON audit_log (function_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id);

-- Knowledge base chunks — pgvector-powered
CREATE TABLE IF NOT EXISTS knowledge_base_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    doc_id VARCHAR(255) NOT NULL,
    doc_version VARCHAR(50) NOT NULL,
    doc_type VARCHAR(50) NOT NULL,
    source_file VARCHAR(500) NOT NULL,
    section VARCHAR(500),
    page_number INTEGER,
    line_number INTEGER,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding vector(1024),
    owner VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    supersedes_id UUID,
    citation_handle VARCHAR(500) NOT NULL,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS ix_kb_chunks_doc_id ON knowledge_base_chunks (doc_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_doc_type ON knowledge_base_chunks (doc_type);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_is_active ON knowledge_base_chunks (is_active);

-- Trade records (read-only reference — populated by Team A's ETL)
CREATE TABLE IF NOT EXISTS trade_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id VARCHAR(100) NOT NULL,
    asset VARCHAR(20) NOT NULL,
    source VARCHAR(20) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    direction VARCHAR(10) NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION,
    quantity DOUBLE PRECISION NOT NULL,
    pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,
    fees DOUBLE PRECISION DEFAULT 0.0,
    slippage_pct DOUBLE PRECISION,
    entry_method VARCHAR(100),
    exit_reason VARCHAR(100),
    filters_fired JSONB,
    parameters JSONB,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS ix_trade_records_strategy_id ON trade_records (strategy_id);
CREATE INDEX IF NOT EXISTS ix_trade_records_entry_time ON trade_records (entry_time);
CREATE INDEX IF NOT EXISTS ix_trade_records_source ON trade_records (source);
"""


async def init_db():
    """Initialize database — create tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        # Register vector type for pgvector
        await register_vector(conn)
    print("Database initialized successfully")
