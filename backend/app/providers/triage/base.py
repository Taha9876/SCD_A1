"""The triage contract.

Everything downstream of this file -- the service, the route, the database
column -- is written against ``TriageResult`` and ``TriageProvider`` and knows
nothing about Groq, Ollama or keyword tables. That is the whole point: the
reader is replaceable.
"""
from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import Category, Priority


class TriageResult(BaseModel):
    """Validated triage output.

    This model is applied to *every* provider's output, including the LLM's.
    A model that returns prose, a code fence, an invented category or a
    400-character "one-line" summary fails here and is handled as an error --
    it never reaches the database.
    """

    category: Category
    priority: Priority
    summary: str = Field(max_length=140)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary")
    @classmethod
    def _single_line(cls, v: str) -> str:
        collapsed = " ".join(v.split())
        if not collapsed:
            raise ValueError("summary must not be empty")
        return collapsed


class TriageError(Exception):
    """Any provider failure. Carries a stable class name for the WARNING log."""


class TriageTimeout(TriageError):
    pass


class TriageRateLimited(TriageError):
    pass


class TriageUpstreamError(TriageError):
    """5xx from the provider -- retryable."""


class TriageBadRequest(TriageError):
    """4xx other than 429 -- NOT retryable. The request was wrong and will be
    wrong again; retrying only burns quota."""


class TriageInvalidOutput(TriageError):
    """The provider answered, but the answer failed schema validation."""


@runtime_checkable
class TriageProvider(Protocol):
    name: str

    async def triage(self, text: str, location: str) -> TriageResult: ...


def content_hash(text: str, location: str) -> str:
    """Stable key for the triage cache and for seed idempotency.

    Normalised so that "Street 12" and "street  12" are one inference, not two
    -- a burst main gets reported by nine neighbours in slightly different words.
    """
    normalised = f"{' '.join(text.lower().split())}|{' '.join(location.lower().split())}"
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
