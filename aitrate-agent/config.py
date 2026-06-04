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

    # ─── Database ───────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://narrux:narrux_dev@localhost:5432/aitrate",
        description="PostgreSQL connection string",
    )
    postgres_user: str = Field(default="narrux")
    postgres_password: str = Field(default="narrux_dev")
    postgres_db: str = Field(default="aitrate")

    # ─── Redis ──────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ─── Anthropic ──────────────────────────────────────────
    anthropic_api_key: str = Field(default="sk-ant-xxx")
    anthropic_model_primary: str = Field(
        default="claude-opus-4-7", description="Primary LLM for F-01, F-02, F-04"
    )
    anthropic_model_secondary: str = Field(
        default="claude-sonnet-4-6", description="Secondary LLM for F-03, F-05"
    )

    # ─── Voyage AI ──────────────────────────────────────────
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
