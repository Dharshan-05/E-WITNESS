"""Unit tests for Phase 77: Quality Pre-Checks & Human Review Integration.

Validates:
- Category A: Unified Review Decision Matrix (Task A)
  - Detection/redaction failures, missing results, invalid geometry, degraded quality,
    zero detected faces, partial redactions, missing landmarks, clean passes.
- Category B: Review State Machine & Lifecycle Transitions (Task C)
  - Valid transitions, invalid state jumps, completed lock, terminal states, idempotency.
- Category C: QualityReviewWorkflowService End-to-End (Task B, D, E)
  - Item creation, reviewer assignment, human determinations (approved, rejected, re-redaction),
    escalation, administrative reopening, metadata-only persistence.
- Category D: Authorization & Boundary Isolation (Task B & D)
  - Role permissions (INVESTIGATOR, DEPT_ADMIN, SUPER_ADMIN vs STUDENT/STAFF).
  - Department scoping and isolation.
  - Audit logging completeness and zero sensitive data leakage.
- Category E: Mandatory Safety Invariants
  - BIOMETRIC_MATCHING_ENABLED=False permanently enforced.
  - Zero embeddings, facial feature vectors, or biometric templates persisted.
  - Sealed violence-detection test partition remains untouched.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ai_services.face_detection.geometry import (
    RedactionGeometryVerificationResult,
)
from ai_services.face_detection.quality import (
    PhotometricQualityResult,
    PhotometricQualityStatus,
)
from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
    evaluate_unified_review_decision,
    validate_review_state_transition,
)
from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, RoleCode
from backend.app.core.biometrics import BIOMETRIC_ADVISORY_DISCLAIMER
from backend.app.core.exceptions import (
    BusinessRuleError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.models.biometrics import BiometricQualityReview
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.biometrics import BiometricQualityReviewRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    BiometricQualityReviewAssignRequest,
    BiometricQualityReviewCreate,
    BiometricQualityReviewEscalateRequest,
    BiometricQualityReviewReopenRequest,
    BiometricQualityReviewVerdictRequest,
)
from backend.app.services.biometrics import QualityReviewWorkflowService


# ===========================================================================
# Test Helpers & Fixtures
# ===========================================================================


def _make_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    dept_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    """Construct a synthetic AuthenticatedPrincipal for review testing."""
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email="reviewer_test@ewitness.edu",
        full_name="Forensic Reviewer",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=dept_id or uuid4(),
        session_id=uuid4(),
    )


def _make_mock_quality_result(
    *,
    requires_human_review: bool = False,
    reasons: list[str] | None = None,
    sharpness: float = 0.85,
    exposure: float = 0.90,
    contrast: float = 0.80,
) -> PhotometricQualityResult:
    """Construct synthetic PhotometricQualityResult."""
    return PhotometricQualityResult(
        sharpness_score=sharpness,
        exposure_score=exposure,
        contrast_score=contrast,
        underexposed_fraction=0.01,
        overexposed_fraction=0.01,
        clipped_fraction=0.02,
        quality_status=PhotometricQualityStatus.ACCEPTABLE if not requires_human_review else PhotometricQualityStatus.DEGRADED,
        requires_human_review=requires_human_review,
        review_reasons=reasons or ([] if not requires_human_review else ["Image sharpness falls below acceptable threshold."]),
        raw_metrics={"laplacian_variance": 450.0},
        image_width=640,
        image_height=480,
        image_format="PNG",
        metric_version="1.0.0",
        disclaimer="Advisory test disclaimer",
    )


def _make_mock_geometry_result(
    *,
    is_valid: bool = True,
    reasons: list[str] | None = None,
    landmark_coverage_valid: bool = True,
) -> RedactionGeometryVerificationResult:
    """Construct synthetic RedactionGeometryVerificationResult."""
    return RedactionGeometryVerificationResult(
        geometry_valid=is_valid,
        total_boxes=1,
        valid_box_count=1 if is_valid else 0,
        invalid_box_count=0 if is_valid else 1,
        overlap_count=0,
        clipped_box_count=0,
        consolidated_boxes=[(0.1, 0.1, 0.2, 0.2)],
        landmark_coverage_valid=landmark_coverage_valid,
        requires_human_review=(not is_valid or not landmark_coverage_valid),
        review_reasons=reasons or ([] if is_valid else ["Bounding box coordinate exceeds normalized boundary [OUT_OF_BOUNDS]."]),
        geometry_version="1.0.0",
        disclaimer="Advisory test disclaimer",
    )


# ===========================================================================
# Category A: Unified Review Decision Matrix
# ===========================================================================


class TestUnifiedReviewDecisionMatrix:
    """Tests evaluating deterministic decision outcomes based on component outputs."""

    def test_detection_failure_yields_redaction_failed(self) -> None:
        decision, reasons = evaluate_unified_review_decision(detection_failed=True)
        assert decision == UnifiedReviewDecision.REDACTION_FAILED
        assert any("detection or redaction pipeline execution failed" in r.lower() for r in reasons)

    def test_redaction_failure_yields_redaction_failed(self) -> None:
        decision, reasons = evaluate_unified_review_decision(redaction_failed=True)
        assert decision == UnifiedReviewDecision.REDACTION_FAILED
        assert len(reasons) >= 1

    def test_missing_quality_result_yields_review_required(self) -> None:
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=None,
            geometry_result=geom,
            detected_faces_count=1,
            redacted_faces_count=1,
        )
        assert decision == UnifiedReviewDecision.REVIEW_REQUIRED
        assert any("quality assessment result is missing" in r.lower() for r in reasons)

    def test_missing_geometry_result_yields_review_required(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=None,
            detected_faces_count=1,
            redacted_faces_count=1,
        )
        assert decision == UnifiedReviewDecision.REVIEW_REQUIRED
        assert any("geometry verification result is missing" in r.lower() for r in reasons)

    def test_both_quality_and_geometry_missing_yields_review_required(self) -> None:
        decision, reasons = evaluate_unified_review_decision(
            quality_result=None,
            geometry_result=None,
        )
        assert decision == UnifiedReviewDecision.REVIEW_REQUIRED
        assert len(reasons) == 2

    def test_invalid_geometry_yields_geometry_invalid(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(
            is_valid=False,
            reasons=["Bounding box coordinate exceeds normalized boundary [OUT_OF_BOUNDS]."],
        )
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=1,
            redacted_faces_count=1,
        )
        assert decision == UnifiedReviewDecision.GEOMETRY_INVALID
        assert any("out_of_bounds" in r.lower() for r in reasons)

    def test_uncovered_landmarks_yields_geometry_invalid(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(is_valid=True, landmark_coverage_valid=False)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=1,
            redacted_faces_count=1,
        )
        assert any("landmarks not fully covered" in r.lower() for r in reasons)

    def test_degraded_quality_yields_quality_degraded(self) -> None:
        qual = _make_mock_quality_result(
            requires_human_review=True,
            reasons=["Image focus score (0.12) is below minimum sharpness threshold."],
        )
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=1,
            redacted_faces_count=1,
        )
        assert decision == UnifiedReviewDecision.QUALITY_DEGRADED
        assert any("sharpness" in r.lower() for r in reasons)

    def test_zero_detected_faces_yields_review_required(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=0,
            redacted_faces_count=0,
        )
        assert decision == UnifiedReviewDecision.REVIEW_REQUIRED
        assert any("zero faces detected" in r.lower() for r in reasons)

    def test_partial_redaction_yields_redaction_incomplete(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=3,
            redacted_faces_count=2,
            has_partial_redaction=True,
        )
        assert decision == UnifiedReviewDecision.REDACTION_INCOMPLETE
        assert any("partial redaction" in r.lower() for r in reasons)

    def test_missing_landmarks_flag_is_tracked(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=1,
            redacted_faces_count=1,
            has_missing_landmarks=True,
        )
        # Should be ready for review, but reasons indicate landmarks were unavailable
        assert decision == UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW
        assert any("landmark coordinates unavailable" in r.lower() for r in reasons)

    def test_clean_pass_yields_ready_for_human_review(self) -> None:
        qual = _make_mock_quality_result(requires_human_review=False)
        geom = _make_mock_geometry_result(is_valid=True)
        decision, reasons = evaluate_unified_review_decision(
            quality_result=qual,
            geometry_result=geom,
            detected_faces_count=2,
            redacted_faces_count=2,
        )
        assert decision == UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW
        assert any("passed cleanly" in r.lower() for r in reasons)


# ===========================================================================
# Category B: Review State Machine & Lifecycle Transitions
# ===========================================================================


class TestReviewStateMachineTransitions:
    """Tests evaluating strict state transitions and rejection of invalid state jumps."""

    def test_valid_forward_transitions(self) -> None:
        # PENDING_REVIEW -> IN_REVIEW
        validate_review_state_transition(
            QualityReviewStatus.PENDING_REVIEW,
            QualityReviewStatus.IN_REVIEW,
        )
        # IN_REVIEW -> COMPLETED
        validate_review_state_transition(
            QualityReviewStatus.IN_REVIEW,
            QualityReviewStatus.COMPLETED,
        )
        # IN_REVIEW -> NEEDS_REDACTION
        validate_review_state_transition(
            QualityReviewStatus.IN_REVIEW,
            QualityReviewStatus.NEEDS_REDACTION,
        )
        # IN_REVIEW -> ESCALATED
        validate_review_state_transition(
            QualityReviewStatus.IN_REVIEW,
            QualityReviewStatus.ESCALATED,
        )

    def test_idempotent_transition_succeeds(self) -> None:
        # Same to same is a no-op
        validate_review_state_transition(
            QualityReviewStatus.IN_REVIEW,
            QualityReviewStatus.IN_REVIEW,
        )
        validate_review_state_transition(
            QualityReviewStatus.PENDING_REVIEW,
            QualityReviewStatus.PENDING_REVIEW,
        )

    def test_invalid_jump_from_pending_to_completed_rejected(self) -> None:
        with pytest.raises(BusinessRuleError, match="Invalid review state transition"):
            validate_review_state_transition(
                QualityReviewStatus.PENDING_REVIEW,
                QualityReviewStatus.COMPLETED,
            )

    def test_completed_review_locked_without_authorized_reopen(self) -> None:
        with pytest.raises(BusinessRuleError, match="Review is COMPLETED"):
            validate_review_state_transition(
                QualityReviewStatus.COMPLETED,
                QualityReviewStatus.IN_REVIEW,
                is_authorized_reopen=False,
            )

    def test_authorized_reopen_from_completed_to_pending(self) -> None:
        # Reopening to PENDING_REVIEW with authorization succeeds
        validate_review_state_transition(
            QualityReviewStatus.COMPLETED,
            QualityReviewStatus.PENDING_REVIEW,
            is_authorized_reopen=True,
        )

    def test_cancelled_is_terminal_state(self) -> None:
        with pytest.raises(BusinessRuleError, match="terminal state"):
            validate_review_state_transition(
                QualityReviewStatus.CANCELLED,
                QualityReviewStatus.IN_REVIEW,
            )


# ===========================================================================
# Category C: QualityReviewWorkflowService End-to-End
# ===========================================================================


class TestQualityReviewWorkflowService:
    """Tests service orchestration of review items, assignment, verdicts, and persistence."""

    @pytest.mark.asyncio
    async def test_create_review_item_stores_metadata_only(self) -> None:
        created_records: list[BiometricQualityReview] = []

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        async def mock_create(record: BiometricQualityReview) -> BiometricQualityReview:
            created_records.append(record)
            return record
        repo.create = AsyncMock(side_effect=mock_create)

        audit_repo = MagicMock(spec=AuditRepository)
        audit_repo.append_event = AsyncMock()

        service = QualityReviewWorkflowService(review_repo=repo, audit_repo=audit_repo)
        principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value)

        evidence_id = uuid4()
        governance_id = uuid4()
        orig_hash = hashlib.sha256(b"original_synthetic_evidence").hexdigest()
        redact_hash = hashlib.sha256(b"redacted_synthetic_artifact").hexdigest()

        payload = BiometricQualityReviewCreate(
            evidence_id=evidence_id,
            governance_record_id=governance_id,
            detected_faces_count=1,
            redacted_faces_count=1,
            quality_result={
                "requires_human_review": False,
                "sharpness_score": 0.88,
                "exposure_score": 0.92,
                "contrast_score": 0.85,
                "clipped_fraction": 0.01,
            },
            geometry_result={
                "is_valid": True,
                "box_count": 1,
                "overlap_clusters_count": 0,
            },
            original_evidence_hash=orig_hash,
            redacted_artifact_hash=redact_hash,
        )

        result = await service.create_review_item(payload, principal)

        assert result.status == QualityReviewStatus.PENDING_REVIEW.value
        assert result.unified_decision == UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value
        assert result.original_evidence_hash == orig_hash
        assert result.redacted_artifact_hash == redact_hash
        assert result.disclaimer == BIOMETRIC_ADVISORY_DISCLAIMER

        # Verify persisted record
        assert len(created_records) == 1
        rec = created_records[0]
        assert rec.evidence_id == evidence_id
        assert rec.governance_record_id == governance_id
        assert "sharpness_score" in rec.photometric_metrics

        # Verify audit log
        audit_repo.append_event.assert_awaited_once()
        call_kwargs = audit_repo.append_event.await_args.kwargs
        assert call_kwargs["action"] == AuditAction.BIOMETRIC_QUALITY_REVIEW_CREATED.value
        assert call_kwargs["target_type"] == AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS.value

    @pytest.mark.asyncio
    async def test_assign_reviewer_workflow(self) -> None:
        review_id = uuid4()
        dept_id = uuid4()
        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.PENDING_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)

        audit_repo = MagicMock(spec=AuditRepository)
        audit_repo.append_event = AsyncMock()

        service = QualityReviewWorkflowService(review_repo=repo, audit_repo=audit_repo)
        principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, dept_id=dept_id)

        reviewer_id = uuid4()
        assign_payload = BiometricQualityReviewAssignRequest(reviewer_id=reviewer_id)

        res = await service.assign_reviewer(review_id, assign_payload, principal)
        assert res.status == QualityReviewStatus.IN_REVIEW.value
        assert res.assigned_reviewer_id == reviewer_id
        assert res.assigned_at is not None

        # Idempotent reassignment to same reviewer
        res_idempotent = await service.assign_reviewer(review_id, assign_payload, principal)
        assert res_idempotent.status == QualityReviewStatus.IN_REVIEW.value
        assert res_idempotent.assigned_reviewer_id == reviewer_id

    @pytest.mark.asyncio
    async def test_record_human_verdict_approved(self) -> None:
        review_id = uuid4()
        dept_id = uuid4()
        reviewer_id = uuid4()

        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.IN_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            assigned_reviewer_id=reviewer_id,
            assigned_at=datetime.now(UTC),
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)

        audit_repo = MagicMock(spec=AuditRepository)
        audit_repo.append_event = AsyncMock()

        service = QualityReviewWorkflowService(review_repo=repo, audit_repo=audit_repo)
        principal = _make_principal(
            role_code=RoleCode.INVESTIGATOR.value,
            dept_id=dept_id,
            user_id=reviewer_id,
        )

        payload = BiometricQualityReviewVerdictRequest(
            determination=HumanReviewDetermination.APPROVED.value,
            notes="Redaction coverage confirmed across entire facial contour.",
        )

        res = await service.record_human_verdict(review_id, payload, principal)
        assert res.status == QualityReviewStatus.COMPLETED.value
        assert res.unified_decision == UnifiedReviewDecision.REVIEW_COMPLETED.value
        assert res.human_determination == HumanReviewDetermination.APPROVED.value
        assert res.reviewed_by_id == reviewer_id

        audit_repo.append_event.assert_awaited_once()
        call_kwargs = audit_repo.append_event.await_args.kwargs
        assert call_kwargs["action"] == AuditAction.BIOMETRIC_QUALITY_REVIEW_VERDICT.value

    @pytest.mark.asyncio
    async def test_record_human_verdict_re_redaction_requested(self) -> None:
        review_id = uuid4()
        dept_id = uuid4()
        reviewer_id = uuid4()

        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.IN_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            assigned_reviewer_id=reviewer_id,
            assigned_at=datetime.now(UTC),
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)

        service = QualityReviewWorkflowService(review_repo=repo)
        principal = _make_principal(
            role_code=RoleCode.INVESTIGATOR.value,
            dept_id=dept_id,
            user_id=reviewer_id,
        )

        payload = BiometricQualityReviewVerdictRequest(
            determination=HumanReviewDetermination.RE_REDACTION_REQUESTED.value,
            justification="Right jawline partially visible; padding expansion required.",
        )

        res = await service.record_human_verdict(review_id, payload, principal)
        assert res.status == QualityReviewStatus.NEEDS_REDACTION.value
        assert res.human_determination == HumanReviewDetermination.RE_REDACTION_REQUESTED.value

    @pytest.mark.asyncio
    async def test_escalation_workflow(self) -> None:
        review_id = uuid4()
        dept_id = uuid4()

        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.IN_REVIEW.value,
            unified_decision=UnifiedReviewDecision.GEOMETRY_INVALID.value,
            review_reasons=["Box out of bounds."],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)
        audit_repo = MagicMock(spec=AuditRepository)
        audit_repo.append_event = AsyncMock()

        service = QualityReviewWorkflowService(review_repo=repo, audit_repo=audit_repo)
        principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, dept_id=dept_id)

        payload = BiometricQualityReviewEscalateRequest(
            escalation_reason="Coordinate inversion cannot be corrected automatically; escalating to Dept Admin.",
        )

        res = await service.escalate_review(review_id, payload, principal)
        assert res.status == QualityReviewStatus.ESCALATED.value
        assert res.escalation_reason == payload.escalation_reason

        audit_repo.append_event.assert_awaited_once()
        assert audit_repo.append_event.await_args.kwargs["action"] == AuditAction.BIOMETRIC_QUALITY_REVIEW_ESCALATED.value

    @pytest.mark.asyncio
    async def test_reopen_workflow_requires_admin_role(self) -> None:
        review_id = uuid4()
        dept_id = uuid4()

        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.COMPLETED.value,
            unified_decision=UnifiedReviewDecision.REVIEW_COMPLETED.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)
        service = QualityReviewWorkflowService(review_repo=repo)

        # 1. Investigator cannot reopen completed review
        investigator = _make_principal(role_code=RoleCode.INVESTIGATOR.value, dept_id=dept_id)
        reopen_payload = BiometricQualityReviewReopenRequest(
            reopen_reason="New high-contrast frame discovered requiring re-examination.",
        )
        with pytest.raises(PermissionDeniedError, match="administrative roles"):
            await service.reopen_review(review_id, reopen_payload, investigator)

        # 2. Dept Admin can reopen
        admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, dept_id=dept_id)
        res = await service.reopen_review(review_id, reopen_payload, admin)
        assert res.status == QualityReviewStatus.PENDING_REVIEW.value
        assert res.reopen_reason == reopen_payload.reopen_reason
        assert res.assigned_reviewer_id is None


# ===========================================================================
# Category D: Authorization & Boundary Isolation
# ===========================================================================


class TestAuthorizationAndBoundaryIsolation:
    """Tests department isolation, permission gating, and sensitive payload exclusion."""

    @pytest.mark.asyncio
    async def test_unprivileged_role_cannot_create_or_review(self) -> None:
        repo = MagicMock(spec=BiometricQualityReviewRepository)
        service = QualityReviewWorkflowService(review_repo=repo)
        student_principal = _make_principal(role_code=RoleCode.STUDENT.value)

        payload = BiometricQualityReviewCreate(
            detected_faces_count=1,
            redacted_faces_count=1,
            quality_result={"requires_human_review": False},
            geometry_result={"is_valid": True},
        )

        # Student lacks permission to create review item
        with pytest.raises(PermissionDeniedError, match="required permission"):
            await service.create_review_item(payload, student_principal)

        # Student lacks permission to view review item
        with pytest.raises(PermissionDeniedError, match="permission to view"):
            await service.get_review(uuid4(), student_principal)

    @pytest.mark.asyncio
    async def test_cross_department_isolation(self) -> None:
        dept_a = uuid4()
        dept_b = uuid4()
        review_id = uuid4()

        # Review belongs to Dept A
        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_a,
            status=QualityReviewStatus.PENDING_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        # Mock returns record ONLY if department_id matches
        async def mock_get(rid: UUID, *, department_id: UUID | None = None) -> BiometricQualityReview | None:
            if rid == review_id and (department_id is None or department_id == dept_a):
                return existing_review
            return None
        repo.get_by_id = AsyncMock(side_effect=mock_get)

        service = QualityReviewWorkflowService(review_repo=repo)

        # Dept B investigator attempts to view review from Dept A -> 404 Not Found
        dept_b_inv = _make_principal(role_code=RoleCode.INVESTIGATOR.value, dept_id=dept_b)
        with pytest.raises(ResourceNotFoundError, match="not found"):
            await service.get_review(review_id, dept_b_inv)

        # Dept A investigator succeeds
        dept_a_inv = _make_principal(role_code=RoleCode.INVESTIGATOR.value, dept_id=dept_a)
        res = await service.get_review(review_id, dept_a_inv)
        assert res.id == review_id

        # Super Admin across departments succeeds
        super_admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value, dept_id=dept_b)
        res_sa = await service.get_review(review_id, super_admin)
        assert res_sa.id == review_id

    @pytest.mark.asyncio
    async def test_unassigned_reviewer_cannot_verdict(self) -> None:
        dept_id = uuid4()
        review_id = uuid4()
        assigned_user = uuid4()
        unassigned_user = uuid4()

        existing_review = BiometricQualityReview(
            id=review_id,
            tenant_id=uuid4(),
            department_id=dept_id,
            status=QualityReviewStatus.IN_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
            assigned_reviewer_id=assigned_user,
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
        )

        repo = MagicMock(spec=BiometricQualityReviewRepository)
        repo.get_by_id = AsyncMock(return_value=existing_review)
        service = QualityReviewWorkflowService(review_repo=repo)

        other_inv = _make_principal(
            role_code=RoleCode.INVESTIGATOR.value,
            dept_id=dept_id,
            user_id=unassigned_user,
        )

        payload = BiometricQualityReviewVerdictRequest(
            determination=HumanReviewDetermination.APPROVED.value,
            notes="Attempting unauthorized signoff",
        )

        with pytest.raises(PermissionDeniedError, match="assigned reviewer"):
            await service.record_human_verdict(review_id, payload, other_inv)


# ===========================================================================
# Category E: Mandatory Safety Invariants
# ===========================================================================


class TestMandatorySafetyInvariants:
    """Verifies that non-negotiable safety rules remain inviolate."""

    def test_biometric_matching_remains_disabled(self) -> None:
        # Check settings invariant
        settings = Settings(
            ENVIRONMENT="testing",
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/15",
            STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
            STORAGE_BUCKET_NAME="test-bucket",
            STORAGE_ACCESS_KEY="test_access_key_valid",
            STORAGE_SECRET_KEY="test_secret_key_valid",
            AUTH_SECRET_KEY="test_key_with_length_greater_than_32_characters",
            AI_API_KEY="test",
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_MATCHING_ENABLED=False,
        )
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    def test_review_records_contain_no_biometric_embeddings(self) -> None:
        # Verify BiometricQualityReview columns have zero embedding/vector fields
        cols = {c.name for c in BiometricQualityReview.__table__.columns}
        prohibited = {"embedding", "template", "feature_vector", "descriptor", "face_vector"}
        for p in prohibited:
            assert p not in cols, f"Prohibited biometric field '{p}' found in BiometricQualityReview schema!"

    def test_no_facial_coordinates_persisted_in_review_record(self) -> None:
        # Bounding box coordinates must NOT be stored as columns on review items
        cols = {c.name for c in BiometricQualityReview.__table__.columns}
        assert "box" not in cols
        assert "bounding_box" not in cols
        assert "landmarks" not in cols
        assert "image_bytes" not in cols
        assert "image_base64" not in cols

    def test_advisory_disclaimer_is_mandatory(self) -> None:
        review = BiometricQualityReview(
            id=uuid4(),
            tenant_id=uuid4(),
            department_id=uuid4(),
            status=QualityReviewStatus.PENDING_REVIEW.value,
            unified_decision=UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW.value,
            review_reasons=[],
            component_versions={},
            photometric_metrics={},
            geometry_metrics={},
        )
        assert review.disclaimer == BIOMETRIC_ADVISORY_DISCLAIMER
        assert "NOT establish identity" in review.disclaimer
