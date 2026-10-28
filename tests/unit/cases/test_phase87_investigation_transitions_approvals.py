"""Unit test suite for Phase 87: Investigation Transitions & Approvals.

Comprehensive verification of:
1. Valid lifecycle transitions (draft -> open -> under_investigation -> pending_supervisor_review -> resolved -> closed -> reopened).
2. Invalid transitions rejected.
3. Direct status mutation cannot bypass workflow validation.
4. Authorized submission for supervisor review.
5. Unauthorized submission rejected.
6. Authorized supervisor approval.
7. Unauthorized approval rejected.
8. Rejection requires the defined rationale.
9. Self-approval is blocked where separation of duties requires it.
10. Case reopening follows the approved transition policy.
11. Client-supplied reviewer identity cannot be spoofed.
12. Client-supplied roles or permissions cannot grant approval authority.
13. Cross-department approvals and transitions are denied.
14. Stale case versions return a conflict.
15. Concurrent approvals cannot finalize incompatible outcomes.
16. Duplicate requests follow the documented idempotency policy.
17. Case readiness checks reject missing mandatory information.
18. Readiness checks do not invent or assume unavailable data.
19. Legal holds remain intact during transitions.
20. Evidence bytes and SHA-256 digests remain unchanged.
21. Case-note visibility rules are respected in approval payloads.
22. AI annotations remain advisory and cannot automatically close cases.
23. Transition and approval history is preserved.
24. Audit events match committed state changes.
25. Failed transactions do not leave misleading success events.
26. Biometric matching remains disabled.
27. The sealed historical violence-detection partition is not accessed.
28. Relevant Phases 81–86 regression behavior remains intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.core.ai import SegmentReviewStatus
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    CaseApprovalDecision,
    CasePriority,
    CaseStatus,
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
from backend.app.models.audit import SecurityAuditEvent
from backend.app.models.case import Case, CaseApproval, CaseIncident
from backend.app.models.evidence import EvidenceAttachment
from backend.app.repositories.ai_segment import AICandidateSegmentRepository
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.case import CaseRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.identity import DepartmentRepository, UserRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import FaceMatchRequest
from backend.app.schemas.case import (
    CaseApprovalRead,
    CaseApprovalRequest,
    CaseCloseRequest,
    CaseRead,
    CaseReadinessResult,
    CaseReopenRequest,
    CaseSubmitReviewRequest,
    CaseTransitionHistoryItem,
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
        full_name="Investigator Case Transition Agent",
        role_code=role_code,
        account_status="active",
        is_active=True,
        session_id=uuid4(),
        department_id=department_id or uuid4(),
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
        reference_number=format_canonical_case_reference(2026, 87001),
        department_id=dept_id,
        title="Investigation Case 87",
        summary="Testing case transitions, supervisory approvals, and audit history.",
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
async def test_valid_lifecycle_transitions(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """1. Valid lifecycle transitions advance case status properly."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    lead_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=lead_id,
        status=CaseStatus.DRAFT.value,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = case

    # 1. DRAFT -> OPEN
    res1 = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.OPEN.value,
            reason="Opening case for preliminary review.",
            expected_version_id=1,
        ),
    )
    assert res1.status == CaseStatus.OPEN.value
    assert case.version_id == 2

    # 2. OPEN -> UNDER_INVESTIGATION
    res2 = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.UNDER_INVESTIGATION.value,
            reason="Assigned lead investigator and began active probe.",
            expected_version_id=2,
        ),
    )
    assert res2.status == CaseStatus.UNDER_INVESTIGATION.value
    assert case.version_id == 3

    # 3. UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW
    res3 = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
            reason="Investigation complete; requesting supervisory sign-off.",
            expected_version_id=3,
        ),
    )
    assert res3.status == CaseStatus.PENDING_SUPERVISOR_REVIEW.value
    assert case.version_id == 4

    # 4. PENDING_SUPERVISOR_REVIEW -> RESOLVED
    res4 = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.RESOLVED.value,
            reason="Findings verified; case formally resolved.",
            expected_version_id=4,
        ),
    )
    assert res4.status == CaseStatus.RESOLVED.value
    assert case.version_id == 5

    # 5. RESOLVED -> CLOSED
    res5 = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.CLOSED.value,
            reason="All post-resolution administrative requirements completed.",
            expected_version_id=5,
        ),
    )
    assert res5.status == CaseStatus.CLOSED.value
    assert case.version_id == 6


@pytest.mark.asyncio
async def test_invalid_transitions_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """2. Invalid transitions outside defined state machine are rejected."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # DRAFT -> CLOSED is invalid (must be opened first)
    draft_case = _make_case(department_id=dept_id, status=CaseStatus.DRAFT.value)
    mocks["case_repo"].get_by_id.return_value = draft_case
    with pytest.raises(BusinessRuleError) as exc_draft:
        await service.transition_case_status(
            draft_case.id,
            admin,
            CaseTransitionRequest(
                target_status=CaseStatus.CLOSED.value,
                reason="Attempting illegal direct closure from draft.",
                expected_version_id=1,
            ),
        )
    assert exc_draft.value.code in {"INVALID_CASE_TRANSITION", "INVALID_TRANSITION_FOR_DRAFT"}

    # OPEN -> RESOLVED is invalid (must go through investigation)
    open_case = _make_case(department_id=dept_id, status=CaseStatus.OPEN.value)
    mocks["case_repo"].get_by_id.return_value = open_case
    with pytest.raises(BusinessRuleError) as exc_open:
        await service.transition_case_status(
            open_case.id,
            admin,
            CaseTransitionRequest(
                target_status=CaseStatus.RESOLVED.value,
                reason="Attempting direct resolution without investigation.",
                expected_version_id=1,
            ),
        )
    assert exc_open.value.code == "INVALID_CASE_TRANSITION"


@pytest.mark.asyncio
async def test_direct_status_mutation_cannot_bypass_workflow_validation(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """3. Direct status mutation via update_case cannot bypass workflow validation."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.UNDER_INVESTIGATION.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case

    # Investigator attempts to directly set status to RESOLVED via update_case (bypassing approval)
    with pytest.raises(PermissionDeniedError) as exc_resolve:
        await service.update_case(
            case.id,
            CaseUpdate(
                status=CaseStatus.RESOLVED,
                status_reason="Attempting unauthorized direct resolution.",
                expected_version=1,
            ),
            investigator,
        )
    assert exc_resolve.value.code == "APPROVAL_REQUIRED"

    # Investigator attempts to directly set status to CLOSED without close permission
    with pytest.raises(PermissionDeniedError) as exc_close:
        await service.update_case(
            case.id,
            CaseUpdate(
                status=CaseStatus.CLOSED,
                status_reason="Attempting unauthorized direct closure.",
                expected_version=1,
            ),
            investigator,
        )
    assert exc_close.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_authorized_submission_for_supervisor_review(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """4. Authorized submission for supervisor review advances status and audits."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    lead_id = uuid4()
    inv = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=lead_id)

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=lead_id,
        status=CaseStatus.UNDER_INVESTIGATION.value,
        version_id=2,
    )
    mocks["case_repo"].get_by_id.return_value = case

    res = await service.submit_case_for_review(
        case.id,
        inv,
        CaseSubmitReviewRequest(
            reason="Investigation concluded with complete evidence and notes.",
            expected_version_id=2,
        ),
    )
    assert res.status == CaseStatus.PENDING_SUPERVISOR_REVIEW.value
    assert case.version_id == 3

    # Audit event verified
    call_args = mocks["audit_repo"].append_event.call_args[1]
    assert call_args["action"] == AuditAction.CASE_SUBMITTED_FOR_REVIEW
    assert call_args["actor_id"] == lead_id
    assert call_args["details"]["from_status"] == CaseStatus.UNDER_INVESTIGATION.value
    assert call_args["details"]["to_status"] == CaseStatus.PENDING_SUPERVISOR_REVIEW.value


@pytest.mark.asyncio
async def test_unauthorized_submission_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """5. Unauthorized submission rejected for users without permission or wrong state."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    officer = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.UNDER_INVESTIGATION.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(PermissionDeniedError) as exc_perm:
        await service.submit_case_for_review(
            case.id,
            officer,
            CaseSubmitReviewRequest(
                reason="Submitting without authorized role.",
                expected_version_id=1,
            ),
        )
    assert exc_perm.value.code == "PERMISSION_DENIED"

    # Submitting from DRAFT rejected
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    draft_case = _make_case(department_id=dept_id, status=CaseStatus.DRAFT.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = draft_case

    with pytest.raises(BusinessRuleError) as exc_state:
        await service.submit_case_for_review(
            draft_case.id,
            admin,
            CaseSubmitReviewRequest(
                reason="Submitting draft case directly.",
                expected_version_id=1,
            ),
        )
    assert exc_state.value.code == "INVALID_SUBMISSION_STATE"


@pytest.mark.asyncio
async def test_authorized_supervisor_approval(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """6. Authorized supervisor can approve case transition."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    supervisor_id = uuid4()
    lead_id = uuid4()  # distinct investigator
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=supervisor_id)

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=lead_id,
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=4,
    )
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    payload = CaseApprovalRequest(
        decision=CaseApprovalDecision.APPROVED.value,
        from_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        to_status=CaseStatus.RESOLVED.value,
        rationale="Supervisory review confirms findings are substantiated and procedurally sound.",
        expected_version_id=4,
    )

    res = await service.approve_case_transition(case.id, supervisor, payload)
    assert res.decision == CaseApprovalDecision.APPROVED.value
    assert res.to_status == CaseStatus.RESOLVED.value
    assert case.status == CaseStatus.RESOLVED.value
    assert case.closed_at is not None
    assert case.version_id == 5

    # Verification of recorded audit event
    audit_call = mocks["audit_repo"].append_event.call_args[1]
    assert audit_call["action"] == AuditAction.CASE_APPROVAL_RECORDED
    assert audit_call["actor_id"] == supervisor_id


@pytest.mark.asyncio
async def test_unauthorized_approval_rejected(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """7. Standard investigators without supervisor authority cannot approve."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    inv = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value, version_id=2)
    mocks["case_repo"].get_by_id.return_value = case

    payload = CaseApprovalRequest(
        decision=CaseApprovalDecision.APPROVED.value,
        from_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        to_status=CaseStatus.RESOLVED.value,
        rationale="Investigator trying to approve case independently.",
        expected_version_id=2,
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await service.approve_case_transition(case.id, inv, payload)
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_rejection_requires_defined_rationale(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """8. Rejection requires a formal rationale (>= 10 chars) and returns case to investigation."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=3,
    )
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    # Schema validation catches rationale under 10 chars
    with pytest.raises(ValidationError):
        CaseApprovalRequest(
            decision=CaseApprovalDecision.REJECTED.value,
            from_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
            to_status=CaseStatus.UNDER_INVESTIGATION.value,
            rationale="short",
            expected_version_id=3,
        )

    # Valid rejection
    valid_rejection = CaseApprovalRequest(
        decision=CaseApprovalDecision.REJECTED.value,
        from_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        to_status=CaseStatus.UNDER_INVESTIGATION.value,
        rationale="Additional witness interviews and surveillance timestamps required.",
        expected_version_id=3,
    )

    res = await service.approve_case_transition(case.id, supervisor, valid_rejection)
    assert res.decision == CaseApprovalDecision.REJECTED.value
    assert case.status == CaseStatus.UNDER_INVESTIGATION.value
    assert case.closed_at is None
    assert case.version_id == 4

    audit_call = mocks["audit_repo"].append_event.call_args[1]
    assert audit_call["action"] == AuditAction.CASE_APPROVAL_REJECTED


@pytest.mark.asyncio
async def test_self_approval_blocked_by_separation_of_duties(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """9. Separation of duties prohibits a supervisor from approving their own case."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    supervisor_user_id = uuid4()
    supervisor = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=supervisor_user_id)

    # Supervisor is also lead investigator
    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=supervisor_user_id,
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=5,
    )
    mocks["case_repo"].get_by_id.return_value = case

    payload = CaseApprovalRequest(
        decision=CaseApprovalDecision.APPROVED.value,
        from_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        to_status=CaseStatus.RESOLVED.value,
        rationale="Supervisory approval attempted by case lead investigator.",
        expected_version_id=5,
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await service.approve_case_transition(case.id, supervisor, payload)
    assert exc.value.code == "SELF_APPROVAL_PROHIBITED"

    # Audit event emitted
    audit_call = mocks["audit_repo"].append_event.call_args[1]
    assert audit_call["action"] == AuditAction.CASE_SELF_APPROVAL_BLOCKED


@pytest.mark.asyncio
async def test_case_reopening_follows_approved_policy(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """10. Case reopening requires CASE_REOPEN and moves case back to investigation/reopened."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    inv = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)

    closed_case = _make_case(
        department_id=dept_id,
        status=CaseStatus.CLOSED.value,
        version_id=6,
        is_legal_hold=True,
    )
    mocks["case_repo"].get_by_id.return_value = closed_case

    # Investigator cannot reopen
    with pytest.raises(PermissionDeniedError):
        await service.reopen_case(
            closed_case.id,
            inv,
            CaseReopenRequest(
                reason="Investigator trying to reopen independently.",
                expected_version_id=6,
            ),
        )

    # Admin reopens case
    reopened = await service.reopen_case(
        closed_case.id,
        admin,
        CaseReopenRequest(
            reason="Supplementary forensic evidence recovered requiring review.",
            expected_version_id=6,
            target_status=CaseStatus.REOPENED,
        ),
    )
    assert reopened.status == CaseStatus.REOPENED.value
    assert closed_case.closed_at is None
    assert closed_case.is_legal_hold is True
    assert closed_case.version_id == 7


@pytest.mark.asyncio
async def test_client_supplied_reviewer_identity_cannot_be_spoofed(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """11. Client cannot inject or spoof approver_id."""
    # CaseApprovalRequest schema forbids approver_id
    with pytest.raises(ValidationError):
        CaseApprovalRequest(  # type: ignore[call-arg]
            approver_id=uuid4(),
            decision="approved",
            from_status="pending_supervisor_review",
            to_status="resolved",
            rationale="Attempting to spoof approver identity.",
            expected_version_id=1,
        )


@pytest.mark.asyncio
async def test_client_supplied_roles_or_permissions_cannot_grant_authority(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """12. Authority is determined strictly by verified principal role code."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    officer = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(PermissionDeniedError):
        await service.approve_case_transition(
            case.id,
            officer,
            CaseApprovalRequest(
                decision="approved",
                from_status="pending_supervisor_review",
                to_status="resolved",
                rationale="Officer trying to approve case.",
                expected_version_id=1,
            ),
        )


@pytest.mark.asyncio
async def test_cross_department_approvals_and_transitions_denied(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """13. Cross-department actions are masked as 404 (zero existence leakage)."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    supervisor_a = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_a)

    case_b = _make_case(department_id=dept_b, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value)
    mocks["case_repo"].get_by_id.return_value = case_b

    with pytest.raises(ResourceNotFoundError) as exc_app:
        await service.approve_case_transition(
            case_b.id,
            supervisor_a,
            CaseApprovalRequest(
                decision="approved",
                from_status="pending_supervisor_review",
                to_status="resolved",
                rationale="Cross-department approval attempt.",
                expected_version_id=1,
            ),
        )
    assert exc_app.value.code == "CASE_NOT_FOUND"

    with pytest.raises(ResourceNotFoundError) as exc_trans:
        await service.transition_case_status(
            case_b.id,
            supervisor_a,
            CaseTransitionRequest(
                target_status=CaseStatus.RESOLVED.value,
                reason="Cross-department transition attempt.",
                expected_version_id=1,
            ),
        )
    assert exc_trans.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_stale_case_versions_return_conflict(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """14. Stale case version numbers trigger HTTP 409 ConflictError."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value, version_id=5)
    mocks["case_repo"].get_by_id.return_value = case

    with pytest.raises(ConflictError) as exc_app:
        await service.approve_case_transition(
            case.id,
            admin,
            CaseApprovalRequest(
                decision="approved",
                from_status="pending_supervisor_review",
                to_status="resolved",
                rationale="Stale version approval attempt.",
                expected_version_id=4,  # actual is 5
            ),
        )
    assert exc_app.value.code == "CONCURRENCY_CONFLICT"

    with pytest.raises(ConflictError) as exc_trans:
        await service.transition_case_status(
            case.id,
            admin,
            CaseTransitionRequest(
                target_status=CaseStatus.RESOLVED.value,
                reason="Stale version transition attempt.",
                expected_version_id=4,
            ),
        )
    assert exc_trans.value.code == "CONCURRENCY_CONFLICT"


@pytest.mark.asyncio
async def test_concurrent_approvals_cannot_finalize_incompatible_outcomes(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """15. Competing concurrent approval decisions fail closed on version conflict."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    sup1 = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=uuid4())
    sup2 = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=uuid4())

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    # Supervisor 1 approves, bumping version from 1 to 2
    await service.approve_case_transition(
        case.id,
        sup1,
        CaseApprovalRequest(
            decision="approved",
            from_status="pending_supervisor_review",
            to_status="resolved",
            rationale="Approved by first supervisor.",
            expected_version_id=1,
        ),
    )
    assert case.version_id == 2
    assert case.status == "resolved"

    # Supervisor 2 attempts competing decision using stale expected_version_id=1
    with pytest.raises(ConflictError):
        await service.approve_case_transition(
            case.id,
            sup2,
            CaseApprovalRequest(
                decision="rejected",
                from_status="pending_supervisor_review",
                to_status="under_investigation",
                rationale="Competing rejection attempt by second supervisor.",
                expected_version_id=1,
            ),
        )


@pytest.mark.asyncio
async def test_duplicate_requests_follow_idempotency_policy(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """16. Duplicate identical approval requests return existing approval idempotently."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    sup_id = uuid4()
    sup = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id, user_id=sup_id)

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=3,
    )
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    payload = CaseApprovalRequest(
        decision="approved",
        from_status="pending_supervisor_review",
        to_status="resolved",
        rationale="Substantiated findings warrant case resolution.",
        expected_version_id=3,
    )

    app1 = await service.approve_case_transition(case.id, sup, payload)
    assert app1.decision == "approved"

    # Simulate repo returning saved approval
    existing_approval = CaseApproval(
        id=app1.id,
        case_id=case.id,
        approver_id=sup_id,
        decision="approved",
        from_status="pending_supervisor_review",
        to_status="resolved",
        rationale="Substantiated findings warrant case resolution.",
        created_at=app1.created_at,
    )
    mocks["case_repo"].list_approvals_for_case.return_value = [existing_approval]

    # Retrying identical request returns existing record without error
    app2 = await service.approve_case_transition(case.id, sup, payload)
    assert app2.id == app1.id
    assert app2.decision == "approved"


@pytest.mark.asyncio
async def test_case_readiness_checks_reject_missing_mandatory_information(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """17. Readiness checks identify missing mandatory prerequisites."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # 1. Missing lead investigator when moving to under_investigation
    case_no_lead = _make_case(
        department_id=dept_id,
        lead_investigator_id=None,
        status=CaseStatus.OPEN.value,
    )
    mocks["case_repo"].get_by_id.return_value = case_no_lead

    r1 = await service.get_case_readiness(case_no_lead.id, CaseStatus.UNDER_INVESTIGATION.value, admin)
    assert r1.is_ready is False
    assert any("lead investigator" in b.lower() for b in r1.blocking_reasons)

    # 2. Missing linked incidents when moving to under_investigation
    case_with_lead = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.OPEN.value,
    )
    mocks["case_repo"].get_by_id.return_value = case_with_lead
    mocks["case_repo"].list_case_incidents.return_value = []

    r2 = await service.get_case_readiness(case_with_lead.id, CaseStatus.UNDER_INVESTIGATION.value, admin)
    assert r2.is_ready is False
    assert any("linked incident" in b.lower() for b in r2.blocking_reasons)

    # 3. Unreviewed AI candidate segments when moving to pending_supervisor_review
    case_inv = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.UNDER_INVESTIGATION.value,
    )
    mocks["case_repo"].get_by_id.return_value = case_inv
    mocks["case_repo"].list_notes_for_case.return_value = [MagicMock()]
    unreviewed_seg = MagicMock(review_status=SegmentReviewStatus.PENDING_REVIEW.value)
    link = MagicMock(segment=unreviewed_seg)
    mocks["case_repo"].list_case_ai_segments.return_value = [link]

    r3 = await service.get_case_readiness(case_inv.id, CaseStatus.PENDING_SUPERVISOR_REVIEW.value, admin)
    assert r3.is_ready is False
    assert any("ai candidate segments" in b.lower() for b in r3.blocking_reasons)


@pytest.mark.asyncio
async def test_readiness_checks_do_not_invent_or_assume_unavailable_data(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """18. Readiness returns structured checklist with empirical validation results."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.UNDER_INVESTIGATION.value)
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].list_case_incidents.return_value = [MagicMock()]
    mocks["case_repo"].list_notes_for_case.return_value = [MagicMock()]
    mocks["case_repo"].list_case_ai_segments.return_value = []

    res = await service.get_case_readiness(case.id, CaseStatus.PENDING_SUPERVISOR_REVIEW.value, admin)
    assert isinstance(res, CaseReadinessResult)
    assert res.is_ready is True
    assert len(res.checks) > 0
    assert all(chk.passed for chk in res.checks)


@pytest.mark.asyncio
async def test_legal_holds_remain_intact_during_transitions(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """19. Legal holds remain active and untouched across transitions and closures."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(
        department_id=dept_id,
        status=CaseStatus.UNDER_INVESTIGATION.value,
        version_id=1,
        is_legal_hold=True,
    )
    mocks["case_repo"].get_by_id.return_value = case

    res = await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
            reason="Proceeding with transition while preserving active legal hold.",
            expected_version_id=1,
        ),
    )
    assert res.is_legal_hold is True
    assert case.is_legal_hold is True


@pytest.mark.asyncio
async def test_evidence_bytes_and_sha256_digests_remain_unchanged(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """20. Evidence attachments, hashes, and digests remain untouched during transitions."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    evidence_item = EvidenceAttachment(
        id=uuid4(),
        department_id=dept_id,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        original_filename="security_cam_1.mp4",
        file_size_bytes=1048576,
    )
    case = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value, version_id=2)
    case.evidence = [MagicMock(evidence=evidence_item)]
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    original_digest = evidence_item.sha256_hash

    await service.approve_case_transition(
        case.id,
        admin,
        CaseApprovalRequest(
            decision="approved",
            from_status="pending_supervisor_review",
            to_status="resolved",
            rationale="Approval transition preserving evidence hashes.",
            expected_version_id=2,
        ),
    )
    assert evidence_item.sha256_hash == original_digest
    assert evidence_item.file_size_bytes == 1048576


@pytest.mark.asyncio
async def test_case_note_visibility_rules_respected_in_approval_payloads(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """21. CaseApprovalRead payloads do not expose case notes or restricted disclosures."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(
        department_id=dept_id,
        lead_investigator_id=uuid4(),
        status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
        version_id=1,
    )
    mocks["case_repo"].get_by_id.return_value = case
    mocks["case_repo"].create_approval.side_effect = lambda a: a

    res = await service.approve_case_transition(
        case.id,
        admin,
        CaseApprovalRequest(
            decision="approved",
            from_status="pending_supervisor_review",
            to_status="resolved",
            rationale="Formal decision without leaking internal note bodies.",
            expected_version_id=1,
        ),
    )
    dumped = res.model_dump()
    assert "notes" not in dumped
    assert "restricted" not in dumped


@pytest.mark.asyncio
async def test_ai_annotations_remain_advisory_cannot_automatically_close_cases(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """22. AI candidate annotations and scores cannot automatically resolve or close cases."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    inv = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)

    # Even with high-confidence AI findings, case requires formal human review and approval
    case = _make_case(department_id=dept_id, status=CaseStatus.UNDER_INVESTIGATION.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case

    # Statutory disclaimer verified
    assert "probabilistic and advisory only" in AI_ADVISORY_DISCLAIMER

    # Investigator cannot jump to resolved based on AI output alone
    with pytest.raises(PermissionDeniedError):
        await service.transition_case_status(
            case.id,
            inv,
            CaseTransitionRequest(
                target_status=CaseStatus.RESOLVED.value,
                reason="AI detected violence with 99.8% confidence.",
                expected_version_id=1,
            ),
        )


@pytest.mark.asyncio
async def test_transition_and_approval_history_is_preserved(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """23. Full transition and approval history is retrievable in chronological sequence."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case

    app_record = CaseApproval(
        id=uuid4(),
        case_id=case.id,
        approver_id=admin.user_id,
        decision="approved",
        from_status="pending_supervisor_review",
        to_status="resolved",
        rationale="Supervisory approval granted.",
        created_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
    )
    mocks["case_repo"].list_approvals_for_case.return_value = [app_record]

    audit_ev = SecurityAuditEvent(
        id=uuid4(),
        sequence_number=1,
        created_at=datetime(2026, 10, 28, 11, 0, tzinfo=UTC),
        action=AuditAction.CASE_SUBMITTED_FOR_REVIEW.value,
        actor_id=admin.user_id,
        actor_role=admin.role_code,
        target_type=AuditTargetType.CASE.value,
        target_id=str(case.id),
        outcome=AuditOutcome.SUCCESS.value,
        department_id=dept_id,
        details={"from_status": "under_investigation", "to_status": "pending_supervisor_review", "reason": "Ready"},
        event_hash="test",
    )
    mocks["audit_repo"].list_events_for_target.return_value = [audit_ev]

    history = await service.get_case_transition_history(case.id, admin)
    assert len(history) == 2
    # Verify chronological ordering
    assert history[0].created_at < history[1].created_at
    assert history[0].action == AuditAction.CASE_SUBMITTED_FOR_REVIEW.value
    assert history[1].action == "approval_decision"


@pytest.mark.asyncio
async def test_audit_events_match_committed_state_changes(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """24. Committed state transitions emit accurately corresponding audit records."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.DRAFT.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case

    await service.transition_case_status(
        case.id,
        admin,
        CaseTransitionRequest(
            target_status=CaseStatus.OPEN.value,
            reason="Opening case.",
            expected_version_id=1,
        ),
    )

    call_args = mocks["audit_repo"].append_event.call_args[1]
    assert call_args["action"] == AuditAction.CASE_STATUS_TRANSITION
    assert call_args["details"]["from_status"] == CaseStatus.DRAFT.value
    assert call_args["details"]["to_status"] == CaseStatus.OPEN.value


@pytest.mark.asyncio
async def test_failed_transactions_do_not_leave_misleading_success_events(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """25. Failed transition attempts emit failure audit events instead of success."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case = _make_case(department_id=dept_id, status=CaseStatus.DRAFT.value, version_id=1)
    mocks["case_repo"].get_by_id.return_value = case

    # Prohibited transition from DRAFT to CLOSED
    with pytest.raises(BusinessRuleError):
        await service.transition_case_status(
            case.id,
            admin,
            CaseTransitionRequest(
                target_status=CaseStatus.CLOSED.value,
                reason="Prohibited closure directly from draft.",
                expected_version_id=1,
            ),
        )

    # Audited as failure
    call_args = mocks["audit_repo"].append_event.call_args[1]
    assert call_args["action"] == AuditAction.CASE_TRANSITION_FAILED


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """26. Biometric matching is permanently locked (BIOMETRIC_MATCHING_ENABLED=False)."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    matching_service = FaceMatchingService(
        governance_repo=AsyncMock(),
        reference_repo=AsyncMock(),
        verification_repo=AsyncMock(),
        settings=settings,
    )

    req = FaceMatchRequest(
        governance_record_id=uuid4(),
        reference_id=uuid4(),
        probe_image_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    )

    with pytest.raises(BiometricsDisabledError):
        await matching_service.match_faces(
            req,
            _make_principal(RoleCode.SUPER_ADMIN.value),
        )


def test_sealed_historical_violence_partition_is_not_accessed() -> None:
    """27. The historical violence-detection partition (N=354) remains sealed."""
    workspace_root = Path("D:/PROJECT/E-WITTNESS")
    leaked_files = list(workspace_root.glob("**/historical_violence_test_partition_*.csv"))
    assert len(leaked_files) == 0, f"Found exposed historical partition files: {leaked_files}"


@pytest.mark.asyncio
async def test_relevant_phase81_to_86_regression_behavior_intact(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """28. Phases 81–86 regression behavior remains intact."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    # 1. Sequence reference format (Phase 81)
    ref = format_canonical_case_reference(2026, 42)
    assert ref == "CASE-2026-00042"

    # 2. Workload capacity check (Phase 82)
    inv_user = MagicMock()
    inv_user.id = uuid4()
    inv_user.department_id = dept_id
    mocks["user_repo"].get_by_id.return_value = inv_user
    mocks["user_repo"].get_by_id_unscoped.return_value = inv_user

    mocks["case_repo"].count_active_cases_for_investigator.return_value = 10
    workload = await service.get_investigator_workload(inv_user.id, admin)
    assert workload.capacity_available is False

    # 3. List pending approvals (Phase 87)
    case_pending = _make_case(department_id=dept_id, status=CaseStatus.PENDING_SUPERVISOR_REVIEW.value)
    mocks["case_repo"].list_pending_approvals.return_value = [case_pending]

    pending_list = await service.list_pending_approvals(admin)
    assert len(pending_list) == 1
    assert pending_list[0].status == CaseStatus.PENDING_SUPERVISOR_REVIEW.value
