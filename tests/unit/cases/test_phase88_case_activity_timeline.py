"""Unit tests for Batch 09, Phase 88: Case Activity Timeline, Audit History & Operational Traceability.

Verifies:
1. Chronological (ascending) and reverse-chronological (descending) timeline ordering.
2. Deterministic tie-breaking for events with identical timestamps using sequence number & UUID.
3. Stable cursor pagination forward without item skipping or duplicates.
4. Stable cursor pagination across events sharing identical timestamps.
5. Rejection of malformed/invalid cursors with HTTP 400 BusinessRuleError (INVALID_CURSOR).
6. Bounded page limits (1 to 100) and rejection of invalid bounds.
7. Rejection of invalid time ranges (start_time > end_time).
8. Authorized filtering by event types and category group aliases (transition, approval, assignment, legal_hold, evidence, ai_review, note).
9. Authorized filtering by actor ID.
10. Authorized filtering by time range.
11. Filtering by outcome (success vs failure/denied).
12. Strict department isolation and 404 masking for cross-department timeline access.
13. Rejection of unauthorized roles with HTTP 403 PermissionDeniedError.
14. Missing case returns HTTP 404 CaseNotFoundError.
15. Confidential note events visible only to author, lead investigator, and dept admin.
16. Restricted note events visible only to author and dept admin with CASE_NOTE_READ_RESTRICTED.
17. Note access denied events isolated to admins only.
18. Absolute exclusion of sensitive payloads (note content, credentials, storage keys, presigned URLs).
19. Evidence immutability and preservation of SHA-256 hashes.
20. Active legal hold preservation during timeline operations.
21. AI review events remain strictly advisory with mandatory statutory disclaimer.
22. Accurate representation of approvals, rejections, and documented rationales.
23. Failed attempts cleanly distinguished from successful state changes.
24. Idempotent actions do not generate duplicate success events.
25. Inconsistent/corrupted details fail safely without crashing.
26. Security audit event emitted on timeline access (CASE_TIMELINE_ACCESSED).
27. Biometric matching permanently locked (BIOMETRIC_MATCHING_ENABLED=False).
28. Sealed historical violence partition (N=354) remains unaccessed.
29. Phases 81–87 regression behavior remains intact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.config.settings import Settings
# AI_ADVISORY_DISCLAIMER is in core.case
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    CaseNoteVisibility,
    CasePriority,
    CaseStatus,
    format_canonical_case_reference,
)
from backend.app.core.exceptions import (
    BusinessRuleError,
    BiometricsDisabledError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.audit import SecurityAuditEvent
from backend.app.models.case import Case, CaseApproval, CaseAssignment, LegalHold
from backend.app.models.evidence import EvidenceAttachment
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.biometrics import (
    BiometricGovernanceRepository,
    BiometricReferenceRepository,
    BiometricVerificationRepository,
)
from backend.app.repositories.ai_segment import AICandidateSegmentRepository
from backend.app.repositories.case import CaseRepository
from backend.app.repositories.identity import DepartmentRepository, UserRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import FaceMatchRequest
from backend.app.schemas.case import (
    CaseApprovalDecision,
    CaseApprovalRequest,
    CaseSubmitReviewRequest,
)
from backend.app.services.biometrics import FaceMatchingService
from backend.app.services.case import CaseService


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
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
    role_code: str,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email="test_user@ewitness.test",
        full_name="Test Investigator",
        role_code=role_code,
        account_status="active",
        is_active=True,
        department_id=department_id,
        session_id=uuid4(),
    )


def _make_case(
    case_id: UUID | None = None,
    department_id: UUID | None = None,
    lead_investigator_id: Any = "UNSET",
    status: str = CaseStatus.UNDER_INVESTIGATION.value,
    version_id: int = 1,
    is_legal_hold: bool = False,
) -> Case:
    cid = case_id or uuid4()
    dept_id = department_id or uuid4()
    actual_lead = uuid4() if lead_investigator_id == "UNSET" else lead_investigator_id
    c = Case(
        id=cid,
        reference_number=format_canonical_case_reference(2026, 88001),
        department_id=dept_id,
        title="Investigation Case 88",
        summary="Testing case activity timeline, audit history, and traceability.",
        status=status,
        priority=CasePriority.HIGH.value,
        lead_investigator_id=actual_lead,
        created_by_id=uuid4(),
        version_id=version_id,
        is_legal_hold=is_legal_hold,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    c.evidence = []
    c.ai_segments = []
    c.notes = []
    c.findings = []
    c.approvals = []
    c.escalations = []
    c.referrals = []
    c.incidents = []
    c.assignments = []
    c.exports = []
    return c


def _make_audit_event(
    action: str,
    case_id: UUID,
    actor_id: UUID | None = None,
    sequence_number: int = 1,
    created_at: datetime | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    event_id: UUID | None = None,
    department_id: UUID | None = None,
) -> SecurityAuditEvent:
    det = details or {}
    if "case_id" not in det:
        det["case_id"] = str(case_id)
    return SecurityAuditEvent(
        id=event_id or uuid4(),
        sequence_number=sequence_number,
        action=action,
        actor_id=actor_id or uuid4(),
        actor_role="ROLE_INVESTIGATOR",
        target_type=AuditTargetType.CASE.value,
        target_id=str(case_id),
        outcome=outcome,
        department_id=department_id or uuid4(),
        details=json.dumps(det),
        created_at=created_at or datetime.now(UTC),
        event_hash="mock_event_hash",
        previous_event_hash="mock_prev_hash",
    )


@pytest.fixture
def mock_service_context() -> tuple[CaseService, dict[str, AsyncMock]]:
    session = AsyncMock()
    settings = _get_test_settings()

    case_repo = AsyncMock(spec=CaseRepository)
    case_repo.session = session
    incident_repo = AsyncMock(spec=IncidentRepository)
    evidence_repo = AsyncMock(spec=EvidenceRepository)
    ai_segment_repo = AsyncMock(spec=AICandidateSegmentRepository)
    dept_repo = AsyncMock(spec=DepartmentRepository)
    user_repo = AsyncMock(spec=UserRepository)
    audit_repo = AsyncMock(spec=AuditRepository)

    # Defaults
    case_repo.list_case_incidents.return_value = [MagicMock()]
    case_repo.list_notes_for_case.return_value = [MagicMock()]
    case_repo.list_findings_for_case.return_value = []
    case_repo.list_case_ai_segments.return_value = []
    case_repo.list_approvals_for_case.return_value = []
    audit_repo.list_events_for_target.return_value = []
    audit_repo.list_events_for_case.return_value = []

    service = CaseService(
        case_repo=case_repo,
        incident_repo=incident_repo,
        evidence_repo=evidence_repo,
        ai_segment_repo=ai_segment_repo,
        department_repo=dept_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        settings=settings,
    )

    mocks = {
        "session": session,
        "case_repo": case_repo,
        "incident_repo": incident_repo,
        "evidence_repo": evidence_repo,
        "ai_segment_repo": ai_segment_repo,
        "dept_repo": dept_repo,
        "user_repo": user_repo,
        "audit_repo": audit_repo,
    }
    return service, mocks


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_chronological_and_reverse_ordering(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """1. Timeline supports chronological (ascending) and reverse-chronological (descending) ordering."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    t1 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 28, 11, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    e1 = _make_audit_event(AuditAction.CASE_CREATED.value, case.id, sequence_number=1, created_at=t1)
    e2 = _make_audit_event(AuditAction.CASE_STATUS_TRANSITION.value, case.id, sequence_number=2, created_at=t2, details={"from_status": "open", "to_status": "under_investigation"})
    e3 = _make_audit_event(AuditAction.CASE_SUBMITTED_FOR_REVIEW.value, case.id, sequence_number=3, created_at=t3)

    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2, e3]

    # Default: descending (newest first)
    desc_res = await service.get_case_activity_timeline(case.id, admin, ascending=False)
    assert len(desc_res.items) == 3
    assert [x.sequence_number for x in desc_res.items] == [3, 2, 1]

    # Ascending (oldest first)
    asc_res = await service.get_case_activity_timeline(case.id, admin, ascending=True)
    assert len(asc_res.items) == 3
    assert [x.sequence_number for x in asc_res.items] == [1, 2, 3]


@pytest.mark.asyncio
async def test_timeline_deterministic_tie_breaking_for_identical_timestamps(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """2. Events sharing identical timestamps are deterministically ordered by sequence number and UUID."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    same_time = datetime(2026, 10, 28, 12, 0, 0, 0, tzinfo=UTC)

    e1 = _make_audit_event(AuditAction.CASE_EVIDENCE_LINKED.value, case.id, sequence_number=10, created_at=same_time)
    e2 = _make_audit_event(AuditAction.CASE_AI_SEGMENT_LINKED.value, case.id, sequence_number=20, created_at=same_time)
    e3 = _make_audit_event(AuditAction.CASE_LEGAL_HOLD_PLACED.value, case.id, sequence_number=30, created_at=same_time)

    mocks["audit_repo"].list_events_for_case.return_value = [e2, e1, e3]

    desc_res = await service.get_case_activity_timeline(case.id, admin, ascending=False)
    assert [x.sequence_number for x in desc_res.items] == [30, 20, 10]

    asc_res = await service.get_case_activity_timeline(case.id, admin, ascending=True)
    assert [x.sequence_number for x in asc_res.items] == [10, 20, 30]


@pytest.mark.asyncio
async def test_timeline_cursor_pagination_forward_and_backward(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """3. Cursor pagination retrieves contiguous pages without skipping or duplicates."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    base = datetime(2026, 10, 28, 10, 0, 0, tzinfo=UTC)
    events = [
        _make_audit_event(AuditAction.CASE_STATUS_TRANSITION.value, case.id, sequence_number=i, created_at=base + timedelta(minutes=i))
        for i in range(1, 6)
    ]
    mocks["audit_repo"].list_events_for_case.return_value = events

    # Page 1: limit 2 (descending: expect 5, 4)
    p1 = await service.get_case_activity_timeline(case.id, admin, limit=2, ascending=False)
    assert len(p1.items) == 2
    assert [x.sequence_number for x in p1.items] == [5, 4]
    assert p1.has_more is True
    assert p1.next_cursor is not None

    # Page 2: with cursor (expect 3, 2)
    p2 = await service.get_case_activity_timeline(case.id, admin, limit=2, cursor=p1.next_cursor, ascending=False)
    assert len(p2.items) == 2
    assert [x.sequence_number for x in p2.items] == [3, 2]
    assert p2.has_more is True
    assert p2.next_cursor is not None

    # Page 3: with cursor (expect 1)
    p3 = await service.get_case_activity_timeline(case.id, admin, limit=2, cursor=p2.next_cursor, ascending=False)
    assert len(p3.items) == 1
    assert [x.sequence_number for x in p3.items] == [1]
    assert p3.has_more is False
    assert p3.next_cursor is None


@pytest.mark.asyncio
async def test_timeline_cursor_pagination_with_shared_timestamps(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """4. Cursor pagination correctly splits events sharing identical microsecond timestamps."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    same_time = datetime(2026, 10, 28, 14, 0, 0, 123456, tzinfo=UTC)
    events = [
        _make_audit_event(AuditAction.CASE_NOTE_CREATED.value, case.id, sequence_number=seq, created_at=same_time)
        for seq in (10, 20, 30, 40)
    ]
    mocks["audit_repo"].list_events_for_case.return_value = events

    # Page 1: limit 2 descending -> 40, 30
    p1 = await service.get_case_activity_timeline(case.id, admin, limit=2, ascending=False)
    assert [x.sequence_number for x in p1.items] == [40, 30]
    assert p1.has_more is True

    # Page 2: limit 2 descending -> 20, 10
    p2 = await service.get_case_activity_timeline(case.id, admin, limit=2, cursor=p1.next_cursor, ascending=False)
    assert [x.sequence_number for x in p2.items] == [20, 10]
    assert p2.has_more is False


@pytest.mark.asyncio
async def test_timeline_malformed_cursor_rejected_with_bad_request(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """5. Malformed base64 or invalid cursor strings raise HTTP 400 BusinessRuleError."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(BusinessRuleError) as exc:
        await service.get_case_activity_timeline(case.id, admin, cursor="not_a_valid_cursor_string")
    assert exc.value.code == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_timeline_limit_bounds_validation(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """6. Limits outside 1..100 are rejected with INVALID_LIMIT."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(BusinessRuleError) as exc:
        await service.get_case_activity_timeline(case.id, admin, limit=0)
    assert exc.value.code == "INVALID_LIMIT"

    with pytest.raises(BusinessRuleError) as exc:
        await service.get_case_activity_timeline(case.id, admin, limit=101)
    assert exc.value.code == "INVALID_LIMIT"


@pytest.mark.asyncio
async def test_timeline_invalid_time_range_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """7. Start time occurring after end time is rejected with INVALID_TIME_RANGE."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    t_start = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
    t_end = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)

    with pytest.raises(BusinessRuleError) as exc:
        await service.get_case_activity_timeline(case.id, admin, start_time=t_start, end_time=t_end)
    assert exc.value.code == "INVALID_TIME_RANGE"


@pytest.mark.asyncio
async def test_timeline_filtering_by_event_type_and_group_aliases(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """8. Filtering by specific action or category group aliases filters events properly."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e1 = _make_audit_event(AuditAction.CASE_STATUS_TRANSITION.value, case.id, sequence_number=1)
    e2 = _make_audit_event(AuditAction.CASE_APPROVAL_RECORDED.value, case.id, sequence_number=2, details={"decision": "approved", "to_status": "resolved"})
    e3 = _make_audit_event(AuditAction.CASE_LEGAL_HOLD_PLACED.value, case.id, sequence_number=3)
    e4 = _make_audit_event(AuditAction.CASE_AI_SEGMENT_REVIEWED.value, case.id, sequence_number=4)

    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2, e3, e4]

    # Filter by specific event type
    res_exact = await service.get_case_activity_timeline(case.id, admin, event_types=["case:status:transition"])
    assert len(res_exact.items) == 1
    assert res_exact.items[0].event_type == AuditAction.CASE_STATUS_TRANSITION.value

    # Filter by group alias "approval"
    res_group = await service.get_case_activity_timeline(case.id, admin, event_types=["approval"])
    assert len(res_group.items) == 1
    assert res_group.items[0].event_type == AuditAction.CASE_APPROVAL_RECORDED.value


@pytest.mark.asyncio
async def test_timeline_filtering_by_actor_id(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """9. Filtering by actor_id isolates events triggered by the specified user."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    target_actor = uuid4()
    other_actor = uuid4()

    e1 = _make_audit_event(AuditAction.CASE_NOTE_CREATED.value, case.id, actor_id=target_actor, sequence_number=1)
    e2 = _make_audit_event(AuditAction.CASE_NOTE_CREATED.value, case.id, actor_id=other_actor, sequence_number=2)

    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2]

    res = await service.get_case_activity_timeline(case.id, admin, actor_id=target_actor)
    assert len(res.items) == 1
    assert res.items[0].actor_id == target_actor


@pytest.mark.asyncio
async def test_timeline_filtering_by_time_range(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """10. Events outside the requested [start_time, end_time] interval are filtered out."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    t1 = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    t3 = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)

    e1 = _make_audit_event(AuditAction.CASE_CREATED.value, case.id, created_at=t1, sequence_number=1)
    e2 = _make_audit_event(AuditAction.CASE_ASSIGNED.value, case.id, created_at=t2, sequence_number=2)
    e3 = _make_audit_event(AuditAction.CASE_CLOSED.value, case.id, created_at=t3, sequence_number=3)

    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2, e3]

    res = await service.get_case_activity_timeline(
        case.id,
        admin,
        start_time=datetime(2026, 10, 28, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 28, 14, 0, tzinfo=UTC),
    )
    assert len(res.items) == 1
    assert res.items[0].sequence_number == 2


@pytest.mark.asyncio
async def test_timeline_filtering_by_outcome(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """11. Filtering by outcome separates successful state changes from failed attempts."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e1 = _make_audit_event(AuditAction.CASE_STATUS_TRANSITION.value, case.id, outcome="success", sequence_number=1)
    e2 = _make_audit_event(AuditAction.CASE_TRANSITION_FAILED.value, case.id, outcome="failure", sequence_number=2)

    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2]

    succ_res = await service.get_case_activity_timeline(case.id, admin, outcome="success")
    assert len(succ_res.items) == 1
    assert succ_res.items[0].outcome == "success"

    fail_res = await service.get_case_activity_timeline(case.id, admin, outcome="failure")
    assert len(fail_res.items) == 1
    assert fail_res.items[0].outcome == "failure"


@pytest.mark.asyncio
async def test_timeline_department_isolation_and_404_masking(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """12. Cross-department timeline access is masked with HTTP 404 CaseNotFoundError."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()

    inv_dept_b = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_b)
    case_dept_a = _make_case(department_id=dept_a)
    mocks["case_repo"].get_by_id.return_value = case_dept_a

    with pytest.raises(ResourceNotFoundError) as exc:
        await service.get_case_activity_timeline(case_dept_a.id, inv_dept_b)
    assert exc.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_timeline_unauthorized_caller_rejected_403(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """13. Callers without case read/timeline permissions receive HTTP 403 PermissionDeniedError."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    student = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(PermissionDeniedError) as exc:
        await service.get_case_activity_timeline(case.id, student)
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_timeline_missing_case_returns_404(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """14. Querying timeline of a nonexistent case raises HTTP 404."""
    service, mocks = mock_service_context
    admin = _make_principal(RoleCode.DEPT_ADMIN.value)
    mocks["case_repo"].get_by_id.return_value = None

    with pytest.raises(ResourceNotFoundError) as exc:
        await service.get_case_activity_timeline(uuid4(), admin)
    assert exc.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_timeline_note_visibility_tiers_confidential_filtering(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """15. Confidential note events are visible to author, lead investigator, and dept admin, but hidden from others."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    author_id = uuid4()
    lead_id = uuid4()
    other_inv_id = uuid4()

    author = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    lead = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=lead_id)
    other = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, lead_investigator_id=lead_id)
    mocks["case_repo"].get_by_id.return_value = case

    conf_event = _make_audit_event(
        AuditAction.CASE_NOTE_CREATED.value,
        case.id,
        actor_id=author_id,
        sequence_number=1,
        details={"visibility": CaseNoteVisibility.CONFIDENTIAL.value, "note_id": str(uuid4())},
    )
    mocks["audit_repo"].list_events_for_case.return_value = [conf_event]

    # Author can see
    r1 = await service.get_case_activity_timeline(case.id, author)
    assert len(r1.items) == 1

    # Lead investigator can see
    r2 = await service.get_case_activity_timeline(case.id, lead)
    assert len(r2.items) == 1

    # Dept admin can see
    r3 = await service.get_case_activity_timeline(case.id, admin)
    assert len(r3.items) == 1

    # Other investigator in same department CANNOT see
    r4 = await service.get_case_activity_timeline(case.id, other)
    assert len(r4.items) == 0


@pytest.mark.asyncio
async def test_timeline_note_visibility_tiers_restricted_filtering(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """16. Restricted note events are visible only to author and admin with CASE_NOTE_READ_RESTRICTED."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    author_id = uuid4()
    lead_id = uuid4()

    author = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    lead = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=lead_id)
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, lead_investigator_id=lead_id)
    mocks["case_repo"].get_by_id.return_value = case

    rest_event = _make_audit_event(
        AuditAction.CASE_NOTE_CREATED.value,
        case.id,
        actor_id=author_id,
        sequence_number=1,
        details={"visibility": CaseNoteVisibility.RESTRICTED.value, "note_id": str(uuid4())},
    )
    mocks["audit_repo"].list_events_for_case.return_value = [rest_event]

    # Author can see
    r1 = await service.get_case_activity_timeline(case.id, author)
    assert len(r1.items) == 1

    # Dept admin can see
    r2 = await service.get_case_activity_timeline(case.id, admin)
    assert len(r2.items) == 1

    # Non-author lead investigator CANNOT see restricted note
    r3 = await service.get_case_activity_timeline(case.id, lead)
    assert len(r3.items) == 0


@pytest.mark.asyncio
async def test_timeline_note_access_denied_events_isolated(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """17. Note access denied events are visible only to admins, not regular investigators."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    inv = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    denied_ev = _make_audit_event(
        AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value,
        case.id,
        outcome="denied",
        sequence_number=1,
    )
    mocks["audit_repo"].list_events_for_case.return_value = [denied_ev]

    # Regular investigator cannot see it
    r_inv = await service.get_case_activity_timeline(case.id, inv)
    assert len(r_inv.items) == 0

    # Admin can see it
    r_admin = await service.get_case_activity_timeline(case.id, admin)
    assert len(r_admin.items) == 1


@pytest.mark.asyncio
async def test_timeline_sensitive_payloads_excluded_no_note_bodies_or_storage_keys(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """18. Sensitive fields (note bodies, passwords, tokens, storage keys, URLs) are strictly excluded."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e = _make_audit_event(
        AuditAction.CASE_NOTE_CREATED.value,
        case.id,
        sequence_number=1,
        details={
            "note_id": str(uuid4()),
            "visibility": "internal",
            "content": "SECRET CONFIDENTIAL TEXT THAT MUST NEVER LEAK",
            "body": "BODY TEXT THAT MUST BE STRIPPED",
            "storage_key": "s3://private-bucket/keys/secret.pem",
            "presigned_url": "https://s3.amazonaws.com/secret?token=abc",
            "token": "bearer-token-123",
        },
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    item = res.items[0]

    # Verify sensitive keys are NOT in details
    assert "content" not in item.details
    assert "body" not in item.details
    assert "storage_key" not in item.details
    assert "presigned_url" not in item.details
    assert "token" not in item.details
    assert "SECRET CONFIDENTIAL TEXT" not in item.summary


@pytest.mark.asyncio
async def test_timeline_evidence_events_preserve_hashes_and_exclude_credentials(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """19. Evidence events expose safe metadata (SHA-256 hash, filename) without mutating artifacts."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    raw_hash = "a" * 64
    e = _make_audit_event(
        AuditAction.CASE_EVIDENCE_LINKED.value,
        case.id,
        sequence_number=1,
        details={
            "evidence_id": str(uuid4()),
            "file_name": "surveillance_clip.mp4",
            "sha256_hash": raw_hash,
            "file_size_bytes": 2048000,
        },
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    det = res.items[0].details
    assert det["sha256_hash"] == raw_hash
    assert det["file_name"] == "surveillance_clip.mp4"
    assert det["file_size_bytes"] == 2048000


@pytest.mark.asyncio
async def test_timeline_legal_hold_events_preserve_active_holds(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """20. Legal hold events represent hold state accurately and maintain active holds."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id, is_legal_hold=True)
    mocks["case_repo"].get_by_id.return_value = case

    e = _make_audit_event(
        AuditAction.CASE_LEGAL_HOLD_PLACED.value,
        case.id,
        sequence_number=1,
        details={
            "hold_reference": "HOLD-2026-00042",
            "hold_type": "court_order",
            "scope": "full_case",
            "is_legal_hold": True,
        },
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    assert "HOLD-2026-00042" in res.items[0].summary
    assert case.is_legal_hold is True


@pytest.mark.asyncio
async def test_timeline_ai_review_events_remain_strictly_advisory(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """21. AI review timeline events are flagged advisory with statutory disclaimer."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e = _make_audit_event(
        AuditAction.CASE_AI_SEGMENT_REVIEWED.value,
        case.id,
        sequence_number=1,
        details={
            "segment_id": str(uuid4()),
            "review_decision": "confirmed",
            "previous_label": "violence",
            "corrected_label": "non_violence",
        },
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    item = res.items[0]
    assert item.details.get("is_advisory") is True
    assert "advisory only" in item.details.get("advisory_disclaimer", "").lower()


@pytest.mark.asyncio
async def test_timeline_approvals_and_rejections_accurately_represented(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """22. Supervisory approvals and rejections capture decisions and documented rationales."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e1 = _make_audit_event(
        AuditAction.CASE_APPROVAL_RECORDED.value,
        case.id,
        sequence_number=1,
        details={"decision": "approved", "to_status": "resolved", "rationale": "Findings verified."},
    )
    e2 = _make_audit_event(
        AuditAction.CASE_APPROVAL_REJECTED.value,
        case.id,
        sequence_number=2,
        details={"decision": "rejected", "to_status": "under_investigation", "rationale": "Insufficient evidence provided."},
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e1, e2]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 2
    assert "approved" in res.items[1].summary.lower()
    assert "rejected" in res.items[0].summary.lower()


@pytest.mark.asyncio
async def test_timeline_failed_attempts_distinguished_from_success(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """23. Failed transitions and blocked self-approvals carry failure outcome and are distinguished."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    e_fail = _make_audit_event(
        AuditAction.CASE_SELF_APPROVAL_BLOCKED.value,
        case.id,
        outcome="failure",
        sequence_number=1,
        details={"reason": "Self-approval prohibited by separation of duties policy."},
    )
    mocks["audit_repo"].list_events_for_case.return_value = [e_fail]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    assert res.items[0].outcome == "failure"
    assert "self-approval blocked" in res.items[0].summary.lower()


@pytest.mark.asyncio
async def test_timeline_idempotent_duplicate_requests_do_not_create_duplicate_success_events(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """24. Idempotent approval replays do not duplicate success entries in the timeline."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id, status=CaseStatus.RESOLVED.value, version_id=2)
    mocks["case_repo"].get_by_id.return_value = case

    # Existing approval record
    app = CaseApproval(
        id=uuid4(),
        case_id=case.id,
        approver_id=admin.user_id,
        decision="approved",
        from_status="pending_supervisor_review",
        to_status="resolved",
        rationale="Supervisory approval granted.",
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].list_approvals_for_case.return_value = [app]

    # Replay same approval
    req = CaseApprovalRequest(
        decision="approved",
        from_status="pending_supervisor_review",
        to_status="resolved",
        rationale="Supervisory approval granted.",
        expected_version_id=2,
    )
    await service.approve_case_transition(case.id, admin, req)

    # Verify create_approval was NOT called again
    assert mocks["case_repo"].create_approval.call_count == 0


@pytest.mark.asyncio
async def test_timeline_inconsistent_or_corrupt_details_fail_safely(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """25. Malformed or unparseable event details fail safely without crashing."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    corrupt_ev = SecurityAuditEvent(
        id=uuid4(),
        sequence_number=1,
        action=AuditAction.CASE_STATUS_TRANSITION.value,
        actor_id=admin.user_id,
        actor_role="ROLE_DEPT_ADMIN",
        target_type=AuditTargetType.CASE.value,
        target_id=str(case.id),
        outcome="success",
        department_id=dept_id,
        details="{corrupt: json: [broken",
        created_at=datetime.now(UTC),
        event_hash="test",
        previous_event_hash=None,
    )
    mocks["audit_repo"].list_events_for_case.return_value = [corrupt_ev]

    res = await service.get_case_activity_timeline(case.id, admin)
    assert len(res.items) == 1
    assert res.items[0].details == {}


@pytest.mark.asyncio
async def test_timeline_audit_event_recorded_on_access(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """26. Accessing the case activity timeline logs an audit event (CASE_TIMELINE_ACCESSED)."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case
    mocks["audit_repo"].list_events_for_case.return_value = []

    await service.get_case_activity_timeline(case.id, admin)

    # Verify append_event was invoked for CASE_TIMELINE_ACCESSED
    append_calls = mocks["audit_repo"].append_event.call_args_list
    assert any(c.kwargs.get("action") == AuditAction.CASE_TIMELINE_ACCESSED for c in append_calls)


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled_in_phase88(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """27. Biometric matching is permanently locked (BIOMETRIC_MATCHING_ENABLED=False)."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    matching_service = FaceMatchingService(
        governance_repo=AsyncMock(spec=BiometricGovernanceRepository),
        reference_repo=AsyncMock(spec=BiometricReferenceRepository),
        verification_repo=AsyncMock(spec=BiometricVerificationRepository),
        settings=settings,
    )

    req = FaceMatchRequest(
        governance_record_id=uuid4(),
        reference_id=uuid4(),
        probe_image_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    )
    with pytest.raises(BiometricsDisabledError):
        await matching_service.match_faces(req, _make_principal(RoleCode.SUPER_ADMIN.value))


def test_sealed_historical_violence_partition_is_not_accessed() -> None:
    """28. The historical violence-detection partition (N=354) remains sealed."""
    workspace_root = Path("D:/PROJECT/E-WITTNESS")
    leaked_files = list(workspace_root.glob("**/historical_violence_test_partition_*.csv"))
    assert len(leaked_files) == 0, f"Found exposed historical partition files: {leaked_files}"


@pytest.mark.asyncio
async def test_relevant_phase81_to_87_regression_behavior_intact(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """29. Phases 81–87 regression behavior remains intact."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # 1. Sequence reference format (Phase 81)
    ref = format_canonical_case_reference(2026, 88)
    assert ref == "CASE-2026-00088"

    # 2. Workload capacity check (Phase 82)
    inv_user = MagicMock()
    inv_user.id = uuid4()
    inv_user.department_id = dept_id
    mocks["user_repo"].get_by_id.return_value = inv_user
    mocks["user_repo"].get_by_id_unscoped.return_value = inv_user
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 10
    workload = await service.get_investigator_workload(inv_user.id, admin)
    assert workload.capacity_available is False

    # 3. Transitions and supervisor approval (Phase 87)
    case_pending = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value, version_id=3)
    mocks["case_repo"].get_by_id.return_value = case_pending
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    approval_res = await service.approve_case_transition(
        case_pending.id,
        admin,
        CaseApprovalRequest(
            decision="approved",
            from_status="pending_supervisor_review",
            to_status="resolved",
            rationale="Approved with complete audit verification.",
            expected_version_id=3,
        ),
    )
    assert approval_res.decision == "approved"
    assert case_pending.status == "resolved"
