"""Test fixtures.

The suite runs with no Postgres, no Redis and no network: SQLite in memory for
persistence, InMemoryCache for Redis, and SimulatedTriage for the model. That
is not a compromise -- it is the design requirement. A suite that needs three
containers to be green is a suite people skip.

Note the one place create_all is called: here, against SQLite. Production
schema is applied only by Alembic.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base
from app.providers.cache import InMemoryCache
from app.providers.triage.simulated import SimulatedTriage
from app.services.triage_service import TriageService


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://unused",
        triage_provider="simulated",
        rate_limit_requests=1000,
        rate_limit_window_seconds=60,
        stats_cache_ttl_seconds=30,
        log_level="WARNING",
    )


@pytest_asyncio.fixture
async def engine():
    # A single shared in-memory connection: SQLite gives each connection its
    # own database otherwise, and the app would see an empty schema.
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=None,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def cache() -> InMemoryCache:
    return InMemoryCache()


@pytest_asyncio.fixture
async def triage_service(settings, cache) -> TriageService:
    return TriageService(
        provider=SimulatedTriage(seed=settings.simulated_seed),
        cache=cache,
        settings=settings,
    )


@pytest_asyncio.fixture
async def app(settings, session_factory, cache, triage_service):
    application = create_app()

    async def _session() -> AsyncIterator:
        async with session_factory() as s:
            yield s

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_settings] = lambda: settings
    # The lifespan handler is not run by ASGITransport, so wire the
    # process-scoped singletons by hand -- the same objects it would build.
    application.state.cache = cache
    application.state.triage_service = triage_service
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def valid_complaint() -> dict[str, str]:
    return {
        "text": (
            "Burst water main flooding Street 12 since fajr, water is entering "
            "ground floors of three houses."
        ),
        "location": "Street 12, G-9/4, Islamabad",
        "reporter_contact": "0300-1234567",
    }
