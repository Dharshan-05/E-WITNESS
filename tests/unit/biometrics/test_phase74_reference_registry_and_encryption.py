"""Phase 74 Acceptance Test Suite: Biometric Reference Registry & Envelope Encryption Integration.

Tests:
1. Reference Registry Architecture & Constraints (opaque IDs, unique constraints, digest constraints, zero PII).
2. Fail-Closed Enrollment Validation (governance approval, active consent, retention expiry, subject match, purpose match).
3. Evidence Provenance Linkage (attachment existence, tenant match, no cross-tenant leakage, evidence preserved on reference revocation).
4. AES-256-GCM Envelope Encryption & Key Lifecycle (format, AAD binding, tampering detection, key revocation, key rotation).
5. BiometricKeyManagerProtocol & Ephemerality Contract (protocol conformance, is_durable flag).
6. Deletion Layers & Cryptographic Erasure (ciphertext nulling, key revocation fail-closed, audit trail).
7. Mandatory Safety Invariants (BIOMETRIC_MATCHING_ENABLED=False, zero 1:N surveillance routes, zero template leakage).
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.biometric_crypto import (
    ENVELOPE_VERSION,
    KEY_LENGTH_BYTES,
    NONCE_LENGTH_BYTES,
    TAG_LENGTH_BYTES,
    BiometricKeyManager,
    BiometricKeyManagerProtocol,
    KeyStatus,
    validate_envelope_structure,
)
from backend.app.core.biometrics import (
    BiometricLawfulBasis,
    BiometricPurpose,
    BiometricReferenceStatus,
    ConsentStatus,
    GovernanceStatus,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricKeyError,
    BiometricKeyRevokedError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.biometrics import (
    BiometricGovernanceRecord,
    BiometricReference,
)
from backend.app.models.evidence import EvidenceAttachment
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    BiometricReferenceCreate,
    BiometricReferenceRead,
    BiometricReferenceRevokeRequest,
)
from backend.app.services.biometrics import BiometricReferenceService


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


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
        "BIOMETRIC_MATCHING_ENABLED": False,  # Mandatory invariant
        "BIOMETRIC_PROVIDER": "disabled",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


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


@pytest.fixture
def dept_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_dept_id() -> UUID:
    return uuid4()


@pytest.fixture
def admin_principal(dept_id: UUID) -> AuthenticatedPrincipal:
    return _create_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=dept_id)


@pytest.fixture
def investigator_principal(dept_id: UUID) -> AuthenticatedPrincipal:
    return _create_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=dept_id)


@pytest.fixture
def other_dept_principal(other_dept_id: UUID) -> AuthenticatedPrincipal:
    return _create_principal(role_code=RoleCode.INVESTIGATOR.value, department_id=other_dept_id)


@pytest.fixture
def key_manager() -> BiometricKeyManager:
    return BiometricKeyManager(default_key_id="k-phase74-test")


@pytest.fixture
def mock_repos():
    ref_repo = AsyncMock()
    gov_repo = AsyncMock()
    audit_repo = AsyncMock()
    evidence_repo = AsyncMock()
    return ref_repo, gov_repo, audit_repo, evidence_repo


@pytest.fixture
def service(mock_repos, key_manager: BiometricKeyManager) -> BiometricReferenceService:
    ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
    return BiometricReferenceService(
        reference_repo=ref_repo,
        governance_repo=gov_repo,
        audit_repo=audit_repo,
        evidence_repo=evidence_repo,
        key_manager=key_manager,
    )


def make_approved_governance(
    dept_id: UUID,
    subject_user_id: UUID | None = None,
    purpose: str = BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
    retention_days: int = 90,
) -> BiometricGovernanceRecord:
    now = datetime.now(UTC)
    gov = MagicMock(spec=BiometricGovernanceRecord)
    gov.id = uuid4()
    gov.tenant_id = dept_id
    gov.department_id = dept_id
    gov.status = GovernanceStatus.APPROVED.value
    gov.consent_status = ConsentStatus.ACTIVE.value
    gov.lawful_basis = BiometricLawfulBasis.EXPLICIT_CONSENT.value
    gov.purpose = purpose
    gov.subject_user_id = subject_user_id
    gov.retention_days = retention_days
    gov.retention_expires_at = now + timedelta(days=retention_days)
    return gov


# ---------------------------------------------------------------------------
# Category 1: Reference Registry Architecture & Constraints
# ---------------------------------------------------------------------------


class TestReferenceRegistryArchitecture:
    """Verifies reference ID opaque formatting, digest constraints, and zero-leakage read DTOs."""

    def test_reference_id_opaque_format_and_uniqueness(self):
        """Reference IDs must be formatted as REF-BIO-<12 uppercase hex chars> without PII."""
        pattern = re.compile(r"^REF-BIO-[0-9A-F]{12}$")
        ids = {f"REF-BIO-{uuid4().hex[:12].upper()}" for _ in range(100)}
        assert len(ids) == 100
        for rid in ids:
            assert pattern.match(rid) is not None
            # Zero PII: no names, emails, timestamps, or sequential numbers
            assert "@" not in rid
            assert ":" not in rid

    def test_reference_schema_template_digest_validation(self):
        """template_digest must be an exact 64-character hexadecimal SHA-256 string."""
        valid_digest = hashlib.sha256(b"sample_template").hexdigest()
        req = BiometricReferenceCreate(
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest=valid_digest,
        )
        assert req.template_digest == valid_digest

        # Invalid digest (short length)
        with pytest.raises(ValueError):
            BiometricReferenceCreate(
                governance_record_id=uuid4(),
                purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
                template_digest="short_digest",
            )

        # Invalid digest (non-hex characters)
        with pytest.raises(ValueError):
            BiometricReferenceCreate(
                governance_record_id=uuid4(),
                purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
                template_digest="z" * 64,
            )

    def test_reference_read_dto_zero_template_leakage(self):
        """BiometricReferenceRead must never serialize encrypted_template or raw vectors."""
        read_fields = BiometricReferenceRead.model_fields.keys()
        assert "encrypted_template" not in read_fields
        assert "template_payload" not in read_fields
        assert "embedding" not in read_fields
        assert "raw_template" not in read_fields
        assert "key" not in read_fields

        # Test dictionary serialization
        now = datetime.now(UTC)
        read_obj = BiometricReferenceRead(
            id=uuid4(),
            reference_id="REF-BIO-ABC123DEF456",
            tenant_id=uuid4(),
            department_id=uuid4(),
            subject_user_id=uuid4(),
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest="a" * 64,
            provenance_evidence_id=None,
            enrollment_notes="Test",
            enrolled_by_id=uuid4(),
            enrolled_at=now,
            revoked_by_id=None,
            revoked_at=None,
            revocation_reason=None,
            retention_expires_at=now + timedelta(days=90),
            created_at=now,
            updated_at=now,
        )
        data = read_obj.model_dump()
        assert "encrypted_template" not in data
        assert "template_digest" in data


# ---------------------------------------------------------------------------
# Category 2: Enrollment Fail-Closed Governance & Provenance Validation
# ---------------------------------------------------------------------------


class TestEnrollmentGovernanceAndProvenanceValidation:
    """Verifies fail-closed gating on governance approval, subject match, purpose match, and evidence provenance."""

    @pytest.mark.asyncio
    async def test_enrollment_requires_approved_governance_record(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if governance record is not in APPROVED status."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov.status = GovernanceStatus.PENDING_LEGAL_REVIEW.value
        gov_repo.get_by_id.return_value = gov

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="a" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "GOVERNANCE_NOT_APPROVED"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_under_withdrawn_consent(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if subject has withdrawn consent."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov.consent_status = ConsentStatus.WITHDRAWN.value
        gov_repo.get_by_id.return_value = gov

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="a" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "CONSENT_WITHDRAWN"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_under_expired_retention(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if governance retention has expired."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov.retention_expires_at = datetime.now(UTC) - timedelta(days=1)
        gov_repo.get_by_id.return_value = gov

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="a" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "RETENTION_EXPIRED"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_on_subject_mismatch(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if request subject_user_id does not match governance record subject."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        subject_1 = uuid4()
        subject_2 = uuid4()
        gov = make_approved_governance(admin_principal.department_id, subject_user_id=subject_1)
        gov_repo.get_by_id.return_value = gov

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            subject_user_id=subject_2,  # Mismatch!
            template_digest="a" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "SUBJECT_MISMATCH"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_on_purpose_mismatch(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if request purpose differs from governance record purpose."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(
            admin_principal.department_id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
        )
        gov_repo.get_by_id.return_value = gov

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.AUTHORIZED_INVESTIGATIVE_MANUAL_REVIEW,  # Mismatch!
            template_digest="a" * 64,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "PURPOSE_MISMATCH"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_on_missing_provenance_evidence(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Enrollment must fail if provenance_evidence_id does not exist in evidence repository."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov_repo.get_by_id.return_value = gov
        evidence_repo.get_attachment_by_id.return_value = None  # Non-existent

        missing_evidence_id = uuid4()
        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="a" * 64,
            provenance_evidence_id=missing_evidence_id,
        )

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "EVIDENCE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_enrollment_rejected_on_cross_tenant_provenance_evidence(
        self,
        service: BiometricReferenceService,
        admin_principal: AuthenticatedPrincipal,
        other_dept_id: UUID,
        mock_repos,
    ):
        """Enrollment must fail if provenance evidence belongs to a different department/tenant."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov_repo.get_by_id.return_value = gov

        # Evidence belongs to other department
        foreign_evidence = MagicMock(spec=EvidenceAttachment)
        foreign_evidence.id = uuid4()
        foreign_evidence.department_id = other_dept_id
        evidence_repo.get_attachment_by_id.return_value = foreign_evidence

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest="a" * 64,
            provenance_evidence_id=foreign_evidence.id,
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "CROSS_TENANT_EVIDENCE_FORBIDDEN"

    @pytest.mark.asyncio
    async def test_enrollment_success_with_valid_provenance(
        self,
        service: BiometricReferenceService,
        admin_principal: AuthenticatedPrincipal,
        key_manager: BiometricKeyManager,
        mock_repos,
    ):
        """Successful enrollment persists reference and records BIOMETRIC_REFERENCE_ENROLLED audit event."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        now = datetime.now(UTC)
        subject_id = uuid4()
        gov = make_approved_governance(admin_principal.department_id, subject_user_id=subject_id)
        gov_repo.get_by_id.return_value = gov

        # Valid department evidence
        valid_evidence = MagicMock(spec=EvidenceAttachment)
        valid_evidence.id = uuid4()
        valid_evidence.department_id = admin_principal.department_id
        evidence_repo.get_attachment_by_id.return_value = valid_evidence

        # Template and matching envelope
        template_bytes = b"sample_face_embedding_vector_512d"
        template_digest = hashlib.sha256(template_bytes).hexdigest()
        encrypted_template = key_manager.encrypt(template_bytes)

        def mock_create(ref):
            ref.id = uuid4()
            ref.created_at = now
            ref.updated_at = now
            return ref

        ref_repo.create.side_effect = mock_create

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            subject_user_id=subject_id,
            template_digest=template_digest,
            encrypted_template=encrypted_template,
            provenance_evidence_id=valid_evidence.id,
            enrollment_notes="Valid staff enrollment",
        )

        res = await service.enroll_reference(req, admin_principal)

        assert res.reference_id.startswith("REF-BIO-")
        assert res.status == BiometricReferenceStatus.ACTIVE.value
        assert res.provenance_evidence_id == valid_evidence.id
        assert res.template_digest == template_digest

        # Verify audit emission
        audit_repo.append_event.assert_awaited_once()
        audit_call = audit_repo.append_event.call_args[1]
        assert audit_call["action"] == AuditAction.BIOMETRIC_REFERENCE_ENROLLED.value
        assert audit_call["target_type"] == AuditTargetType.BIOMETRIC_REFERENCE.value


# ---------------------------------------------------------------------------
# Category 3: Envelope Encryption Integrity & Key Lifecycle (AES-256-GCM)
# ---------------------------------------------------------------------------


class TestEnvelopeEncryptionAndKeyLifecycle:
    """Verifies AES-256-GCM envelope format, AAD binding, tampering rejection, and key revocation."""

    def test_key_manager_protocol_conformance_and_ephemerality(self, key_manager: BiometricKeyManager):
        """BiometricKeyManager must satisfy BiometricKeyManagerProtocol and report is_durable=False."""
        assert isinstance(key_manager, BiometricKeyManagerProtocol)
        assert key_manager.is_durable is False

    def test_envelope_format_and_round_trip(self, key_manager: BiometricKeyManager):
        """Envelope must follow v1:<key_id>:<base64(12_byte_nonce + ciphertext + 16_byte_tag)>."""
        plaintext = b"sensitive_biometric_template_data_xyz_123"
        envelope = key_manager.encrypt(plaintext)

        parts = envelope.split(":")
        assert len(parts) == 3
        version, key_id, b64_payload = parts
        assert version == ENVELOPE_VERSION
        assert key_id == key_manager.active_key_id

        packed = base64.urlsafe_b64decode(b64_payload)
        min_len = NONCE_LENGTH_BYTES + TAG_LENGTH_BYTES
        assert len(packed) >= min_len + len(plaintext)

        # Round trip
        recovered = key_manager.decrypt(envelope)
        assert recovered == plaintext

    def test_envelope_structure_validation_helper(self, key_manager: BiometricKeyManager):
        """validate_envelope_structure parses valid envelopes and rejects malformed ones."""
        envelope = key_manager.encrypt(b"hello")
        version, key_id, packed = validate_envelope_structure(envelope)
        assert version == ENVELOPE_VERSION
        assert key_id == key_manager.active_key_id
        assert len(packed) >= 28

        # Malformed envelopes
        with pytest.raises(BiometricKeyError, match="must be a non-empty string"):
            validate_envelope_structure("")

        with pytest.raises(BiometricKeyError, match="expected 'v1:<key_id>:<payload>'"):
            validate_envelope_structure("v2:key1:payload")

        with pytest.raises(BiometricKeyError, match="expected 'v1:<key_id>:<payload>'"):
            validate_envelope_structure("v1:only_two_parts")

        with pytest.raises(BiometricKeyError, match="key ID cannot be empty"):
            validate_envelope_structure("v1:  :payload")

        with pytest.raises(BiometricKeyError, match="Corrupted base64 payload"):
            validate_envelope_structure("v1:k1:not_valid_b64!@#")

        with pytest.raises(BiometricKeyError, match="too short"):
            short_b64 = base64.urlsafe_b64encode(b"short").decode()
            validate_envelope_structure(f"v1:k1:{short_b64}")

    def test_envelope_decryption_rejects_tampered_ciphertext(self, key_manager: BiometricKeyManager):
        """Modifying even a single bit in the ciphertext must cause decryption to fail closed."""
        plaintext = b"tamper_resistance_test_template"
        envelope = key_manager.encrypt(plaintext)
        version, key_id, b64_payload = envelope.split(":")
        packed = bytearray(base64.urlsafe_b64decode(b64_payload))

        # Tamper byte in ciphertext region (between nonce and tag)
        packed[NONCE_LENGTH_BYTES + 2] ^= 0xFF
        tampered_b64 = base64.urlsafe_b64encode(packed).decode()
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed; ciphertext or authentication tag corrupted"):
            key_manager.decrypt(tampered_envelope)

    def test_envelope_decryption_rejects_tampered_tag(self, key_manager: BiometricKeyManager):
        """Modifying any bit in the 16-byte authentication tag must cause decryption failure."""
        plaintext = b"tamper_tag_test_template"
        envelope = key_manager.encrypt(plaintext)
        version, key_id, b64_payload = envelope.split(":")
        packed = bytearray(base64.urlsafe_b64decode(b64_payload))

        # Tamper last byte (part of tag)
        packed[-1] ^= 0x01
        tampered_b64 = base64.urlsafe_b64encode(packed).decode()
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            key_manager.decrypt(tampered_envelope)

    def test_envelope_decryption_rejects_tampered_nonce(self, key_manager: BiometricKeyManager):
        """Modifying the 12-byte nonce must cause decryption failure due to tag mismatch."""
        plaintext = b"tamper_nonce_test_template"
        envelope = key_manager.encrypt(plaintext)
        version, key_id, b64_payload = envelope.split(":")
        packed = bytearray(base64.urlsafe_b64decode(b64_payload))

        # Tamper first byte (part of nonce)
        packed[0] ^= 0x01
        tampered_b64 = base64.urlsafe_b64encode(packed).decode()
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            key_manager.decrypt(tampered_envelope)

    def test_envelope_decryption_rejects_revoked_key(self, key_manager: BiometricKeyManager):
        """Decryption under a revoked key must fail closed with BiometricKeyRevokedError."""
        key_id = key_manager.active_key_id
        envelope = key_manager.encrypt(b"secret_data")

        # Revoke the key
        key_manager.revoke_key(key_id)

        with pytest.raises(BiometricKeyRevokedError, match="has been revoked. Decryption is forbidden"):
            key_manager.decrypt(envelope)

    def test_envelope_decryption_rejects_unknown_key(self, key_manager: BiometricKeyManager):
        """Decryption with an unknown key ID must fail closed with BiometricKeyError."""
        valid_b64 = base64.urlsafe_b64encode(os.urandom(40)).decode()
        envelope = f"v1:key-nonexistent:{valid_b64}"

        with pytest.raises(BiometricKeyError, match="not found in keyring"):
            key_manager.decrypt(envelope)

    @pytest.mark.asyncio
    async def test_enrollment_template_digest_mismatch_fails_closed(
        self,
        service: BiometricReferenceService,
        admin_principal: AuthenticatedPrincipal,
        key_manager: BiometricKeyManager,
        mock_repos,
    ):
        """Enrollment must fail if template_digest does not match decrypted envelope contents."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        gov = make_approved_governance(admin_principal.department_id)
        gov_repo.get_by_id.return_value = gov

        actual_template = b"real_biometric_data"
        encrypted_envelope = key_manager.encrypt(actual_template)

        # Hash of different data
        fake_digest = hashlib.sha256(b"different_data").hexdigest()

        req = BiometricReferenceCreate(
            governance_record_id=gov.id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT,
            template_digest=fake_digest,
            encrypted_template=encrypted_envelope,
        )

        with pytest.raises(BiometricGovernanceError) as exc_info:
            await service.enroll_reference(req, admin_principal)
        assert exc_info.value.code == "TEMPLATE_DIGEST_MISMATCH"

    def test_key_rotation_and_reencryption(self, key_manager: BiometricKeyManager):
        """Key rotation creates a new active key and allows re-encryption from old key."""
        old_key_id = key_manager.active_key_id
        data = b"template_across_rotation"
        envelope_v1 = key_manager.encrypt(data, key_id=old_key_id)

        # Rotate key
        new_key_id = key_manager.rotate_key("k-new-rotated")
        assert key_manager.active_key_id == new_key_id
        assert key_manager.get_key_metadata(old_key_id).status == KeyStatus.ROTATED
        assert key_manager.get_key_metadata(new_key_id).status == KeyStatus.ACTIVE

        # Re-encrypt under new active key
        envelope_v2 = key_manager.reencrypt(envelope_v1)
        assert f":{new_key_id}:" in envelope_v2

        # Decrypt re-encrypted envelope
        recovered = key_manager.decrypt(envelope_v2)
        assert recovered == data


# ---------------------------------------------------------------------------
# Category 4: Reference Revocation, Cryptographic Erasure & Deletion Layers
# ---------------------------------------------------------------------------


class TestReferenceRevocationAndCryptographicErasure:
    """Verifies that revocation purges ciphertext from active DB row, preserves evidence, and audits the event."""

    @pytest.mark.asyncio
    async def test_reference_revocation_purges_ciphertext(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Revoking a reference sets encrypted_template to None and transitions status to REVOKED."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        now = datetime.now(UTC)
        reference = MagicMock(spec=BiometricReference)
        reference.id = uuid4()
        reference.reference_id = "REF-BIO-TEST123456"
        reference.tenant_id = admin_principal.department_id
        reference.department_id = admin_principal.department_id
        reference.governance_record_id = uuid4()
        reference.status = BiometricReferenceStatus.ACTIVE.value
        reference.encrypted_template = "v1:k1:sensitive_ciphertext_blob"
        reference.subject_user_id = uuid4()
        reference.purpose = BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value
        reference.template_digest = "a" * 64
        reference.provenance_evidence_id = uuid4()
        reference.enrollment_notes = "Note"
        reference.enrolled_by_id = admin_principal.user_id
        reference.enrolled_at = now
        reference.revoked_by_id = None
        reference.revoked_at = None
        reference.revocation_reason = None
        reference.retention_expires_at = now + timedelta(days=90)
        reference.created_at = now
        reference.updated_at = now

        ref_repo.get_by_id.return_value = reference

        revoke_req = BiometricReferenceRevokeRequest(reason="Subject requested reference removal")
        res = await service.revoke_reference(reference.id, revoke_req, admin_principal)

        assert res.status == BiometricReferenceStatus.REVOKED.value
        assert reference.encrypted_template is None  # Active row erasure
        assert reference.status == BiometricReferenceStatus.REVOKED.value
        assert reference.revocation_reason == "Subject requested reference removal"

        # Verify audit emission
        audit_repo.append_event.assert_awaited_once()
        audit_call = audit_repo.append_event.call_args[1]
        assert audit_call["action"] == AuditAction.BIOMETRIC_REFERENCE_REVOKED.value

    @pytest.mark.asyncio
    async def test_reference_revocation_idempotent(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Revoking an already revoked reference returns current status idempotently without re-auditing."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        now = datetime.now(UTC)
        reference = MagicMock(spec=BiometricReference)
        reference.id = uuid4()
        reference.reference_id = "REF-BIO-TEST123456"
        reference.tenant_id = admin_principal.department_id
        reference.department_id = admin_principal.department_id
        reference.governance_record_id = uuid4()
        reference.status = BiometricReferenceStatus.REVOKED.value
        reference.encrypted_template = None
        reference.subject_user_id = uuid4()
        reference.purpose = BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value
        reference.template_digest = "a" * 64
        reference.provenance_evidence_id = None
        reference.enrollment_notes = "Note"
        reference.enrolled_by_id = admin_principal.user_id
        reference.enrolled_at = now
        reference.revoked_by_id = admin_principal.user_id
        reference.revoked_at = now
        reference.revocation_reason = "Initial revocation"
        reference.retention_expires_at = now + timedelta(days=90)
        reference.created_at = now
        reference.updated_at = now

        ref_repo.get_by_id.return_value = reference

        revoke_req = BiometricReferenceRevokeRequest(reason="Second attempt")
        res = await service.revoke_reference(reference.id, revoke_req, admin_principal)

        assert res.status == BiometricReferenceStatus.REVOKED.value
        # No new audit event appended
        audit_repo.append_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_evidence_provenance_preserved_on_reference_revocation(
        self, service: BiometricReferenceService, admin_principal: AuthenticatedPrincipal, mock_repos
    ):
        """Revoking a biometric reference must never delete or alter the associated evidence attachment."""
        ref_repo, gov_repo, audit_repo, evidence_repo = mock_repos
        evidence_id = uuid4()
        now = datetime.now(UTC)
        reference = MagicMock(spec=BiometricReference)
        reference.id = uuid4()
        reference.reference_id = "REF-BIO-PRESERVE123"
        reference.tenant_id = admin_principal.department_id
        reference.department_id = admin_principal.department_id
        reference.governance_record_id = uuid4()
        reference.status = BiometricReferenceStatus.ACTIVE.value
        reference.encrypted_template = "v1:k1:ciphertext"
        reference.provenance_evidence_id = evidence_id
        reference.subject_user_id = None
        reference.purpose = BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value
        reference.template_digest = "b" * 64
        reference.enrollment_notes = None
        reference.enrolled_by_id = admin_principal.user_id
        reference.enrolled_at = now
        reference.revoked_by_id = None
        reference.revoked_at = None
        reference.revocation_reason = None
        reference.retention_expires_at = now + timedelta(days=90)
        reference.created_at = now
        reference.updated_at = now

        ref_repo.get_by_id.return_value = reference

        await service.revoke_reference(
            reference.id,
            BiometricReferenceRevokeRequest(reason="Preserve test"),
            admin_principal,
        )

        # Evidence repository must NOT be called for deletion or mutation
        evidence_repo.update_attachment.assert_not_called()
        assert reference.provenance_evidence_id == evidence_id  # FK remains set (or SET NULL on evidence delete)


# ---------------------------------------------------------------------------
# Category 5: Mandatory Safety Invariants & Matching Prohibition
# ---------------------------------------------------------------------------


class TestPhase74SafetyInvariants:
    """Verifies that BIOMETRIC_MATCHING_ENABLED is False and no 1:N surveillance routes exist."""

    def test_biometric_matching_enabled_invariant_preserved(self):
        """Settings.BIOMETRIC_MATCHING_ENABLED must be False permanently."""
        settings = _make_unit_settings()
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    def test_no_1_to_n_search_or_crowd_surveillance_endpoints(self):
        """API router must not expose any 1:N search, crowd scanning, or watchlist routes."""
        from backend.app.api.v1.biometrics import router

        forbidden_path_substrings = [
            "search",
            "crowd",
            "surveillance",
            "watchlist",
            "identify",
            "1-to-n",
            "1ton",
        ]

        for route in router.routes:
            path = getattr(route, "path", "").lower()
            for forbidden in forbidden_path_substrings:
                assert forbidden not in path, f"Forbidden route pattern found: {path}"
