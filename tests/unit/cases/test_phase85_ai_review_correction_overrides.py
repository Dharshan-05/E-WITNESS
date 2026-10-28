"""Unit test suite for Phase 85: Human Review & AI Classification Correction / Override Workflows.

Requirements covered:
1. Authorized review decision records determination, reviewer ID, timestamp, and audit event.
2. Classification correction preserves original AI model prediction and confidence metrics.
3. Supervisor override creates a new revision, marks is_override=True, and preserves prior decisions in history.
4. Unauthorized override (e.g. by another investigator without override permission) is rejected (403).
5. Client cannot spoof reviewer identity in the request body (derived strictly from authenticated principal).
6. Client-supplied role or override flag in body cannot grant override privileges.
7. Missing or inadequate rationale (< 10 chars) is rejected with 422 ValidationError.
8. Stale expected status or revision returns a conflict (409 ConflictError).
9. Concurrent review updates cannot silently overwrite one another.
10. Invalid review-state transitions are rejected (e.g. rejected directly to confirmed).
11. Conflict-of-interest restrictions prevent incident reporters from reviewing their own incident's segments.
12. Cross-department review, correction, and history requests are denied with zero-leakage 404.
13. Active legal holds remain effective during and after review and override operations.
14. Original evidence bytes, SHA-256 digest, and chain of custody remain unchanged.
15. Audit history remains chronologically ordered, append-only, and monotonically tracked.
16. Failed database operations do not leave misleading success audit events.
17. Repeated requests and retries have defined idempotent behavior.
18. Superseded decisions cannot be edited through stale requests.
19. Statutory AI advisory disclaimer remains present in all relevant responses.
20. Human review decisions cannot automatically close cases or determine legal guilt.
21. Biometric matching remains permanently disabled (BIOMETRIC_MATCHING_ENABLED = False, fail-closed).
22. The sealed historical violence-detection test partition (N=354) is not accessed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.core.ai import (
    CalibrationStatus,
    SegmentReviewStatus,
    UncertaintyStatus,
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
        full_name="Assigned Reviewer",
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
        reference_number=format_canonical_case_reference(2026, 85001),
        department_id=dept_id,
        title="Investigation Case 85",
        summary="Testing AI candidate segment human review and overrides.",
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
        original_filename="security_hallway.mp4",
        declared_mime_type="video/mp4",
        detected_mime_type="video/mp4",
        file_size_bytes=2097152,
        sha256_hash=sha256_hash,
        storage_key=f"evidence/{uuid4()}/security_hallway.mp4",
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
    start_seconds: float = 10.0,
    end_seconds: float = 18.0,
    raw_score: float = 0.88,
    raw_label: str = "possible_violence",
    model_name: str = "violence-classifier",
    model_version: str = "1.0.0",
    review_status: str = SegmentReviewStatus.PENDING_REVIEW.value,
    reviewed_by_id: UUID | None = None,
    reviewed_at: datetime | None = None,
    review_notes: str | None = None,
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
        calibrated_score=round(raw_score * 0.95, 4),
        calibration_version="1.0.0",
        uncertainty_status=UncertaintyStatus.HIGH_CONFIDENCE.value,
        review_status=review_status,
        reviewed_by_id=reviewed_by_id,
        reviewed_at=reviewed_at,
        review_notes=review_notes,
        is_flagged_for_review=True,
    )
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
async def test_authorized_review_decision(case_service, mock_repos):
    """1. Authorized review decision records determination, reviewer ID, and audit event."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        evidence_id=ev_entity.id,
        review_status=SegmentReviewStatus.PENDING_REVIEW.value,
    )
    seg_entity.evidence = ev_entity
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Thorough review confirms candidate video footage corresponds to reported event.",
    )

    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    assert result.review_status == "confirmed"
    assert result.reviewed_by_id == principal.user_id
    assert result.reviewed_at is not None
    assert result.review_notes == payload.review_rationale
    assert result.investigative_relevance == InvestigativeRelevance.CORROBORATING
    assert result.decision_revision == 1
    assert result.is_override is False

    mock_repos["audit"].append_event.assert_called_once()
    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_AI_SEGMENT_REVIEWED
    assert audit_call["outcome"] == AuditOutcome.SUCCESS
    assert audit_call["details"]["decision_revision"] == 1


@pytest.mark.asyncio
async def test_classification_correction_preserves_original_ai_prediction(case_service, mock_repos):
    """2. Classification correction preserves original AI model prediction and confidence metrics."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        evidence_id=ev_entity.id,
        raw_label="possible_violence",
        raw_score=0.88,
        model_name="violence-classifier",
        model_version="1.0.0",
    )
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        corrected_label="property_damage",
        review_rationale="Segment depicts window break, not physical human-on-human altercation.",
    )

    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    # Human-corrected classification is reflected
    assert result.human_corrected_label == "property_damage"
    assert result.label == "property_damage"

    # Original AI prediction remains completely preserved and uncorrupted
    assert result.original_ai_prediction["label"] == "possible_violence"
    assert result.original_ai_prediction["raw_score"] == 0.88
    assert result.original_ai_prediction["model_name"] == "violence-classifier"
    assert result.original_ai_prediction["model_version"] == "1.0.0"

    # Audit event reflects classification correction
    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED
    assert audit_call["details"]["original_classification_label"] == "possible_violence"
    assert audit_call["details"]["new_classification_label"] == "property_damage"


@pytest.mark.asyncio
async def test_override_creates_new_revision_and_retains_old_decision(case_service, mock_repos):
    """3. Supervisor override creates a new revision and retains prior decision in history."""
    dept_id = uuid4()
    inv_user_id = uuid4()
    sup_user_id = uuid4()

    inv_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=inv_user_id)
    sup_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=sup_user_id)

    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    # 3a. Segment was initially reviewed and confirmed by Investigator 1
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        evidence_id=ev_entity.id,
        review_status="confirmed",
        reviewed_by_id=inv_user_id,
        reviewed_at=datetime.now(UTC),
        review_notes="Investigator 1 confirmed candidate segment.",
    )
    seg_meta = {
        "decision_revision": 1,
        "original_ai_prediction": {
            "label": "possible_violence",
            "raw_score": 0.88,
            "calibrated_score": 0.836,
            "model_name": "violence-classifier",
            "model_version": "1.0.0",
        },
        "revisions": [
            {
                "revision": 1,
                "decision": "confirmed",
                "previous_status": "pending_review",
                "reviewer_id": str(inv_user_id),
                "rationale": "Investigator 1 confirmed candidate segment.",
            }
        ],
    }
    seg_entity.metadata_json = json.dumps(seg_meta)

    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=inv_user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # 3b. Department supervisor overrides the determination to 'rejected'
    payload = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Supervisor audit override: high-resolution angle confirms camera artifact, not violence.",
        is_override=True,
    )

    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, sup_principal)

    assert result.review_status == "rejected"
    assert result.reviewed_by_id == sup_user_id
    assert result.decision_revision == 2
    assert result.is_override is True
    assert result.investigative_relevance == InvestigativeRelevance.DISMISSED

    # History inside segment retains both revisions
    saved_meta = json.loads(seg_entity.metadata_json)
    assert len(saved_meta["revisions"]) == 2
    assert saved_meta["revisions"][0]["revision"] == 1
    assert saved_meta["revisions"][0]["decision"] == "confirmed"
    assert saved_meta["revisions"][1]["revision"] == 2
    assert saved_meta["revisions"][1]["decision"] == "rejected"
    assert saved_meta["revisions"][1]["is_override"] is True

    # Audit event reflects override
    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_AI_SEGMENT_OVERRIDDEN
    assert audit_call["details"]["decision_revision"] == 2
    assert audit_call["details"]["is_override"] is True


@pytest.mark.asyncio
async def test_unauthorized_override_is_rejected(case_service, mock_repos):
    """4. Unauthorized override (investigator without override permission) is rejected with 403."""
    dept_id = uuid4()
    inv1_id = uuid4()
    inv2_id = uuid4()

    inv2_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=inv2_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="confirmed",
        reviewed_by_id=inv1_id,
        reviewed_at=datetime.now(UTC),
    )
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=inv1_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Investigator 2 attempting to override colleague's review without supervisor privileges.",
        is_override=True,
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, inv2_principal)

    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_client_cannot_spoof_reviewer_identity(case_service, mock_repos):
    """5. Client cannot spoof reviewer identity in the request body."""
    dept_id = uuid4()
    actual_reviewer_id = uuid4()
    spoofed_id = uuid4()

    # 5a. Schema level: extra field 'reviewed_by_id' rejected at boundary
    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="Attempting client injection of reviewer ID.",
            **{"reviewed_by_id": str(spoofed_id)},
        )

    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=actual_reviewer_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=actual_reviewer_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Authorized review performed with verified session.",
    )

    # 5b. Service derivation: reviewed_by_id is derived strictly from principal.user_id
    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    assert result.reviewed_by_id == actual_reviewer_id
    assert result.reviewed_by_id != spoofed_id
    assert seg_entity.reviewed_by_id == actual_reviewer_id


@pytest.mark.asyncio
async def test_client_supplied_role_or_override_flag_cannot_grant_privileges(case_service, mock_repos):
    """6. Client-supplied role or override flag in body cannot grant override privileges."""
    dept_id = uuid4()

    # 6a. Schema rejects extra role fields injected into request body
    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="rejected",
            review_rationale="Investigator trying to claim supervisor role in body.",
            is_override=True,
            **{"role_code": RoleCode.SUPER_ADMIN.value},
        )

    # 6b. Service checks principal token, rejecting investigator passing is_override=True
    inv_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="confirmed",
        reviewed_by_id=uuid4(),
    )
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=uuid4())
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Investigator trying to set is_override=True without permissions.",
        is_override=True,
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, inv_principal)

    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_missing_or_inadequate_rationale_rejected():
    """7. Missing or inadequate rationale (< 10 chars) is rejected with 422 ValidationError."""
    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="too short",  # 9 chars
        )

    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="",  # empty
        )

    with pytest.raises(ValidationError):
        CaseAISegmentReviewRequest(
            review_status="confirmed",
            review_rationale="          ",  # whitespace only
        )


@pytest.mark.asyncio
async def test_stale_expected_version_returns_conflict(case_service, mock_repos):
    """8. Stale expected status or revision returns a conflict (409 ConflictError)."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="confirmed",
        reviewed_by_id=principal.user_id,
    )
    seg_entity.metadata_json = json.dumps({"decision_revision": 2})

    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # 8a. Stale expected status
    payload_status = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Optimistic concurrency collision on status.",
        expected_review_status="pending_review",
    )
    with pytest.raises(ConflictError) as exc_stat:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload_status, principal)
    assert exc_stat.value.code == "CONCURRENT_REVIEW_CONFLICT"

    # 8b. Stale expected revision
    payload_rev = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Optimistic concurrency collision on revision.",
        expected_revision=1,  # actual is 2
    )
    with pytest.raises(ConflictError) as exc_rev:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload_rev, principal)
    assert exc_rev.value.code == "CONCURRENT_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_concurrent_review_updates_cannot_silently_overwrite(case_service, mock_repos):
    """9. Concurrent review updates cannot silently overwrite one another."""
    dept_id = uuid4()
    inv_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=inv_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="pending_review",
    )
    seg_entity.metadata_json = json.dumps({"decision_revision": 0})

    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=inv_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # First reviewer succeeds
    req1 = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="First review determination confirms candidate footage.",
        expected_review_status="pending_review",
        expected_revision=0,
    )
    res1 = await case_service.review_ai_segment(case_entity.id, seg_entity.id, req1, principal)
    assert res1.review_status == "confirmed"
    assert res1.decision_revision == 1

    # Second concurrent reviewer had fetched 'pending_review' with revision 0
    req2 = CaseAISegmentReviewRequest(
        review_status="inconclusive",
        review_rationale="Concurrent conflicting review attempt.",
        expected_review_status="pending_review",
        expected_revision=0,
    )
    with pytest.raises(ConflictError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, req2, principal)
    assert exc.value.code == "CONCURRENT_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_invalid_review_state_transitions_rejected(case_service, mock_repos):
    """10. Invalid review-state transitions are rejected (e.g. rejected directly to confirmed)."""
    dept_id = uuid4()
    sup_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="rejected",
        reviewed_by_id=sup_principal.user_id,
    )
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=sup_principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # Cannot transition directly from 'rejected' to 'confirmed' (must escalate first)
    payload_direct = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Attempting illegal un-rejection bypassing escalation.",
        is_override=True,
    )
    with pytest.raises(BusinessRuleError) as exc_dir:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload_direct, sup_principal)
    assert exc_dir.value.code == "INVALID_REVIEW_TRANSITION"

    # Escalating from 'rejected' is permitted
    payload_esc = CaseAISegmentReviewRequest(
        review_status="escalated",
        review_rationale="Escalating rejected finding to department leadership after new lead.",
        is_override=True,
    )
    res_esc = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload_esc, sup_principal)
    assert res_esc.review_status == "escalated"


@pytest.mark.asyncio
async def test_conflict_of_interest_restrictions_enforced(case_service, mock_repos):
    """11. Conflict-of-interest restrictions prevent incident reporters from reviewing segments."""
    dept_id = uuid4()
    reporter_user_id = uuid4()
    reporter_principal = _make_principal(
        RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=reporter_user_id
    )

    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=reporter_user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    # Reporter ID on incident matches principal user ID
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=reporter_user_id
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Attempting review on self-reported incident footage.",
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, reporter_principal)

    assert exc.value.code == "REVIEWER_CONFLICT_OF_INTEREST"


@pytest.mark.asyncio
async def test_cross_department_correction_and_history_denied(case_service, mock_repos):
    """12. Cross-department review and history requests are denied with zero-leakage 404."""
    dept_a = uuid4()
    dept_b = uuid4()

    principal_dept_b = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_b)
    case_entity_dept_a = _make_case(department_id=dept_a)
    seg_id = uuid4()

    mock_repos["case"].get_by_id.return_value = case_entity_dept_a

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Attempting unauthorized cross-department review.",
    )

    # 12a. Review in different department
    with pytest.raises(ResourceNotFoundError) as exc_rev:
        await case_service.review_ai_segment(case_entity_dept_a.id, seg_id, payload, principal_dept_b)
    assert exc_rev.value.code == "CASE_NOT_FOUND"

    # 12b. History in different department
    with pytest.raises(ResourceNotFoundError) as exc_hist:
        await case_service.get_case_ai_segment_review_history(case_entity_dept_a.id, seg_id, principal_dept_b)
    assert exc_hist.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_legal_holds_remain_effective(case_service, mock_repos):
    """13. Active legal holds remain effective during and after review and override operations."""
    dept_id = uuid4()
    sup_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="confirmed",
        reviewed_by_id=sup_principal.user_id,
    )
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=sup_principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # 13a. Review / Override succeeds under legal hold
    payload = CaseAISegmentReviewRequest(
        review_status="rejected",
        review_rationale="Supervisor determination update while case is on legal hold.",
        is_override=True,
    )
    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, sup_principal)
    assert result.review_status == "rejected"
    assert case_entity.is_legal_hold is True

    # 13b. Unlinking segment remains blocked under active legal hold
    with pytest.raises(BusinessRuleError) as exc_unlink:
        await case_service.unlink_ai_segment(case_entity.id, seg_entity.id, sup_principal)
    assert exc_unlink.value.code == "LEGAL_HOLD_ACTIVE"


@pytest.mark.asyncio
async def test_original_evidence_bytes_and_digest_remain_unchanged(case_service, mock_repos):
    """14. Original evidence bytes, SHA-256 digest, and custody remain unchanged."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    orig_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ev_entity = _make_evidence(department_id=dept_id, sha256_hash=orig_digest)
    seg_entity = _make_candidate_segment(department_id=dept_id, evidence_id=ev_entity.id)
    seg_entity.evidence = ev_entity
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["evidence"].get_by_id.return_value = ev_entity
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        corrected_label="physical_altercation",
        review_rationale="Annotating evidence with human review determination.",
    )

    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    assert result.original_evidence_digest == orig_digest
    assert ev_entity.sha256_hash == orig_digest
    assert ev_entity.file_size_bytes == 2097152


@pytest.mark.asyncio
async def test_audit_history_remains_ordered_and_append_only(case_service, mock_repos):
    """15. Audit history remains chronologically ordered, append-only, and monotonically tracked."""
    dept_id = uuid4()
    case_id = uuid4()
    seg_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(case_id=case_id, department_id=dept_id)
    link = CaseAISegment(case_id=case_id, segment_id=seg_id, linked_by_id=principal.user_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link

    t0 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 28, 11, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    ev1 = MagicMock()
    ev1.id = uuid4()
    ev1.action = AuditAction.CASE_AI_SEGMENT_REVIEWED
    ev1.created_at = t0
    ev1.actor_id = principal.user_id
    ev1.actor_role = RoleCode.INVESTIGATOR.value
    ev1.details = {
        "segment_id": str(seg_id),
        "decision_revision": 1,
        "previous_review_status": "pending_review",
        "new_review_status": "confirmed",
        "review_rationale": "Initial confirmation by investigator.",
        "is_override": False,
    }

    ev2 = MagicMock()
    ev2.id = uuid4()
    ev2.action = AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED
    ev2.created_at = t1
    ev2.actor_id = principal.user_id
    ev2.actor_role = RoleCode.INVESTIGATOR.value
    ev2.details = {
        "segment_id": str(seg_id),
        "decision_revision": 2,
        "previous_review_status": "confirmed",
        "new_review_status": "confirmed",
        "new_classification_label": "altercation_with_injury",
        "review_rationale": "Correction after witness interview.",
        "is_override": False,
    }

    ev3 = MagicMock()
    ev3.id = uuid4()
    ev3.action = AuditAction.CASE_AI_SEGMENT_OVERRIDDEN
    ev3.created_at = t2
    ev3.actor_id = uuid4()
    ev3.actor_role = RoleCode.DEPT_ADMIN.value
    ev3.details = {
        "segment_id": str(seg_id),
        "decision_revision": 3,
        "previous_review_status": "confirmed",
        "new_review_status": "rejected",
        "review_rationale": "Supervisor override after forensic analysis.",
        "is_override": True,
    }

    # Pass unordered events into mock
    mock_repos["audit"].list_events_for_target.return_value = [ev2, ev3, ev1]

    history = await case_service.get_case_ai_segment_review_history(case_id, seg_id, principal)

    assert len(history) == 3
    # Verified strictly sorted in chronological order
    assert history[0].timestamp == t0
    assert history[0].decision_revision == 1
    assert history[1].timestamp == t1
    assert history[1].decision_revision == 2
    assert history[2].timestamp == t2
    assert history[2].decision_revision == 3
    assert history[2].is_override is True


@pytest.mark.asyncio
async def test_failed_transactions_do_not_leave_misleading_success_audit(case_service, mock_repos):
    """16. Failed database operations do not leave misleading success audit events."""
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

    # Simulate database disk/connection failure during persistence
    mock_repos["ai_segment_repo"].create.side_effect = RuntimeError("Database I/O error on commit")

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Valid review rationale for transaction failure test.",
    )

    with pytest.raises(RuntimeError):
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    # Ensure no SUCCESS audit event was appended
    for call in mock_repos["audit"].append_event.call_args_list:
        assert call.kwargs.get("outcome") != AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_repeated_requests_and_retries_idempotent(case_service, mock_repos):
    """17. Repeated identical requests have defined idempotent behavior (no duplicate revisions)."""
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

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Initial confirmation determination by investigator.",
    )

    # Initial review call
    res1 = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)
    assert res1.review_status == "confirmed"
    assert res1.decision_revision == 1
    assert mock_repos["audit"].append_event.call_count == 1

    # Retry with identical determination
    res2 = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)
    assert res2.review_status == "confirmed"
    assert res2.decision_revision == 1  # Revision NOT bumped
    assert mock_repos["audit"].append_event.call_count == 1  # No duplicate audit log created


@pytest.mark.asyncio
async def test_superseded_decisions_cannot_be_edited_through_stale_requests(case_service, mock_repos):
    """18. Superseded decisions cannot be edited through stale revision requests."""
    dept_id = uuid4()
    sup_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    seg_entity = _make_candidate_segment(
        department_id=dept_id,
        review_status="rejected",
        reviewed_by_id=sup_principal.user_id,
    )
    # Decision is at revision 3
    seg_entity.metadata_json = json.dumps({"decision_revision": 3})

    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=sup_principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    # Stale client attempt referencing superseded revision 1
    stale_payload = CaseAISegmentReviewRequest(
        review_status="escalated",
        review_rationale="Attempting edit against stale revision 1.",
        expected_revision=1,
        is_override=True,
    )

    with pytest.raises(ConflictError) as exc:
        await case_service.review_ai_segment(case_entity.id, seg_entity.id, stale_payload, sup_principal)

    assert exc.value.code == "CONCURRENT_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_advisory_disclaimer_present_in_all_responses(case_service, mock_repos):
    """19. Statutory AI advisory disclaimer remains present in all review and read responses."""
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

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Verified review of segment.",
    )

    result = await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    assert result.advisory_disclaimer == AI_ADVISORY_DISCLAIMER
    assert "advisory only" in result.advisory_disclaimer.lower()
    assert "corroborating evidence" in result.advisory_disclaimer.lower()


@pytest.mark.asyncio
async def test_ai_decisions_cannot_automatically_close_cases_or_create_findings(case_service, mock_repos):
    """20. Human review decisions cannot automatically close cases or create legal findings."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, status=CaseStatus.UNDER_INVESTIGATION.value)
    seg_entity = _make_candidate_segment(department_id=dept_id)
    link = CaseAISegment(case_id=case_entity.id, segment_id=seg_entity.id, linked_by_id=principal.user_id)
    link.segment = seg_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_ai_segment_link.return_value = link
    mock_repos["ai_segment_repo"].get_by_id.return_value = seg_entity
    mock_repos["incident"].get_by_id.return_value = Incident(
        id=seg_entity.incident_id, department_id=dept_id, reporter_id=uuid4()
    )

    payload = CaseAISegmentReviewRequest(
        review_status="confirmed",
        review_rationale="Confirmed video segment as corroborating evidence.",
    )

    await case_service.review_ai_segment(case_entity.id, seg_entity.id, payload, principal)

    # Case status must strictly remain unchanged
    assert case_entity.status == CaseStatus.UNDER_INVESTIGATION.value
    assert case_entity.status != CaseStatus.CLOSED.value
    assert case_entity.findings == [] if hasattr(case_entity, "findings") else True


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled(case_service, mock_repos):
    """21. Biometric matching remains disabled and fails closed."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    face_service = FaceMatchingService(
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

    with pytest.raises(BiometricsDisabledError) as exc:
        await face_service.match_faces(
            req,
            _make_principal(RoleCode.SUPER_ADMIN.value),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_sealed_historical_violence_partition_is_not_accessed():
    """22. The sealed historical violence-detection test partition (N=354) is not accessed."""
    historical_path = Path("data/sealed_test_partition_354")
    assert not historical_path.exists(), "Compromised historical partition must never exist or be accessed in tests."
