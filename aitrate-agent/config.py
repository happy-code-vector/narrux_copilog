"""Application settings — loaded from environment variables via Pydantic Settings.

Single lru_cache get_settings() function. All env vars typed. Never hardcode secrets.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. Reads from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── Vector Store (Qdrant) ─────────────────────────────────
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant server URL (Docker mode)",
    )
    qdrant_path: str = Field(
        default="./qdrant_data",
        description="Path for Qdrant embedded storage (local dev fallback)",
    )
    qdrant_collection: str = Field(
        default="kb_chunks",
        description="Qdrant collection name for KB chunks",
    )
    qdrant_mode: str = Field(
        default="server",
        description="Qdrant mode: 'server' (Docker) or 'embedded' (local)",
    )

    # ─── Redis ──────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ─── LLM Provider ───────────────────────────────────────
    llm_provider: str = Field(
        default="gemini",
        description="LLM provider: 'gemini' or 'anthropic'",
    )

    # ─── Gemini (development) ────────────────────────────────
    google_api_key: str = Field(default="")
    gemini_model_primary: str = Field(
        default="gemini-2.5-flash",
        description="Primary Gemini model for F-01, F-02, F-04",
    )
    gemini_model_secondary: str = Field(
        default="gemini-2.5-flash",
        description="Secondary Gemini model for F-03, F-05",
    )

    # ─── Anthropic (production) ─────────────────────────────
    anthropic_api_key: str = Field(default="sk-ant-xxx")
    anthropic_model_primary: str = Field(
        default="claude-opus-4-7", description="Primary LLM for F-01, F-02, F-04"
    )
    anthropic_model_secondary: str = Field(
        default="claude-sonnet-4-6", description="Secondary LLM for F-03, F-05"
    )

    # ─── Embedding Model ─────────────────────────────────────
    embedding_provider: str = Field(
        default="gemini",
        description="Embedding provider: 'local', 'gemini', or 'voyage'",
    )
    embedding_model: str = Field(
        default="models/text-embedding-004",
        description="Embedding model name",
    )
    embedding_dims: int = Field(
        default=768,
        description="Embedding dimensions (must match model)",
    )

    # ─── Gemini (development) ────────────────────────────────
    google_api_key: str = Field(default="")

    # ─── Voyage AI (production) ──────────────────────────────
    voyage_api_key: str = Field(default="pa-xxx")
    voyage_embedding_model: str = Field(default="voyage-3-large")
    voyage_rerank_model: str = Field(default="rerank-2")

    # ─── Langfuse ───────────────────────────────────────────
    langfuse_host: str = Field(default="https://cloud.langfuse.com")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")

    # ─── Auth ───────────────────────────────────────────────
    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=480)

    # ─── Retrieval ──────────────────────────────────────────
    retrieval_top_k: int = Field(default=20)
    rerank_top_n: int = Field(default=5)
    min_rerank_score: float = Field(default=0.3)
    reranker_provider: str = Field(
        default="local",
        description="Reranker provider: 'voyage', 'local', or 'none'",
    )

    # ─── Ingestion ──────────────────────────────────────────
    chunk_size_tokens: int = Field(default=400)
    chunk_overlap_tokens: int = Field(default=80)

    # ─── Agent ──────────────────────────────────────────────
    daily_token_cap_per_user: int = Field(default=100000)
    max_tokens_per_response: int = Field(default=4096)

    # ─── Environment ────────────────────────────────────────
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance. Cached after first call."""
    return Settings()
