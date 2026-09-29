"""SQLAlchemy ORM models.

The table definitions here describe the schema; they never create it. All DDL
is applied by Alembic (``alembic/versions/``). ``create_all`` is called in
exactly one place -- the unit-test fixture, against SQLite -- and never at
application startup.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import Category, Priority, Status, TriagedBy


class Base(DeclarativeBase):
    pass


def _enum(py_enum: type, name: str) -> sa.Enum:
    """Native PG enum, VARCHAR + CHECK on SQLite. Values, not member names."""
    return sa.Enum(
        py_enum,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
    )


class Complaint(Base):
    __tablename__ = "complaints"

    # The server-side gen_random_uuid() default is declared in the migration,
    # which is the only thing that emits DDL. Here we only say what the
    # application writes -- and it always writes an explicit UUID.
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    location: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    reporter_contact: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)

    category: Mapped[Category] = mapped_column(
        _enum(Category, "category_enum"), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        _enum(Priority, "priority_enum"), nullable=False
    )
    status: Mapped[Status] = mapped_column(
        _enum(Status, "status_enum"),
        nullable=False,
        server_default=Status.OPEN.value,
        default=Status.OPEN,
    )

    ai_summary: Mapped[str | None] = mapped_column(sa.String(140), nullable=True)
    triaged_by: Mapped[TriagedBy] = mapped_column(
        _enum(TriagedBy, "triaged_by_enum"), nullable=False
    )
    triage_latency_ms: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0"
    )
    triage_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    #: Stable hash of (text, location). Lets the seed be idempotent and lets us
    #: spot duplicate reports of the same incident without a full-text scan.
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        # Enforced in the DB as well as in Pydantic: the app is not the only
        # thing that can write to this table (seed scripts, psql, a future
        # service), so the invariant lives where the data lives.
        sa.CheckConstraint(
            "length(text) BETWEEN 10 AND 2000", name="ck_complaints_text_len"
        ),
        sa.CheckConstraint(
            "length(location) BETWEEN 3 AND 200", name="ck_complaints_location_len"
        ),
        # Serves the dashboard's default query: filter by status+priority,
        # newest first. See docs/ENGINEERING-NOTES.md Q-index.
        sa.Index("ix_complaints_status_priority", "status", "priority"),
        # Serves the unfiltered dashboard page and the stats time window.
        sa.Index("ix_complaints_created_at", "created_at"),
        # Serves the triage de-duplication lookup in the seed script.
        sa.Index("ix_complaints_content_hash", "content_hash"),
    )
