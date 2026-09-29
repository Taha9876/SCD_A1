"""Redis behind an interface, plus an in-memory stand-in for tests.

Services depend on ``Cache``, not on redis-py, so the unit suite runs with no
container and the integration suite runs against the real thing -- same code
path either way.
"""
from __future__ import annotations

import time
from typing import Protocol

import redis.asyncio as redis


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def incr_with_expiry(self, key: str, window_seconds: int) -> tuple[int, int]: ...
    async def ping(self) -> None: ...
    async def close(self) -> None: ...


class RedisCache:
    def __init__(self, url: str) -> None:
        self._client: redis.Redis = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def incr_with_expiry(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Atomically bump a fixed-window counter and report (count, ttl).

        INCR and EXPIRE go in one pipeline so two pods incrementing the same
        key cannot interleave into a counter that never expires. The state is
        in Redis, not in the process, which is the whole reason this works when
        the HPA gives you four backends.
        """
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = await pipe.execute()
        if ttl is None or ttl < 0:
            await self._client.expire(key, window_seconds)
            ttl = window_seconds
        return int(count), int(ttl)

    async def ping(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()


class InMemoryCache:
    """Test double. Deliberately NOT used in production: an in-process dict
    rate-limits per replica, which means four replicas permit four times the
    traffic. See docs/adr and ENGINEERING-NOTES."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def _purge(self, key: str) -> None:
        item = self._data.get(key)
        if item and item[1] <= time.monotonic():
            self._data.pop(key, None)

    async def get(self, key: str) -> str | None:
        self._purge(key)
        item = self._data.get(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    async def incr_with_expiry(self, key: str, window_seconds: int) -> tuple[int, int]:
        self._purge(key)
        item = self._data.get(key)
        if item is None:
            self._data[key] = ("1", time.monotonic() + window_seconds)
            return 1, window_seconds
        count = int(item[0]) + 1
        self._data[key] = (str(count), item[1])
        return count, max(1, int(item[1] - time.monotonic()))

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self._data.clear()
