"""Database session management — async and sync engines."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from config.settings import get_settings

settings = get_settings()

# ─── Async Engine (for FastAPI) ──────────────────────────────────────────────

async_engine = create_async_engine(
    settings.database_url,
    echo=(settings.environment == "development"),
    pool_size=20,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI routes — yields an async session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ─── Sync Engine (for Alembic migrations) ────────────────────────────────────

sync_engine = create_engine(
    settings.database_url_sync,
    echo=(settings.environment == "development"),
)

sync_session_factory = sessionmaker(
    sync_engine,
    expire_on_commit=False,
)


def get_sync_session() -> Session:
    """Returns a sync session — for migrations and scripts."""
    return sync_session_factory()
