"""Add public visibility tier to case notes and visibility tracking to note history (Phase 86).

Revision ID: 20261028_0020
Revises: 20261028_0019
Create Date: 2026-10-28 15:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0020"
down_revision: str | None = "20261028_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_NOTE_VISIBILITY_VALUES = "'internal', 'confidential', 'restricted'"
_NEW_NOTE_VISIBILITY_VALUES = "'public', 'internal', 'confidential', 'restricted'"


def upgrade() -> None:
    """Apply Phase 86 case note public visibility tier and history tracking."""
    # 1. Update check constraint on case_notes for visibility
    with op.batch_alter_table("case_notes") as batch_op:
        batch_op.drop_constraint("ck_case_notes_visibility", type_="check")
        batch_op.create_check_constraint(
            "ck_case_notes_visibility",
            f"visibility IN ({_NEW_NOTE_VISIBILITY_VALUES})",
        )

    # 2. Add visibility and previous_visibility columns to case_note_history
    with op.batch_alter_table("case_note_history") as batch_op:
        batch_op.add_column(
            sa.Column(
                "visibility",
                sa.String(length=32),
                nullable=False,
                server_default="internal",
            )
        )
        batch_op.add_column(
            sa.Column(
                "previous_visibility",
                sa.String(length=32),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Revert Phase 86 case note public visibility tier and history tracking."""
    with op.batch_alter_table("case_note_history") as batch_op:
        batch_op.drop_column("previous_visibility")
        batch_op.drop_column("visibility")

    with op.batch_alter_table("case_notes") as batch_op:
        batch_op.drop_constraint("ck_case_notes_visibility", type_="check")
        batch_op.create_check_constraint(
            "ck_case_notes_visibility",
            f"visibility IN ({_OLD_NOTE_VISIBILITY_VALUES})",
        )
