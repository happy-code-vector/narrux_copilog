"""SQLAlchemy models for aiTrate Agent.

Tables:
- audit_log: Append-only log of every agent output with rationale
- conversations: Chat conversation state
- messages: Individual messages within conversations
- knowledge_base_chunks: pgvector-powered KB storage
"""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─── Audit Log ───────────────────────────────────────────────────────────────


class AuditLog(Base):
    """Append-only log of every agent output. Never update, never delete."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    function_id: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # e.g., "F-01", "F-02"
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tools_called: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_function_id", "function_id"),
    )


# ─── Conversations ───────────────────────────────────────────────────────────


class Conversation(Base):
    """Chat conversation state. Persists across sessions."""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    """Individual message within a conversation."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        Enum("user", "assistant", "system", name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tools_called: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ─── Knowledge Base Chunks ───────────────────────────────────────────────────


class KnowledgeBaseChunk(Base):
    """Document chunk stored in pgvector for similarity search."""

    __tablename__ = "knowledge_base_chunks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Document metadata
    doc_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # Unique document identifier
    doc_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "1.0", "v14"
    doc_type: Mapped[str] = mapped_column(
        Enum(
            "strategy_spec",
            "governance_doc",
            "pine_source",
            "parameter_class",
            "filter_glossary",
            "tsi_spec",
            "other",
            name="doc_type",
        ),
        nullable=False,
    )
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Embedding (pgvector)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)

    # Ownership and versioning
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )  # Points to the chunk this replaces

    # Citation handle — what the agent cites
    citation_handle: Mapped[str] = mapped_column(
        String(500), nullable=False
    )  # e.g., "Master Long v14, §3.2, F19"

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_kb_chunks_doc_id", "doc_id"),
        Index("ix_kb_chunks_doc_type", "doc_type"),
        Index("ix_kb_chunks_is_active", "is_active"),
        # HNSW index for fast approximate nearest neighbor search
        # Index("ix_kb_chunks_embedding", "embedding", postgresql_using="hnsw"),
    )


# ─── Trade Records (read-only reference) ─────────────────────────────────────


class TradeRecord(Base):
    """Unified trade record — backtest and live trades.

    This table is populated by Team A's ETL pipeline.
    The agent only reads from it (read-only in v1).
    """

    __tablename__ = "trade_records"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        Enum("backtest", "live", name="trade_source"), nullable=False
    )
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    direction: Mapped[str] = mapped_column(
        Enum("long", "short", name="trade_direction"), nullable=False
    )
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Entry/exit details
    entry_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filters_fired: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Parameters used
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_trade_records_strategy_id", "strategy_id"),
        Index("ix_trade_records_entry_time", "entry_time"),
        Index("ix_trade_records_source", "source"),
    )
