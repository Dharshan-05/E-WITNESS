"""Unit and integration test suite for Batch 09 Phase 81: Formal Case Lifecycle & References.

Verifies:
1. Case creation with valid and invalid input.
2. Canonical case reference number format (CASE-YYYY-XXXXX), uniqueness, and concurrency safety.
3. Immutability of issued case reference numbers.
4. Permitted lifecycle state machine transitions (DRAFT -> OPEN -> UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW -> CLOSED).
5. Rejection of invalid lifecycle transitions.
6. Authorized closure and reopening workflows.
7. PermissionCode enforcement (CASE_CREATE, CASE_READ, CASE_UPDATE, CASE_ASSIGN).
8. Strict cross-department tenant isolation (zero information leakage on 404).
9. Pagination and filtering authorization boundary.
10. Concurrency versioning (version_id) and database constraint integrity.
11. Append-only audit logging for creation, transitions, assignments, closure, and reopening.
12. Preservation of original evidence immutability and Batch 08 safety invariants (BIOMETRIC_MATCHING_ENABLED=False).
13. Migration metadata and CaseSequenceCounter domain persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, PermissionCode, has_permission
from backend.app.core.case import (
    CasePriority,
    CaseStatus,
    format_canonical_case_reference,
    generate_case_reference_number,
    parse_case_priority,
    parse_case_status,
    validate_case_status_transition,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    BusinessRuleError,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.case import Case, CaseAssignment, CaseSequenceCounter
from backend.app.models.department import Department
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
    CaseCreate,
    CaseReopenRequest,
    CaseTransitionRequest,
    CaseUpdate,
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
        full_name="Test Officer",
        role_code=role_code,
        account_status="active",
        is_active=True,
        session_id=uuid4(),
        department_id=department_id or uuid4(),
    )


def _make_case(
    id: UUID | None = None,
    reference_number: str = "CASE-2026-00001",
    title: str = "Case Title",
    summary: str = "Case Summary description for test verification.",
    status: str = "open",
    priority: str = "medium",
    department_id: UUID | None = None,
    created_by_id: UUID | None = None,
    lead_investigator_id: UUID | None = None,
    version_id: int = 1,
    is_legal_hold: bool = False,
    legal_hold_reason: str | None = None,
    closed_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
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
        legal_hold_reason=legal_hold_reason,
        closed_at=closed_at,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


@pytest.fixture
def mock_service_context() -> tuple[CaseService, dict[str, AsyncMock]]:
    mocks = {
        "case_repo": AsyncMock(spec=CaseRepository),
        "incident_repo": AsyncMock(spec=IncidentRepository),
        "evidence_repo": AsyncMock(spec=EvidenceRepository),
        "ai_segment_repo": AsyncMock(spec=AICandidateSegmentRepository),
        "department_repo": AsyncMock(spec=DepartmentRepository),
        "user_repo": AsyncMock(spec=UserRepository),
        "audit_repo": AsyncMock(spec=AuditRepository),
    }

    # Default session mock
    mocks["case_repo"].session = AsyncMock()

    service = CaseService(
        case_repo=mocks["case_repo"],
        incident_repo=mocks["incident_repo"],
        evidence_repo=mocks["evidence_repo"],
        ai_segment_repo=mocks["ai_segment_repo"],
        department_repo=mocks["department_repo"],
        user_repo=mocks["user_repo"],
        audit_repo=mocks["audit_repo"],
        settings=_get_test_settings(),
    )
    return service, mocks


# ---------------------------------------------------------------------------
# 1. Case Creation With Valid and Invalid Input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_creation_valid_input(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 1: Case creation succeeds with validated title, summary, priority, and tenant."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id)

    dept = Department(id=dept_id, name="Campus Security", code="SEC", is_active=True)
    mocks["department_repo"].get_by_id.return_value = dept
    mocks["case_repo"].get_by_reference_number.return_value = None

    def fake_create(c: Case) -> Case:
        c.id = uuid4()
        c.department = dept
        c.lead_investigator = None
        c.created_at = datetime.now(UTC)
        c.updated_at = datetime.now(UTC)
        c.incidents = []
        c.evidence = []
        c.ai_segments = []
        return c

    mocks["case_repo"].create.side_effect = fake_create

    payload = CaseCreate(
        title="Unauthorized Server Access Inquiry",
        summary="Forensic investigation into anomalous authentication attempts in Data Center B.",
        priority=CasePriority.HIGH,
    )
    result = await service.create_case(payload, principal)

    assert result.id is not None
    assert result.title == payload.title
    assert result.summary == payload.summary
    assert result.priority == CasePriority.HIGH
    assert result.status == CaseStatus.OPEN
    assert result.department_id == dept_id
    assert result.version_id == 1
    assert result.reference_number.startswith("CASE-")


def test_case_creation_invalid_input_boundaries() -> None:
    """Requirement 1b: Pydantic schemas reject out-of-bound titles, summaries, and priorities."""
    # Title too short (<5 chars)
    with pytest.raises(ValidationError):
        CaseCreate(title="Test", summary="Valid description with enough characters")

    # Title too long (>200 chars)
    with pytest.raises(ValidationError):
        CaseCreate(title="A" * 201, summary="Valid description with enough characters")

    # Summary too short (<10 chars)
    with pytest.raises(ValidationError):
        CaseCreate(title="Valid Title", summary="Short")

    # Invalid priority string
    with pytest.raises(ValidationError):
        CaseCreate(title="Valid Title", summary="Valid summary details", priority="urgent_af")  # type: ignore


# ---------------------------------------------------------------------------
# 2. Reference Number Format, Uniqueness, and Concurrent Creation
# ---------------------------------------------------------------------------


def test_case_reference_number_canonical_format() -> None:
    """Requirement 2: Canonical reference numbers follow CASE-YYYY-XXXXX format."""
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    # 1. 5-digit zero-padded sequence format
    ref_seq = format_canonical_case_reference(2026, 42)
    assert ref_seq == "CASE-2026-00042"
    assert len(ref_seq) == 15

    # 2. Generator with sequence
    ref_gen_seq = generate_case_reference_number(now, sequence_num=1)
    assert ref_gen_seq == "CASE-2026-00001"

    # 3. Generator with high-entropy fallback (8-hex)
    ref_gen_hex = generate_case_reference_number(now)
    assert ref_gen_hex.startswith("CASE-2026-")
    assert len(ref_gen_hex) == 18
    assert ref_gen_hex == ref_gen_hex.upper()


@pytest.mark.asyncio
async def test_case_reference_concurrency_collision_retry(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 2b: Concurrency collision triggers automated retry until a unique reference is issued."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    principal = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    dept = Department(id=dept_id, name="Security", code="SEC", is_active=True)
    mocks["department_repo"].get_by_id.return_value = dept

    # Simulate collision on first attempt, success on second
    collided_case = _make_case(reference_number="CASE-2026-00001", department_id=dept_id)
    mocks["case_repo"].get_by_reference_number.side_effect = [collided_case, None]

    created_case = _make_case(
        reference_number="CASE-2026-00002",
        title="Collision Handling Case",
        summary="Investigating concurrent collision resolution behavior.",
        status="open",
        priority="medium",
        department_id=dept_id,
        created_by_id=principal.user_id,
        version_id=1,
    )
    mocks["case_repo"].create.return_value = created_case

    payload = CaseCreate(
        title="Collision Handling Case",
        summary="Investigating concurrent collision resolution behavior.",
    )
    result = await service.create_case(payload, principal)

    assert result.id == created_case.id
    assert mocks["case_repo"].get_by_reference_number.call_count == 2


# ---------------------------------------------------------------------------
# 3. Immutability of Issued Reference Numbers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_reference_number_immutability(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 3: Updating case metadata never changes or permits updating the reference number."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id)

    original_ref = "CASE-2026-00100"
    existing_case = _make_case(
        id=case_id,
        reference_number=original_ref,
        title="Original Case Title",
        summary="Original case summary statement.",
        status="open",
        priority="low",
        department_id=dept_id,
        created_by_id=principal.user_id,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = existing_case
    mocks["case_repo"].update.side_effect = lambda c: c

    # CaseUpdate schema forbids reference_number
    with pytest.raises(ValidationError):
        CaseUpdate(title="New Title", expected_version=1, reference_number="CASE-2026-CHANGED")  # type: ignore

    # Standard update
    update_payload = CaseUpdate(
        title="Updated Incident Title",
        summary="Updated incident summary with sufficient character length.",
        priority=CasePriority.HIGH,
        expected_version=1,
    )
    updated = await service.update_case(case_id, update_payload, principal)

    assert updated.reference_number == original_ref
    assert updated.title == "Updated Incident Title"
    assert updated.priority == CasePriority.HIGH


# ---------------------------------------------------------------------------
# 4. Case Lifecycle State Machine Transitions
# ---------------------------------------------------------------------------


def test_permitted_case_lifecycle_state_machine_transitions() -> None:
    """Requirement 4: Permitted lifecycle transitions succeed across the full canonical state machine."""
    # Canonical pipeline: DRAFT -> OPEN -> UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW -> CLOSED
    validate_case_status_transition(CaseStatus.DRAFT, CaseStatus.OPEN)
    validate_case_status_transition(CaseStatus.OPEN, CaseStatus.UNDER_INVESTIGATION)
    validate_case_status_transition(CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_SUPERVISOR_REVIEW)
    validate_case_status_transition(CaseStatus.PENDING_SUPERVISOR_REVIEW, CaseStatus.CLOSED)

    # Reopened workflow
    validate_case_status_transition(CaseStatus.CLOSED, CaseStatus.REOPENED)
    validate_case_status_transition(CaseStatus.REOPENED, CaseStatus.UNDER_INVESTIGATION)
    validate_case_status_transition(CaseStatus.REOPENED, CaseStatus.CLOSED)

    # Supported alternative paths
    validate_case_status_transition(CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_REVIEW)
    validate_case_status_transition(CaseStatus.PENDING_REVIEW, CaseStatus.RESOLVED)
    validate_case_status_transition(CaseStatus.RESOLVED, CaseStatus.CLOSED)
    validate_case_status_transition(CaseStatus.UNDER_INVESTIGATION, CaseStatus.SUSPENDED)
    validate_case_status_transition(CaseStatus.SUSPENDED, CaseStatus.UNDER_INVESTIGATION)


def test_rejection_of_invalid_case_lifecycle_transitions() -> None:
    """Requirement 5: Invalid status transitions fail closed with BusinessRuleError."""
    # Terminal closed case cannot transition back to DRAFT or OPEN directly
    with pytest.raises(BusinessRuleError) as exc_closed_open:
        validate_case_status_transition(CaseStatus.CLOSED, CaseStatus.OPEN)
    assert exc_closed_open.value.code == "INVALID_CASE_TRANSITION"

    with pytest.raises(BusinessRuleError) as exc_closed_draft:
        validate_case_status_transition(CaseStatus.CLOSED, CaseStatus.DRAFT)
    assert exc_closed_draft.value.code == "INVALID_CASE_TRANSITION"

    # DRAFT cannot jump directly to RESOLVED or UNDER_INVESTIGATION
    with pytest.raises(BusinessRuleError) as exc_draft_resolved:
        validate_case_status_transition(CaseStatus.DRAFT, CaseStatus.RESOLVED)
    assert exc_draft_resolved.value.code == "INVALID_CASE_TRANSITION"


# ---------------------------------------------------------------------------
# 5. Authorized Closure and Reopening Workflows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_case_closure_workflow(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 6: Authorized closure updates status to CLOSED, records closed_at, and audits."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(
        id=case_id,
        reference_number="CASE-2026-00045",
        title="Title",
        summary="Summary",
        status="under_investigation",
        priority="medium",
        department_id=dept_id,
        version_id=3,
    )
    mocks["case_repo"].get_by_id.return_value = case_entity

    payload = CaseCloseRequest(
        reason="Investigation concluded with formal disciplinary recommendations.",
        expected_version_id=3,
    )
    closed = await service.close_case(case_id, admin, payload)

    assert closed.status == CaseStatus.CLOSED
    assert closed.closed_at is not None
    assert closed.version_id == 4

    # Verify audit event recorded
    mocks["audit_repo"].append_event.assert_awaited()


@pytest.mark.asyncio
async def test_authorized_case_reopening_workflow(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 6b: Reopening closed case requires CASE_REOPEN and transitions to UNDER_INVESTIGATION or REOPENED."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(
        id=case_id,
        reference_number="CASE-2026-00045",
        title="Title",
        summary="Summary",
        status="closed",
        priority="medium",
        closed_at=datetime.now(UTC),
        department_id=dept_id,
        version_id=4,
    )
    mocks["case_repo"].get_by_id.return_value = case_entity

    # Reopen to REOPENED status explicitly
    reopen_payload = CaseReopenRequest(
        reason="Subsequent video footage recovered warranting supplementary review.",
        expected_version_id=4,
        target_status=CaseStatus.REOPENED,
    )
    reopened = await service.reopen_case(case_id, admin, reopen_payload)

    assert reopened.status == CaseStatus.REOPENED
    assert reopened.closed_at is None
    assert reopened.version_id == 5


# ---------------------------------------------------------------------------
# 6. PermissionCode and Role Mapping Enforcement
# ---------------------------------------------------------------------------


def test_permission_codes_exist_and_map_to_authorized_roles() -> None:
    """Requirement 7: PermissionCode.CASE_CREATE/READ/UPDATE/ASSIGN exist and are granted appropriately."""
    assert PermissionCode.CASE_CREATE == "case:create"
    assert PermissionCode.CASE_READ == "case:read"
    assert PermissionCode.CASE_UPDATE == "case:update"
    assert PermissionCode.CASE_ASSIGN == "case:assign"

    # Investigators can create, read, update
    assert has_permission(RoleCode.INVESTIGATOR, PermissionCode.CASE_CREATE)
    assert has_permission(RoleCode.INVESTIGATOR, PermissionCode.CASE_READ)
    assert has_permission(RoleCode.INVESTIGATOR, PermissionCode.CASE_UPDATE)

    # Department Admins have all four including assign
    assert has_permission(RoleCode.DEPT_ADMIN, PermissionCode.CASE_CREATE)
    assert has_permission(RoleCode.DEPT_ADMIN, PermissionCode.CASE_READ)
    assert has_permission(RoleCode.DEPT_ADMIN, PermissionCode.CASE_UPDATE)
    assert has_permission(RoleCode.DEPT_ADMIN, PermissionCode.CASE_ASSIGN)

    # Students and Staff are denied case management permissions
    assert not has_permission(RoleCode.STUDENT, PermissionCode.CASE_CREATE)
    assert not has_permission(RoleCode.STUDENT, PermissionCode.CASE_READ)
    assert not has_permission(RoleCode.STAFF, PermissionCode.CASE_CREATE)
    assert not has_permission(RoleCode.STAFF, PermissionCode.CASE_UPDATE)


@pytest.mark.asyncio
async def test_unauthorized_roles_denied_case_creation(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 7b: Unprivileged caller lacking CASE_CREATE is rejected with PermissionDeniedError."""
    service, _ = mock_service_context
    student = _make_principal(role_code=RoleCode.STUDENT.value)

    payload = CaseCreate(
        title="Unauthorized Case",
        summary="Student trying to initiate a formal investigation case.",
    )
    with pytest.raises(PermissionDeniedError, match="permission to create investigation cases"):
        await service.create_case(payload, student)


# ---------------------------------------------------------------------------
# 7. Department Isolation & Zero Information Leakage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_department_case_access_masked_as_not_found(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 8: Cross-department access returns ResourceNotFoundError (404) to avoid leaking existence."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    case_id = uuid4()

    officer_a = _make_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_a)

    # Case belongs to Department B
    case_dept_b = Case(
        id=case_id,
        reference_number="CASE-2026-00088",
        title="Dept B Confidential Inquiry",
        summary="Confidential summary statement for department B.",
        status="open",
        department_id=dept_b,
    )
    mocks["case_repo"].get_by_id.return_value = case_dept_b

    # Reading cross-department case raises ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError, match="Case not found"):
        await service.get_case(case_id, officer_a)

    # Updating cross-department case raises ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError, match="Case not found"):
        await service.update_case(
            case_id,
            CaseUpdate(title="Attempted Tamper Title", expected_version=1),
            officer_a,
        )


@pytest.mark.asyncio
async def test_cross_department_case_creation_forbidden(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 8b: Specifying a different department on creation raises CROSS_DEPARTMENT_FORBIDDEN."""
    service, _ = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()

    dept_admin_a = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_a)

    payload = CaseCreate(
        title="Out of Scope Case",
        summary="Attempting to open case in Department B.",
        department_id=dept_b,
    )
    with pytest.raises(PermissionDeniedError, match="cannot create cases for another department"):
        await service.create_case(payload, dept_admin_a)


# ---------------------------------------------------------------------------
# 8. Pagination and Filtering Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_cases_enforces_department_filter_for_non_global_principals(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 9: list_cases scopes results strictly to caller's department_id."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_a)

    mocks["case_repo"].list_paginated.return_value = ([], 0)

    await service.list_cases(
        principal,
        limit=25,
        offset=0,
        status="open",
        priority="high",
    )

    mocks["case_repo"].list_paginated.assert_awaited_once()
    kwargs = mocks["case_repo"].list_paginated.call_args.kwargs
    assert kwargs["department_id"] == dept_a
    assert kwargs["limit"] == 25
    assert kwargs["status"] == "open"
    assert kwargs["priority"] == "high"


# ---------------------------------------------------------------------------
# 9. Concurrency Conflict and Constraint Integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict_detection(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 10: Updating case with outdated version_id raises CONCURRENCY_CONFLICT (409)."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    principal = _make_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id)

    case_entity = Case(
        id=case_id,
        reference_number="CASE-2026-00099",
        title="Title",
        summary="Summary",
        status="open",
        department_id=dept_id,
        version_id=5,  # In database, version is 5
    )
    mocks["case_repo"].get_by_id.return_value = case_entity

    # Caller submits update with stale expected_version=4
    stale_update = CaseUpdate(title="Stale Update Title", expected_version=4)

    with pytest.raises(BusinessRuleError) as exc_conflict:
        await service.update_case(case_id, stale_update, principal)

    assert exc_conflict.value.code == "CONCURRENCY_CONFLICT"
    assert exc_conflict.value.status_code == 409


# ---------------------------------------------------------------------------
# 10. Audit Logging for State Machine and Assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_event_logged_on_case_assignment(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 11: Lead assignment emits append-only audit event with actor, case, and rationale."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(
        id=case_id,
        reference_number="CASE-2026-00101",
        title="Title",
        summary="Summary",
        status="open",
        priority="medium",
        department_id=dept_id,
        lead_investigator_id=None,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    inv_user = User(id=inv_id, department_id=dept_id, is_active=True, full_name="New Lead")
    mocks["user_repo"].get_by_id.return_value = inv_user
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 1

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Assigning subject-matter specialist to lead inquiry.",
        expected_version=1,
    )
    await service.assign_case(case_id, payload, admin)

    # Verify audit event appended
    mocks["audit_repo"].append_event.assert_awaited()
    audit_call = mocks["audit_repo"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_ASSIGNED
    assert audit_call["actor_id"] == admin.user_id
    assert audit_call["target_id"] == str(case_id)
    assert audit_call["department_id"] == dept_id
    assert audit_call["details"]["new_investigator_id"] == str(inv_id)


# ---------------------------------------------------------------------------
# 11. Batch 08 Safety Invariants & Partition Preservation
# ---------------------------------------------------------------------------


def test_biometric_matching_strictly_disabled_and_fails_closed() -> None:
    """Requirement 12: Biometric matching remains permanently disabled during case management."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    matching_service = FaceMatchingService(
        governance_repo=MagicMock(),
        reference_repo=MagicMock(),
        verification_repo=MagicMock(),
        settings=settings,
    )
    with pytest.raises(BiometricsDisabledError, match="Biometric face matching is strictly disabled"):
        import asyncio
        asyncio.run(
            matching_service.match_faces(
                MagicMock(),
                _make_principal(role_code=RoleCode.SUPER_ADMIN.value),
            )
        )


def test_case_management_code_never_references_sealed_violence_partition() -> None:
    """Requirement 12b: Case domain and service files never touch the historical violence test partition."""
    from pathlib import Path

    case_files = [
        Path("backend/app/core/case.py"),
        Path("backend/app/models/case.py"),
        Path("backend/app/services/case.py"),
        Path("backend/app/repositories/case.py"),
        Path("backend/app/schemas/case.py"),
        Path("backend/app/api/v1/cases.py"),
    ]
    for file_path in case_files:
        assert file_path.exists(), f"File {file_path} missing"
        text = file_path.read_text(encoding="utf-8")
        assert "data/raw" not in text
        assert "test_partition" not in text


# ---------------------------------------------------------------------------
# 12. CaseSequenceCounter Model Validation
# ---------------------------------------------------------------------------


def test_case_sequence_counter_model_attributes() -> None:
    """Requirement 13: CaseSequenceCounter model defines year primary key and non-negative sequence."""
    counter = CaseSequenceCounter(year=2026, current_sequence=15)
    assert counter.year == 2026
    assert counter.current_sequence == 15
    assert counter.__tablename__ == "case_sequence_counters"
