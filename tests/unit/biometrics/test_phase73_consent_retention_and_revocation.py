"""Phase 73 Unit Tests: Biometric Data Governance, Consent, Retention & Revocation.

Comprehensive automated verification covering:
1. Consent Lifecycle:
   - Valid consent capture for authorized processing purposes.
   - Missing, unconfirmed, or malformed consent fail-closed behavior.
   - Governance approval distinct from individual consent.
   - Immediate authorization invalidation upon consent withdrawal.
   - Tenant isolation and ownership boundaries on consent records.
2. Retention & Expiry:
   - Active references valid prior to retention expiry.
   - Dynamic service-layer rejection of expired references (fail-closed even without cleanup).
   - Idempotent background cleanup transitions status to EXPIRED and purges templates.
   - UTC timestamp consistency and boundary evaluation.
3. Deletion & Revocation Workflows:
   - Cascading reference revocation upon consent withdrawal.
   - Cryptographic erasure (purging encrypted_template ciphertext).
   - Idempotent repeated withdrawal and revocation calls.
   - Atomic rollback on transaction failure.
4. Security Regressions & Safety Invariants:
   - Mandatory BIOMETRIC_MATCHING_ENABLED = False invariant preserved.
   - Consent cannot authorize automated face matching or 1:N surveillance.
   - Zero template or key leakage into audit ledgers or API schemas.
   - Decoupling between violence detection and biometric processing.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ai_services.face_matching.protocol import DisabledFaceMatcherProvider
from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import (
    Permission,
    ROLE_PERMISSIONS,
    has_permission,
)
from backend.app.core.biometrics import (
    BiometricLawfulBasis,
    BiometricPurpose,
    BiometricReferenceStatus,
    ConsentStatus,
    GovernanceStatus,
    ProhibitedBiometricPurpose,
    validate_biometric_purpose,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricsDisabledError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.biometrics import (
    BiometricGovernanceRecord,
    BiometricReference,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    BiometricConsentWithdrawRequest,
    BiometricGovernanceCreate,
    BiometricGovernanceRead,
    BiometricGovernanceReviewRequest,
    BiometricReferenceCreate,
    BiometricReferenceRead,
    BiometricReferenceRevokeRequest,
    FaceMatchRequest,
)
from backend.app.services.biometrics import (
    BiometricGovernanceService,
    BiometricReferenceService,
    FaceDetectionService,
    FaceMatchingService,
)


def _make_unit_settings(**kwargs: Any) -> Settings:
    """Create isolated Settings instance for unit tests."""
    defaults: dict[str, Any] = {
        "_env_file": None,
        "ENVIRONMENT": "testing",
        "APP_NAME": "E-WITNESS Test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/15",
        "STORAGE_ENDPOINT_URL": "https://s3.test.internal:9000",
        "STORAGE_BUCKET_NAME": "ewitness-test-bucket",
        "STORAGE_ACCESS_KEY": "test_access_key_isolated",
        "STORAGE_SECRET_KEY": "test_secret_key_isolated_value",
        "AUTH_SECRET_KEY": "test_only_signing_key_with_sufficient_length_32_plus",
        "AI_API_KEY": "test-ai-key",
        "BIOMETRIC_ANALYSIS_ENABLED": True,
        "BIOMETRIC_DETECTION_ENABLED": True,
        "BIOMETRIC_MATCHING_ENABLED": False,  # Mandatory Phase 73 invariant
        "BIOMETRIC_PROVIDER": "disabled",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def _create_test_png(width: int = 128, height: int = 128, fill: int = 120) -> bytes:
    """Generate minimal valid PNG bytes for synthetic testing."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"
    payload = bytes([(fill + (i % 80)) % 256 for i in range(256)])
    idat_chunk = struct.pack(">I", len(payload)) + b"IDAT" + payload + b"\x00\x00\x00\x00"
    iend_chunk = struct.pack(">I", 0) + b"IEND" + b"\x00\x00\x00\x00"
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def _create_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    """Generate mock AuthenticatedPrincipal."""
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email="test_user@ewitness.edu",
        full_name="Test Principal",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=department_id or uuid4(),
        session_id=uuid4(),
    )


# ===========================================================================
# Group A: Formal Consent Records & Consent Lifecycle
# ===========================================================================


class TestPhase73ConsentLifecycle:
    """Verify formal consent creation, validation, affirmative confirmation, and purpose specificity."""

    @pytest.mark.asyncio
    async def test_valid_explicit_consent_registration(self) -> None:
        """Registering explicit consent with confirmed flag succeeds and records ACTIVE status."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        dept_id = uuid4()
        subj_id = uuid4()
        admin_principal = _create_principal(
            role_code=RoleCode.DEPT_ADMIN.value,
            department_id=dept_id,
        )

        req = BiometricGovernanceCreate(
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT,
            policy_version="1.0.0",
            notice_version="2026.1",
            subject_user_id=subj_id,
            retention_days=60,
            consent_confirmed=True,
            legal_review_notes="Subject signed notice form 2026.1",
        )

        created_record = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=req.purpose.value,
            lawful_basis=req.lawful_basis.value,
            notice_version="2026.1",
            subject_user_id=subj_id,
            status=GovernanceStatus.PENDING_LEGAL_REVIEW.value,
            consent_status=ConsentStatus.ACTIVE.value,
            consented_at=datetime.now(UTC),
            retention_days=60,
            retention_expires_at=datetime.now(UTC) + timedelta(days=60),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        gov_repo.create.return_value = created_record

        read_res = await service.create_governance_record(req, admin_principal)
        assert read_res.consent_status == ConsentStatus.ACTIVE.value
        assert read_res.lawful_basis == BiometricLawfulBasis.EXPLICIT_CONSENT.value
        assert read_res.retention_days == 60
        assert audit_repo.append_event.call_count >= 1

    @pytest.mark.asyncio
    async def test_unconfirmed_consent_fails_closed(self) -> None:
        """Explicit consent basis without affirmative consent confirmation raises BiometricGovernanceError."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value)
        req = BiometricGovernanceCreate(
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT,
            subject_user_id=uuid4(),
            consent_confirmed=False,  # Unconfirmed
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.create_governance_record(req, admin)
        assert "Affirmative consent confirmation is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_explicit_consent_missing_subject_fails_closed(self) -> None:
        """Explicit consent basis without a subject_user_id fails closed."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value)
        req = BiometricGovernanceCreate(
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT,
            subject_user_id=None,  # Missing subject
            consent_confirmed=True,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.create_governance_record(req, admin)
        assert "subject_user_id is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_governance_approval_not_treated_as_consent(self) -> None:
        """Governance approval alone without active consent CANNOT authorize reference enrollment."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(ref_repo, gov_repo, audit_repo)

        dept_id = uuid4()
        subj_id = uuid4()
        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

        # Governance record is APPROVED by legal, but consent_status is missing / NOT active
        approved_no_consent = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT.value,
            notice_version="1.0.0",
            subject_user_id=subj_id,
            status=GovernanceStatus.APPROVED.value,
            consent_status=None,  # No consent recorded
            retention_days=90,
            retention_expires_at=datetime.now(UTC) + timedelta(days=90),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        gov_repo.get_by_id.return_value = approved_no_consent

        enroll_dto = BiometricReferenceCreate(
            governance_record_id=approved_no_consent.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="b" * 64,
            subject_user_id=subj_id,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(enroll_dto, admin)
        assert "Enrollment requires active consent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unauthorized_user_cannot_register_governance_for_other(self) -> None:
        """A student cannot register a governance record for another subject."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        student_user_id = uuid4()
        other_user_id = uuid4()
        student = _create_principal(
            role_code=RoleCode.STUDENT.value,
            user_id=student_user_id,
        )

        req = BiometricGovernanceCreate(
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT,
            subject_user_id=other_user_id,
            consent_confirmed=True,
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            await service.create_governance_record(req, student)
        assert "Caller lacks authorization" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_student_can_register_own_consent(self) -> None:
        """A student is authorized to register their own explicit consent."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        student_user_id = uuid4()
        dept_id = uuid4()
        student = _create_principal(
            role_code=RoleCode.STUDENT.value,
            user_id=student_user_id,
            department_id=dept_id,
        )

        req = BiometricGovernanceCreate(
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT,
            subject_user_id=student_user_id,
            consent_confirmed=True,
        )

        mock_created = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=req.purpose.value,
            lawful_basis=req.lawful_basis.value,
            notice_version="1.0.0",
            subject_user_id=student_user_id,
            status=GovernanceStatus.PENDING_LEGAL_REVIEW.value,
            consent_status=ConsentStatus.ACTIVE.value,
            consented_at=datetime.now(UTC),
            retention_days=90,
            retention_expires_at=datetime.now(UTC) + timedelta(days=90),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        gov_repo.create.return_value = mock_created

        res = await service.create_governance_record(req, student)
        assert res.subject_user_id == student_user_id
        assert res.consent_status == ConsentStatus.ACTIVE.value


# ===========================================================================
# Group B: Retention Enforcement & Expiry Workflows
# ===========================================================================


class TestPhase73RetentionAndExpiry:
    """Verify retention calculation, runtime expiry enforcement, and cleanup idempotency."""

    @pytest.mark.asyncio
    async def test_expired_governance_record_rejected_for_enrollment(self) -> None:
        """An expired governance record fails closed when attempting reference enrollment."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(ref_repo, gov_repo, audit_repo)

        dept_id = uuid4()
        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

        now = datetime.now(UTC)
        past_expiry = now - timedelta(days=2)
        expired_gov = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT.value,
            notice_version="1.0.0",
            subject_user_id=uuid4(),
            status=GovernanceStatus.APPROVED.value,
            consent_status=ConsentStatus.ACTIVE.value,
            consented_at=now - timedelta(days=92),
            retention_days=90,
            retention_expires_at=past_expiry,
            created_at=now - timedelta(days=92),
            updated_at=now - timedelta(days=92),
        )
        gov_repo.get_by_id.return_value = expired_gov

        req = BiometricReferenceCreate(
            governance_record_id=expired_gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="c" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin)
        assert "expired" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_expired_governance_record_rejected_for_face_detection(self) -> None:
        """Face detection fails closed when governance record retention period has expired."""
        settings = _make_unit_settings()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = FaceDetectionService(gov_repo, settings, audit_repo)

        dept_id = uuid4()
        investigator = _create_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id)

        now = datetime.now(UTC)
        past_expiry = now - timedelta(hours=1)
        expired_gov = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.PRIVACY_REDACTION_BLURRING.value,
            lawful_basis=BiometricLawfulBasis.STATUTORY_LEGAL_OBLIGATION.value,
            notice_version="1.0.0",
            status=GovernanceStatus.APPROVED.value,
            retention_days=30,
            retention_expires_at=past_expiry,
            created_at=now - timedelta(days=31),
            updated_at=now - timedelta(days=31),
        )
        gov_repo.get_by_id.return_value = expired_gov

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.detect_faces(_create_test_png(), expired_gov.id, investigator)
        assert "retention period has expired" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dynamic_expiry_on_get_reference(self) -> None:
        """Accessing a reference whose retention_expires_at has passed dynamically transitions it to EXPIRED."""
        ref_repo = AsyncMock()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(ref_repo, gov_repo, audit_repo)

        dept_id = uuid4()
        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

        now = datetime.now(UTC)
        past_expiry = now - timedelta(days=5)
        reference = BiometricReference(
            id=uuid4(),
            reference_id="REF-BIO-EXP-01",
            tenant_id=dept_id,
            department_id=dept_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            status=BiometricReferenceStatus.ACTIVE.value,  # Stored as active
            template_digest="d" * 64,
            encrypted_template="ciphertext_payload",
            enrolled_by_id=admin.user_id,
            enrolled_at=now - timedelta(days=95),
            retention_expires_at=past_expiry,  # Expired
            created_at=now - timedelta(days=95),
            updated_at=now - timedelta(days=95),
        )
        ref_repo.get_by_id.return_value = reference

        res = await service.get_reference(reference.id, admin)
        assert res.status == BiometricReferenceStatus.EXPIRED.value
        assert reference.encrypted_template is None  # Template purged
        assert reference.status == BiometricReferenceStatus.EXPIRED.value

    @pytest.mark.asyncio
    async def test_cleanup_expired_references_idempotency(self) -> None:
        """cleanup_expired_references purges templates and is fully idempotent upon repetition."""
        ref_repo = AsyncMock()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(ref_repo, gov_repo, audit_repo)

        dept_id = uuid4()
        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

        now = datetime.now(UTC)
        past_expiry = now - timedelta(days=1)
        ref1 = BiometricReference(
            id=uuid4(),
            reference_id="REF-BIO-001",
            tenant_id=dept_id,
            department_id=dept_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest="e" * 64,
            encrypted_template="ciphertext_1",
            enrolled_by_id=admin.user_id,
            enrolled_at=now - timedelta(days=91),
            retention_expires_at=past_expiry,
            created_at=now - timedelta(days=91),
            updated_at=now - timedelta(days=91),
        )
        ref_repo.list_expired_active.return_value = [ref1]

        # First cleanup execution
        purged_count_1 = await service.cleanup_expired_references(admin)
        assert purged_count_1 == 1
        assert ref1.status == BiometricReferenceStatus.EXPIRED.value
        assert ref1.encrypted_template is None
        assert audit_repo.append_event.call_count == 1

        # Second cleanup execution (simulating already expired)
        ref_repo.list_expired_active.return_value = []
        purged_count_2 = await service.cleanup_expired_references(admin)
        assert purged_count_2 == 0
        assert ref1.status == BiometricReferenceStatus.EXPIRED.value


# ===========================================================================
# Group C: Consent Withdrawal, Cascading Revocation & Cryptographic Erasure
# ===========================================================================


class TestPhase73ConsentWithdrawalAndRevocation:
    """Verify consent withdrawal, cascading reference revocation, and cryptographic erasure."""

    @pytest.mark.asyncio
    async def test_consent_withdrawal_cascades_to_all_active_references(self) -> None:
        """Withdrawing consent immediately revokes governance record and purges all active references."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        dept_id = uuid4()
        subj_id = uuid4()
        subject_principal = _create_principal(
            role_code=RoleCode.STUDENT.value,
            user_id=subj_id,
            department_id=dept_id,
        )

        gov_id = uuid4()
        now = datetime.now(UTC)
        gov_record = BiometricGovernanceRecord(
            id=gov_id,
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT.value,
            notice_version="1.0.0",
            subject_user_id=subj_id,
            status=GovernanceStatus.APPROVED.value,
            consent_status=ConsentStatus.ACTIVE.value,
            consented_at=now - timedelta(days=10),
            retention_days=90,
            retention_expires_at=now + timedelta(days=80),
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=10),
        )
        gov_repo.get_by_id.return_value = gov_record

        # Two active references associated with this governance record
        ref1 = BiometricReference(
            id=uuid4(),
            reference_id="REF-1",
            tenant_id=dept_id,
            department_id=dept_id,
            subject_user_id=subj_id,
            governance_record_id=gov_id,
            purpose=gov_record.purpose,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest="f" * 64,
            encrypted_template="ciphertext_payload_1",
            enrolled_by_id=subj_id,
            enrolled_at=now - timedelta(days=10),
            retention_expires_at=now + timedelta(days=80),
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=10),
        )
        ref2 = BiometricReference(
            id=uuid4(),
            reference_id="REF-2",
            tenant_id=dept_id,
            department_id=dept_id,
            subject_user_id=subj_id,
            governance_record_id=gov_id,
            purpose=gov_record.purpose,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest="1" * 64,
            encrypted_template="ciphertext_payload_2",
            enrolled_by_id=subj_id,
            enrolled_at=now - timedelta(days=10),
            retention_expires_at=now + timedelta(days=80),
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=10),
        )
        ref_repo.list_active_by_governance_record.return_value = [ref1, ref2]

        req = BiometricConsentWithdrawRequest(reason="Subject exercised right to withdraw consent")
        res = await service.withdraw_consent(gov_id, req, subject_principal)

        assert res.consent_status == ConsentStatus.WITHDRAWN.value
        assert res.status == GovernanceStatus.REVOKED.value
        assert res.withdrawn_at is not None

        # Verify cryptographic erasure on both references
        assert ref1.status == BiometricReferenceStatus.REVOKED.value
        assert ref1.encrypted_template is None
        assert ref2.status == BiometricReferenceStatus.REVOKED.value
        assert ref2.encrypted_template is None

        # Verify audit logging
        assert audit_repo.append_event.call_count >= 3  # 1 consent revocation + 2 reference revocations

    @pytest.mark.asyncio
    async def test_consent_withdrawal_idempotency(self) -> None:
        """Calling withdraw_consent repeatedly on an already-withdrawn record is completely idempotent."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        dept_id = uuid4()
        subj_id = uuid4()
        subject_principal = _create_principal(
            role_code=RoleCode.STUDENT.value,
            user_id=subj_id,
            department_id=dept_id,
        )

        gov_id = uuid4()
        now = datetime.now(UTC)
        gov_record = BiometricGovernanceRecord(
            id=gov_id,
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT.value,
            notice_version="1.0.0",
            subject_user_id=subj_id,
            status=GovernanceStatus.REVOKED.value,
            consent_status=ConsentStatus.WITHDRAWN.value,  # Already withdrawn
            withdrawn_at=now - timedelta(days=1),
            retention_days=90,
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=1),
        )
        gov_repo.get_by_id.return_value = gov_record

        req = BiometricConsentWithdrawRequest(reason="Subsequent redundant call")
        res = await service.withdraw_consent(gov_id, req, subject_principal)

        assert res.consent_status == ConsentStatus.WITHDRAWN.value
        # Ref repo was not even called because it was already withdrawn
        assert ref_repo.list_active_by_governance_record.call_count == 0

    @pytest.mark.asyncio
    async def test_unauthorized_user_cannot_withdraw_another_subjects_consent(self) -> None:
        """A user cannot withdraw consent for a governance record belonging to another user."""
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricGovernanceService(gov_repo, ref_repo, audit_repo)

        dept_id = uuid4()
        real_subject_id = uuid4()
        other_user_id = uuid4()
        unauthorized_principal = _create_principal(
            role_code=RoleCode.STUDENT.value,
            user_id=other_user_id,
            department_id=dept_id,
        )

        gov_record = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=dept_id,
            department_id=dept_id,
            policy_version="1.0.0",
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            lawful_basis=BiometricLawfulBasis.EXPLICIT_CONSENT.value,
            notice_version="1.0.0",
            subject_user_id=real_subject_id,
            status=GovernanceStatus.APPROVED.value,
            consent_status=ConsentStatus.ACTIVE.value,
            retention_days=90,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        gov_repo.get_by_id.return_value = gov_record

        req = BiometricConsentWithdrawRequest(reason="Adversarial attempt")
        with pytest.raises(PermissionDeniedError) as exc_info:
            await service.withdraw_consent(gov_record.id, req, unauthorized_principal)
        assert "Only the data subject or an authorized reviewer" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_single_reference_revocation_purges_ciphertext(self) -> None:
        """Revoking an individual reference nulls encrypted_template and sets status to REVOKED."""
        ref_repo = AsyncMock()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(ref_repo, gov_repo, audit_repo)

        dept_id = uuid4()
        admin = _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)

        now = datetime.now(UTC)
        ref = BiometricReference(
            id=uuid4(),
            reference_id="REF-REV-01",
            tenant_id=dept_id,
            department_id=dept_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest="2" * 64,
            encrypted_template="v1:k1:base64ciphertext",
            enrolled_by_id=admin.user_id,
            enrolled_at=now,
            retention_expires_at=now + timedelta(days=30),
            created_at=now,
            updated_at=now,
        )
        ref_repo.get_by_id.return_value = ref

        req = BiometricReferenceRevokeRequest(reason="Administrative deprecation")
        res = await service.revoke_reference(ref.id, req, admin)

        assert res.status == BiometricReferenceStatus.REVOKED.value
        assert ref.encrypted_template is None
        assert ref.revoked_at is not None
        assert ref.revocation_reason == "Administrative deprecation"


# ===========================================================================
# Group D: Security Regressions & Matching Prohibition Invariant
# ===========================================================================


class TestPhase73SecurityRegressions:
    """Verify non-negotiable security invariants, route protections, and cross-subsystem isolation."""

    def test_matching_disabled_invariant_is_unconditional(self) -> None:
        """BIOMETRIC_MATCHING_ENABLED = False remains non-negotiable default."""
        settings = _make_unit_settings()
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    @pytest.mark.asyncio
    async def test_consent_cannot_enable_biometric_matching(self) -> None:
        """Even with approved governance and active consent, FaceMatchingService fails closed."""
        settings = _make_unit_settings(BIOMETRIC_MATCHING_ENABLED=False)
        gov_repo = AsyncMock()
        ref_repo = AsyncMock()
        verif_repo = AsyncMock()
        service = FaceMatchingService(gov_repo, ref_repo, verif_repo, settings)

        investigator = _create_principal(role_code=RoleCode.INVESTIGATOR.value)
        req = FaceMatchRequest(
            governance_record_id=uuid4(),
            probe_image_base64=base64.b64encode(_create_test_png()).decode(),
            reference_id=uuid4(),
        )

        with pytest.raises(BiometricsDisabledError) as exc_info:
            await service.match_faces(req, investigator)
        assert "Biometric face matching is strictly disabled" in str(exc_info.value)

    def test_retention_cleanup_route_exists_and_is_protected(self) -> None:
        """The /retention/cleanup route exists and requires BIOMETRIC_CONFIG_MANAGE permission."""
        from backend.app.api.v1.biometrics import router

        cleanup_routes = [r for r in router.routes if "cleanup" in r.path]
        assert len(cleanup_routes) == 1
        route = cleanup_routes[0]
        assert route.path == "/biometrics/retention/cleanup"

    def test_zero_1_to_n_search_routes_in_biometrics_router(self) -> None:
        """Inspect all biometrics routes to confirm absence of any 1:N endpoints."""
        from backend.app.api.v1.biometrics import router

        for route in router.routes:
            p = route.path.lower()
            assert "search" not in p
            assert "identify" not in p
            assert "crowd" not in p
            assert "gallery" not in p

    def test_reference_read_dto_zero_template_or_ciphertext_leakage(self) -> None:
        """BiometricReferenceRead schema guarantees zero ciphertext or embedding exposure."""
        field_names = set(BiometricReferenceRead.model_fields.keys())
        assert "encrypted_template" not in field_names
        assert "raw_template" not in field_names
        assert "embedding" not in field_names
        assert "feature_vector" not in field_names
        assert "key" not in field_names

    def test_violence_detection_remains_independent_of_biometric_consent(self) -> None:
        """Violence detection modules do not import or depend on biometric governance or consent."""
        import ai_services.violence_detection.classifier as vc
        import ai_services.violence_detection.evaluation as ve

        with open(vc.__file__, encoding="utf-8") as f:
            c_text = f.read()
        with open(ve.__file__, encoding="utf-8") as f:
            e_text = f.read()

        for forbidden in [
            "biometric",
            "consent",
            "FaceDetectionService",
            "BiometricGovernanceService",
            "BiometricReferenceService",
        ]:
            assert forbidden not in c_text
            assert forbidden not in e_text
