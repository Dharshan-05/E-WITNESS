"""Add supervisor override fields to case_assignments table (Phase 82).

Revision ID: 20261028_0018
Revises: 20261028_0017
Create Date: 2026-10-28 10:45:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0018"
down_revision: str | None = "20261028_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "case_assignments",
        sa.Column(
            "is_supervisor_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "case_assignments",
        sa.Column(
            "override_justification",
            sa.String(length=1000),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("case_assignments", "override_justification")
    op.drop_column("case_assignments", "is_supervisor_override")
