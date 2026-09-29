"""initial complaints schema

Revision ID: 0001
Revises:
Create Date: 2026-09-20

This is the only place the complaints table is ever created. The application
does not call create_all at startup; a startup script is a hope, a migration is
a versioned, reviewable, reversible change.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# create_type=False matters. The types are created explicitly in upgrade() so
# their lifecycle is visible and reversible; without this flag, create_table
# ALSO emits CREATE TYPE for every enum column and the migration dies with
# `type "category_enum" already exists`. (It did, the first time this ran
# against a real Postgres. SQLite in the unit suite has no enum types, so only
# the Compose integration job could have caught it -- which is the argument
# for that job existing.)
CATEGORY = postgresql.ENUM(
    "water", "electricity", "sanitation", "roads", "streetlights", "other",
    name="category_enum",
    create_type=False,
)
PRIORITY = postgresql.ENUM("high", "normal", "low", name="priority_enum", create_type=False)
STATUS = postgresql.ENUM(
    "open", "in_progress", "resolved", "rejected", name="status_enum", create_type=False
)
TRIAGED_BY = postgresql.ENUM(
    "llm:groq", "llm:ollama", "rules", "rules:fallback", "simulated",
    name="triaged_by_enum",
    create_type=False,
)


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto on older servers; on PG 13+ it is
    # built in, but creating the extension is idempotent and makes the
    # migration portable to a 12.x that somebody inevitably still runs.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    for enum_type in (CATEGORY, PRIORITY, STATUS, TRIAGED_BY):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "complaints",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("reporter_contact", sa.String(length=200), nullable=True),
        sa.Column("category", CATEGORY, nullable=False),
        sa.Column("priority", PRIORITY, nullable=False),
        sa.Column("status", STATUS, nullable=False, server_default="open"),
        sa.Column("ai_summary", sa.String(length=140), nullable=True),
        sa.Column("triaged_by", TRIAGED_BY, nullable=False),
        sa.Column("triage_latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triage_confidence", sa.Float(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # The length rules are enforced here as well as in Pydantic. The API is
        # not the only writer this table will ever have.
        sa.CheckConstraint(
            "length(text) BETWEEN 10 AND 2000", name="ck_complaints_text_len"
        ),
        sa.CheckConstraint(
            "length(location) BETWEEN 3 AND 200", name="ck_complaints_location_len"
        ),
    )

    # Serves: SELECT ... WHERE status = :s AND priority = :p ORDER BY created_at DESC
    # -- the dashboard's filtered view, which is the hot read path.
    op.create_index("ix_complaints_status_priority", "complaints", ["status", "priority"])
    # Serves: SELECT ... ORDER BY created_at DESC LIMIT :n OFFSET :o
    # -- the unfiltered first page, and any future time-window aggregate.
    op.create_index("ix_complaints_created_at", "complaints", ["created_at"])
    # Serves: SELECT ... WHERE content_hash = :h -- the seed's idempotency check.
    op.create_index("ix_complaints_content_hash", "complaints", ["content_hash"])

    # Keeps updated_at honest even for writes that do not come through the ORM
    # (psql, the seed script, a future service). The application also sets it;
    # the trigger is the backstop.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER complaints_set_updated_at
        BEFORE UPDATE ON complaints
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS complaints_set_updated_at ON complaints")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.drop_index("ix_complaints_content_hash", table_name="complaints")
    op.drop_index("ix_complaints_created_at", table_name="complaints")
    op.drop_index("ix_complaints_status_priority", table_name="complaints")
    op.drop_table("complaints")

    bind = op.get_bind()
    for enum_type in (TRIAGED_BY, STATUS, PRIORITY, CATEGORY):
        enum_type.drop(bind, checkfirst=True)
