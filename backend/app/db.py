"""Database engine and session plumbing.

The engine is created once at import time and disposed on shutdown so that a
SIGTERM closes pool connections rather than leaving them for the server to
reap. No module outside ``app.repositories`` imports ``select`` from here.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

_engine_kwargs: dict[str, object] = {"echo": False, "pool_pre_ping": True}
if not _settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = _settings.db_pool_size
    _engine_kwargs["max_overflow"] = _settings.db_max_overflow

engine: AsyncEngine = create_async_engine(_settings.database_url, **_engine_kwargs)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Routes depend on services, not on this -- but the
    composition root needs a place to open exactly one session per request."""
    async with SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
