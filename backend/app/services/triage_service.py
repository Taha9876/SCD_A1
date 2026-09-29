"""Triage orchestration -- the engineering around the model.

The provider call itself is one line in here. Everything else in this file is
what makes a dependency on a probabilistic third party safe to put in front of
citizens: a hard timeout, one jittered retry on retryable errors only, a
content-hash cache, a fallback that cannot fail, and a record of which of those
actually decided each complaint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass

from opentelemetry import trace

from app.config import Settings
from app.domain.enums import TriagedBy
from app.providers.cache import Cache
from app.providers.triage.base import (
    TriageError,
    TriageProvider,
    TriageResult,
    content_hash,
)
from app.providers.triage.llm import RETRYABLE
from app.providers.triage.rules import RuleBasedTriage

logger = logging.getLogger("civicpulse.triage")

#: How many recent outcomes /api/meta/providers reports. Bounded on purpose:
#: an unbounded observability buffer is a memory leak with good intentions.
_RECENT_CAPACITY = 20

#: A no-op until app/tracing.py installs a real provider, so this costs nothing
#: in tests and whenever OTEL_EXPORTER_OTLP_ENDPOINT is unset.
_tracer = trace.get_tracer("civicpulse.triage")


@dataclass(frozen=True)
class TriageOutcome:
    result: TriageResult
    triaged_by: TriagedBy
    latency_ms: int
    cache_hit: bool
    fallback: bool
    content_hash: str
    #: Why the provider failed, when it did. Carried out rather than logged
    #: here: the spec wants the fallback WARNING to name the complaint id,
    #: which does not exist until ComplaintService has persisted the row.
    error_class: str | None = None


@dataclass
class TriageRecord:
    """One line of the observability surface."""

    provider: str
    latency_ms: int
    fallback: bool
    cache_hit: bool
    category: str
    priority: str
    error_class: str | None = None


class TriageService:
    def __init__(
        self,
        *,
        provider: TriageProvider,
        cache: Cache,
        settings: Settings,
        fallback: RuleBasedTriage | None = None,
        sleep=asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._settings = settings
        self._fallback = fallback or RuleBasedTriage()
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._recent: deque[TriageRecord] = deque(maxlen=_RECENT_CAPACITY)
        self._cache_hits = 0
        self._cache_lookups = 0

    # -- observability ----------------------------------------------------

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def recent(self) -> list[TriageRecord]:
        """Newest first -- an operator reading this wants the last thing
        that happened at the top."""
        return list(reversed(self._recent))

    def cache_stats(self) -> dict[str, object]:
        rate = (self._cache_hits / self._cache_lookups) if self._cache_lookups else 0.0
        return {
            "lookups": self._cache_lookups,
            "hits": self._cache_hits,
            "hit_rate": round(rate, 4),
        }

    # -- the work ---------------------------------------------------------

    async def triage(self, text: str, location: str) -> TriageOutcome:
        # One span around the whole decision, so a trace shows the cache
        # lookup, both attempts and the outbound LLM request as children of a
        # single step, and records which path actually decided the complaint.
        with _tracer.start_as_current_span("triage") as span:
            outcome = await self._triage(text, location)
            span.set_attributes(
                {
                    "triage.provider": self._provider.name,
                    "triage.triaged_by": outcome.triaged_by.value,
                    "triage.cache_hit": outcome.cache_hit,
                    "triage.fallback": outcome.fallback,
                    "triage.category": outcome.result.category.value,
                    "triage.latency_ms": outcome.latency_ms,
                }
            )
            if outcome.error_class:
                span.set_attribute("triage.error_class", outcome.error_class)
            return outcome

    async def _triage(self, text: str, location: str) -> TriageOutcome:
        digest = content_hash(text, location)
        started = time.perf_counter()

        cached = await self._read_cache(digest)
        if cached is not None:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._record(cached[0], cached[1], latency_ms, fallback=False, cache_hit=True)
            return TriageOutcome(
                result=cached[0],
                triaged_by=cached[1],
                latency_ms=latency_ms,
                cache_hit=True,
                fallback=False,
                content_hash=digest,
            )

        result, triaged_by, error = await self._call_with_retry(text, location)
        latency_ms = int((time.perf_counter() - started) * 1000)
        fallback = triaged_by is TriagedBy.RULES_FALLBACK

        if not fallback:
            await self._write_cache(digest, result, triaged_by)

        self._record(
            result, triaged_by, latency_ms, fallback=fallback, cache_hit=False, error=error
        )
        return TriageOutcome(
            result=result,
            triaged_by=triaged_by,
            latency_ms=latency_ms,
            cache_hit=False,
            fallback=fallback,
            content_hash=digest,
            error_class=error,
        )

    async def _call_with_retry(
        self, text: str, location: str
    ) -> tuple[TriageResult, TriagedBy, str | None]:
        attempts = self._settings.triage_max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                # Hard cap regardless of what the provider client does. A hung
                # call must not be able to exhaust the worker pool.
                result = await asyncio.wait_for(
                    self._provider.triage(text, location),
                    timeout=self._settings.triage_timeout_seconds,
                )
                return result, self._triaged_by_for(self._provider.name), None
            except (TimeoutError, TriageError) as exc:
                last_error = exc
                retryable = isinstance(exc, (*RETRYABLE, asyncio.TimeoutError))
                if attempt + 1 < attempts and retryable:
                    # Full jitter. Without it, every pod that hit the same 429
                    # retries in lockstep and re-creates the burst.
                    await self._sleep(self._rng.uniform(0.05, 0.4))
                    continue
                break

        error_class = type(last_error).__name__ if last_error else "UnknownError"
        # No WARNING here on purpose. §2.2 asks for exactly one per fallback,
        # naming the complaint id -- ComplaintService.submit emits it once the
        # row exists. Logging here too would make it two, and neither complete.
        return (
            self._fallback.triage_sync(text, location),
            TriagedBy.RULES_FALLBACK,
            error_class,
        )

    # -- cache ------------------------------------------------------------

    async def _read_cache(self, digest: str) -> tuple[TriageResult, TriagedBy] | None:
        self._cache_lookups += 1
        key = f"triage:{digest}"
        try:
            raw = await self._cache.get(key)
        except Exception:  # cache is an optimisation, never a dependency
            logger.warning("triage cache read failed", extra={"event": "triage.cache_error"})
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            result = TriageResult.model_validate(payload["result"])
            triaged_by = TriagedBy(payload["triaged_by"])
        except Exception:
            # A poisoned or stale-shaped entry is discarded, not trusted.
            await self._cache.delete(key)
            return None
        self._cache_hits += 1
        return result, triaged_by

    async def _write_cache(self, digest: str, result: TriageResult, by: TriagedBy) -> None:
        payload = json.dumps(
            {"result": result.model_dump(mode="json"), "triaged_by": by.value}
        )
        try:
            await self._cache.set(
                f"triage:{digest}", payload, self._settings.triage_cache_ttl_seconds
            )
        except Exception:
            logger.warning("triage cache write failed", extra={"event": "triage.cache_error"})

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _triaged_by_for(provider_name: str) -> TriagedBy:
        try:
            return TriagedBy(provider_name)
        except ValueError:
            return TriagedBy.RULES

    def _record(
        self,
        result: TriageResult,
        triaged_by: TriagedBy,
        latency_ms: int,
        *,
        fallback: bool,
        cache_hit: bool,
        error: str | None = None,
    ) -> None:
        self._recent.append(
            TriageRecord(
                provider=triaged_by.value,
                latency_ms=latency_ms,
                fallback=fallback,
                cache_hit=cache_hit,
                category=result.category.value,
                priority=result.priority.value,
                error_class=error,
            )
        )
