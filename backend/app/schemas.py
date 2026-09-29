"""HTTP request and response models.

Pydantic gives us one validation mechanism used twice: here for untrusted HTTP
input, and in providers/triage/base.py for untrusted model output. Same mental
model, same failure mode, same error rendering.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Category, Priority, Status, TriagedBy


class ComplaintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=10, max_length=2000)
    location: str = Field(min_length=3, max_length=200)
    reporter_contact: str | None = Field(default=None, max_length=200)

    @field_validator("text", "location")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("reporter_contact")
    @classmethod
    def _normalise_contact(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status


class ComplaintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    location: str
    reporter_contact: str | None
    category: Category
    priority: Priority
    status: Status
    ai_summary: str | None
    triaged_by: TriagedBy
    triage_latency_ms: int
    triage_confidence: float | None
    created_at: datetime
    updated_at: datetime
    #: Rendered by the frontend so it never has to hold a copy of the state
    #: machine. One source of truth, and it is the server.
    allowed_transitions: list[Status] = Field(default_factory=list)


class ComplaintPage(BaseModel):
    items: list[ComplaintOut]
    total: int
    page: int
    page_size: int
    pages: int


class StatsOut(BaseModel):
    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
    generated_at: datetime


class TriageRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    latency_ms: int
    fallback: bool
    cache_hit: bool
    category: str
    priority: str
    error_class: str | None = None


class ProvidersOut(BaseModel):
    active_provider: str
    configured_provider: str
    triage_cache: dict[str, object]
    recent: list[TriageRecordOut]


class ReadyOut(BaseModel):
    status: str
    dependencies: dict[str, str]


class HealthOut(BaseModel):
    status: str
    service: str


class FieldError(BaseModel):
    field: str
    message: str
    type: str


class ErrorOut(BaseModel):
    """Every non-2xx body in the system has this shape."""

    error: str
    detail: str
    fields: list[FieldError] | None = None
