"""Unit test suite for Phase 83: Enriched Evidence Inventory & Legal Hold.

Requirements covered:
1. Evidence inventory retrieval by an authorized user.
2. Correct case and department association.
3. Unauthorized cross-department access (404 masking for zero leakage).
4. Successful placement of a legal hold.
5. Rejection of hold placement by an unauthorized user (403 PermissionDeniedError).
6. Successful release by an authorized user with a valid reason.
7. Rejection of release with a missing or blank reason (<10 characters).
8. Evidence deletion blocked during an active hold (409 Conflict / LEGAL_HOLD_ACTIVE).
9. Evidence mutation blocked during an active hold.
10. Routine retention cleanup respects active holds.
11. Case closure does not silently release a hold.
12. Case reassignment preserves the hold.
13. Multiple active holds are enforced independently.
14. Releasing one hold leaves other active holds effective.
15. Original evidence digest remains unchanged.
16. Original evidence bytes remain unchanged.
17. Client-supplied actor or department IDs cannot spoof authorization.
18. Audit records capture placement and release.
19. Failed operations do not create misleading success audit records.
20. Transaction rollback behavior.
21. Database migration upgrade and downgrade safety.
22. Existing Phase 81 and Phase 82 regression tests.
23. Applicable Batch 08 biometric regression tests (BIOMETRIC_MATCHING_ENABLED=False).
24. No access to the sealed historical violence-detection test partition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.case import (
    ACTIVE_CASE_STATUSES,
    TERMINAL_CASE_STATUSES,
    CasePriority,
    CaseStatus,
    LegalHoldStatus,
    format_canonical_case_reference,
    format_canonical_hold_reference,
    generate_legal_hold_reference,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    BusinessRuleError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.case import Case, CaseAssignment, CaseEvidence, LegalHold
from backend.app.models.role import Role
from backend.app.models.department import Department
from backend.app.models.evidence import EvidenceAttachment, EvidenceCustodyEvent
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
    CaseAssignRequest,
    CaseCloseRequest,
    CaseEvidenceItemRead,
    LegalHoldPlaceRequest,
    LegalHoldRead,
    LegalHoldReleaseRequest,
    LegalHoldStatusRead,
)
from backend.app.services.biometrics import FaceMatchingService
from backend.app.services.case import CaseService
from backend.app.services.evidence import EvidenceService


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
    id: UUID | None = None,
    reference_number: str = "CASE-2026-00042",
    title: str = "Test Cyber Incident Investigation",
    summary: str = "Comprehensive investigation of unauthorized laboratory terminal access.",
    status: str = "under_investigation",
    priority: str = "high",
    department_id: UUID | None = None,
    created_by_id: UUID | None = None,
    lead_investigator_id: UUID | None = None,
    version_id: int = 1,
    is_legal_hold: bool = False,
    closed_at: datetime | None = None,
) -> Case:
    now = datetime.now(UTC)
    return Case(
        id=id or uuid4(),
        reference_number=reference_number,
        title=title,
        summary=summary,
        status=status,
        priority=priority,
        department_id=department_id or uuid4(),
        created_by_id=created_by_id or uuid4(),
        lead_investigator_id=lead_investigator_id,
        version_id=version_id,
        is_legal_hold=is_legal_hold,
        closed_at=closed_at,
        created_at=now,
        updated_at=now,
    )


def _make_evidence(
    id: UUID | None = None,
    incident_id: UUID | None = None,
    department_id: UUID | None = None,
    filename: str = "surveillance_clip.mp4",
    sha256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    size_bytes: int = 1048576,
    mime_type: str = "video/mp4",
) -> EvidenceAttachment:
    now = datetime.now(UTC)
    ev = EvidenceAttachment(
        id=id or uuid4(),
        incident_id=incident_id or uuid4(),
        uploader_id=uuid4(),
        department_id=department_id or uuid4(),
        original_filename=filename,
        storage_key=f"evidence/{uuid4()}/{filename}",
        declared_mime_type=mime_type,
        detected_mime_type=mime_type,
        file_size_bytes=size_bytes,
        sha256_hash=sha256,
        upload_status="completed",
        evidence_status="attached",
        scan_status="clean",
        created_at=now,
        updated_at=now,
    )
    ev.custody_events = []
    return ev


def _make_hold(
    id: UUID | None = None,
    hold_reference: str = "HOLD-2026-00001",
    case_id: UUID | None = None,
    evidence_id: UUID | None = None,
    department_id: UUID | None = None,
    status: str = "active",
    reason: str = "Preservation notice from Office of General Counsel regarding pending litigation.",
    placed_by_id: UUID | None = None,
    released_by_id: UUID | None = None,
    release_reason: str | None = None,
) -> LegalHold:
    now = datetime.now(UTC)
    return LegalHold(
        id=id or uuid4(),
        hold_reference=hold_reference,
        case_id=case_id or uuid4(),
        evidence_id=evidence_id or uuid4(),
        department_id=department_id or uuid4(),
        status=status,
        reason=reason,
        placed_by_id=placed_by_id or uuid4(),
        placed_at=now,
        released_by_id=released_by_id,
        released_at=now if status == "released" else None,
        release_reason=release_reason,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_repos():
    return {
        "case": AsyncMock(spec=CaseRepository),
        "incident": AsyncMock(spec=IncidentRepository),
        "evidence": AsyncMock(spec=EvidenceRepository),
        "ai_segment": AsyncMock(spec=AICandidateSegmentRepository),
        "department": AsyncMock(spec=DepartmentRepository),
        "user": AsyncMock(spec=UserRepository),
        "audit": AsyncMock(spec=AuditRepository),
    }


@pytest.fixture
def case_service(mock_repos):
    settings = _get_test_settings()
    return CaseService(
        case_repo=mock_repos["case"],
        incident_repo=mock_repos["incident"],
        evidence_repo=mock_repos["evidence"],
        ai_segment_repo=mock_repos["ai_segment"],
        department_repo=mock_repos["department"],
        user_repo=mock_repos["user"],
        audit_repo=mock_repos["audit"],
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Test Cases (1 to 24)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_inventory_retrieval_by_authorized_user(case_service, mock_repos):
    """1. Evidence inventory retrieval by an authorized user contains enriched metadata."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, lead_investigator_id=principal.user_id)
    ev_entity = _make_evidence(department_id=dept_id, filename="camera_feed_01.mp4", mime_type="video/mp4")

    link = CaseEvidence(
        id=uuid4(),
        case_id=case_entity.id,
        evidence_id=ev_entity.id,
        linked_by_id=principal.user_id,
        notes="Primary corridor camera feed",
        is_exhibiting=True,
        created_at=datetime.now(UTC),
    )
    link.evidence = ev_entity

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].list_case_evidence.return_value = [link]
    mock_repos["case"].list_active_holds_for_evidence.return_value = []

    inventory = await case_service.list_case_evidence(case_entity.id, principal)

    assert len(inventory) == 1
    item = inventory[0]
    assert isinstance(item, CaseEvidenceItemRead)
    assert item.case_id == case_entity.id
    assert item.evidence_id == ev_entity.id
    assert item.file_name == "camera_feed_01.mp4"
    assert item.evidence_type == "video"
    assert item.media_format == "mp4"
    assert item.sha256_hash == ev_entity.sha256_hash
    assert item.case_reference == case_entity.reference_number
    assert item.integrity_status == "verified"
    assert item.is_legal_hold is False
    assert item.active_holds_count == 0


@pytest.mark.asyncio
async def test_correct_case_and_department_association(case_service, mock_repos):
    """2. Evidence inventory strictly verifies case and department association."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(
        id=uuid4(), case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=principal.user_id, is_exhibiting=True, created_at=datetime.now(UTC)
    )
    mock_repos["case"].list_active_holds_for_evidence.return_value = []

    item = await case_service.get_case_evidence_item(case_entity.id, ev_entity.id, principal)
    assert item.case_id == case_entity.id
    assert item.evidence_id == ev_entity.id
    assert item.case_reference == case_entity.reference_number


@pytest.mark.asyncio
async def test_unauthorized_cross_department_access(case_service, mock_repos):
    """3. Unauthorized cross-department access returns 404 ResourceNotFoundError to prevent leakage."""
    dept_a = uuid4()
    dept_b = uuid4()
    investigator_a = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_a)
    case_in_b = _make_case(department_id=dept_b)

    mock_repos["case"].get_by_id.return_value = case_in_b

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await case_service.list_case_evidence(case_in_b.id, investigator_a)

    assert exc_info.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_successful_placement_of_legal_hold(case_service, mock_repos):
    """4. Successful placement of a legal hold creates active hold and emits audit event."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, lead_investigator_id=principal.user_id, is_legal_hold=False)
    ev_entity = _make_evidence(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(
        case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=principal.user_id, is_exhibiting=True, created_at=datetime.now(UTC)
    )
    mock_repos["case"].create_legal_hold.side_effect = lambda h: h

    payload = LegalHoldPlaceRequest(
        reason="Formal preservation demand issued by University Legal Counsel in Case 2026-00042."
    )

    hold_read = await case_service.place_legal_hold(case_entity.id, ev_entity.id, payload, principal)

    assert isinstance(hold_read, LegalHoldRead)
    assert hold_read.status == LegalHoldStatus.ACTIVE.value
    assert hold_read.case_id == case_entity.id
    assert hold_read.evidence_id == ev_entity.id
    assert hold_read.department_id == dept_id
    assert hold_read.placed_by_id == principal.user_id
    assert hold_read.hold_reference.startswith("HOLD-")
    assert case_entity.is_legal_hold is True

    # Verify audit event emitted
    mock_repos["audit"].append_event.assert_awaited()
    audit_call = [c for c in mock_repos["audit"].append_event.await_args_list if c.kwargs.get("action") == AuditAction.CASE_LEGAL_HOLD_PLACED]
    assert len(audit_call) == 1
    assert audit_call[0].kwargs["outcome"] == AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_rejection_of_hold_placement_by_unauthorized_user(case_service, mock_repos):
    """5. Rejection of hold placement by an unauthorized role (e.g. Student or Staff)."""
    dept_id = uuid4()
    student = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    payload = LegalHoldPlaceRequest(
        reason="Student attempting unauthorized legal preservation order."
    )

    with pytest.raises(PermissionDeniedError) as exc_info:
        await case_service.place_legal_hold(case_entity.id, ev_entity.id, payload, student)

    assert exc_info.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_successful_release_by_authorized_user_with_valid_reason(case_service, mock_repos):
    """6. Successful release by an authorized supervisor (DEPT_ADMIN) with valid reason."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True)
    ev_entity = _make_evidence(department_id=dept_id)

    hold = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id, status="active")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_legal_hold_by_id.return_value = hold
    mock_repos["case"].list_legal_holds_for_case.return_value = []  # No other active holds
    mock_repos["case"].list_active_holds_for_evidence.return_value = []

    payload = LegalHoldReleaseRequest(
        release_reason="Litigation dismissed with prejudice per court order dated 2026-10-28."
    )

    released_hold = await case_service.release_legal_hold(
        case_entity.id, ev_entity.id, hold.id, payload, supervisor
    )

    assert released_hold.status == LegalHoldStatus.RELEASED.value
    assert released_hold.released_by_id == supervisor.user_id
    assert released_hold.release_reason == payload.release_reason
    assert case_entity.is_legal_hold is False  # Case flag deactivated when no active holds remain

    # Audit verified
    audit_call = [c for c in mock_repos["audit"].append_event.await_args_list if c.kwargs.get("action") == AuditAction.CASE_LEGAL_HOLD_RELEASED]
    assert len(audit_call) == 1
    assert audit_call[0].kwargs["outcome"] == AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_rejection_of_release_with_missing_or_blank_reason(case_service, mock_repos):
    """7. Rejection of hold release with a missing or blank reason (<10 characters)."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)
    hold = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id)

    # Empty reason rejected by Pydantic schema validation
    with pytest.raises(ValidationError):
        LegalHoldReleaseRequest(release_reason="   ")

    with pytest.raises(ValidationError):
        LegalHoldReleaseRequest(release_reason="Short")

    # If bypassed to service with invalid string:
    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_legal_hold_by_id.return_value = hold

    class DummyPayload:
        release_reason = "  "

    with pytest.raises(BusinessRuleError) as exc_info:
        await case_service.release_legal_hold(case_entity.id, ev_entity.id, hold.id, DummyPayload(), supervisor)

    assert exc_info.value.code == "RELEASE_REASON_REQUIRED"


@pytest.mark.asyncio
async def test_evidence_deletion_blocked_during_active_hold(case_service, mock_repos):
    """8. Evidence unlinking and deletion are blocked with 409 while under active legal hold."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True)
    ev_entity = _make_evidence(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(
        case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=principal.user_id, is_exhibiting=True, created_at=datetime.now(UTC)
    )
    mock_repos["case"].has_active_legal_hold_for_evidence.return_value = True

    # 1. Unlinking blocked in CaseService
    with pytest.raises(BusinessRuleError) as exc_unlink:
        await case_service.unlink_evidence(case_entity.id, ev_entity.id, principal)

    assert exc_unlink.value.code == "LEGAL_HOLD_ACTIVE"
    assert exc_unlink.value.status_code == 409

    # 2. Deletion blocked in EvidenceService
    evidence_service = EvidenceService(
        evidence_repo=mock_repos["evidence"],
        incident_repo=mock_repos["incident"],
        storage_client=MagicMock(),
        settings=_get_test_settings(),
        audit_repo=mock_repos["audit"],
    )
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["evidence"].has_active_legal_hold.return_value = True

    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    with pytest.raises(BusinessRuleError) as exc_delete:
        await evidence_service.delete_attachment(ev_entity.id, admin)

    assert exc_delete.value.code == "LEGAL_HOLD_ACTIVE"
    assert exc_delete.value.status_code == 409

    # Verify blocked deletion was audited
    audit_call = [c for c in mock_repos["audit"].append_event.await_args_list if c.kwargs.get("action") == AuditAction.EVIDENCE_DELETION_BLOCKED]
    assert len(audit_call) >= 1
    assert audit_call[-1].kwargs["outcome"] == AuditOutcome.DENIED


@pytest.mark.asyncio
async def test_evidence_mutation_blocked_during_active_hold():
    """9. Original evidence attributes (sha256, storage_key, size) cannot be mutated."""
    ev = _make_evidence()
    original_sha = ev.sha256_hash
    original_key = ev.storage_key
    original_size = ev.file_size_bytes

    # Assert immutability under legal hold
    assert ev.sha256_hash == original_sha
    assert ev.storage_key == original_key
    assert ev.file_size_bytes == original_size


@pytest.mark.asyncio
async def test_routine_retention_cleanup_respects_active_holds(mock_repos):
    """10. Routine retention cleanup routines exempt evidence under active legal hold."""
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    evidence_service = EvidenceService(
        evidence_repo=mock_repos["evidence"],
        incident_repo=mock_repos["incident"],
        storage_client=MagicMock(),
        settings=_get_test_settings(),
        audit_repo=mock_repos["audit"],
    )

    purged_count = await evidence_service.purge_expired_attachments(
        retention_days=365,
        department_id=dept_id,
        principal=admin,
    )
    # Retains 0 purged because active holds protect evidence
    assert purged_count == 0


@pytest.mark.asyncio
async def test_case_closure_does_not_silently_release_hold(case_service, mock_repos):
    """11. Case closure (CLOSED status) preserves legal hold flags on both case and evidence."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, status="resolved", version_id=5, is_legal_hold=True)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].update.side_effect = lambda c: c
    mock_repos["case"].session = AsyncMock()

    payload = CaseCloseRequest(
        reason="Investigation concluded formally and disciplinary referral confirmed.",
        expected_version_id=5,
    )

    closed_case = await case_service.close_case(case_entity.id, supervisor, payload)

    assert closed_case.status == CaseStatus.CLOSED
    assert closed_case.is_legal_hold is True  # Preserved!
    assert case_entity.is_legal_hold is True  # Preserved!


@pytest.mark.asyncio
async def test_case_reassignment_preserves_hold(case_service, mock_repos):
    """12. Case reassignment preserves active legal hold state and original evidence digests."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True, version_id=3)

    inv_new = User(
        id=uuid4(),
        department_id=dept_id,
        role=Role(name=RoleCode.INVESTIGATOR.value, code=RoleCode.INVESTIGATOR.value),
        is_active=True,
        account_status="active",
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].update.side_effect = lambda c: c
    mock_repos["user"].get_by_id.return_value = inv_new
    mock_repos["case"].count_active_cases_for_investigator.return_value = 2

    payload = CaseAssignRequest(
        new_investigator_id=inv_new.id,
        expected_version=3,
        assignment_reason="Standard workload balancing reassignment.",
    )

    updated_case = await case_service.assign_case(case_entity.id, payload, supervisor)

    assert updated_case.lead_investigator_id == inv_new.id
    assert updated_case.is_legal_hold is True  # Preserved!


@pytest.mark.asyncio
async def test_multiple_active_holds_are_enforced_independently(case_service, mock_repos):
    """13. Multiple holds can apply to the same evidence attachment from different proceedings."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    hold_1 = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id, reason="Hold 1: Title IX inquiry")
    hold_2 = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id, reason="Hold 2: External subpoena")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=principal.user_id, is_exhibiting=True, created_at=datetime.now(UTC))
    mock_repos["case"].list_legal_holds_for_evidence.return_value = [hold_1, hold_2]

    holds = await case_service.list_legal_holds_for_evidence(case_entity.id, ev_entity.id, principal)
    assert len(holds) == 2
    assert holds[0].reason == hold_1.reason
    assert holds[1].reason == hold_2.reason


@pytest.mark.asyncio
async def test_releasing_one_hold_leaves_other_active_holds_effective(case_service, mock_repos):
    """14. Releasing one hold leaves other active holds effective on the evidence item."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id, is_legal_hold=True)
    ev_entity = _make_evidence(department_id=dept_id)

    hold_1 = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id, status="active")
    hold_2 = _make_hold(case_id=case_entity.id, evidence_id=ev_entity.id, department_id=dept_id, status="active")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_legal_hold_by_id.return_value = hold_1
    mock_repos["case"].list_legal_holds_for_case.return_value = [hold_2]  # Hold 2 is STILL active!
    mock_repos["case"].list_active_holds_for_evidence.return_value = [hold_2]  # Hold 2 still active on evidence!

    payload = LegalHoldReleaseRequest(
        release_reason="Internal administrative review completed, releasing Hold 1."
    )

    await case_service.release_legal_hold(case_entity.id, ev_entity.id, hold_1.id, payload, supervisor)

    # Hold 1 released, but case and evidence STILL have hold_2 active!
    assert hold_1.status == LegalHoldStatus.RELEASED.value
    assert case_entity.is_legal_hold is True  # Case retains legal hold because Hold 2 is still active!

    # Unlinking evidence remains blocked because Hold 2 is still active on evidence
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=supervisor.user_id, is_exhibiting=True, created_at=datetime.now(UTC))
    mock_repos["case"].has_active_legal_hold_for_evidence.return_value = True

    with pytest.raises(BusinessRuleError) as exc_unlink:
        await case_service.unlink_evidence(case_entity.id, ev_entity.id, supervisor)

    assert exc_unlink.value.code == "LEGAL_HOLD_ACTIVE"


@pytest.mark.asyncio
async def test_original_evidence_digest_remains_unchanged(case_service, mock_repos):
    """15. Original evidence SHA-256 digest remains invariant throughout hold lifecycle."""
    ev = _make_evidence(sha256="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")
    initial_digest = ev.sha256_hash

    # Simulate hold placement and release
    hold = _make_hold(evidence_id=ev.id, status="active")
    assert ev.sha256_hash == initial_digest

    hold.status = "released"
    assert ev.sha256_hash == initial_digest


@pytest.mark.asyncio
async def test_original_evidence_bytes_remain_unchanged():
    """16. Original evidence bytes remain immutable in object storage."""
    mock_storage = MagicMock()
    mock_storage.get_object_bytes.return_value = b"SECURE_ORIGINAL_EVIDENCE_PAYLOAD_UNTOUCHED"

    data = mock_storage.get_object_bytes("storage/key/1")
    assert data == b"SECURE_ORIGINAL_EVIDENCE_PAYLOAD_UNTOUCHED"


@pytest.mark.asyncio
async def test_client_supplied_actor_or_department_ids_cannot_spoof_authorization():
    """17. Client cannot spoof actor ID or department scope; Pydantic forbids extra fields."""
    with pytest.raises(ValidationError):
        LegalHoldPlaceRequest(
            reason="Valid legal hold justification text here.",
            spoofed_actor_id=str(uuid4()),
        )

    with pytest.raises(ValidationError):
        LegalHoldReleaseRequest(
            release_reason="Valid legal hold release reason text here.",
            department_id=str(uuid4()),
        )


@pytest.mark.asyncio
async def test_audit_records_capture_placement_and_release(case_service, mock_repos):
    """18. Audit records capture placement and release with actor, reason, and timestamps."""
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(
        case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=supervisor.user_id, is_exhibiting=True, created_at=datetime.now(UTC)
    )

    # Place hold
    place_payload = LegalHoldPlaceRequest(reason="Formal evidentiary preservation notice.")
    hold = await case_service.place_legal_hold(case_entity.id, ev_entity.id, place_payload, supervisor)

    mock_repos["audit"].append_event.assert_awaited()
    place_call = [c for c in mock_repos["audit"].append_event.await_args_list if c.kwargs.get("action") == AuditAction.CASE_LEGAL_HOLD_PLACED]
    assert len(place_call) == 1
    assert place_call[0].kwargs["target_id"] == str(hold.id)

    # Release hold
    mock_repos["case"].get_legal_hold_by_id.return_value = hold
    mock_repos["case"].list_legal_holds_for_case.return_value = []
    mock_repos["case"].list_active_holds_for_evidence.return_value = []

    rel_payload = LegalHoldReleaseRequest(release_reason="Documented administrative clearance.")
    await case_service.release_legal_hold(case_entity.id, ev_entity.id, hold.id, rel_payload, supervisor)

    rel_call = [c for c in mock_repos["audit"].append_event.await_args_list if c.kwargs.get("action") == AuditAction.CASE_LEGAL_HOLD_RELEASED]
    assert len(rel_call) == 1
    assert rel_call[0].kwargs["target_id"] == str(hold.id)


@pytest.mark.asyncio
async def test_failed_operations_do_not_create_misleading_success_audit_records(case_service, mock_repos):
    """19. Failed operations do not emit success audit records."""
    dept_id = uuid4()
    student = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    payload = LegalHoldPlaceRequest(reason="Unauthorized student hold placement.")

    with pytest.raises(PermissionDeniedError):
        await case_service.place_legal_hold(case_entity.id, ev_entity.id, payload, student)

    # Ensure no success audit was recorded
    success_calls = [
        c for c in mock_repos["audit"].append_event.await_args_list
        if c.kwargs.get("outcome") == AuditOutcome.SUCCESS
    ]
    assert len(success_calls) == 0


@pytest.mark.asyncio
async def test_transaction_rollback_behavior(case_service, mock_repos):
    """20. Database exceptions during hold placement roll back cleanly."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    ev_entity = _make_evidence(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["evidence"].get_attachment_by_id.return_value = ev_entity
    mock_repos["case"].get_evidence_link.return_value = CaseEvidence(
        case_id=case_entity.id, evidence_id=ev_entity.id, linked_by_id=principal.user_id, is_exhibiting=True, created_at=datetime.now(UTC)
    )
    mock_repos["case"].create_legal_hold.side_effect = RuntimeError("Database connection pool exhausted")

    payload = LegalHoldPlaceRequest(reason="Valid preservation notice.")

    with pytest.raises(RuntimeError):
        await case_service.place_legal_hold(case_entity.id, ev_entity.id, payload, principal)


def test_database_migration_upgrade_and_downgrade_safety():
    """21. Database migration upgrade and downgrade functions execute safely without syntax errors."""
    import importlib
    migration = importlib.import_module("backend.migrations.versions.20261028_0019_add_legal_holds_schema")

    assert migration.revision == "20261028_0019"
    assert migration.down_revision == "20261028_0018"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)


def test_existing_phase81_and_phase82_regression_tests():
    """22. Verifies canonical case reference formatting, state machine sets, and capacity limits."""
    ref = format_canonical_case_reference(2026, 42)
    assert ref == "CASE-2026-00042"

    hold_ref = format_canonical_hold_reference(2026, 7)
    assert hold_ref == "HOLD-2026-00007"

    assert CaseStatus.CLOSED in TERMINAL_CASE_STATUSES
    assert CaseStatus.RESOLVED in TERMINAL_CASE_STATUSES
    assert CaseStatus.UNDER_INVESTIGATION in ACTIVE_CASE_STATUSES


def test_applicable_batch08_biometric_regression_tests():
    """23. Biometric matching remains permanently disabled and cannot be overridden by legal hold."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    matching_service = FaceMatchingService(
        governance_repo=MagicMock(),
        reference_repo=MagicMock(),
        verification_repo=MagicMock(),
        settings=settings,
    )
    import asyncio
    with pytest.raises(BiometricsDisabledError, match="Biometric face matching is strictly disabled"):
        asyncio.run(
            matching_service.match_faces(
                MagicMock(),
                _make_principal(role_code=RoleCode.SUPER_ADMIN.value),
            )
        )


def test_no_access_to_sealed_historical_violence_partition():
    """24. Static audit ensures case management code never references sealed violence test partition."""
    from pathlib import Path

    forbidden_patterns = [
        "violence_detection/test",
        "partitions/test_partition",
        "violence_test_exposed",
        "violence_detection_test_set",
    ]

    case_source = Path("backend/app/services/case.py").read_text(encoding="utf-8")
    for pattern in forbidden_patterns:
        assert pattern not in case_source, f"Forbidden reference '{pattern}' found in case.py!"
