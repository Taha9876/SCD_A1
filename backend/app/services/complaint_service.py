"""Business rules for complaints.

Owns the order of operations for intake (validate -> triage -> persist ->
invalidate stats) and the status state machine. Knows nothing about HTTP status
codes and nothing about SQL.
"""
from __future__ import annotations

import logging
import uuid

from app.domain.enums import Category, Priority, Status
from app.domain.state_machine import assert_transition
from app.metrics import metrics
from app.models import Complaint
from app.repositories.complaint_repo import ComplaintRepository, NewComplaint, Page
from app.schemas import ComplaintCreate
from app.services.stats_service import StatsService
from app.services.triage_service import TriageService

logger = logging.getLogger("civicpulse.triage")


class ComplaintNotFound(Exception):
    def __init__(self, complaint_id: uuid.UUID) -> None:
        self.complaint_id = complaint_id
        super().__init__(f"complaint {complaint_id} not found")


class ComplaintService:
    def __init__(
        self,
        *,
        repo: ComplaintRepository,
        triage: TriageService,
        stats: StatsService,
    ) -> None:
        self._repo = repo
        self._triage = triage
        self._stats = stats

    async def submit(self, payload: ComplaintCreate) -> Complaint:
        outcome = await self._triage.triage(payload.text, payload.location)
        metrics.observe_triage(outcome.latency_ms / 1000.0, fallback=outcome.fallback)

        row = await self._repo.create(
            NewComplaint(
                text=payload.text,
                location=payload.location,
                reporter_contact=payload.reporter_contact,
                category=outcome.result.category,
                priority=outcome.result.priority,
                ai_summary=outcome.result.summary,
                triaged_by=outcome.triaged_by,
                triage_latency_ms=outcome.latency_ms,
                triage_confidence=outcome.result.confidence,
                content_hash=outcome.content_hash,
            )
        )

        if outcome.fallback:
            # Exactly one WARNING per fallback, carrying what §2.2 asks for: the
            # complaint id, the provider that failed, and why. Emitted here
            # because this is the first moment the id exists.
            logger.warning(
                "triage fallback engaged",
                extra={
                    "event": "triage.fallback",
                    "complaint_id": str(row.id),
                    "provider": self._triage.provider_name,
                    "error_class": outcome.error_class,
                },
            )

        # Explicit invalidation, not just TTL expiry: a citizen who submits a
        # complaint and immediately opens the dashboard must see their own
        # report in the totals, not a number up to 30 seconds stale.
        await self._stats.invalidate()
        return row

    async def get(self, complaint_id: uuid.UUID) -> Complaint:
        row = await self._repo.get(complaint_id)
        if row is None:
            raise ComplaintNotFound(complaint_id)
        return row

    async def list(
        self,
        *,
        category: Category | None,
        priority: Priority | None,
        status: Status | None,
        page: int,
        page_size: int,
    ) -> Page:
        return await self._repo.list(
            category=category,
            priority=priority,
            status=status,
            page=page,
            page_size=page_size,
        )

    async def change_status(self, complaint_id: uuid.UUID, new_status: Status) -> Complaint:
        row = await self.get(complaint_id)
        # Raises InvalidTransition, which the route renders as a 409 naming the
        # attempted transition. The rule lives in the domain, not in the route.
        assert_transition(Status(row.status), new_status)
        updated = await self._repo.update_status(row, new_status)
        await self._stats.invalidate()
        return updated
