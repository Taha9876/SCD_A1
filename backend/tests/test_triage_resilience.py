"""The tests that matter most: what happens when the model misbehaves.

If you read one test file in this repository, read this one. Every case here
corresponds to a real failure mode of a hosted LLM, and each is deterministic
-- no sleeps, no re-runs, no network.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.domain.enums import Category, Priority, TriagedBy
from app.providers.cache import InMemoryCache
from app.providers.triage.base import (
    TriageBadRequest,
    TriageInvalidOutput,
    TriageRateLimited,
    TriageResult,
)
from app.providers.triage.parsing import parse_triage_json
from app.services.triage_service import TriageService

TEXT = "Transformer is sparking badly and a live wire is hanging low over the footpath."
LOCATION = "Street 9, Johar Town, Lahore"


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "redis_url": "redis://unused",
        "triage_provider": "simulated",
        "triage_timeout_seconds": 0.2,
        "triage_max_retries": 1,
    }
    base.update(overrides)
    return Settings(**base)


class AlwaysRaises:
    """The provider is down, or your key expired, or the region is on fire."""

    name = "llm:groq"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        raise self._exc


class Hangs:
    name = "llm:groq"

    def __init__(self) -> None:
        self.calls = 0

    async def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        await asyncio.sleep(10)  # far past the configured timeout
        raise AssertionError("should have been cancelled by the timeout")


class Counting:
    name = "llm:groq"

    def __init__(self) -> None:
        self.calls = 0

    async def triage(self, text: str, location: str) -> TriageResult:
        self.calls += 1
        return TriageResult(
            category=Category.ELECTRICITY,
            priority=Priority.HIGH,
            summary="Live wire hanging over footpath",
            confidence=0.9,
        )


def _service(provider, **setting_overrides) -> TriageService:
    return TriageService(
        provider=provider,
        cache=InMemoryCache(),
        settings=_settings(**setting_overrides),
        sleep=_no_sleep,
        rng=_FixedRandom(),
    )


async def _no_sleep(_seconds: float) -> None:
    """Jitter is real in production and pointless in a test. Asserting that we
    slept at all is the useful part; waiting for it is not."""
    return None


class _FixedRandom:
    def uniform(self, a: float, b: float) -> float:
        return a


# --- The test the assignment says to write if you write no other -----------


async def test_provider_that_always_raises_still_returns_a_result_via_fallback():
    service = _service(AlwaysRaises(TriageRateLimited("429")))

    outcome = await service.triage(TEXT, LOCATION)

    assert outcome.triaged_by is TriagedBy.RULES_FALLBACK
    assert outcome.fallback is True
    # The rules provider still did real work: this is an electricity complaint
    # with a danger keyword, so it must come out high priority.
    assert outcome.result.category is Category.ELECTRICITY
    assert outcome.result.priority is Priority.HIGH


# --- Retry policy ----------------------------------------------------------


async def test_retryable_error_is_retried_exactly_once():
    provider = AlwaysRaises(TriageRateLimited("429"))
    service = _service(provider)

    await service.triage(TEXT, LOCATION)

    assert provider.calls == 2, "expected one initial call plus exactly one retry"


async def test_non_retryable_error_is_not_retried():
    """A 400 was wrong when we sent it and will be wrong 300ms later.
    Retrying it only burns quota on a request that cannot succeed."""
    provider = AlwaysRaises(TriageBadRequest("400 invalid model"))
    service = _service(provider)

    await service.triage(TEXT, LOCATION)

    assert provider.calls == 1


async def test_invalid_output_is_not_retried_and_falls_back():
    provider = AlwaysRaises(TriageInvalidOutput("model returned prose"))
    service = _service(provider)

    outcome = await service.triage(TEXT, LOCATION)

    assert provider.calls == 1
    assert outcome.triaged_by is TriagedBy.RULES_FALLBACK


async def test_timeout_is_enforced_and_falls_back():
    provider = Hangs()
    service = _service(provider, triage_timeout_seconds=0.05)

    outcome = await service.triage(TEXT, LOCATION)

    assert outcome.triaged_by is TriagedBy.RULES_FALLBACK
    assert provider.calls == 2  # timeout is retryable, so one retry happened


# --- Content-hash cache ----------------------------------------------------


async def test_identical_complaint_costs_one_inference_not_two():
    provider = Counting()
    service = _service(provider)

    first = await service.triage(TEXT, LOCATION)
    second = await service.triage(TEXT, LOCATION)

    assert provider.calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.result.category is first.result.category


async def test_cache_key_normalises_whitespace_and_case():
    """Nine neighbours reporting one burst main should cost one inference."""
    provider = Counting()
    service = _service(provider)

    await service.triage(TEXT, LOCATION)
    await service.triage(TEXT.upper(), f"  {LOCATION}  ")

    assert provider.calls == 1


async def test_fallback_results_are_never_cached():
    """Caching a degraded answer for 24 hours would turn a 30-second provider
    outage into a day of wrong categories."""
    provider = AlwaysRaises(TriageRateLimited("429"))
    service = _service(provider)

    await service.triage(TEXT, LOCATION)
    second = await service.triage(TEXT, LOCATION)

    assert second.cache_hit is False


async def test_hit_rate_is_measured():
    service = _service(Counting())

    await service.triage(TEXT, LOCATION)
    await service.triage(TEXT, LOCATION)
    await service.triage(TEXT, LOCATION)

    stats = service.cache_stats()
    assert stats["lookups"] == 3
    assert stats["hits"] == 2
    assert stats["hit_rate"] == pytest.approx(2 / 3, abs=1e-3)


# --- Output validation -----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "I think this is probably a water issue, quite urgent.",          # prose
        '{"category": "potholes", "priority": "high", "summary": "x", "confidence": 0.5}',  # invented enum
        '{"category": "roads", "priority": "urgent", "summary": "x", "confidence": 0.5}',   # invented priority
        '{"category": "roads", "priority": "high", "summary": "x", "confidence": 2.0}',     # out of range
        '{"category": "roads", "priority": "high"}',                       # missing fields
        "",                                                                # empty body
        "[]",                                                              # not an object
    ],
)
def test_malformed_model_output_is_rejected(raw: str):
    with pytest.raises(TriageInvalidOutput):
        parse_triage_json(raw)


def test_code_fenced_json_is_accepted():
    """Models wrap JSON in a fence constantly, however firmly you ask them not
    to. Rejecting that would be correct and useless."""
    result = parse_triage_json(
        '```json\n{"category": "water", "priority": "high", '
        '"summary": "Burst main flooding Street 12", "confidence": 0.91}\n```'
    )
    assert result.category is Category.WATER


def test_prose_wrapped_json_is_accepted():
    result = parse_triage_json(
        'Sure! Here is the classification:\n'
        '{"category": "roads", "priority": "normal", "summary": "Pothole", "confidence": 0.7}\n'
        'Let me know if you need anything else.'
    )
    assert result.category is Category.ROADS


def test_overlong_summary_is_truncated_not_rejected():
    """The classification is still useful even when the model ignores
    'one line'; the prose is not."""
    long_summary = "x" * 400
    result = parse_triage_json(
        '{"category": "water", "priority": "low", '
        f'"summary": "{long_summary}", "confidence": 0.5}}'
    )
    assert len(result.summary) == 140
