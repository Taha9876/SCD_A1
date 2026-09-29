"""The test the assignment names explicitly, at the level it names it.

§2.5: "Write this test if you write no other: given a provider that always
raises, POST /api/complaints still returns 201 and triaged_by == 'rules:fallback'."

test_triage_resilience.py covers the same path at the service level. This file
covers it through HTTP, because that is where a citizen meets it, and it also
checks §2.2's logging contract: exactly one WARNING per fallback, naming the
complaint id, the provider and the error class.
"""
from __future__ import annotations

import logging

from app.providers.cache import InMemoryCache
from app.providers.triage.base import TriageRateLimited, TriageResult
from app.services.triage_service import TriageService


class AlwaysRaises:
    name = "llm:groq"

    async def triage(self, text: str, location: str) -> TriageResult:
        raise TriageRateLimited("429 from the provider")


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_post_with_a_provider_that_always_raises_still_returns_201(app, client, settings):
    app.state.triage_service = TriageService(
        provider=AlwaysRaises(), cache=InMemoryCache(), settings=settings, sleep=_no_sleep
    )

    # Attached to the logger itself rather than using caplog: create_app()
    # reconfigures the root logger, which would detach caplog's handler.
    collector = _Collect()
    triage_logger = logging.getLogger("civicpulse.triage")
    triage_logger.addHandler(collector)
    try:
        response = await client.post(
            "/api/complaints",
            json={
                "text": "Transformer is sparking and a live wire is hanging over the footpath.",
                "location": "Street 9, Johar Town, Lahore",
            },
        )
    finally:
        triage_logger.removeHandler(collector)

    # The citizen never sees the provider's failure.
    assert response.status_code == 201
    body = response.json()
    assert body["triaged_by"] == "rules:fallback"
    # And the fallback still triaged it properly.
    assert body["category"] == "electricity"
    assert body["priority"] == "high"

    # §2.2: one WARNING per fallback with the complaint id, provider, error class.
    fallbacks = [r for r in collector.records if getattr(r, "event", None) == "triage.fallback"]
    assert len(fallbacks) == 1, "expected exactly one fallback WARNING"
    record = fallbacks[0]
    assert record.levelno == logging.WARNING
    assert record.complaint_id == body["id"]
    assert record.provider == "llm:groq"
    assert record.error_class == "TriageRateLimited"


async def test_a_healthy_provider_logs_no_fallback_warning(client):
    collector = _Collect()
    triage_logger = logging.getLogger("civicpulse.triage")
    triage_logger.addHandler(collector)
    try:
        response = await client.post(
            "/api/complaints",
            json={
                "text": "Garbage has not been lifted from our lane for two weeks now.",
                "location": "Lane 6, Nazimabad, Karachi",
            },
        )
    finally:
        triage_logger.removeHandler(collector)

    assert response.status_code == 201
    assert not [r for r in collector.records if getattr(r, "event", None) == "triage.fallback"]
