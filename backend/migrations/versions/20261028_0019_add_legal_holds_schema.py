"""Add legal_holds table and schema (Phase 83).

Revision ID: 20261028_0019
Revises: 20261028_0018
Create Date: 2026-10-28 11:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0019"
down_revision: str | None = "20261028_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("hold_reference", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("evidence_attachments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column(
            "placed_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "released_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_legal_holds_status_allowed",
        ),
    )

    op.create_index("ix_legal_holds_case_id", "legal_holds", ["case_id"])
    op.create_index("ix_legal_holds_evidence_id", "legal_holds", ["evidence_id"])
    op.create_index("ix_legal_holds_department_id", "legal_holds", ["department_id"])
    op.create_index("ix_legal_holds_status", "legal_holds", ["status"])
    op.create_index(
        "ix_legal_holds_hold_reference",
        "legal_holds",
        ["hold_reference"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_legal_holds_hold_reference", table_name="legal_holds")
    op.drop_index("ix_legal_holds_status", table_name="legal_holds")
    op.drop_index("ix_legal_holds_department_id", table_name="legal_holds")
    op.drop_index("ix_legal_holds_evidence_id", table_name="legal_holds")
    op.drop_index("ix_legal_holds_case_id", table_name="legal_holds")
    op.drop_table("legal_holds")
