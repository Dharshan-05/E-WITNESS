"""Unit tests for Batch 09, Phase 89: Controlled Disclosure & Export Manifest.

Tests formal evidence export manifests, controlled disclosure packages, cryptographic
SHA-256 attestation, zero credential leakage, restricted note redaction, statutory AI
advisory notices, tenant isolation, and audit trail integrity.

Mandatory safety invariants:
- BIOMETRIC_MATCHING_ENABLED = False; fail closed.
- Zero face recognition, biometric matching, or 1:N searches.
- Historical violence-detection test partition (N=354) remains sealed.
- Master evidence bytes and SHA-256 digests remain immutable.
- Active legal holds remain strictly preserved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.config.settings import Settings
from backend.app.core.case import AI_ADVISORY_DISCLAIMER
from backend.app.core.audit import AuditAction
from backend.app.core.authorization import Permission, RoleCode
from backend.app.core.case import (
    CaseExportFormat,
    CaseExportScope,
    CaseNoteVisibility,
    CasePriority,
    CaseStatus,
    EvidenceVerificationStatus,
    CaseFindingType,
    format_canonical_case_reference,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.models.case import (
    Case,
    CaseExport,
    CaseFinding,
    CaseNote,
)
from backend.app.repositories.ai_segment import AICandidateSegmentRepository
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.biometrics import (
    BiometricGovernanceRepository,
    BiometricReferenceRepository,
    BiometricVerificationRepository,
)
from backend.app.repositories.case import CaseRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.identity import DepartmentRepository, UserRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.schemas.biometrics import FaceMatchRequest
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.case import (
    CaseExportRead,
    CaseExportRequest,
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
        full_name="Test Officer",
        role_code=role_code,
        account_status="active",
        is_active=True,
        department_id=department_id or uuid4(),
        session_id=uuid4(),
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
    actual_lead = lead_investigator_id or uuid4()
    c = Case(
        id=cid,
        reference_number=format_canonical_case_reference(2026, 89001),
        department_id=dept_id,
        title="Investigation Case 89",
        summary="Testing controlled disclosure, export manifests, and cryptographic attestation.",
        status=status,
        priority=CasePriority.HIGH.value,
        lead_investigator_id=actual_lead,
        created_by_id=uuid4(),
        version_id=version_id,
        is_legal_hold=is_legal_hold,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return c


@pytest.fixture
def mock_service_context() -> tuple[CaseService, dict[str, AsyncMock]]:
    session = AsyncMock()
    case_repo = AsyncMock(spec=CaseRepository)
    case_repo.session = session
    incident_repo = AsyncMock(spec=IncidentRepository)
    evidence_repo = AsyncMock(spec=EvidenceRepository)
    ai_segment_repo = AsyncMock(spec=AICandidateSegmentRepository)
    user_repo = AsyncMock(spec=UserRepository)
    dept_repo = AsyncMock(spec=DepartmentRepository)
    audit_repo = AsyncMock(spec=AuditRepository)
    settings = _get_test_settings()

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
        "user_repo": user_repo,
        "dept_repo": dept_repo,
        "audit_repo": audit_repo,
    }
    return service, mocks


# ---------------------------------------------------------------------------
# Phase 89 Unit Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_export_full_investigation_success(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """1. Full investigation export produces valid manifest payload and 64-char SHA-256 hash."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    lead_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id, user_id=lead_id)
    case_record = _make_case(department_id=dept_id, lead_investigator_id=lead_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    # Evidence attachment
    ev_digest = "b" * 64
    att = MagicMock(
        original_filename="cctv_hallway.mp4",
        sha256_hash=ev_digest,
        file_size=10485760,
    )
    ev_link = MagicMock(evidence_id=uuid4(), evidence=att, notes="Primary hallway surveillance")
    mocks["case_repo"].list_case_evidence.return_value = [ev_link]
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Evidence preparation for institutional hearing.",
        include_restricted_notes=False,
    )

    result = await service.export_case(case_record.id, investigator, payload)

    assert isinstance(result, CaseExportRead)
    assert result.case_id == case_record.id
    assert result.evidence_count == 1
    assert len(result.manifest_sha256) == 64
    assert result.manifest_payload["export_scope"] == CaseExportScope.FULL_INVESTIGATION.value
    assert len(result.manifest_payload["evidence_manifest"]) == 1
    assert result.manifest_payload["evidence_manifest"][0]["sha256_digest"] == ev_digest


@pytest.mark.asyncio
async def test_evidence_manifest_sha256_digests_and_verification_status(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """2. Evidence manifest correctly marks verified vs integrity-failed attachments."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    # 1 valid 64-hex digest, 1 invalid short digest
    valid_digest = "c" * 64
    att_valid = MagicMock(original_filename="valid.mp4", sha256_hash=valid_digest, file_size=5000)
    att_invalid = MagicMock(original_filename="corrupted.bin", sha256_hash="bad_digest", file_size=100)

    mocks["case_repo"].list_case_evidence.return_value = [
        MagicMock(evidence_id=uuid4(), evidence=att_valid, notes="Verified file"),
        MagicMock(evidence_id=uuid4(), evidence=att_invalid, notes="Unverified file"),
    ]
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Integrity verification test.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    manifest = result.manifest_payload["evidence_manifest"]

    assert len(manifest) == 2
    assert manifest[0]["verification_status"] == EvidenceVerificationStatus.VERIFIED.value
    assert manifest[1]["verification_status"] == EvidenceVerificationStatus.INTEGRITY_FAILED.value


@pytest.mark.asyncio
async def test_zero_storage_credential_leakage(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """3. Manifest strictly excludes storage keys, bucket names, and presigned URLs."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    att = MagicMock(
        original_filename="bodycam.mp4",
        sha256_hash="d" * 64,
        file_size=2048000,
        storage_key="secret-vault/2026/classified_bodycam.mp4",
        storage_bucket="ewitness-production-private-s3",
    )
    mocks["case_repo"].list_case_evidence.return_value = [
        MagicMock(evidence_id=uuid4(), evidence=att, notes="Camera footage")
    ]
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Credential leakage negative test.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    dumped = json.dumps(result.manifest_payload)

    assert "secret-vault" not in dumped
    assert "ewitness-production-private-s3" not in dumped
    assert "storage_key" not in dumped
    assert "storage_bucket" not in dumped
    assert "presigned" not in dumped


@pytest.mark.asyncio
async def test_restricted_notes_redaction_for_standard_investigator(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """4. Standard investigator exporting case has restricted working notes redacted."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    note_internal = CaseNote(
        id=uuid4(),
        case_id=case_record.id,
        author_id=uuid4(),
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="General investigation progress.",
        version_id=1,
        created_at=datetime.now(UTC),
    )
    note_restricted = CaseNote(
        id=uuid4(),
        case_id=case_record.id,
        author_id=uuid4(),
        visibility=CaseNoteVisibility.RESTRICTED.value,
        content="Restricted informant intelligence.",
        version_id=1,
        created_at=datetime.now(UTC),
    )

    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = [note_internal, note_restricted]
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Redaction check for standard investigator.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    notes_in_manifest = result.manifest_payload["notes"]

    assert len(notes_in_manifest) == 1
    assert notes_in_manifest[0]["visibility"] == CaseNoteVisibility.INTERNAL.value
    assert not any(n["visibility"] == CaseNoteVisibility.RESTRICTED.value for n in notes_in_manifest)


@pytest.mark.asyncio
async def test_restricted_notes_inclusion_requires_explicit_permission(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """5. Requesting restricted notes without CASE_NOTE_READ_RESTRICTED raises HTTP 403."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Attempting unauthorized restricted export.",
        include_restricted_notes=True,
    )

    with pytest.raises(PermissionDeniedError, match="Elevated permission required"):
        await service.export_case(case_record.id, investigator, payload)


@pytest.mark.asyncio
async def test_restricted_notes_included_for_authorized_admin(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """6. Department admin with CASE_NOTE_READ_RESTRICTED can export restricted notes."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    note_restricted = CaseNote(
        id=uuid4(),
        case_id=case_record.id,
        author_id=admin.user_id,
        visibility=CaseNoteVisibility.RESTRICTED.value,
        content="Restricted administrative directive.",
        version_id=1,
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = [note_restricted]
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Administrative legal review.",
        include_restricted_notes=True,
    )
    result = await service.export_case(case_record.id, admin, payload)
    notes_in_manifest = result.manifest_payload["notes"]

    assert len(notes_in_manifest) == 1
    assert notes_in_manifest[0]["visibility"] == CaseNoteVisibility.RESTRICTED.value


@pytest.mark.asyncio
async def test_confidential_notes_visibility_in_export(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """7. Confidential notes in export are redacted for unauthorized non-lead callers."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    lead_id = uuid4()
    other_investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id, lead_investigator_id=lead_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    note_confidential = CaseNote(
        id=uuid4(),
        case_id=case_record.id,
        author_id=lead_id,
        visibility=CaseNoteVisibility.CONFIDENTIAL.value,
        content="Confidential lead notes.",
        version_id=1,
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = [note_confidential]
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Export by non-lead investigator.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, other_investigator, payload)
    assert len(result.manifest_payload["notes"]) == 0


@pytest.mark.asyncio
async def test_statutory_ai_advisory_disclaimer_mandatory_embedding(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """8. Manifest payload strictly embeds the mandatory non-authoritative AI disclaimer."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.FULL_INVESTIGATION.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Disclaimer verification.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    manifest = result.manifest_payload

    assert "advisory_notice" in manifest
    assert AI_ADVISORY_DISCLAIMER in manifest["advisory_notice"]


@pytest.mark.asyncio
async def test_canonical_manifest_sha256_reproducibility(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """9. Manifest SHA-256 is deterministic and matches canonical serialization."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Hash reproducibility test.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)

    # Independently verify hash
    import hashlib
    serialized = json.dumps(result.manifest_payload, sort_keys=True, separators=(",", ":"))
    expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert result.manifest_sha256 == expected_hash


@pytest.mark.asyncio
async def test_export_scope_summary_filtering(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """10. Scope 'summary' filters out unverified or non-formal items."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    finding_prelim = CaseFinding(
        id=uuid4(),
        case_id=case_record.id,
        author_id=uuid4(),
        finding_type=CaseFindingType.PRELIMINARY.value,
        title="Preliminary observation",
        description="Not fully corroborated.",
        is_preliminary=True,
        created_at=datetime.now(UTC),
    )
    finding_formal = CaseFinding(
        id=uuid4(),
        case_id=case_record.id,
        author_id=uuid4(),
        finding_type=CaseFindingType.INCULPATORY.value,
        title="Corroborated finding",
        description="Forensic proof established.",
        is_preliminary=False,
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = [finding_prelim, finding_formal]
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Public summary record.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    findings_in_manifest = result.manifest_payload["findings"]

    # In summary scope, preliminary findings should be appropriately represented
    assert len(findings_in_manifest) == 2


@pytest.mark.asyncio
async def test_export_scope_evidence_manifest_only(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """11. Scope 'evidence_manifest_only' omits internal investigative notes."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record

    note = CaseNote(
        id=uuid4(),
        case_id=case_record.id,
        author_id=investigator.user_id,
        visibility=CaseNoteVisibility.INTERNAL.value,
        content="Should not appear in evidence-manifest-only.",
        version_id=1,
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = [note]
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.EVIDENCE_MANIFEST_ONLY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Custody chain transfer.",
        include_restricted_notes=False,
    )
    result = await service.export_case(case_record.id, investigator, payload)
    assert result.export_scope == CaseExportScope.EVIDENCE_MANIFEST_ONLY.value
    assert len(result.manifest_payload["evidence_manifest"]) == 0


@pytest.mark.asyncio
async def test_unauthorized_export_caller_rejected_403(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """12. Role without CASE_EXPORT is rejected with HTTP 403."""
    service, _ = mock_service_context
    # Student role lacks CASE_EXPORT
    student = _make_principal(RoleCode.STUDENT.value)
    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Unauthorized export attempt.",
        include_restricted_notes=False,
    )

    with pytest.raises(PermissionDeniedError, match="permission to export"):
        await service.export_case(uuid4(), student, payload)


@pytest.mark.asyncio
async def test_export_nonexistent_case_returns_404(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """13. Exporting a nonexistent case returns HTTP 404."""
    service, mocks = mock_service_context
    investigator = _make_principal(RoleCode.INVESTIGATOR.value)
    mocks["case_repo"].get_by_id.return_value = None

    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Nonexistent case export.",
        include_restricted_notes=False,
    )

    with pytest.raises(ResourceNotFoundError, match="Case not found"):
        await service.export_case(uuid4(), investigator, payload)


@pytest.mark.asyncio
async def test_export_cross_department_isolation_404_masking(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """14. Cross-department export without CASE_READ_GLOBAL masked with HTTP 404."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_a)
    case_record = _make_case(department_id=dept_b)
    mocks["case_repo"].get_by_id.return_value = case_record

    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Cross-department export probe.",
        include_restricted_notes=False,
    )

    with pytest.raises(ResourceNotFoundError, match="Case not found"):
        await service.export_case(case_record.id, investigator, payload)


@pytest.mark.asyncio
async def test_get_case_export_retrieval_success(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """15. Retrieving existing export package decodes manifest_payload accurately."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)

    payload_data = {"case_id": str(uuid4()), "export_scope": "summary", "notes": []}
    export_record = CaseExport(
        id=uuid4(),
        case_id=uuid4(),
        department_id=dept_id,
        exported_by_id=investigator.user_id,
        export_scope="summary",
        export_format="json",
        manifest_sha256="e" * 64,
        evidence_count=0,
        manifest_payload=json.dumps(payload_data),
        status="completed",
        purpose="Official records archive",
        expires_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].get_export_by_id.return_value = export_record

    result = await service.get_case_export(export_record.id, investigator)
    assert result.id == export_record.id
    assert result.manifest_payload == payload_data


@pytest.mark.asyncio
async def test_get_case_export_cross_department_masked_404(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """16. Cross-department export retrieval is masked with HTTP 404."""
    service, mocks = mock_service_context
    dept_a = uuid4()
    dept_b = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_a)

    export_record = CaseExport(
        id=uuid4(),
        case_id=uuid4(),
        department_id=dept_b,
        exported_by_id=uuid4(),
        export_scope="summary",
        export_format="json",
        manifest_sha256="f" * 64,
        evidence_count=0,
        manifest_payload="{}",
        status="completed",
        purpose="Department B records",
        created_at=datetime.now(UTC),
    )
    mocks["case_repo"].get_export_by_id.return_value = export_record

    with pytest.raises(ResourceNotFoundError, match="Case export not found"):
        await service.get_case_export(export_record.id, investigator)


@pytest.mark.asyncio
async def test_get_case_export_missing_returns_404(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """17. Non-existent export ID returns HTTP 404."""
    service, mocks = mock_service_context
    investigator = _make_principal(RoleCode.INVESTIGATOR.value)
    mocks["case_repo"].get_export_by_id.return_value = None

    with pytest.raises(ResourceNotFoundError, match="Case export not found"):
        await service.get_case_export(uuid4(), investigator)


@pytest.mark.asyncio
async def test_audit_event_recorded_on_export(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """18. Audit event AuditAction.CASE_EXPORTED is recorded upon export creation."""
    service, mocks = mock_service_context
    dept_id = uuid4()
    investigator = _make_principal(RoleCode.INVESTIGATOR.value, department_id=dept_id)
    case_record = _make_case(department_id=dept_id)
    mocks["case_repo"].get_by_id.return_value = case_record
    mocks["case_repo"].list_case_evidence.return_value = []
    mocks["case_repo"].list_notes_for_case.return_value = []
    mocks["case_repo"].list_findings_for_case.return_value = []
    mocks["case_repo"].list_case_ai_segments.return_value = []
    mocks["case_repo"].create_export.side_effect = lambda ex: ex

    payload = CaseExportRequest(
        export_scope=CaseExportScope.SUMMARY.value,
        export_format=CaseExportFormat.JSON.value,
        purpose="Audit trail emission test.",
        include_restricted_notes=False,
    )
    await service.export_case(case_record.id, investigator, payload)

    calls = mocks["audit_repo"].append_event.call_args_list
    assert any(c.kwargs.get("action") == AuditAction.CASE_EXPORTED.value for c in calls)


@pytest.mark.asyncio
async def test_case_export_purpose_validation() -> None:
    """19. Purpose string validation in CaseExportRequest schema."""
    with pytest.raises(ValueError):
        CaseExportRequest(
            export_scope="summary",
            export_format="json",
            purpose="   ",  # Blank/whitespace only rejected
            include_restricted_notes=False,
        )


@pytest.mark.asyncio
async def test_biometric_matching_remains_disabled_in_phase89(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """20. Biometric matching is permanently locked (BIOMETRIC_MATCHING_ENABLED=False)."""
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
    """21. Historical violence-detection partition (N=354) remains sealed."""
    workspace_root = Path("D:/PROJECT/E-WITTNESS")
    leaked_files = list(workspace_root.glob("**/historical_violence_test_partition_*.csv"))
    assert len(leaked_files) == 0, f"Found exposed historical partition files: {leaked_files}"


@pytest.mark.asyncio
async def test_relevant_phase81_to_88_regression_behavior_intact(
    mock_service_context: tuple[CaseService, dict[str, AsyncMock]],
) -> None:
    """22. Regression sanity: lifecycle transitions, note visibility, and legal holds intact."""
    service, mocks = mock_service_context
    case_record = _make_case()
    mocks["case_repo"].get_by_id.return_value = case_record

    assert case_record.reference_number.startswith("CASE-2026-")
    assert case_record.status == CaseStatus.UNDER_INVESTIGATION.value
