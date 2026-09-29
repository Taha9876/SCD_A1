"""Composition root.

Routes ask for a service; this module is the only place that knows how a
service is built out of a repository, a cache and a provider. Overriding any of
these in a test replaces the whole graph below it, which is how the suite runs
with no Postgres, no Redis and no network.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.providers.cache import Cache
from app.providers.rate_limiter import RateLimiter
from app.repositories.complaint_repo import ComplaintRepository
from app.services.complaint_service import ComplaintService
from app.services.stats_service import StatsService
from app.services.triage_service import TriageService

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_cache(request: Request) -> Cache:
    """One connection pool for the process, created in the lifespan handler."""
    return request.app.state.cache


def get_triage_service(request: Request) -> TriageService:
    """One instance for the process: it owns the recent-outcomes ring buffer
    and the cache hit counters, which must not reset per request."""
    return request.app.state.triage_service


def get_repository(session: SessionDep) -> ComplaintRepository:
    return ComplaintRepository(session)


def get_stats_service(
    repo: Annotated[ComplaintRepository, Depends(get_repository)],
    cache: Annotated[Cache, Depends(get_cache)],
    settings: SettingsDep,
) -> StatsService:
    return StatsService(repo=repo, cache=cache, ttl_seconds=settings.stats_cache_ttl_seconds)


def get_complaint_service(
    repo: Annotated[ComplaintRepository, Depends(get_repository)],
    triage: Annotated[TriageService, Depends(get_triage_service)],
    stats: Annotated[StatsService, Depends(get_stats_service)],
) -> ComplaintService:
    return ComplaintService(repo=repo, triage=triage, stats=stats)


def get_rate_limiter(
    cache: Annotated[Cache, Depends(get_cache)], settings: SettingsDep
) -> RateLimiter:
    return RateLimiter(
        cache,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


ComplaintServiceDep = Annotated[ComplaintService, Depends(get_complaint_service)]
StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]
TriageServiceDep = Annotated[TriageService, Depends(get_triage_service)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
RepositoryDep = Annotated[ComplaintRepository, Depends(get_repository)]
CacheDep = Annotated[Cache, Depends(get_cache)]


def client_key(request: Request) -> str:
    """Identify the caller for rate limiting.

    Behind nginx and an Ingress the socket peer is the proxy, so the real
    client is the first hop in X-Forwarded-For. Trusting that header is only
    safe because the only thing that can reach this port is our own proxy --
    stated here so the assumption is visible rather than implied.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
