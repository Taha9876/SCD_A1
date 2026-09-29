"""Deterministic fake provider for CI.

Not a mock bolted onto a test -- a real implementation of the interface, chosen
by TRIAGE_PROVIDER=simulated, so CI exercises the same wiring that production
uses. Same input always gives the same output, so the pipeline is green on
every run without a single sleep() or re-run.

Failure injection is first-class because the interesting tests are the failure
ones: fallback, retry, and malformed output.
"""
from __future__ import annotations

import hashlib

from app.providers.triage.base import (
    TriageResult,
    TriageUpstreamError,
)
from app.providers.triage.parsing import parse_triage_json
from app.providers.triage.rules import RuleBasedTriage


class SimulatedTriage:
    name = "simulated"

    def __init__(
        self,
        *,
        seed: int = 1337,
        failure_rate: float = 0.0,
        malformed_rate: float = 0.0,
    ) -> None:
        self._seed = seed
        self._failure_rate = failure_rate
        self._malformed_rate = malformed_rate
        self._rules = RuleBasedTriage()

    def _roll(self, text: str, salt: str) -> float:
        """Deterministic pseudo-random in [0,1) derived from the input.

        Seeded by content rather than by call order, so a test that submits the
        same complaint always gets the same verdict regardless of what else ran
        first -- test isolation without resetting global state.
        """
        digest = hashlib.sha256(f"{self._seed}:{salt}:{text}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    async def triage(self, text: str, location: str) -> TriageResult:
        if self._roll(text, "fail") < self._failure_rate:
            raise TriageUpstreamError("simulated provider failure (injected)")

        if self._roll(text, "malformed") < self._malformed_rate:
            # Exactly the shape a real model produces when it misbehaves:
            # a code fence around an invented category.
            return parse_triage_json(
                '```json\n{"category": "potholes", "priority": "urgent", '
                '"summary": "x", "confidence": 2.0}\n```'
            )

        base = self._rules.triage_sync(text, location)
        # Nudge confidence so simulated output is distinguishable from a real
        # rules run in the dashboard, while staying deterministic.
        return TriageResult(
            category=base.category,
            priority=base.priority,
            summary=base.summary,
            confidence=round(min(0.99, base.confidence + 0.10), 2),
        )
