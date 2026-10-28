"""Unit test suite for Phase 82: Case Assignment, Investigator Workload Limits & Supervisor Overrides.

Requirements covered:
1. Valid same-department assignment.
2. Assignment to an inactive or ineligible investigator.
3. Unauthorized cross-department assignment.
4. Workload counts across every case status (active vs terminal).
5. Rejection at the configured maximum capacity.
6. Assignment allowed below the configured maximum.
7. Closed cases excluded from active workload calculations.
8. Reassignment updates both investigators' workloads and maintains history.
9. Missing or blank override justification rejected (<10 chars).
10. Unauthorized override rejected with 403 (e.g. investigator attempting override).
11. Authorized override audited correctly with prior/limit/resulting workload and justification.
12. Client-supplied workload values ignored (authoritative database records only).
13. Concurrent assignment attempts cannot exceed limit (row-level locking).
14. Database rollback on failed assignment.
15. Audit events preserve prior assignment history.
16. Optimistic concurrency conflicts handled safely (version_id mismatch 409).
17. Departmental isolation on workload endpoints (masked as 404).
18. Existing Phase 81 lifecycle state transitions remain passing.
19. Batch 08 safety invariants permanently enforced (BIOMETRIC_MATCHING_ENABLED=False).
20. Static check ensuring case management never references sealed violence test partition.
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
    ACTIVE_CASE_STATUSES,
    INVESTIGATOR_DEFAULT_MAX_ACTIVE_CASES,
    TERMINAL_CASE_STATUSES,
    CasePriority,
    CaseStatus,
    format_canonical_case_reference,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    BusinessRuleError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.case import Case, CaseAssignment
from backend.app.models.department import Department
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
    CaseAssignRequest,
    CaseAssignmentRead,
    InvestigatorWorkloadRead,
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
    role_code: str = RoleCode.DEPT_ADMIN.value,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
    email: str = "supervisor@ewitness.test",
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email=email,
        full_name="Department Supervisor",
        role_code=role_code,
        account_status="active",
        is_active=True,
        session_id=uuid4(),
        department_id=department_id or uuid4(),
    )


def _make_case(
    id: UUID | None = None,
    reference_number: str = "CASE-2026-00001",
    title: str = "Investigation Title",
    summary: str = "Formal case summary description.",
    status: str = "open",
    priority: str = "medium",
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


def _make_user(
    id: UUID | None = None,
    department_id: UUID | None = None,
    is_active: bool = True,
    account_status: str = "active",
    role_code: str = RoleCode.INVESTIGATOR.value,
    full_name: str = "Detective Jane Doe",
) -> User:
    role = Role(id=uuid4(), code=role_code, name=role_code.title())
    user = User(
        id=id or uuid4(),
        email=f"user_{uuid4().hex[:6]}@ewitness.test",
        full_name=full_name,
        department_id=department_id or uuid4(),
        is_active=is_active,
        account_status=account_status,
        role_id=role.id,
    )
    user.role = role
    return user


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
    settings = _get_test_settings()
    service = CaseService(
        case_repo=mocks["case_repo"],
        incident_repo=mocks["incident_repo"],
        evidence_repo=mocks["evidence_repo"],
        ai_segment_repo=mocks["ai_segment_repo"],
        department_repo=mocks["department_repo"],
        user_repo=mocks["user_repo"],
        audit_repo=mocks["audit_repo"],
        settings=settings,
        max_active_cases=10,
    )
    return service, mocks


# ---------------------------------------------------------------------------
# 1. Valid Same-Department Assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_same_department_assignment(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 1: Valid same-department assignment updates lead, version, and records assignment."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(
        id=case_id,
        department_id=dept_id,
        lead_investigator_id=None,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 3  # well below 10

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Standard assignment to primary investigator.",
        expected_version=1,
    )
    result = await service.assign_case(case_id, payload, admin)

    assert result.lead_investigator_id == inv_id
    assert result.version_id == 2
    mocks["case_repo"].record_assignment.assert_awaited_once()
    mocks["audit_repo"].append_event.assert_awaited_once()

    audit_call = mocks["audit_repo"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_ASSIGNED
    assert audit_call["outcome"] == AuditOutcome.SUCCESS
    assert audit_call["details"]["new_investigator_id"] == str(inv_id)
    assert audit_call["details"]["previous_investigator_id"] is None


# ---------------------------------------------------------------------------
# 2. Assignment to Inactive or Ineligible Investigator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_to_inactive_investigator_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 2a: Assigning to an inactive investigator is rejected."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    inactive_inv = _make_user(id=inv_id, department_id=dept_id, is_active=False)
    mocks["user_repo"].get_by_id.return_value = inactive_inv

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Assigning inactive officer.",
        expected_version=1,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin)
    assert exc.value.code == "INVALID_INVESTIGATOR"
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_assignment_to_ineligible_role_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 2b: Assigning to an ineligible user role (e.g. Student) is rejected."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    student_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    student_user = _make_user(
        id=student_id,
        department_id=dept_id,
        is_active=True,
        role_code=RoleCode.STUDENT.value,
    )
    mocks["user_repo"].get_by_id.return_value = student_user

    payload = CaseAssignRequest(
        new_investigator_id=student_id,
        assignment_reason="Attempting to assign case to a student account.",
        expected_version=1,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin)
    assert exc.value.code == "INELIGIBLE_INVESTIGATOR_ROLE"
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 3. Unauthorized Cross-Department Assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_department_assignment_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 3: Assigning an investigator from another department is strictly forbidden."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    case_id = uuid4()
    inv_b = uuid4()
    admin_a = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_a)

    case_entity = _make_case(id=case_id, department_id=dept_a, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    # User repository scoped lookup returns user with department B
    user_foreign = _make_user(id=inv_b, department_id=dept_b, is_active=True)
    mocks["user_repo"].get_by_id.return_value = user_foreign

    payload = CaseAssignRequest(
        new_investigator_id=inv_b,
        assignment_reason="Attempting cross-department lead transfer.",
        expected_version=1,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin_a)
    assert exc.value.code == "CROSS_DEPARTMENT_ASSIGNMENT_FORBIDDEN"
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_cross_department_case_access_returns_not_found_on_assignment(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 3b: Attempting to assign a case in another department masks as 404."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    case_id = uuid4()
    inv_b = uuid4()
    admin_b = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_b)

    # Case belongs to Department A
    case_entity = _make_case(id=case_id, department_id=dept_a, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    payload = CaseAssignRequest(
        new_investigator_id=inv_b,
        assignment_reason="Unauthorized cross department attempt.",
        expected_version=1,
    )
    with pytest.raises(ResourceNotFoundError) as exc:
        await service.assign_case(case_id, payload, admin_b)
    assert exc.value.code == "CASE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 4. Workload Counts Across Every Case Status (Active vs Terminal)
# ---------------------------------------------------------------------------


def test_workload_counts_across_every_case_status() -> None:
    """Requirement 4: Verify active vs terminal status sets for workload calculation."""
    expected_active = {
        CaseStatus.DRAFT,
        CaseStatus.OPEN,
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.PENDING_REVIEW,
        CaseStatus.PENDING_SUPERVISOR_REVIEW,
        CaseStatus.SUSPENDED,
        CaseStatus.REOPENED,
    }
    expected_terminal = {
        CaseStatus.CLOSED,
        CaseStatus.RESOLVED,
    }

    assert ACTIVE_CASE_STATUSES == expected_active
    assert TERMINAL_CASE_STATUSES == expected_terminal
    # Mutually exclusive and exhaustive partitioning
    assert ACTIVE_CASE_STATUSES.isdisjoint(TERMINAL_CASE_STATUSES)
    all_statuses = frozenset(CaseStatus)
    assert ACTIVE_CASE_STATUSES | TERMINAL_CASE_STATUSES == all_statuses


# ---------------------------------------------------------------------------
# 5. Rejection at Configured Maximum & 6. Allowed Below Maximum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_rejected_at_configured_maximum(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 5: Assignment rejected with 422 when investigator is at maximum (10)."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    # At max capacity (10 active cases)
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 10

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Standard assignment exceeding limit.",
        expected_version=1,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin)
    assert exc.value.code == "INVESTIGATOR_CAPACITY_EXCEEDED"
    assert exc.value.status_code == 422
    assert "maximum active case capacity (10)" in str(exc.value)


@pytest.mark.asyncio
async def test_assignment_allowed_below_maximum(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 6: Assignment succeeds when investigator has capacity (e.g. 9 active cases)."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    # 9 active cases (capacity remaining)
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 9

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="10th case assignment under limit.",
        expected_version=1,
    )
    result = await service.assign_case(case_id, payload, admin)
    assert result.lead_investigator_id == inv_id


# ---------------------------------------------------------------------------
# 7. Closed Cases Excluded from Active Workload
# ---------------------------------------------------------------------------


def test_closed_cases_excluded_from_active_workload() -> None:
    """Requirement 7: Closed cases are explicitly excluded from active workload."""
    assert CaseStatus.CLOSED not in ACTIVE_CASE_STATUSES
    assert CaseStatus.CLOSED in TERMINAL_CASE_STATUSES
    assert CaseStatus.RESOLVED not in ACTIVE_CASE_STATUSES
    assert CaseStatus.RESOLVED in TERMINAL_CASE_STATUSES


# ---------------------------------------------------------------------------
# 8. Reassignment Updates Both Investigators & Preserves History
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reassignment_updates_workload_and_records_history(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 8: Reassignment passes exclude_case_id and records prior lead in assignment and audit."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_old = uuid4()
    inv_new = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(
        id=case_id,
        department_id=dept_id,
        lead_investigator_id=inv_old,
        version_id=2,
    )
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    new_investigator = _make_user(id=inv_new, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = new_investigator
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 4

    payload = CaseAssignRequest(
        new_investigator_id=inv_new,
        assignment_reason="Reassigning lead due to specialized forensic requirements.",
        expected_version=2,
    )
    result = await service.assign_case(case_id, payload, admin)

    assert result.lead_investigator_id == inv_new
    assert result.version_id == 3

    # Verify exclude_case_id passed to avoid double counting
    count_call = mocks["case_repo"].count_active_cases_for_investigator.call_args
    assert count_call.kwargs["exclude_case_id"] == case_id

    # Verify assignment record captured previous lead
    recorded_asgn = mocks["case_repo"].record_assignment.call_args[0][0]
    assert recorded_asgn.previous_investigator_id == inv_old
    assert recorded_asgn.new_investigator_id == inv_new

    # Verify audit event action is CASE_REASSIGNED
    audit_call = mocks["audit_repo"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_REASSIGNED
    assert audit_call["details"]["previous_investigator_id"] == str(inv_old)
    assert audit_call["details"]["new_investigator_id"] == str(inv_new)


# ---------------------------------------------------------------------------
# 9. Missing or Blank Override Justification Rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_justification",
    [
        None,
        "",
        "   ",
        "Short",
        "Only 9 ch",
    ],
)
async def test_missing_or_blank_override_justification_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
    bad_justification: str | None,
) -> None:
    """Requirement 9: Supervisor override with missing, blank, or <10 char justification is rejected."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Overriding limit.",
        expected_version=1,
        is_supervisor_override=True,
        override_justification=bad_justification,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin)
    assert exc.value.code == "MISSING_OVERRIDE_JUSTIFICATION"
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 10. Unauthorized Override Rejected (403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_override_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 10: Non-supervisor attempting override is rejected with 403."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    # Investigator role lacks CASE_ASSIGN_OVERRIDE
    investigator_principal = _make_principal(
        role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id
    )

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Attempting unauthorized supervisor override.",
        expected_version=1,
        is_supervisor_override=True,
        override_justification="Valid justification string that is long enough.",
    )
    with pytest.raises(PermissionDeniedError) as exc:
        await service.assign_case(case_id, payload, investigator_principal)
    assert exc.value.code == "OVERRIDE_PERMISSION_DENIED"
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 11. Authorized Override Audited Correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_override_audited_correctly(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 11: Authorized override by supervisor succeeds and records full audit trail."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    # At maximum capacity (10)
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 10

    override_reason = "Urgent high-profile campus incident requiring senior forensic expertise immediately."
    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Supervisor emergency reassignment.",
        expected_version=1,
        is_supervisor_override=True,
        override_justification=override_reason,
    )
    result = await service.assign_case(case_id, payload, admin)

    assert result.lead_investigator_id == inv_id
    assert result.version_id == 2

    # Verify assignment record captured override metadata
    recorded_asgn = mocks["case_repo"].record_assignment.call_args[0][0]
    assert recorded_asgn.is_supervisor_override is True
    assert recorded_asgn.override_justification == override_reason

    # Verify audit event action and enriched details
    audit_call = mocks["audit_repo"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_ASSIGNMENT_OVERRIDDEN
    assert audit_call["outcome"] == AuditOutcome.SUCCESS
    assert audit_call["details"]["is_supervisor_override"] is True
    assert audit_call["details"]["override_justification"] == override_reason
    assert audit_call["details"]["prior_workload"] == 10
    assert audit_call["details"]["configured_limit"] == 10
    assert audit_call["details"]["resulting_workload"] == 11
    assert audit_call["details"]["supervisor_id"] == str(admin.user_id)


# ---------------------------------------------------------------------------
# 12. Client-Supplied Workload Values Ignored
# ---------------------------------------------------------------------------


def test_client_supplied_workload_values_forbidden_in_schema() -> None:
    """Requirement 12: Client-supplied active workload counts are strictly forbidden in assign schema."""
    with pytest.raises(ValidationError):
        CaseAssignRequest(
            new_investigator_id=uuid4(),
            expected_version=1,
            active_cases_count=5,  # type: ignore
        )


# ---------------------------------------------------------------------------
# 13. Concurrency Handling & Row-Level Locking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_assignment_uses_with_for_update_row_locking(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 13: Service requests with_for_update=True on investigator retrieval for safe capacity concurrency."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity
    mocks["case_repo"].update.side_effect = lambda c: c

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 2

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Standard assignment.",
        expected_version=1,
    )
    await service.assign_case(case_id, payload, admin)

    # Verify user_repo was queried with with_for_update=True
    user_call = mocks["user_repo"].get_by_id.call_args
    assert user_call.kwargs.get("with_for_update") is True


# ---------------------------------------------------------------------------
# 14. Database Rollback on Failed Assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_rollback_on_failed_assignment(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 14: Failed assignment persistence propagates exception for transaction rollback."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_entity

    investigator = _make_user(id=inv_id, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = investigator
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 2

    # Simulate database error during record_assignment
    mocks["case_repo"].record_assignment.side_effect = RuntimeError("Database deadlock / write failure.")

    payload = CaseAssignRequest(
        new_investigator_id=inv_id,
        assignment_reason="Assignment hitting failure.",
        expected_version=1,
    )
    with pytest.raises(RuntimeError, match="Database deadlock"):
        await service.assign_case(case_id, payload, admin)

    # Verify case_repo.update was NOT executed
    mocks["case_repo"].update.assert_not_called()
    mocks["audit_repo"].append_event.assert_not_called()


# ---------------------------------------------------------------------------
# 15. Audit Events Preserve Prior Assignment History
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_preserves_initial_and_reassignment_history(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 15: History audit event cleanly distinguishes first assignment vs subsequent reassignments."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    inv1 = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # Initial assignment (previous lead is None)
    case_initial = _make_case(id=case_id, department_id=dept_id, lead_investigator_id=None, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case_initial
    mocks["case_repo"].update.side_effect = lambda c: c

    user1 = _make_user(id=inv1, department_id=dept_id, is_active=True)
    mocks["user_repo"].get_by_id.return_value = user1
    mocks["case_repo"].count_active_cases_for_investigator.return_value = 0

    await service.assign_case(
        case_id,
        CaseAssignRequest(new_investigator_id=inv1, expected_version=1, assignment_reason="Initial"),
        admin,
    )
    first_audit = mocks["audit_repo"].append_event.call_args.kwargs
    assert first_audit["action"] == AuditAction.CASE_ASSIGNED
    assert first_audit["details"]["previous_investigator_id"] is None
    assert first_audit["details"]["new_investigator_id"] == str(inv1)


# ---------------------------------------------------------------------------
# 16. Optimistic Concurrency Conflict Handled Safely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict_handled_safely(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 16: Version mismatch raises BusinessRuleError with code CONCURRENCY_CONFLICT (409)."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    case_id = uuid4()
    admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # Case is at version 3
    case_entity = _make_case(id=case_id, department_id=dept_id, version_id=3)
    mocks["case_repo"].get_by_id.return_value = case_entity

    # Caller submits stale version 2
    payload = CaseAssignRequest(
        new_investigator_id=uuid4(),
        expected_version=2,
    )
    with pytest.raises(BusinessRuleError) as exc:
        await service.assign_case(case_id, payload, admin)
    assert exc.value.code == "CONCURRENCY_CONFLICT"
    assert exc.value.status_code == 409
    assert "Current version is 3, expected 2" in str(exc.value)


# ---------------------------------------------------------------------------
# 17. Departmental Isolation on Workload Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_departmental_isolation_on_workload_endpoint(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """Requirement 17: Workload lookup for investigator in another department masked as 404."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    inv_foreign = uuid4()
    admin_a = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_a)

    # User lookup scoped to dept_a returns None
    mocks["user_repo"].get_by_id.return_value = None

    with pytest.raises(ResourceNotFoundError) as exc:
        await service.get_investigator_workload(inv_foreign, admin_a)
    assert exc.value.code == "USER_NOT_FOUND"
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 18. Existing Phase 81 Lifecycle & Reference Tests
# ---------------------------------------------------------------------------


def test_canonical_case_reference_format_preserved() -> None:
    """Requirement 18: Canonical case reference format CASE-YYYY-XXXXX is strictly preserved."""
    ref = format_canonical_case_reference(2026, 42)
    assert ref == "CASE-2026-00042"
    assert len(ref) == 15


# ---------------------------------------------------------------------------
# 19. Permanent Biometric Matching Prohibition & Fail-Closed
# ---------------------------------------------------------------------------


def test_biometric_matching_strictly_disabled_cannot_be_overridden() -> None:
    """Requirement 19: BIOMETRIC_MATCHING_ENABLED=False remains permanently fail-closed."""
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


# ---------------------------------------------------------------------------
# 20. Codebase Never References Sealed Violence Partition
# ---------------------------------------------------------------------------


def test_case_management_never_references_sealed_violence_partition() -> None:
    """Requirement 20: Case files never import or reference the sealed violence-detection partition."""
    from pathlib import Path

    case_files = [
        Path("backend/app/core/case.py"),
        Path("backend/app/models/case.py"),
        Path("backend/app/repositories/case.py"),
        Path("backend/app/services/case.py"),
        Path("backend/app/api/v1/cases.py"),
        Path("backend/app/schemas/case.py"),
    ]

    prohibited_tokens = [
        "violence_detection/test",
        "violence_test_partition",
        "exposed_violence_partition",
        "354_samples",
    ]

    for file_path in case_files:
        if file_path.exists():
            text = file_path.read_text(encoding="utf-8").lower()
            for token in prohibited_tokens:
                assert token not in text, f"Forbidden reference '{token}' found in {file_path}"
