"""Persistence for complaints. Every SQL statement in the system lives here.

Services call these methods; they never see a Session, a select() or a column.
If you find yourself importing sqlalchemy anywhere else under app/, the
layering has been broken.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Category, Priority, Status, TriagedBy
from app.models import Complaint


@dataclass(frozen=True)
class Page:
    items: list[Complaint]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class NewComplaint:
    text: str
    location: str
    reporter_contact: str | None
    category: Category
    priority: Priority
    ai_summary: str | None
    triaged_by: TriagedBy
    triage_latency_ms: int
    triage_confidence: float | None
    content_hash: str


class ComplaintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: NewComplaint) -> Complaint:
        row = Complaint(
            id=uuid.uuid4(),
            text=data.text,
            location=data.location,
            reporter_contact=data.reporter_contact,
            category=data.category,
            priority=data.priority,
            status=Status.OPEN,
            ai_summary=data.ai_summary,
            triaged_by=data.triaged_by,
            triage_latency_ms=data.triage_latency_ms,
            triage_confidence=data.triage_confidence,
            content_hash=data.content_hash,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get(self, complaint_id: uuid.UUID) -> Complaint | None:
        return await self._session.get(Complaint, complaint_id)

    async def get_by_content_hash(self, content_hash: str) -> Complaint | None:
        stmt = sa.select(Complaint).where(Complaint.content_hash == content_hash).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        category: Category | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page:
        filters = []
        if category is not None:
            filters.append(Complaint.category == category)
        if priority is not None:
            filters.append(Complaint.priority == priority)
        if status is not None:
            filters.append(Complaint.status == status)

        total_stmt = sa.select(sa.func.count()).select_from(Complaint)
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = int((await self._session.execute(total_stmt)).scalar_one())

        stmt = sa.select(Complaint)
        if filters:
            stmt = stmt.where(*filters)
        stmt = (
            stmt.order_by(Complaint.created_at.desc(), Complaint.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def update_status(self, row: Complaint, new_status: Status) -> Complaint:
        row.status = new_status
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def counts_by_category(self) -> dict[str, int]:
        stmt = sa.select(Complaint.category, sa.func.count()).group_by(Complaint.category)
        rows = (await self._session.execute(stmt)).all()
        return {_value(c): int(n) for c, n in rows}

    async def counts_by_priority(self) -> dict[str, int]:
        stmt = sa.select(Complaint.priority, sa.func.count()).group_by(Complaint.priority)
        rows = (await self._session.execute(stmt)).all()
        return {_value(p): int(n) for p, n in rows}

    async def counts_by_status(self) -> dict[str, int]:
        stmt = sa.select(Complaint.status, sa.func.count()).group_by(Complaint.status)
        rows = (await self._session.execute(stmt)).all()
        return {_value(s): int(n) for s, n in rows}

    async def total(self) -> int:
        stmt = sa.select(sa.func.count()).select_from(Complaint)
        return int((await self._session.execute(stmt)).scalar_one())

    async def ping(self) -> None:
        """Cheapest possible round trip, for the readiness probe."""
        await self._session.execute(sa.text("SELECT 1"))


def _value(v: object) -> str:
    return v.value if hasattr(v, "value") else str(v)
