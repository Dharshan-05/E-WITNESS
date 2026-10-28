"""Add case sequence counters and update case lifecycle statuses (Phase 81).

Revision ID: 20261028_0017
Revises: 20261028_0016
Create Date: 2026-10-28 09:55:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.models.base import UTCDateTime

revision: str = "20261028_0017"
down_revision: str | None = "20261028_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPDATED_STATUS_VALUES = (
    "'draft', 'open', 'under_investigation', 'pending_review', "
    "'pending_supervisor_review', 'suspended', 'resolved', 'closed', 'reopened'"
)
_ORIGINAL_STATUS_VALUES = (
    "'draft', 'open', 'under_investigation', 'pending_review', 'suspended', 'resolved', 'closed'"
)


def upgrade() -> None:
    """Apply Phase 81 case sequence counters table and update status constraint."""
    # 1. Create case_sequence_counters table for concurrency-safe annual reference generation
    op.create_table(
        "case_sequence_counters",
        sa.Column("year", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("current_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "year >= 2020 AND year <= 2100",
            name="ck_case_seq_year_range",
        ),
        sa.CheckConstraint(
            "current_sequence >= 0",
            name="ck_case_seq_positive",
        ),
    )

    # 2. Update ck_cases_status_allowed_values constraint on cases table
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_cases_status_allowed_values", "cases", type_="check")
        op.create_check_constraint(
            "ck_cases_status_allowed_values",
            "cases",
            f"status IN ({_UPDATED_STATUS_VALUES})",
        )
    else:
        with op.batch_alter_table("cases") as batch_op:
            batch_op.drop_constraint("ck_cases_status_allowed_values", type_="check")
            batch_op.create_check_constraint(
                "ck_cases_status_allowed_values",
                f"status IN ({_UPDATED_STATUS_VALUES})",
            )


def downgrade() -> None:
    """Revert Phase 81 case sequence counters table and status constraint."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("ck_cases_status_allowed_values", "cases", type_="check")
        op.create_check_constraint(
            "ck_cases_status_allowed_values",
            "cases",
            f"status IN ({_ORIGINAL_STATUS_VALUES})",
        )
    else:
        with op.batch_alter_table("cases") as batch_op:
            batch_op.drop_constraint("ck_cases_status_allowed_values", type_="check")
            batch_op.create_check_constraint(
                "ck_cases_status_allowed_values",
                f"status IN ({_ORIGINAL_STATUS_VALUES})",
            )

    op.drop_table("case_sequence_counters")
