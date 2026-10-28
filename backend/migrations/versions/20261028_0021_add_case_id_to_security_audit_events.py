"""Add case_id and indexes to security_audit_events table (Phase 90).

Revision ID: 20261028_0021
Revises: 20261028_0020
Create Date: 2026-10-28 19:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0021"
down_revision: str | None = "20261028_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add case_id column and indexes to security_audit_events."""
    op.add_column(
        "security_audit_events",
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_security_audit_events_case_id",
        "security_audit_events",
        ["case_id"],
    )
    op.create_index(
        "ix_security_audit_events_case_created",
        "security_audit_events",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    """Remove case_id column and indexes from security_audit_events."""
    op.drop_index(
        "ix_security_audit_events_case_created",
        table_name="security_audit_events",
    )
    op.drop_index(
        "ix_security_audit_events_case_id",
        table_name="security_audit_events",
    )
    op.drop_column("security_audit_events", "case_id")
