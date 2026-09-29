"""Distributed fixed-window rate limiter.

Keyed by client IP and held in Redis, because the moment the HPA scales the
backend to four pods an in-process counter silently permits 4x the configured
traffic -- and the thing it is protecting is a free LLM tier measured in tens
of requests per minute.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.providers.cache import Cache


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    limit: int


class RateLimiter:
    def __init__(self, cache: Cache, *, limit: int, window_seconds: int) -> None:
        self._cache = cache
        self._limit = limit
        self._window = window_seconds

    async def check(self, client_key: str) -> RateLimitDecision:
        # Window is bucketed into the key itself, so the counter for an old
        # window can never be read by a request in a new one even if the TTL
        # write lost a race.
        key = f"ratelimit:complaints:{client_key}"
        count, ttl = await self._cache.incr_with_expiry(key, self._window)
        allowed = count <= self._limit
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(0, self._limit - count),
            retry_after_seconds=max(1, ttl),
            limit=self._limit,
        )
