-- NARRUX aiTrate Co-Pilot — Database Schema
-- PostgreSQL 16 + pgvector

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── Knowledge Base Documents ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kb_documents (
    doc_id TEXT PRIMARY KEY,
    doc_version VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    scope VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    volume VARCHAR(50),
    module_id VARCHAR(50),
    owner VARCHAR(255) NOT NULL DEFAULT 'NARRUX',
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    supersedes TEXT REFERENCES kb_documents(doc_id),
    deprecated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Knowledge Base Chunks (vector store) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES kb_documents(doc_id) ON DELETE CASCADE,
    doc_version VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    embedding VECTOR(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for cosine similarity search
CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding
    ON kb_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN index for JSONB metadata filtering
CREATE INDEX IF NOT EXISTS ix_kb_chunks_metadata
    ON kb_chunks USING gin (metadata);

-- B-tree index on doc_id for FK lookups
CREATE INDEX IF NOT EXISTS ix_kb_chunks_doc_id
    ON kb_chunks (doc_id);

-- ─── Audit Log (APPEND-ONLY — critical) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    entry_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    response_id UUID,
    user_id VARCHAR(255),
    function_id VARCHAR(20),
    prompt_template_version VARCHAR(50),
    system_prompt_hash VARCHAR(64),
    user_message TEXT,
    retrieval_query TEXT,
    retrieval_results JSONB DEFAULT '[]',
    rerank_scores JSONB DEFAULT '[]',
    llm_model VARCHAR(100),
    llm_input_tokens INTEGER DEFAULT 0,
    llm_output_tokens INTEGER DEFAULT 0,
    llm_cost_usd NUMERIC(10,6) DEFAULT 0,
    raw_llm_response TEXT,
    parsed_response JSONB DEFAULT '{}',
    validator_log JSONB DEFAULT '{}',
    duration_ms INTEGER DEFAULT 0,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- CRITICAL: Deny UPDATE and DELETE on audit_log at the database level
CREATE OR REPLACE RULE audit_log_no_update AS
    ON UPDATE TO audit_log DO INSTEAD NOTHING;

CREATE OR REPLACE RULE audit_log_no_delete AS
    ON DELETE TO audit_log DO INSTEAD NOTHING;

-- Indexes for audit_log
CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp ON audit_log (timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_function_id ON audit_log (function_id);

-- ─── Trade Records ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trade_records (
    trade_id UUID PRIMARY KEY,
    strategy_id VARCHAR(100) NOT NULL,
    asset VARCHAR(20) NOT NULL,
    timeframe VARCHAR(20),
    source TEXT NOT NULL CHECK (source IN ('backtest', 'live')),
    execution_mode TEXT CHECK (execution_mode IN ('CLOSED', 'INTRABAR')),
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    entry_price NUMERIC(18,8) NOT NULL,
    exit_price NUMERIC(18,8),
    size NUMERIC(18,8),
    pnl NUMERIC(18,8),
    pnl_pct NUMERIC(10,6),
    mae NUMERIC(10,6) DEFAULT 0,
    mfe NUMERIC(10,6) DEFAULT 0,
    entry_method VARCHAR(100),
    exit_reason VARCHAR(200) DEFAULT '',
    filters_fired TEXT[] DEFAULT '{}',
    regime_label VARCHAR(50),
    params_hash VARCHAR(64),
    capital_basis NUMERIC(18,8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_trade_records_strategy_asset
    ON trade_records (strategy_id, asset, source);
CREATE INDEX IF NOT EXISTS ix_trade_records_entry_time
    ON trade_records (entry_time DESC);

-- ─── TSI Scores ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tsi_scores (
    score_id UUID PRIMARY KEY,
    strategy_id VARCHAR(100) NOT NULL,
    asset VARCHAR(20) NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    components JSONB DEFAULT '{}',
    weighted_score NUMERIC(6,2),
    grade TEXT NOT NULL CHECK (grade IN ('S', 'A', 'B', 'C', 'D')),
    leverage_cap NUMERIC(4,1),
    dq_triggers TEXT[] DEFAULT '{}',
    computed_from_raw BOOLEAN DEFAULT FALSE,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tsi_scores_strategy_asset
    ON tsi_scores (strategy_id, asset, computed_at DESC);
