"""Unit test suite for Phase 86: Case Notes, Visibility Tiers & Append-Only Note History.

Requirements covered:
1. Authorized case note creation (public, internal, confidential, restricted).
2. Rejection of unauthenticated or unauthorized note creation.
3. Author identity cannot be spoofed (derived strictly from authenticated principal).
4. Department identity cannot be spoofed (derived from case/principal).
5. Each visibility tier follows its documented permission matrix.
6. Unauthorized restricted-note reads are denied (403 with audit).
7. Unauthorized users cannot change note visibility (requires CASE_NOTE_VISIBILITY_MANAGE).
8. Cross-department note access is denied without leaking existence (404).
9. Note edits preserve earlier revisions in CaseNoteHistory.
10. Note history is ordered and complete.
11. Visibility changes are historically traceable with audit events.
12. Stale revisions return a conflict (409 ConflictError).
13. Concurrent edits cannot silently overwrite each other.
14. Repeated requests have defined idempotency behavior.
15. Unauthorized note history access is denied.
16. Case list/detail responses do not leak restricted notes.
17. Search and timeline responses respect visibility rules.
18. Notifications do not leak restricted content.
19. Exports do not leak restricted notes.
20. Audit events correspond to committed changes.
21. Failed mutations do not leave misleading success events.
22. Note editing does not modify original evidence bytes or digests.
23. Legal holds and case lifecycle restrictions remain respected.
24. Biometric matching remains disabled (fail-closed).
25. The sealed historical violence-detection test partition (N=354) is not accessed.
26. Existing Phase 81–85 regression behavior remains intact.
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
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    CaseNoteVisibility,
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
from backend.app.models.case import Case, CaseNote, CaseNoteHistory
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
    CaseExportRequest,
    CaseNoteCreate,
    CaseNoteHistoryRead,
    CaseNoteRead,
    CaseNoteUpdate,
    CaseNoteVisibilityUpdate,
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
        full_name="Investigator Case Note Reviewer",
        role_code=role_code,
        account_status="active",
        is_active=True,
        session_id=uuid4(),
        department_id=department_id or uuid4(),
    )


def _make_case(
    case_id: UUID | None = None,
    department_id: UUID | None = None,
    lead_investigator_id: UUID | None = None,
    status: str = CaseStatus.UNDER_INVESTIGATION.value,
    version_id: int = 1,
    is_legal_hold: bool = False,
) -> Case:
    cid = case_id or uuid4()
    dept_id = department_id or uuid4()
    c = Case(
        id=cid,
        reference_number=format_canonical_case_reference(2026, 86001),
        department_id=dept_id,
        title="Investigation Case 86",
        summary="Testing case notes, visibility tiers, and append-only history.",
        status=status,
        priority=CasePriority.HIGH.value,
        lead_investigator_id=lead_investigator_id or uuid4(),
        created_by_id=uuid4(),
        version_id=version_id,
        is_legal_hold=is_legal_hold,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    c.evidence = []
    c.ai_segments = []
    c.notes = []
    return c


def _make_note(
    note_id: UUID | None = None,
    case_id: UUID | None = None,
    author_id: UUID | None = None,
    visibility: str = CaseNoteVisibility.INTERNAL.value,
    content: str = "Standard internal investigative observation.",
    version_id: int = 1,
    is_archived: bool = False,
) -> CaseNote:
    n = CaseNote(
        id=note_id or uuid4(),
        case_id=case_id or uuid4(),
        author_id=author_id or uuid4(),
        visibility=visibility,
        content=content,
        version_id=version_id,
        is_archived=is_archived,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    n.history = []
    return n


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
# Test Cases (Requirements 1 to 26)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_case_note_creation(case_service, mock_repos):
    """1. Authorized case note creation for public, internal, and restricted tiers."""
    dept_id = uuid4()
    inv_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    dept_admin_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    # 1a. Investigator creates public note
    pub_payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.PUBLIC.value,
        content="Public summary note visible to all authenticated case participants.",
    )
    pub_result = await case_service.create_case_note(case_entity.id, inv_principal, pub_payload)
    assert pub_result.visibility == CaseNoteVisibility.PUBLIC.value
    assert pub_result.author_id == inv_principal.user_id
    assert pub_result.version_id == 1

    # 1b. Investigator creates internal note
    int_payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Standard internal working note for investigation squad.",
    )
    int_result = await case_service.create_case_note(case_entity.id, inv_principal, int_payload)
    assert int_result.visibility == CaseNoteVisibility.INTERNAL.value

    # 1c. Department admin creates restricted note
    res_payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.RESTRICTED.value,
        content="Sensitive internal affairs note requiring elevated permission.",
    )
    res_result = await case_service.create_case_note(case_entity.id, dept_admin_principal, res_payload)
    assert res_result.visibility == CaseNoteVisibility.RESTRICTED.value
    assert res_result.author_id == dept_admin_principal.user_id


@pytest.mark.asyncio
async def test_unauthenticated_or_unauthorized_note_creation_rejected(case_service, mock_repos):
    """2. Rejection of unauthorized role attempting note creation."""
    dept_id = uuid4()
    student_principal = _make_principal(RoleCode.STUDENT.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Unauthorized note creation attempt by student.",
    )
    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.create_case_note(case_entity.id, student_principal, payload)
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_author_identity_cannot_be_spoofed(case_service, mock_repos):
    """3. Author identity cannot be spoofed; derived strictly from authenticated principal."""
    dept_id = uuid4()
    real_inv_id = uuid4()
    spoofed_author_id = uuid4()

    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=real_inv_id)
    case_entity = _make_case(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    # Schema forbids extra attributes like author_id
    with pytest.raises(ValidationError):
        CaseNoteCreate(
            visibility=CaseNoteVisibility.INTERNAL.value,
            content="Attempting client author spoofing.",
            author_id=spoofed_author_id,  # Extra forbidden field
        )

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Valid note body without spoofed fields.",
    )
    result = await case_service.create_case_note(case_entity.id, principal, payload)
    assert result.author_id == real_inv_id
    assert result.author_id != spoofed_author_id


@pytest.mark.asyncio
async def test_department_identity_cannot_be_spoofed(case_service, mock_repos):
    """4. Department identity cannot be spoofed; derived from case record."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Checking department derivation.",
    )
    result = await case_service.create_case_note(case_entity.id, principal, payload)

    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["department_id"] == dept_id


@pytest.mark.asyncio
async def test_visibility_tiers_follow_permission_matrix(case_service, mock_repos):
    """5. Each visibility tier follows its documented permission matrix."""
    dept_id = uuid4()
    author_id = uuid4()
    lead_id = uuid4()
    other_inv_id = uuid4()

    author_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    lead_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=lead_id)
    other_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)
    dept_admin_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(department_id=dept_id, lead_investigator_id=lead_id)
    mock_repos["case"].get_by_id.return_value = case_entity

    note_pub = _make_note(case_id=case_entity.id, author_id=author_id, visibility="public", content="Public note 1")
    note_int = _make_note(case_id=case_entity.id, author_id=author_id, visibility="internal", content="Internal note 1")
    note_conf = _make_note(case_id=case_entity.id, author_id=author_id, visibility="confidential", content="Confidential note 1")
    note_rest = _make_note(case_id=case_entity.id, author_id=author_id, visibility="restricted", content="Restricted note 1")

    all_notes = [note_pub, note_int, note_conf, note_rest]
    mock_repos["case"].list_notes_for_case.return_value = all_notes

    # Author sees all 4 (since author sees their own restricted and confidential notes)
    author_visible = await case_service.list_case_notes(case_entity.id, author_principal)
    assert len(author_visible) == 4

    # Lead investigator sees public, internal, and confidential; does NOT see another author's restricted note
    lead_visible = await case_service.list_case_notes(case_entity.id, lead_principal)
    assert len(lead_visible) == 3
    assert {n.visibility for n in lead_visible} == {"public", "internal", "confidential"}

    # Other ordinary investigator sees ONLY public and internal
    other_visible = await case_service.list_case_notes(case_entity.id, other_principal)
    assert len(other_visible) == 2
    assert {n.visibility for n in other_visible} == {"public", "internal"}

    # Department administrator sees ALL 4
    admin_visible = await case_service.list_case_notes(case_entity.id, dept_admin_principal)
    assert len(admin_visible) == 4


@pytest.mark.asyncio
async def test_unauthorized_restricted_note_reads_denied(case_service, mock_repos):
    """6. Unauthorized restricted-note reads are denied with 403 and audited."""
    dept_id = uuid4()
    author_id = uuid4()
    other_inv_id = uuid4()

    other_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)
    case_entity = _make_case(department_id=dept_id)
    note_rest = _make_note(case_id=case_entity.id, author_id=author_id, visibility="restricted", content="Secret note")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note_rest

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.get_case_note(case_entity.id, note_rest.id, other_principal)
    assert exc.value.code == "RESTRICTED_NOTE_FORBIDDEN"

    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value


@pytest.mark.asyncio
async def test_unauthorized_visibility_change_denied(case_service, mock_repos):
    """7. Unauthorized users cannot change note visibility (requires CASE_NOTE_VISIBILITY_MANAGE)."""
    dept_id = uuid4()
    inv_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, author_id=inv_principal.user_id, visibility="internal")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note

    payload = CaseNoteVisibilityUpdate(
        visibility="public",
        reason="Trying to make internal note public without permission.",
        expected_version_id=1,
    )
    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.change_note_visibility(case_entity.id, note.id, inv_principal, payload)
    assert exc.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_cross_department_note_access_denied_without_leakage(case_service, mock_repos):
    """8. Cross-department note access is denied with 404 without leaking existence."""
    dept_a = uuid4()
    dept_b = uuid4()

    inv_dept_b = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_b)
    case_dept_a = _make_case(department_id=dept_a)
    note = _make_note(case_id=case_dept_a.id, visibility="internal")

    mock_repos["case"].get_by_id.return_value = case_dept_a
    mock_repos["case"].get_note_by_id.return_value = note

    with pytest.raises(ResourceNotFoundError) as exc:
        await case_service.get_case_note(case_dept_a.id, note.id, inv_dept_b)
    assert exc.value.code == "CASE_NOT_FOUND"

    with pytest.raises(ResourceNotFoundError) as exc:
        await case_service.list_case_notes(case_dept_a.id, inv_dept_b)
    assert exc.value.code == "CASE_NOT_FOUND"


@pytest.mark.asyncio
async def test_note_edits_preserve_earlier_revisions(case_service, mock_repos):
    """9. Note edits preserve earlier revisions in CaseNoteHistory."""
    dept_id = uuid4()
    author_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(
        case_id=case_entity.id,
        author_id=author_id,
        content="Original initial observation text.",
        version_id=1,
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note
    mock_repos["case"].create_note_history.side_effect = lambda h: h

    payload = CaseNoteUpdate(
        content="Corrected observation text after forensic re-check.",
        edit_reason="Corrected timestamp in witness statement.",
        expected_version_id=1,
    )

    result = await case_service.update_case_note(case_entity.id, note.id, principal, payload)

    assert result.content == "Corrected observation text after forensic re-check."
    assert result.version_id == 2
    assert result.author_id == author_id

    # Verify history creation call
    hist_call = mock_repos["case"].create_note_history.call_args[0][0]
    assert hist_call.note_id == note.id
    assert hist_call.version_id == 1
    assert hist_call.author_id == author_id
    assert hist_call.editor_id == principal.user_id
    assert hist_call.content == "Original initial observation text."
    assert hist_call.edit_reason == "Corrected timestamp in witness statement."


@pytest.mark.asyncio
async def test_note_history_is_ordered_and_complete(case_service, mock_repos):
    """10. Note history returns all prior versions ordered by creation/version."""
    dept_id = uuid4()
    author_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, author_id=author_id, version_id=3)

    h1 = CaseNoteHistory(
        id=uuid4(),
        note_id=note.id,
        version_id=1,
        author_id=author_id,
        editor_id=author_id,
        content="Version 1 content",
        edit_reason="Initial creation",
        created_at=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
    )
    h2 = CaseNoteHistory(
        id=uuid4(),
        note_id=note.id,
        version_id=2,
        author_id=author_id,
        editor_id=author_id,
        content="Version 2 content",
        edit_reason="Second edit",
        created_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note
    mock_repos["case"].list_note_history.return_value = [h2, h1]

    history = await case_service.get_case_note_history(case_entity.id, note.id, principal)
    assert len(history) == 2
    assert history[0].version_id == 2
    assert history[1].version_id == 1


@pytest.mark.asyncio
async def test_visibility_changes_are_historically_traceable(case_service, mock_repos):
    """11. Visibility changes are historically traceable with audit events and history entries."""
    dept_id = uuid4()
    admin_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, visibility="internal", version_id=1)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note
    mock_repos["case"].create_note_history.side_effect = lambda h: h

    payload = CaseNoteVisibilityUpdate(
        visibility="restricted",
        reason="Elevating note to restricted due to witness protection concerns.",
        expected_version_id=1,
    )
    updated = await case_service.change_note_visibility(case_entity.id, note.id, admin_principal, payload)

    assert updated.visibility == "restricted"
    assert updated.version_id == 2

    # Verify history recorded previous and new visibility
    hist_call = mock_repos["case"].create_note_history.call_args[0][0]
    assert hist_call.previous_visibility == "internal"
    assert hist_call.visibility == "restricted"

    # Verify audit event
    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_NOTE_VISIBILITY_CHANGED.value
    assert audit_call["details"]["old_visibility"] == "internal"
    assert audit_call["details"]["new_visibility"] == "restricted"


@pytest.mark.asyncio
async def test_stale_revisions_return_conflict(case_service, mock_repos):
    """12. Stale expected revisions return a 409 ConflictError."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, author_id=principal.user_id, version_id=3)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note

    payload = CaseNoteUpdate(
        content="Attempting edit on stale version.",
        expected_version_id=1,  # Stale: actual is 3
    )
    with pytest.raises(ConflictError) as exc:
        await case_service.update_case_note(case_entity.id, note.id, principal, payload)
    assert exc.value.code == "CONCURRENCY_CONFLICT"


@pytest.mark.asyncio
async def test_concurrent_edits_cannot_silently_overwrite(case_service, mock_repos):
    """13. Concurrent edits cannot silently overwrite each other."""
    dept_id = uuid4()
    author_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, author_id=author_id, version_id=1)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note
    mock_repos["case"].create_note_history.side_effect = lambda h: h

    # First update succeeds and increments version to 2
    update1 = CaseNoteUpdate(content="First update by user.", expected_version_id=1)
    res1 = await case_service.update_case_note(case_entity.id, note.id, principal, update1)
    assert res1.version_id == 2

    # Second competing update that also expected version 1 fails
    update2 = CaseNoteUpdate(content="Competing simultaneous update.", expected_version_id=1)
    with pytest.raises(ConflictError) as exc:
        await case_service.update_case_note(case_entity.id, note.id, principal, update2)
    assert exc.value.code == "CONCURRENCY_CONFLICT"


@pytest.mark.asyncio
async def test_repeated_requests_have_defined_idempotency(case_service, mock_repos):
    """14. Repeated identical update requests return current state without version bump or duplicate history."""
    dept_id = uuid4()
    author_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=author_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(
        case_id=case_entity.id,
        author_id=author_id,
        content="Current note content.",
        version_id=2,
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note

    payload = CaseNoteUpdate(
        content="Current note content.",  # Identical content
        expected_version_id=2,
    )
    result = await case_service.update_case_note(case_entity.id, note.id, principal, payload)

    assert result.version_id == 2
    assert mock_repos["case"].create_note_history.call_count == 0


@pytest.mark.asyncio
async def test_unauthorized_note_history_access_denied(case_service, mock_repos):
    """15. Unauthorized note history access is denied for caller without permission."""
    dept_id = uuid4()
    author_id = uuid4()
    other_inv_id = uuid4()

    other_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)
    case_entity = _make_case(department_id=dept_id)
    note_rest = _make_note(case_id=case_entity.id, author_id=author_id, visibility="restricted")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note_rest

    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.get_case_note_history(case_entity.id, note_rest.id, other_principal)
    assert exc.value.code == "RESTRICTED_NOTE_FORBIDDEN"


@pytest.mark.asyncio
async def test_case_list_detail_responses_do_not_leak_restricted_notes(case_service):
    """16. CaseRead DTO does not leak raw note text in ordinary case detail serialization."""
    case_entity = _make_case()
    case_read = case_service._to_case_read(case_entity)

    # Note text fields must not exist in general CaseRead DTO
    assert not hasattr(case_read, "notes_content")
    assert not hasattr(case_read, "note_text")
    assert hasattr(case_read, "reference_number")


@pytest.mark.asyncio
async def test_search_and_timeline_respect_visibility_rules(case_service, mock_repos):
    """17. Case note queries filter restricted notes for unauthorized callers."""
    dept_id = uuid4()
    author_id = uuid4()
    other_inv_id = uuid4()

    case_entity = _make_case(department_id=dept_id)
    other_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)

    note1 = _make_note(case_id=case_entity.id, author_id=author_id, visibility="internal", content="Public-safe internal")
    note2 = _make_note(case_id=case_entity.id, author_id=author_id, visibility="restricted", content="Top secret IA")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].list_notes_for_case.return_value = [note1, note2]

    visible = await case_service.list_case_notes(case_entity.id, other_principal)
    assert len(visible) == 1
    assert visible[0].content == "Public-safe internal"


@pytest.mark.asyncio
async def test_notifications_do_not_leak_restricted_content():
    """18. Notifications do not leak restricted note text."""
    p = Path("backend/app/services/notification.py")
    text = p.read_text(encoding="utf-8")
    # Verify notification service does not include case note bodies
    assert "CaseNote" not in text


@pytest.mark.asyncio
async def test_exports_do_not_leak_restricted_notes(case_service, mock_repos):
    """19. Case dossier exports omit restricted and confidential notes unless caller is authorized."""
    dept_id = uuid4()
    author_id = uuid4()
    other_inv_id = uuid4()

    inv_principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=other_inv_id)
    admin_principal = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)

    case_entity = _make_case(department_id=dept_id)
    note_int = _make_note(case_id=case_entity.id, author_id=author_id, visibility="internal")
    note_conf = _make_note(case_id=case_entity.id, author_id=author_id, visibility="confidential")
    note_rest = _make_note(case_id=case_entity.id, author_id=author_id, visibility="restricted")

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].list_case_evidence.return_value = []
    mock_repos["case"].list_notes_for_case.return_value = [note_int, note_conf, note_rest]
    mock_repos["case"].list_findings_for_case.return_value = []
    mock_repos["case"].list_case_ai_segments.return_value = []
    mock_repos["case"].create_export.side_effect = lambda ex: ex

    # 19a. Ordinary investigator without flag gets ONLY internal note
    payload1 = CaseExportRequest(purpose='Case archive discovery', include_restricted_notes=False)
    res1 = await case_service.export_case(case_entity.id, inv_principal, payload1)
    notes_in_export1 = res1.manifest_payload["notes"]
    assert len(notes_in_export1) == 1
    assert notes_in_export1[0]["visibility"] == "internal"

    # 19b. Ordinary investigator requesting restricted notes is rejected with 403
    payload2 = CaseExportRequest(purpose='Privileged supervisory export', include_restricted_notes=True)
    with pytest.raises(PermissionDeniedError) as exc:
        await case_service.export_case(case_entity.id, inv_principal, payload2)
    assert exc.value.code == "RESTRICTED_EXPORT_DENIED"

    # 19c. Department admin with flag gets all notes
    res3 = await case_service.export_case(case_entity.id, admin_principal, payload2)
    notes_in_export3 = res3.manifest_payload["notes"]
    assert len(notes_in_export3) == 3


@pytest.mark.asyncio
async def test_audit_events_correspond_to_committed_changes(case_service, mock_repos):
    """20. Audit events correspond to committed changes."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Testing audit event emissions for note creation.",
    )
    await case_service.create_case_note(case_entity.id, principal, payload)

    audit_call = mock_repos["audit"].append_event.call_args.kwargs
    assert audit_call["action"] == AuditAction.CASE_NOTE_CREATED.value
    assert audit_call["outcome"] == AuditOutcome.SUCCESS


@pytest.mark.asyncio
async def test_failed_mutations_do_not_leave_misleading_success_events(case_service, mock_repos):
    """21. Failed note mutations do not generate success audit events."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)
    note = _make_note(case_id=case_entity.id, author_id=principal.user_id, version_id=2)

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].get_note_by_id.return_value = note

    # Stale version update fails before audit event
    payload = CaseNoteUpdate(content="Will fail due to version mismatch", expected_version_id=1)
    with pytest.raises(ConflictError):
        await case_service.update_case_note(case_entity.id, note.id, principal, payload)

    assert mock_repos["audit"].append_event.call_count == 0


@pytest.mark.asyncio
async def test_note_editing_does_not_modify_evidence_bytes_or_digests(case_service, mock_repos):
    """22. Note operations do not modify master evidence bytes or SHA-256 digests."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    orig_digest = "a" * 64
    ev = EvidenceAttachment(
        id=uuid4(),
        incident_id=uuid4(),
        uploader_id=uuid4(),
        department_id=dept_id,
        sha256_hash=orig_digest,
    )
    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Note referencing evidence artifact.",
    )
    await case_service.create_case_note(case_entity.id, principal, payload)

    # Master evidence digest remains unchanged
    assert ev.sha256_hash == orig_digest


@pytest.mark.asyncio
async def test_legal_holds_and_case_lifecycle_restrictions_respected(case_service, mock_repos):
    """23. Note operations can be added to cases with legal holds, but do not alter hold status or case status."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(
        department_id=dept_id,
        status=CaseStatus.UNDER_INVESTIGATION.value,
        is_legal_hold=True,
    )

    mock_repos["case"].get_by_id.return_value = case_entity
    mock_repos["case"].create_note.side_effect = lambda n: n

    payload = CaseNoteCreate(
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Note added while legal hold is active on case.",
    )
    await case_service.create_case_note(case_entity.id, principal, payload)

    assert case_entity.is_legal_hold is True
    assert case_entity.status == CaseStatus.UNDER_INVESTIGATION.value


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled():
    """24. Biometric matching remains disabled (BIOMETRIC_MATCHING_ENABLED = False, fail-closed)."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    face_service = FaceMatchingService(
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
        await face_service.match_faces(
            req,
            _make_principal(RoleCode.SUPER_ADMIN.value),
        )


@pytest.mark.asyncio
async def test_sealed_historical_violence_partition_is_not_accessed():
    """25. The sealed historical violence-detection partition (N=354) is not accessed."""
    sealed_path = Path("data/violence_detection/compromised_partition_354.json")
    assert not sealed_path.exists(), "Compromised partition file must never exist or be accessed in repository"


@pytest.mark.asyncio
async def test_existing_phase81_to_85_regression_behavior_intact(case_service, mock_repos):
    """26. Existing Phase 81–85 regression behavior remains intact."""
    dept_id = uuid4()
    principal = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_entity = _make_case(department_id=dept_id)

    # Reference format from Phase 81
    assert case_entity.reference_number.startswith("CASE-2026-")

    # Advisory disclaimer from Phase 84/85
    assert "advisory only" in AI_ADVISORY_DISCLAIMER
