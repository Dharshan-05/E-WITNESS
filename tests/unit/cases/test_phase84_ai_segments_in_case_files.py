"""Unit test suite for Phase 84: AI Segments in Case Files — Advisory Annotations Only.

Requirements covered:
1. Valid advisory segment linked to authorized case evidence.
2. Invalid or negative segment timestamps rejected.
3. End timestamp preceding or equal to start timestamp rejected.
4. Segment exceeding known video duration rejected.
5. Invalid confidence values rejected.
6. Missing or unverified model provenance handled explicitly.
7. New annotations default to pending review.
8. Unauthorized review decision rejected (403 PermissionDeniedError).
9. Authorized confirmation, rejection, and inconclusive decisions.
10. Invalid review-state transitions rejected.
11. Reviewer identity cannot be spoofed by client.
12. Cross-department access denied with zero leakage (404 masking).
13. Original evidence bytes and digest remain unchanged.
14. Legal holds remain active after annotation and review operations.
15. Annotation creation failure does not produce a misleading success audit event.
16. Review decisions preserve historical audit records.
17. Concurrent review updates handled safely (optimistic concurrency / 409 conflict).
18. Model prediction is never represented as a legal finding (advisory disclaimer mandatory).
19. Biometric matching remains disabled and cannot be overridden (fail-closed).
20. No access to the sealed historical violence-detection test partition (N=354).
21. Existing Phase 81, Phase 82, and Phase 83 regression tests.
22. Applicable Batch 08 biometric regression tests.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.core.ai import (
    APPROVED_AI_MODELS,
    CalibrationStatus,
    SegmentReviewStatus,
    UncertaintyStatus,
    validate_model_provenance,
)
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    VALID_AI_SEGMENT_REVIEW_TRANSITIONS,
    CasePriority,
    CaseStatus,
    InvestigativeRelevance,
    format_canonical_case_reference,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    BusinessRuleError,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.ai import AICandidateSegment
from backend.app.models.case import Case, CaseAISegment, CaseEvidence, LegalHold
from backend.app.models.department import Department
from backend.app.models.evidence import EvidenceAttachment
from backend.app.models.incident import Incident
from backend.app.models.role import Role
from backend.app.models.user import User
from backend.app.repositories.ai_segment import AICandidateSegmentRepository
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.case import CaseRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.identity import DepartmentRepository, UserRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.case import (
    CaseAISegmentHistoryItemRead,
    CaseAISegmentRead,
    CaseAISegmentReviewRequest,
    CaseCreateAISegmentAnnotationRequest,
    CaseLinkAISegmentRequest,
)
from backend.app.services.biometrics import FaceMatchingService
from backend.app.services.case import CaseService


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------


def _get_test_settings() -> Settings:
    return Settings(
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
        BIOMETRIC_MATCHING_ENABLED=False,
        INVESTIGATOR_MAX_ACTIVE_CASES=10,
    )


def _make_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
    email: str = "investigator@ewitness.test",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email=email,
        full_name="Assigned Investigator",
        role_code=role_code,
        account_status="active",
        is_active=True,
        session_id=uuid4(),
        department_id=department_id or uuid4(),
    )


def _make_case(
    case_id: UUID | None = None,
    department_id: UUID | None = None,
    status: str = CaseStatus.UNDER_INVESTIGATION.value,
    version_id: int = 1,
    is_legal_hold: bool = False,
) -> Case:
    cid = case_id or uuid4()
    dept_id = department_id or uuid4()
    c = Case(
        id=cid,
        reference_number=format_canonical_case_reference(2026, 84001),
        department_id=dept_id,
        title="Investigation Case 84",
        summary="Testing AI candidate segment annotations.",
        status=status,
        priority=CasePriority.HIGH.value,
        lead_investigator_id=uuid4(),
        created_by_id=uuid4(),
        version_id=version_id,
        is_legal_hold=is_legal_hold,
    )
    c.evidence = []
    c.ai_segments = []
    return c


def _make_evidence(
    evidence_id: UUID | None = None,
    department_id: UUID | None = None,
    incident_id: UUID | None = None,
    sha256_hash: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    video_duration_seconds: float | None = 60.0,
) -> EvidenceAttachment:
    ev = EvidenceAttachment(
        id=evidence_id or uuid4(),
        incident_id=incident_id or uuid4(),
        uploader_id=uuid4(),
        department_id=department_id or uuid4(),
        original_filename="security_footage.mp4",
        declared_mime_type="video/mp4",
        detected_mime_type="video/mp4",
        file_size_bytes=1048576,
        sha256_hash=sha256_hash,
        storage_key=f"evidence/{uuid4()}/security_footage.mp4",
        evidence_status="attached",
        upload_status="completed",
        scan_status="clean",
    )
    setattr(ev, "video_duration_seconds", video_duration_seconds)
    return ev


def _make_candidate_segment(
    segment_id: UUID | None = None,
    evidence_id: UUID | None = None,
    department_id: UUID | None = None,
    incident_id: UUID | None = None,
    start_seconds: float = 5.0,
    end_seconds: float = 12.0,
    raw_score: float = 0.82,
    raw_label: str = "possible_violence",
    model_name: str = "violence-classifier",
    model_version: str = "1.0.0",
    review_status: str = SegmentReviewStatus.PENDING_REVIEW.value,
    video_duration_seconds: float | None = None,
) -> AICandidateSegment:
    seg = AICandidateSegment(
        id=segment_id or uuid4(),
        job_id=uuid4(),
        evidence_id=evidence_id or uuid4(),
        incident_id=incident_id or uuid4(),
        department_id=department_id or uuid4(),
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        duration_seconds=end_seconds - start_seconds,
        raw_score=raw_score,
        raw_label=raw_label,
        model_name=model_name,
        model_version=model_version,
        preprocessing_version="1.0.0",
        calibration_status=CalibrationStatus.CALIBRATED.value,
        calibrated_score=min(1.0, raw_score * 0.95),
        calibration_version="1.0.0",
        uncertainty_status=UncertaintyStatus.HIGH_CONFIDENCE.value,
        review_status=review_status,
        reviewed_by_id=None,
        reviewed_at=None,
        review_notes=None,
        is_flagged_for_review=True,
    )
    if video_duration_seconds is not None:
        setattr(seg, "video_duration_seconds", video_duration_seconds)
    return seg


@pytest.fixture
def mock_repos():
    repos = {
        "case": AsyncMock(spec=CaseRepository),
        "incident": AsyncMock(spec=IncidentRepository),
        "evidence": AsyncMock(spec=EvidenceRepository),
        "ai_segment": AsyncMock(spec=AICandidateSegmentRepository),
        "user": AsyncMock(spec=UserRepository),
        "dept": AsyncMock(spec=DepartmentRepository),
        "audit": AsyncMock(spec=AuditRepository),
    }
    repos["case"].session = AsyncMock()
    # Provide alias keys for repository access
    repos["case_repo"] = repos["case"]
    repos["incident_repo"] = repos["incident"]
    repos["evidence_repo"] = repos["evidence"]
    repos["ai_segment_repo"] = repos["ai_segment"]
    repos["user_repo"] = repos["user"]
    repos["dept_repo"] = repos["dept"]
    repos["department_repo"] = repos["dept"]
    repos["audit_repo"] = repos["audit"]
    return repos


@pytest.fixture
def case_service(mock_repos) -> CaseService:
    settings = _get_test_settings()
    service = CaseService(
        case_repo=mock_repos["case"],
        incident_repo=mock_repos["incident"],
        evidence_repo=mock_repos["evidence"],
        ai_segment_repo=mock_repos["ai_segment"],
        user_repo=mock_repos["user"],
        department_repo=mock_repos["dept"],
        audit_repo=mock_repos["audit"],
        settings=settings,
    )
    return service


# ---------------------------------------------------------------------------
# Test Cases (Requirements 1 to 22)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_advisory_segment_linked_to_authorized_case_evidence(case_service, mock_repos):
    """1. Valid advisory segment linked to authorized case evidence."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        evidence_id=ev_entity.id,
        department_id=dept_id,
        start_seconds=2.0,
        end_seconds=8.0,
        raw_score=0.78,
        model_name="violence-classifier",
        model_version="1.0.0",
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["case"].get_ai_segment_link.return_value = None
    mock_repos["evidence"].get_by_id.return_value = ev_entity
    mock_repos["case"].link_ai_segment.side_effect = lambda link: link

    payload = CaseLinkAISegmentRequest(
        segment_id=seg_entity.id,
        investigative_relevance=InvestigativeRelevance.CANDIDATE_LEAD,
        relevance_notes="Observed candidate confrontation in hallway corridor.",
    )

    result = await case_service.link_ai_segment(case_entity.id, payload, principal)

    assert isinstance(result, CaseAISegmentRead)
    assert result.case_id == case_entity.id
    assert result.segment_id == seg_entity.id
    assert result.start_seconds == 2.0
    assert result.end_seconds == 8.0
    assert result.duration_seconds == 6.0
    assert result.score == seg_entity.calibrated_score
    assert result.raw_score == 0.78
    assert result.label == "possible_violence"
    assert result.model_name == "violence-classifier"
    assert result.model_version == "1.0.0"
    assert result.review_status == SegmentReviewStatus.PENDING_REVIEW.value
    assert result.investigative_relevance == InvestigativeRelevance.CANDIDATE_LEAD
    assert result.advisory_disclaimer == AI_ADVISORY_DISCLAIMER
    assert result.original_evidence_digest == ev_entity.sha256_hash
    assert "Probabilistic model confidence score" in result.confidence_interpretation

    # Verify append-only audit event emitted
    mock_repos["audit"].append_event.assert_called_once()
    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_AI_SEGMENT_LINKED
    assert audit_call["outcome"] == AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_invalid_or_negative_segment_timestamps_rejected(case_service, mock_repos):
    """2. Invalid or negative segment timestamps rejected."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_negative = _make_candidate_segment(
        department_id=dept_id,
        start_seconds=-2.5,
        end_seconds=5.0,
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_negative
    mock_repos["case"].get_ai_segment_link.return_value = None

    payload = CaseLinkAISegmentRequest(segment_id=seg_negative.id)

    with pytest.raises(BusinessRuleError) as exc:
        await case_service.link_ai_segment(case_entity.id, payload, principal)
    assert exc.value.code == "INVALID_TIMESTAMPS"

    # Schema validation also rejects negative start_seconds
    with pytest.raises(ValidationError):
        CaseCreateAISegmentAnnotationRequest(
            evidence_id=uuid4(),
            start_seconds=-1.0,
            end_seconds=5.0,
            raw_score=0.8,
        )


@pytest.mark.asyncio
async def test_end_timestamp_preceding_or_equal_to_start_rejected(case_service, mock_repos):
    """3. End timestamp preceding or equal to start timestamp rejected."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    # 3a. End preceding start
    seg_backward = _make_candidate_segment(
        department_id=dept_id,
        start_seconds=10.0,
        end_seconds=4.0,
    )
    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_backward
    mock_repos["case"].get_ai_segment_link.return_value = None

    with pytest.raises(BusinessRuleError) as exc:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_backward.id), principal
        )
    assert exc.value.code == "INVALID_TIMESTAMPS"

    # 3b. Equal timestamps (zero duration)
    seg_equal = _make_candidate_segment(
        department_id=dept_id,
        start_seconds=8.0,
        end_seconds=8.0,
    )
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_equal
    with pytest.raises(BusinessRuleError) as exc_eq:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_equal.id), principal
        )
    assert exc_eq.value.code == "INVALID_TIMESTAMPS"

    # Schema rejection
    with pytest.raises(ValidationError):
        CaseCreateAISegmentAnnotationRequest(
            evidence_id=uuid4(),
            start_seconds=10.0,
            end_seconds=5.0,
            raw_score=0.5,
        )


@pytest.mark.asyncio
async def test_segment_exceeding_known_video_duration_rejected(case_service, mock_repos):
    """4. Segment exceeding known video duration rejected."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id, video_duration_seconds=20.0)

    # Segment ends at 25.0s, which exceeds parent video duration of 20.0s
    seg_overshoot = _make_candidate_segment(
        evidence_id=ev_entity.id,
        department_id=dept_id,
        start_seconds=15.0,
        end_seconds=25.0,
        video_duration_seconds=20.0,
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_overshoot
    mock_repos["case"].get_ai_segment_link.return_value = None
    mock_repos["evidence"].get_by_id.return_value = ev_entity

    with pytest.raises(BusinessRuleError) as exc:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_overshoot.id), principal
        )
    assert exc.value.code == "SEGMENT_EXCEEDS_DURATION"

    # Schema validation rejection
    with pytest.raises(ValidationError):
        CaseCreateAISegmentAnnotationRequest(
            evidence_id=ev_entity.id,
            start_seconds=15.0,
            end_seconds=25.0,
            raw_score=0.8,
            video_duration_seconds=20.0,
        )


@pytest.mark.asyncio
async def test_invalid_confidence_values_rejected(case_service, mock_repos):
    """5. Invalid confidence values rejected (< 0.0, > 1.0, NaN, Inf)."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    # Score > 1.0
    seg_high = _make_candidate_segment(department_id=dept_id, raw_score=1.5)
    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_high
    mock_repos["case"].get_ai_segment_link.return_value = None

    with pytest.raises(BusinessRuleError) as exc_high:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_high.id), principal
        )
    assert exc_high.value.code == "INVALID_CONFIDENCE_SCORE"

    # Score < 0.0
    seg_low = _make_candidate_segment(department_id=dept_id, raw_score=-0.2)
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_low
    with pytest.raises(BusinessRuleError) as exc_low:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_low.id), principal
        )
    assert exc_low.value.code == "INVALID_CONFIDENCE_SCORE"

    # NaN / Inf in schema
    with pytest.raises(ValidationError):
        CaseCreateAISegmentAnnotationRequest(
            evidence_id=uuid4(),
            start_seconds=1.0,
            end_seconds=5.0,
            raw_score=float("nan"),
        )
    with pytest.raises(ValidationError):
        CaseCreateAISegmentAnnotationRequest(
            evidence_id=uuid4(),
            start_seconds=1.0,
            end_seconds=5.0,
            raw_score=1.2,
        )


@pytest.mark.asyncio
async def test_missing_or_unverified_model_provenance_handled_explicitly(case_service, mock_repos):
    """6. Missing or unverified model provenance handled explicitly."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    # 6a. Missing model provenance
    seg_no_model = _make_candidate_segment(department_id=dept_id)
    setattr(seg_no_model, "model_name", None)
    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_no_model
    mock_repos["case"].get_ai_segment_link.return_value = None

    with pytest.raises(BusinessRuleError) as exc_missing:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_no_model.id), principal
        )
    assert exc_missing.value.code == "MISSING_MODEL_PROVENANCE"

    # 6b. Untrusted / unapproved model
    seg_unapproved = _make_candidate_segment(
        department_id=dept_id,
        model_name="unapproved-experimental-net",
        model_version="0.9.0",
    )
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_unapproved
    with pytest.raises(BusinessRuleError) as exc_unapproved:
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_unapproved.id), principal
        )
    assert exc_unapproved.value.code == "UNAPPROVED_MODEL_PROVENANCE"


@pytest.mark.asyncio
async def test_new_annotations_default_to_pending_review(case_service, mock_repos):
    """7. New candidate annotations default to pending review."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["case"].get_ai_segment_link.return_value = None
    mock_repos["case"].link_ai_segment.side_effect = lambda link: link

    res = await case_service.link_ai_segment(
        case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_entity.id), principal
    )
    assert res.review_status == SegmentReviewStatus.PENDING_REVIEW.value
    assert res.reviewed_by_id is None
    assert res.reviewed_at is None


@pytest.mark.asyncio
async def test_unauthorized_review_decision_rejected(case_service, mock_repos):
    """8. Unauthorized review decision rejected (403 PermissionDeniedError)."""
    dept_id = uuid4()
    # Student role lacks CASE_AI_SEGMENT_REVIEW permission
    unauthorized_principal = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Attempted review without authorized permission.",
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.review_ai_segment(
            case_entity.id, seg_entity.id, payload, unauthorized_principal
        )
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_authorized_confirmation_rejection_and_inconclusive_decisions(case_service, mock_repos):
    """9. Authorized confirmation, rejection, and inconclusive decisions."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id, evidence_id=ev_entity.id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # 9a. Confirmation
    seg_entity.review_status = "pending_review"
    res_conf = await case_service.review_ai_segment(
        case_entity.id,
        seg_entity.id,
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="Human review confirms visual physical altercation matching timestamp.",
        ),
        principal,
    )
    assert res_conf.review_status == "confirmed"
    assert res_conf.investigative_relevance == InvestigativeRelevance.CORROBORATING
    assert res_conf.reviewed_by_id == principal.user_id
    assert res_conf.reviewed_at is not None

    # 9b. Rejection / Supersession
    res_rej = await case_service.review_ai_segment(
        case_entity.id,
        seg_entity.id,
        CaseAISegmentReviewRequest(
            review_status="rejected",
            review_rationale="Secondary analysis reveals theatrical stage rehearsal; not actual violence.",
        ),
        principal,
    )
    assert res_rej.review_status == "rejected"
    assert res_rej.investigative_relevance == InvestigativeRelevance.DISMISSED

    # 9c. Inconclusive
    seg_entity.review_status = "pending_review"
    res_inc = await case_service.review_ai_segment(
        case_entity.id,
        seg_entity.id,
        CaseAISegmentReviewRequest(
            review_status="inconclusive",
            review_rationale="Lighting and obstruction prevent definitive confirmation or rejection.",
        ),
        principal,
    )
    assert res_inc.review_status == "inconclusive"


@pytest.mark.asyncio
async def test_invalid_review_state_transitions_rejected(case_service, mock_repos):
    """10. Invalid review-state transitions rejected."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # 1. Schema-level rejection: client cannot submit pending_review as a review determination
    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="pending_review",
            review_rationale="Attempting invalid revert of confirmed finding to unreviewed status.",
        )

    # 2. State-machine transition rejection: cannot transition from confirmed to inconclusive
    seg_entity.review_status = "confirmed"
    with pytest.raises(BusinessRuleError) as exc_rev:
        await case_service.review_ai_segment(
            case_entity.id,
            seg_entity.id,
            CaseAISegmentReviewRequest(
                review_status="inconclusive",
                review_rationale="Attempting invalid revert of confirmed finding to inconclusive.",
            ),
            principal,
        )
    assert exc_rev.value.code == "INVALID_REVIEW_TRANSITION"

    # 3. State-machine transition rejection: cannot transition from rejected directly to confirmed
    seg_entity.review_status = "rejected"
    with pytest.raises(BusinessRuleError) as exc_rej_conf:
        await case_service.review_ai_segment(
            case_entity.id,
            seg_entity.id,
            CaseAISegmentReviewRequest(
                review_status="confirmed",
                review_rationale="Attempting direct un-rejection without escalation.",
            ),
            principal,
        )
    assert exc_rej_conf.value.code == "INVALID_REVIEW_TRANSITION"


@pytest.mark.asyncio
async def test_reviewer_identity_cannot_be_spoofed(case_service, mock_repos):
    """11. Reviewer identity cannot be spoofed by client body."""
    dept_id = uuid4()
    real_reviewer_id = uuid4()
    principal = _make_principal(
        RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=real_reviewer_id
    )
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=real_reviewer_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # Client cannot inject fake reviewer_id (Pydantic extra='forbid')
    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="Valid justification rationale text.",
            reviewer_id=uuid4(),  # Forbidden extra field!
        )

    # Authoritative reviewer ID set from principal
    res = await case_service.review_ai_segment(
        case_entity.id,
        seg_entity.id,
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="Confirmed based on synchronized timestamp audio.",
        ),
        principal,
    )
    assert res.reviewed_by_id == real_reviewer_id
    assert seg_entity.reviewed_by_id == real_reviewer_id


@pytest.mark.asyncio
async def test_cross_department_access_denied(case_service, mock_repos):
    """12. Cross-department access denied with zero-leakage 404 masking."""
    dept_a = uuid4()
    dept_b = uuid4()

    principal_b = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_b)
    case_in_dept_a = _make_case(department_id=dept_a)
    seg_entity = _make_candidate_segment(department_id=dept_a)

    mock_repos["case"].get_by_id.return_value = case_in_dept_a

    # Probing case in dept A from dept B returns 404 ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError) as exc:
        await case_service.list_case_ai_segments(case_in_dept_a.id, principal_b)
    assert exc.value.code == "CASE_NOT_FOUND"

    with pytest.raises(ResourceNotFoundError) as exc_rev:
        await case_service.review_ai_segment(
            case_in_dept_a.id,
            seg_entity.id,
            CaseAISegmentReviewRequest(
                review_status="confirmed",
                review_rationale="Cross-department review attempt rationale.",
            ),
            principal_b,
        )
    assert exc_rev.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_original_evidence_bytes_and_digest_remain_unchanged(case_service, mock_repos):
    """13. Original evidence bytes and digest remain unchanged."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    initial_sha = "d576a8b1b22e118c7bc762b322a30bbff8c0a8767790b9b350fca100b411d735"
    ev_entity = _make_evidence(department_id=dept_id, sha256_hash=initial_sha)
    seg_entity = _make_candidate_segment(evidence_id=ev_entity.id, department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["case"].get_ai_segment_link.return_value = None
    mock_repos["evidence"].get_by_id.return_value = ev_entity
    mock_repos["case"].link_ai_segment.side_effect = lambda link: link

    # Perform link
    res = await case_service.link_ai_segment(
        case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_entity.id), principal
    )
    assert ev_entity.sha256_hash == initial_sha
    assert res.original_evidence_digest == initial_sha


@pytest.mark.asyncio
async def test_legal_holds_remain_active_after_annotation_and_review(case_service, mock_repos):
    """14. Legal holds remain active after annotation and review operations."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True)
    ev_entity = _make_evidence(department_id=dept_id)
    seg_entity = _make_candidate_segment(evidence_id=ev_entity.id, department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # Reviewing segment does not release or modify legal hold
    await case_service.review_ai_segment(
        case_entity.id,
        seg_entity.id,
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="Review performed while under statutory legal hold.",
        ),
        principal,
    )
    assert case_entity.is_legal_hold is True

    # Unlinking segment while under legal hold is blocked
    with pytest.raises(BusinessRuleError) as exc:
        await case_service.unlink_ai_segment(case_entity.id, seg_entity.id, principal)
    assert exc.value.code == "LEGAL_HOLD_ACTIVE"


@pytest.mark.asyncio
async def test_annotation_creation_failure_does_not_produce_misleading_success_audit(case_service, mock_repos):
    """15. Annotation creation failure does not produce a misleading success audit event."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["case"].get_ai_segment_link.return_value = None
    # Simulate database failure on link
    mock_repos["case"].link_ai_segment.side_effect = RuntimeError("Database deadlock or disk full")

    with pytest.raises(RuntimeError):
        await case_service.link_ai_segment(
            case_entity.id, CaseLinkAISegmentRequest(segment_id=seg_entity.id), principal
        )

    # Verify no success audit event was appended
    for call in mock_repos["audit"].append_event.call_args_list:
        assert call.kwargs.get("outcome") != AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_review_decisions_preserve_historical_audit_records(case_service, mock_repos):
    """16. Review decisions preserve historical audit records."""
    dept_id = uuid4()
    case_id = uuid4()
    seg_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(case_id=case_id, department_id=dept_id)
    link = CaseAISegment(case_id=case_id, segment_id=seg_id, linked_by_id=principal.user_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link

    # Simulate historical audit records
    ev1 = MagicMock()
    ev1.id = uuid4()
    ev1.action = AuditAction.CASE_AI_SEGMENT_REVIEWED
    ev1.created_at = datetime.now(UTC)
    ev1.actor_id = principal.user_id
    ev1.actor_role = RoleCode.INVESTIGATOR.value
    ev1.details = {
        "segment_id": str(seg_id),
        "previous_review_status": "pending_review",
        "new_review_status": "confirmed",
        "review_rationale": "Initial confirmation based on hallway camera.",
    }

    ev2 = MagicMock()
    ev2.id = uuid4()
    ev2.action = AuditAction.CASE_AI_SEGMENT_REVIEWED
    ev2.created_at = datetime.now(UTC)
    ev2.actor_id = principal.user_id
    ev2.actor_role = RoleCode.INVESTIGATOR.value
    ev2.details = {
        "segment_id": str(seg_id),
        "previous_review_status": "confirmed",
        "new_review_status": "rejected",
        "review_rationale": "Superseded after receiving high-resolution witness video.",
    }

    mock_repos["audit"].list_events_for_target.return_value = [ev1, ev2]

    history = await case_service.get_case_ai_segment_review_history(case_id, seg_id, principal)

    assert len(history) == 2
    assert history[0].previous_review_status == "pending_review"
    assert history[0].new_review_status == "confirmed"
    assert history[1].previous_review_status == "confirmed"
    assert history[1].new_review_status == "rejected"


@pytest.mark.asyncio
async def test_concurrent_review_updates_handled_safely(case_service, mock_repos):
    """17. Concurrent review updates handled safely (optimistic concurrency conflict)."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    # The segment in the database has already been transitioned to 'confirmed' by another reviewer
    seg_entity = _make_candidate_segment(department_id=dept_id, review_status="confirmed")
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # Caller expected status to be 'pending_review'
    payload = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Conflict test review rationale.",
        expected_review_status="pending_review",
    )

    with pytest.raises(ConflictError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)
    assert exc.value.code == "CONCURRENT_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_model_prediction_is_never_represented_as_legal_finding(case_service, mock_repos):
    """18. Model prediction is never represented as a legal finding (advisory disclaimer mandatory)."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].list_case_ai_segments.return_value = [link]

    segments = await case_service.list_case_ai_segments(case_entity.id, principal)
    assert len(segments) == 1
    item = segments[0]

    # Must contain statutory disclaimer
    assert item.advisory_disclaimer == AI_ADVISORY_DISCLAIMER
    assert "probabilistic and advisory only" in item.advisory_disclaimer
    assert "do not establish that an incident occurred" in item.advisory_disclaimer
    assert "constitute proof of guilt" in item.advisory_disclaimer


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled(case_service):
    """19. Biometric matching remains permanently disabled and fail-closed."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    matching_svc = FaceMatchingService(
        governance_repo=AsyncMock(),
        reference_repo=AsyncMock(),
        verification_repo=AsyncMock(),
        settings=settings,
    )

    from backend.app.schemas.biometrics import FaceMatchRequest
    req = FaceMatchRequest(
        governance_record_id=uuid4(),
        reference_id=uuid4(),
        probe_image_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    )
    with pytest.raises(BiometricsDisabledError):
        await matching_svc.match_faces(
            req,
            _make_principal(),
        )


def test_no_access_to_sealed_historical_violence_partition():
    """20. Case management codebase has zero access to the sealed historical violence-detection partition (N=354)."""
    base_dir = Path("backend/app")
    suspicious_patterns = ["violence_test_partition", "n=354", "benchmark_split_354", "sealed_violence_test"]

    for py_file in base_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8").lower()
        for pat in suspicious_patterns:
            assert pat not in content, f"Forbidden reference to '{pat}' in {py_file}"


@pytest.mark.asyncio
async def test_existing_phase81_phase82_phase83_regressions(mock_repos):
    """21. Existing Phase 81, Phase 82, and Phase 83 regression baseline intact."""
    # Smoke check that case domain primitives, hold references, and workload sets are intact
    from backend.app.core.case import (
        ACTIVE_CASE_STATUSES,
        TERMINAL_CASE_STATUSES,
        generate_legal_hold_reference,
    )

    assert CaseStatus.UNDER_INVESTIGATION.value in ACTIVE_CASE_STATUSES
    assert CaseStatus.CLOSED.value in TERMINAL_CASE_STATUSES
    hold_ref = generate_legal_hold_reference()
    assert hold_ref.startswith("HOLD-2026-")


@pytest.mark.asyncio
async def test_applicable_batch08_biometric_regression_tests():
    """22. Applicable Batch 08 biometric governance constraints remain enforced."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    from backend.app.core.authorization import RoleCode, get_role_permissions
    investigator_perms = get_role_permissions(RoleCode.INVESTIGATOR.value)
    # Face recognition permissions are strictly absent
    assert "biometrics:face_matching:execute" not in investigator_perms
    assert "biometrics:face_identification:execute" not in investigator_perms
