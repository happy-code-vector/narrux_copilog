"""Application settings — loaded from environment variables via Pydantic Settings."""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Central configuration. Reads from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── Anthropic ──────────────────────────────────────────
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    anthropic_model_sonnet: str = Field(
        default="claude-sonnet-4-6", description="Model for routine queries"
    )
    anthropic_model_opus: str = Field(
        default="claude-opus-4-8", description="Model for complex reasoning"
    )

    # ─── Voyage AI ──────────────────────────────────────────
    voyage_api_key: str = Field(..., description="Voyage AI API key")
    voyage_embedding_model: str = Field(
        default="voyage-3-large", description="Embedding model"
    )
    voyage_reranker_model: str = Field(
        default="rerank-2", description="Reranker model"
    )

    # ─── Database ───────────────────────────────────────────
    database_url: str = Field(
        ..., description="PostgreSQL async connection string"
    )
    database_url_sync: str = Field(
        ..., description="PostgreSQL sync connection string (for migrations)"
    )

    # ─── Redis ──────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ─── Langfuse ───────────────────────────────────────────
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    langfuse_host: str = Field(default="https://cloud.langfuse.com")

    # ─── Auth ───────────────────────────────────────────────
    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_minutes: int = Field(default=60)

    # ─── Agent ──────────────────────────────────────────────
    agent_max_tokens: int = Field(default=4096)
    agent_temperature_routine: float = Field(default=0.1)
    agent_temperature_recommendation: float = Field(default=0.3)
    agent_streaming: bool = Field(default=True)

    # ─── Retrieval ──────────────────────────────────────────
    retrieval_top_k: int = Field(default=50, description="Chunks to retrieve")
    retrieval_top_n: int = Field(default=10, description="Chunks after reranking")
    retrieval_chunk_size: int = Field(default=1000)
    retrieval_chunk_overlap: int = Field(default=200)

    # ─── Eval ───────────────────────────────────────────────
    eval_min_recall_at_5: float = Field(default=0.9)
    eval_min_faithfulness: float = Field(default=0.85)

    # ─── Environment ────────────────────────────────────────
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: str = Field(default="INFO")

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance. Cached after first call."""
    return Settings()
