"""Add biometric quality reviews table for human oversight (Phase 77).

Revision ID: 20261028_0016
Revises: 20261021_0015
Create Date: 2026-10-28 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.models.base import UTCDateTime

revision: str = "20261028_0016"
down_revision: str | None = "20261021_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_VALUES = (
    "'PENDING_REVIEW', 'IN_REVIEW', 'COMPLETED', 'NEEDS_REDACTION', 'ESCALATED', 'CANCELLED'"
)
_UNIFIED_DECISION_VALUES = (
    "'READY_FOR_HUMAN_REVIEW', 'REVIEW_REQUIRED', 'REDACTION_FAILED', "
    "'REDACTION_INCOMPLETE', 'QUALITY_DEGRADED', 'GEOMETRY_INVALID', 'REVIEW_COMPLETED'"
)
_HUMAN_DETERMINATION_VALUES = "'approved', 'rejected', 're_redaction_requested'"


def upgrade() -> None:
    """Apply Phase 77 biometric quality review schema."""
    op.create_table(
        "biometric_quality_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "department_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("evidence_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "governance_record_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("biometric_governance_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column("unified_decision", sa.String(length=32), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("component_versions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("photometric_metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("geometry_metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "assigned_reviewer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assigned_at", UTCDateTime(), nullable=True),
        sa.Column(
            "reviewed_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", UTCDateTime(), nullable=True),
        sa.Column("human_determination", sa.String(length=32), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.Column("original_evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("redacted_artifact_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "disclaimer",
            sa.Text(),
            nullable=False,
            server_default=(
                "Face detection identifies bounding box coordinates for authorized forensic review "
                "or privacy redaction. It does NOT establish identity, infer emotion or character, "
                "or make autonomous disciplinary or legal determinations."
            ),
        ),
        sa.Column(
            "created_at",
            UTCDateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="ck_biometric_quality_review_status",
        ),
        sa.CheckConstraint(
            f"unified_decision IN ({_UNIFIED_DECISION_VALUES})",
            name="ck_biometric_quality_review_unified_decision",
        ),
        sa.CheckConstraint(
            f"human_determination IS NULL OR human_determination IN ({_HUMAN_DETERMINATION_VALUES})",
            name="ck_biometric_quality_review_human_determination",
        ),
    )

    op.create_index(
        "ix_biometric_quality_review_tenant_dept_status",
        "biometric_quality_reviews",
        ["tenant_id", "department_id", "status"],
    )
    op.create_index(
        "ix_biometric_quality_review_evidence_id",
        "biometric_quality_reviews",
        ["evidence_id"],
    )
    op.create_index(
        "ix_biometric_quality_review_assigned_reviewer",
        "biometric_quality_reviews",
        ["assigned_reviewer_id"],
    )


def downgrade() -> None:
    """Drop Phase 77 biometric quality review schema."""
    op.drop_index(
        "ix_biometric_quality_review_assigned_reviewer",
        table_name="biometric_quality_reviews",
    )
    op.drop_index(
        "ix_biometric_quality_review_evidence_id",
        table_name="biometric_quality_reviews",
    )
    op.drop_index(
        "ix_biometric_quality_review_tenant_dept_status",
        table_name="biometric_quality_reviews",
    )
    op.drop_table("biometric_quality_reviews")
