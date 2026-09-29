"""Aggregate statistics with a read-through Redis cache.

Two invalidation strategies are used together on purpose, and the reason is
worth being able to say out loud:

- TTL alone is wrong because a write makes the cached value incorrect
  immediately, and a citizen who just submitted a complaint would watch a
  stale total for up to 30 seconds.
- Explicit invalidation alone is wrong because it only covers writes this
  process knows about. The seed script, a psql session, a future second
  service, or a DELETE that we forget to hook all leave a permanently stale
  key. The TTL is the backstop that bounds how wrong we can be.

Together: correct immediately after our own writes, and self-healing within
30 seconds after anyone else's.
"""
from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from app.providers.cache import Cache
from app.repositories.complaint_repo import ComplaintRepository

STATS_CACHE_KEY = "stats:v1"


@dataclass(frozen=True)
class StatsPayload:
    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
    generated_at: datetime
    cache_hit: bool


class StatsService:
    def __init__(self, *, repo: ComplaintRepository, cache: Cache, ttl_seconds: int) -> None:
        self._repo = repo
        self._cache = cache
        self._ttl = ttl_seconds

    async def get(self) -> StatsPayload:
        try:
            raw = await self._cache.get(STATS_CACHE_KEY)
        except Exception:
            raw = None  # degrade to a MISS rather than a 500

        if raw is not None:
            try:
                payload = json.loads(raw)
                return StatsPayload(
                    total=payload["total"],
                    by_category=payload["by_category"],
                    by_priority=payload["by_priority"],
                    by_status=payload["by_status"],
                    generated_at=datetime.fromisoformat(payload["generated_at"]),
                    cache_hit=True,
                )
            except Exception:
                await self._cache.delete(STATS_CACHE_KEY)

        fresh = StatsPayload(
            total=await self._repo.total(),
            by_category=await self._repo.counts_by_category(),
            by_priority=await self._repo.counts_by_priority(),
            by_status=await self._repo.counts_by_status(),
            generated_at=datetime.now(UTC),
            cache_hit=False,
        )

        # A cache that will not accept a write is still not a 500.
        with suppress(Exception):
            await self._cache.set(
                STATS_CACHE_KEY,
                json.dumps(
                    {
                        "total": fresh.total,
                        "by_category": fresh.by_category,
                        "by_priority": fresh.by_priority,
                        "by_status": fresh.by_status,
                        "generated_at": fresh.generated_at.isoformat(),
                    }
                ),
                self._ttl,
            )

        return fresh

    async def invalidate(self) -> None:
        with suppress(Exception):
            await self._cache.delete(STATS_CACHE_KEY)
