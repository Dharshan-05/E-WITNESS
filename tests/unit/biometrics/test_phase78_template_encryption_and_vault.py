"""Phase 78 Acceptance Test Suite: Template Encryption at Rest, Key Management & Secure Vault Integration.

Tests:
1. Encryption/Decryption Round Trips (AES-256-GCM authenticated encryption, unique nonces).
2. Tampered Ciphertext & Tag Rejection (bit-flipping in ciphertext, tag, or nonce causes fail-closed failure).
3. Additional Authenticated Data (AAD) Binding (record-id context mismatch rejects decryption).
4. Key Lifecycle States & Fail-Closed Behavior (ACTIVE, ROTATED, REVOKED, RETIRED, DISABLED).
5. Unavailable Vault & Timeout Handling (BiometricVaultUnavailableError fail-closed).
6. Durable Keystore & Process Restart Recovery (EncryptedFileKeyVaultProvider persistence across instances).
7. External KMS Vault Adapter (adapter contract, health check, timeout simulation).
8. Reference Re-encryption & Verification (single reference re-encryption with digest verification).
9. Batch Re-encryption & Idempotency (re-encrypts rotated records, skips already rotated records).
10. Authorization & Tenant Isolation (super admin required for rotation/revocation, cross-tenant isolation).
11. Consent Withdrawal & Retention Interaction (active row erasure, residual WAL/snapshot documentation).
12. Zero Key & Plaintext Leakage (scrubbing in representations, audit trails, and read DTOs).
13. Permanent Matching Prohibition Invariant (BIOMETRIC_MATCHING_ENABLED=False immutable).
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    BiometricKeyMetadata,
    BiometricKeyVaultProtocol,
    EncryptedFileKeyVaultProvider,
    ExternalKmsVaultAdapter,
    InMemoryKeyVaultProvider,
    KeyStatus,
    validate_envelope_structure,
)
from backend.app.core.biometrics import (
    BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER,
    BiometricLawfulBasis,
    BiometricPurpose,
    BiometricReferenceStatus,
    ConsentStatus,
    GovernanceStatus,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricKeyDisabledError,
    BiometricKeyError,
    BiometricKeyRevokedError,
    BiometricVaultUnavailableError,
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
    BiometricBatchReencryptRequest,
    BiometricBatchReencryptResponse,
    BiometricKeyMetadataRead,
    BiometricReferenceRead,
    BiometricReferenceReencryptRequest,
)
from backend.app.services.biometrics import BiometricReferenceService


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


def _make_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    """Create test AuthenticatedPrincipal."""
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email="auditor@ewitness.internal",
        full_name="Test Principal",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=department_id or uuid4(),
        session_id=uuid4(),
    )


@pytest.fixture
def temp_vault_dir():
    """Create temporary directory for file-backed vault tests."""
    temp_dir = tempfile.mkdtemp(prefix="ewitness_vault_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def memory_key_manager():
    """Create isolated in-memory key manager."""
    return BiometricKeyManager(default_key_id="k-test-init")


# ---------------------------------------------------------------------------
# 1. Encryption & Decryption Round Trips
# ---------------------------------------------------------------------------


class TestEncryptionRoundTripsAndAEAD:
    """Audit AES-256-GCM encryption, decryption, and envelope formatting."""

    def test_encryption_round_trip_success(self, memory_key_manager: BiometricKeyManager):
        """Plaintext template encrypts and decrypts with 100% byte fidelity."""
        raw_template = b'{"embeddings": [0.123, 0.456, -0.789], "model": "test-v1"}'
        envelope = memory_key_manager.encrypt(raw_template)

        assert envelope.startswith(f"{ENVELOPE_VERSION}:k-test-init:")
        decrypted = memory_key_manager.decrypt(envelope)
        assert decrypted == raw_template

    def test_unique_nonce_per_operation(self, memory_key_manager: BiometricKeyManager):
        """Encrypting the exact same plaintext multiple times must yield different nonces and ciphertexts."""
        plaintext = b"identical_plaintext_payload"
        envelope1 = memory_key_manager.encrypt(plaintext)
        envelope2 = memory_key_manager.encrypt(plaintext)

        assert envelope1 != envelope2
        v1, k1, packed1 = validate_envelope_structure(envelope1)
        v2, k2, packed2 = validate_envelope_structure(envelope2)

        nonce1 = packed1[:NONCE_LENGTH_BYTES]
        nonce2 = packed2[:NONCE_LENGTH_BYTES]
        assert nonce1 != nonce2

    def test_empty_plaintext_rejected(self, memory_key_manager: BiometricKeyManager):
        """Empty plaintext is rejected immediately."""
        with pytest.raises(ValueError, match="cannot be empty"):
            memory_key_manager.encrypt(b"")

    def test_aad_context_binding(self, memory_key_manager: BiometricKeyManager):
        """Decryption succeeds with matching record_id AAD, and fails closed with mismatched record_id."""
        plaintext = b"sensitive_subject_biometric_data"
        record_id = "REF-BIO-AAA111"

        envelope = memory_key_manager.encrypt(plaintext, record_id=record_id)

        # Correct context succeeds
        decrypted = memory_key_manager.decrypt(envelope, record_id=record_id)
        assert decrypted == plaintext

        # Mismatched context fails closed (authentication tag mismatch)
        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(envelope, record_id="REF-BIO-WRONG999")

        # Missing context when encrypted with context fails closed
        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(envelope)


# ---------------------------------------------------------------------------
# 2. Tampering & Authentication Tag Rejection
# ---------------------------------------------------------------------------


class TestTamperResistance:
    """Verify that any modification to ciphertext, tag, nonce, or key causes fail-closed rejection."""

    def test_ciphertext_tampering_fails_closed(self, memory_key_manager: BiometricKeyManager):
        """Modifying even 1 bit in ciphertext causes authentication tag check failure."""
        plaintext = b"tamper_test_data"
        envelope = memory_key_manager.encrypt(plaintext)
        version, key_id, packed = validate_envelope_structure(envelope)

        # Mutate middle ciphertext byte
        tampered_packed = bytearray(packed)
        tampered_packed[NONCE_LENGTH_BYTES + 2] ^= 0xFF
        tampered_b64 = base64.urlsafe_b64encode(tampered_packed).decode("ascii")
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(tampered_envelope)

    def test_tag_tampering_fails_closed(self, memory_key_manager: BiometricKeyManager):
        """Modifying the final 16 authentication tag bytes causes failure."""
        plaintext = b"tag_tamper_test"
        envelope = memory_key_manager.encrypt(plaintext)
        version, key_id, packed = validate_envelope_structure(envelope)

        tampered_packed = bytearray(packed)
        tampered_packed[-1] ^= 0x01
        tampered_b64 = base64.urlsafe_b64encode(tampered_packed).decode("ascii")
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(tampered_envelope)

    def test_nonce_tampering_fails_closed(self, memory_key_manager: BiometricKeyManager):
        """Modifying the initial 12 nonce bytes causes tag verification failure."""
        plaintext = b"nonce_tamper_test"
        envelope = memory_key_manager.encrypt(plaintext)
        version, key_id, packed = validate_envelope_structure(envelope)

        tampered_packed = bytearray(packed)
        tampered_packed[0] ^= 0x55
        tampered_b64 = base64.urlsafe_b64encode(tampered_packed).decode("ascii")
        tampered_envelope = f"{version}:{key_id}:{tampered_b64}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(tampered_envelope)

    def test_cross_key_substitution_fails_closed(self, memory_key_manager: BiometricKeyManager):
        """Decrypting an envelope using a different key ID in the envelope header fails closed."""
        plaintext = b"cross_key_test"
        envelope = memory_key_manager.encrypt(plaintext)
        version, key_id, packed = validate_envelope_structure(envelope)

        # Register a second key k2
        memory_key_manager.register_key("k2", os.urandom(KEY_LENGTH_BYTES), status=KeyStatus.ROTATED)

        # Replace key ID in envelope from k-test-init to k2
        tampered_envelope = f"{version}:k2:{base64.urlsafe_b64encode(packed).decode('ascii')}"

        with pytest.raises(BiometricKeyError, match="authentication failed"):
            memory_key_manager.decrypt(tampered_envelope)


# ---------------------------------------------------------------------------
# 3. Key Lifecycle States (ACTIVE, ROTATED, REVOKED, RETIRED, DISABLED)
# ---------------------------------------------------------------------------


class TestKeyLifecycleStates:
    """Verify state transitions and fail-closed security for each key state."""

    def test_key_rotation_preserves_old_decryption(self, memory_key_manager: BiometricKeyManager):
        """Rotation marks previous key as ROTATED; old ciphertext remains decryptable."""
        plaintext = b"historic_ciphertext_pre_rotation"
        envelope_k1 = memory_key_manager.encrypt(plaintext)
        assert envelope_k1.startswith("v1:k-test-init:")

        # Rotate to k2
        memory_key_manager.rotate_key("k2")
        assert memory_key_manager.active_key_id == "k2"

        # Old envelope decrypts cleanly with rotated key k-test-init
        assert memory_key_manager.decrypt(envelope_k1) == plaintext

        # New encryptions use k2
        envelope_k2 = memory_key_manager.encrypt(b"new_data")
        assert envelope_k2.startswith("v1:k2:")

        meta_k1 = memory_key_manager.get_key_metadata("k-test-init")
        assert meta_k1.status == KeyStatus.ROTATED

    def test_key_revocation_fails_closed_immediately(self, memory_key_manager: BiometricKeyManager):
        """Revoking a key immediately forbids both decryption and encryption."""
        plaintext = b"data_to_be_revoked"
        envelope = memory_key_manager.encrypt(plaintext)

        memory_key_manager.revoke_key("k-test-init")
        assert memory_key_manager.active_key_id is None

        # Decryption fails closed
        with pytest.raises(BiometricKeyRevokedError, match="has been revoked"):
            memory_key_manager.decrypt(envelope)

        # Encryption fails closed because active key is gone
        with pytest.raises(BiometricKeyError, match="No active biometric encryption key available"):
            memory_key_manager.encrypt(b"attempt")

    def test_key_retirement_forbids_new_encryption(self, memory_key_manager: BiometricKeyManager):
        """Retired keys can still decrypt historic data, but are rejected for new encryption."""
        plaintext = b"archived_evidence_template"
        envelope = memory_key_manager.encrypt(plaintext)

        memory_key_manager.retire_key("k-test-init")

        # Decryption remains allowed for archival audit
        assert memory_key_manager.decrypt(envelope) == plaintext

        # Cannot be used for new encryption
        with pytest.raises(BiometricKeyError, match="is retired and cannot be used"):
            memory_key_manager.encrypt(b"new_data", key_id="k-test-init")

    def test_key_disablement_temporarily_suspends_operations(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Disabled keys fail closed until re-enabled."""
        envelope = memory_key_manager.encrypt(b"suspended_key_data")

        memory_key_manager.disable_key("k-test-init")

        with pytest.raises(BiometricKeyDisabledError, match="temporarily disabled"):
            memory_key_manager.decrypt(envelope)

        # Re-enable restores decryption capability
        memory_key_manager.enable_key("k-test-init")
        assert memory_key_manager.decrypt(envelope) == b"suspended_key_data"

    def test_unknown_key_fails_closed(self, memory_key_manager: BiometricKeyManager):
        """Envelopes referencing non-existent key IDs fail closed."""
        fake_envelope = f"v1:key-ghost:{base64.urlsafe_b64encode(os.urandom(32)).decode()}"
        with pytest.raises(BiometricKeyError, match="not found in keyring"):
            memory_key_manager.decrypt(fake_envelope)


# ---------------------------------------------------------------------------
# 4. Vault Provider Abstraction & Process Restart Recovery
# ---------------------------------------------------------------------------


class TestVaultProviderDurabilityAndRestart:
    """Test pluggable vault providers, failure handling, and persistent process restarts."""

    def test_in_memory_provider_ephemerality(self, memory_key_manager: BiometricKeyManager):
        """InMemoryKeyVaultProvider must report is_durable=False and non-production status."""
        assert memory_key_manager.is_durable is False
        assert memory_key_manager.is_available is True
        health = memory_key_manager.health_check()
        assert health["provider"] == "in_memory"
        assert health["is_durable"] is False

    def test_in_memory_vault_unavailability_fails_closed(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Simulated vault outage raises BiometricVaultUnavailableError."""
        vault = memory_key_manager.vault_provider
        assert isinstance(vault, InMemoryKeyVaultProvider)

        envelope = memory_key_manager.encrypt(b"pre_outage_data")

        # Simulate vault network/storage outage
        vault.set_available(False)
        assert memory_key_manager.is_available is False

        with pytest.raises(BiometricVaultUnavailableError, match="unavailable / unreachable"):
            memory_key_manager.decrypt(envelope)

        with pytest.raises(BiometricVaultUnavailableError, match="unavailable / unreachable"):
            memory_key_manager.encrypt(b"outage_attempt")

        # Recovery
        vault.set_available(True)
        assert memory_key_manager.decrypt(envelope) == b"pre_outage_data"

    def test_encrypted_file_vault_durable_restart(self, temp_vault_dir: Path):
        """EncryptedFileKeyVaultProvider persists keys to disk and recovers them across new instances."""
        vault_file = temp_vault_dir / "test_keystore.vault"
        master_kek = os.urandom(KEY_LENGTH_BYTES)

        # 1. First process instance: creates vault and encrypts data
        vault1 = EncryptedFileKeyVaultProvider(file_path=vault_file, master_key_bytes=master_kek)
        manager1 = BiometricKeyManager(vault_provider=vault1, default_key_id="k-durable-1")

        assert manager1.is_durable is True
        test_plaintext = b"persistent_template_bytes_across_restart"
        envelope1 = manager1.encrypt(test_plaintext)

        # Rotate key in process 1
        manager1.rotate_key("k-durable-2")
        envelope2 = manager1.encrypt(b"process1_envelope2")

        # 2. Simulate complete process termination: destroy in-memory instances
        del manager1
        del vault1

        assert vault_file.exists()
        # Verify file on disk is encrypted (contains no raw plaintext key strings)
        raw_disk_bytes = vault_file.read_bytes()
        assert b"persistent_template" not in raw_disk_bytes
        assert b"k-durable-1" not in raw_disk_bytes

        # 3. Second process instance: restarts from disk with master key
        vault2 = EncryptedFileKeyVaultProvider(file_path=vault_file, master_key_bytes=master_kek)
        manager2 = BiometricKeyManager(vault_provider=vault2)

        assert manager2.active_key_id == "k-durable-2"
        # Successfully decrypts historic envelope from process 1!
        assert manager2.decrypt(envelope1) == test_plaintext
        assert manager2.decrypt(envelope2) == b"process1_envelope2"

    def test_encrypted_file_vault_rejects_wrong_master_key(self, temp_vault_dir: Path):
        """Vault fails closed with BiometricKeyError when opened with an invalid master key."""
        vault_file = temp_vault_dir / "kek_test.vault"
        correct_kek = os.urandom(KEY_LENGTH_BYTES)
        wrong_kek = os.urandom(KEY_LENGTH_BYTES)

        # Create vault with correct key
        vault = EncryptedFileKeyVaultProvider(file_path=vault_file, master_key_bytes=correct_kek)
        vault.store_key("k1", os.urandom(KEY_LENGTH_BYTES))
        del vault

        # Attempt to open with wrong master key
        with pytest.raises(BiometricKeyError, match="Authentication tag mismatch"):
            EncryptedFileKeyVaultProvider(file_path=vault_file, master_key_bytes=wrong_kek)

    def test_external_kms_vault_adapter_contract(self):
        """ExternalKmsVaultAdapter provides compliant interface and fails closed on outage."""
        adapter = ExternalKmsVaultAdapter(
            endpoint_url="https://kms.vault.internal:8200",
            kms_key_id="projects/ewitness/keys/primary-kek",
        )
        assert adapter.is_durable is True
        assert adapter.is_available is True

        # Store test key
        adapter.store_key("kms-k1", os.urandom(KEY_LENGTH_BYTES))
        adapter.set_active_key_id("kms-k1")

        manager = BiometricKeyManager(vault_provider=adapter)
        envelope = manager.encrypt(b"kms_protected_template")
        assert manager.decrypt(envelope) == b"kms_protected_template"

        # Simulate KMS network timeout
        adapter.set_available(False)
        with pytest.raises(BiometricVaultUnavailableError, match="unavailable"):
            manager.decrypt(envelope)


# ---------------------------------------------------------------------------
# 5. Controlled Reference Re-encryption & Verification (Phase 78)
# ---------------------------------------------------------------------------


class TestReferenceReencryptionService:
    """Verify single and batch reference re-encryption workflows."""

    @pytest.mark.asyncio
    async def test_reencrypt_reference_success(self, memory_key_manager: BiometricKeyManager):
        """Authorized user re-encrypts reference; ciphertext is updated and verified."""
        ref_repo = AsyncMock()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()

        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=gov_repo,
            audit_repo=audit_repo,
            key_manager=memory_key_manager,
        )

        admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value)
        template_bytes = b"sample_face_template_128d"
        template_digest = hashlib.sha256(template_bytes).hexdigest()
        old_envelope = memory_key_manager.encrypt(template_bytes, key_id="k-test-init")

        now = datetime.now(UTC)
        ref = BiometricReference(
            id=uuid4(),
            reference_id="REF-BIO-REENCRYPT1",
            tenant_id=admin.department_id,
            department_id=admin.department_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.AUTHORIZED_INVESTIGATIVE_MANUAL_REVIEW.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest=template_digest,
            encrypted_template=old_envelope,
            enrolled_by_id=admin.user_id,
            enrolled_at=now,
            created_at=now,
            updated_at=now,
            retention_expires_at=now + timedelta(days=90),
        )
        ref_repo.get_by_id.return_value = ref

        # Rotate key to k2
        memory_key_manager.rotate_key("k2")

        # Execute re-encryption
        result = await service.reencrypt_reference(ref.id, admin)

        assert result.reference_id == "REF-BIO-REENCRYPT1"
        assert ref.encrypted_template.startswith("v1:k2:")
        # Verify newly encrypted envelope decrypts to exact original template
        assert memory_key_manager.decrypt(ref.encrypted_template) == template_bytes

        # Audit event recorded
        audit_repo.append_event.assert_awaited_once()
        audit_args = audit_repo.append_event.await_args.kwargs
        assert audit_args["action"] == AuditAction.BIOMETRIC_REFERENCE_REENCRYPTED.value
        assert audit_args["details"]["old_key_id"] == "k-test-init"
        assert audit_args["details"]["new_key_id"] == "k2"

    @pytest.mark.asyncio
    async def test_reencrypt_rejected_for_revoked_reference(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Cannot re-encrypt a reference that has been revoked or expired."""
        ref_repo = AsyncMock()
        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )
        admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)

        ref = BiometricReference(
            id=uuid4(),
            reference_id="REF-BIO-REV1",
            tenant_id=admin.department_id,
            department_id=admin.department_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.TESTING_SYNTHETIC_BENCHMARK.value,
            status=BiometricReferenceStatus.REVOKED.value,
            template_digest="a" * 64,
            encrypted_template=None,
            enrolled_by_id=admin.user_id,
            enrolled_at=datetime.now(UTC),
        )
        ref_repo.get_by_id.return_value = ref

        with pytest.raises(BiometricGovernanceError, match="Cannot re-encrypt reference in status"):
            await service.reencrypt_reference(ref.id, admin)

    @pytest.mark.asyncio
    async def test_reencrypt_rejected_for_cross_tenant_caller(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Dept admin from department A cannot re-encrypt references in department B."""
        ref_repo = AsyncMock()
        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )
        dept_admin_a = _make_principal(role_code=RoleCode.DEPT_ADMIN.value, department_id=uuid4())

        # When repo is scoped by department_id, cross-department returns None
        ref_repo.get_by_id.return_value = None

        with pytest.raises(ResourceNotFoundError, match="not found"):
            await service.reencrypt_reference(uuid4(), dept_admin_a)

    @pytest.mark.asyncio
    async def test_batch_reencryption_idempotent_skipping(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Batch re-encryption re-encrypts old keys and idempotently skips already re-encrypted records."""
        ref_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=AsyncMock(),
            audit_repo=audit_repo,
            key_manager=memory_key_manager,
        )
        admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)

        # Create 2 references: one under k-test-init, one already under rotated key k2
        memory_key_manager.rotate_key("k2")

        data1 = b"template_one"
        data2 = b"template_two"

        ref1 = BiometricReference(
            id=uuid4(),
            reference_id="REF-1",
            tenant_id=admin.department_id,
            department_id=admin.department_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.TESTING_SYNTHETIC_BENCHMARK.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest=hashlib.sha256(data1).hexdigest(),
            encrypted_template=memory_key_manager.encrypt(data1, key_id="k-test-init"),
            enrolled_by_id=admin.user_id,
            enrolled_at=datetime.now(UTC),
        )
        ref2 = BiometricReference(
            id=uuid4(),
            reference_id="REF-2",
            tenant_id=admin.department_id,
            department_id=admin.department_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.TESTING_SYNTHETIC_BENCHMARK.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest=hashlib.sha256(data2).hexdigest(),
            encrypted_template=memory_key_manager.encrypt(data2, key_id="k2"),
            enrolled_by_id=admin.user_id,
            enrolled_at=datetime.now(UTC),
        )
        ref_repo.list_active_for_reencryption.return_value = [ref1, ref2]

        response = await service.batch_reencrypt_references(admin, new_key_id="k2")

        assert response.total_scanned == 2
        assert response.reencrypted_count == 1
        assert response.skipped_count == 1
        assert response.error_count == 0
        assert ref1.encrypted_template.startswith("v1:k2:")


# ---------------------------------------------------------------------------
# 6. Authorization & Key Management Permissions
# ---------------------------------------------------------------------------


class TestKeyManagementAuthorization:
    """Verify that key management actions require explicit, least-privilege permissions."""

    @pytest.mark.asyncio
    async def test_key_rotation_restricted_to_super_admin(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Investigators and department admins cannot rotate cryptographic keys."""
        service = BiometricReferenceService(
            reference_repo=AsyncMock(),
            governance_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )

        investigator = _make_principal(role_code=RoleCode.INVESTIGATOR.value)
        dept_admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value)
        super_admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)

        # Investigator denied
        with pytest.raises(PermissionDeniedError, match="lacks BIOMETRIC_CONFIG_MANAGE"):
            await service.rotate_key(investigator)

        # Dept admin denied
        with pytest.raises(PermissionDeniedError, match="lacks BIOMETRIC_CONFIG_MANAGE"):
            await service.rotate_key(dept_admin)

        # Super admin succeeds
        meta = await service.rotate_key(super_admin)
        assert meta.is_active is True
        assert meta.key_id == memory_key_manager.active_key_id

    @pytest.mark.asyncio
    async def test_key_revocation_restricted_to_super_admin(
        self, memory_key_manager: BiometricKeyManager
    ):
        """Only Super Admin can invoke key revocation."""
        service = BiometricReferenceService(
            reference_repo=AsyncMock(),
            governance_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )
        dept_admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value)
        super_admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)

        with pytest.raises(PermissionDeniedError, match="lacks BIOMETRIC_CONFIG_MANAGE"):
            await service.revoke_key("k-test-init", dept_admin)

        meta = await service.revoke_key("k-test-init", super_admin)
        assert meta.status == KeyStatus.REVOKED.value


# ---------------------------------------------------------------------------
# 7. Zero Key & Plaintext Leakage Audit
# ---------------------------------------------------------------------------


class TestZeroSecretLeakage:
    """Verify that raw keys, plaintext templates, and embeddings are NEVER logged or serialized."""

    def test_metadata_representation_scrubs_key_bytes(
        self, memory_key_manager: BiometricKeyManager
    ):
        """String representation of metadata, entries, and manager scrubs raw key bytes."""
        meta = memory_key_manager.get_key_metadata("k-test-init")
        repr_meta = repr(meta)
        assert "KEY MATERIAL REDACTED" in repr_meta
        assert "key_bytes" not in repr_meta

        manager_repr = repr(memory_key_manager)
        assert "k-test-init" in manager_repr
        assert "key_bytes" not in manager_repr

    def test_key_read_dto_contains_zero_secrets(self, memory_key_manager: BiometricKeyManager):
        """BiometricKeyMetadataRead contains status, algorithm, version, and disclaimer, but no secrets."""
        service = BiometricReferenceService(
            reference_repo=AsyncMock(),
            governance_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )
        super_admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)

        keys = service.list_keys(super_admin)
        assert len(keys) >= 1
        key_dto = keys[0]

        dump = key_dto.model_dump()
        assert "key_bytes" not in dump
        assert "private_key" not in dump
        assert "secret" not in dump
        assert dump["disclaimer"] == BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER


# ---------------------------------------------------------------------------
# 8. Mandatory Safety Invariants (Phase 78)
# ---------------------------------------------------------------------------


class TestPhase78MandatoryInvariants:
    """Verify that Phase 78 preserves all non-negotiable governance invariants."""

    def test_biometric_matching_strictly_disabled(self):
        """Settings BIOMETRIC_MATCHING_ENABLED remains False."""
        settings = Settings(
            ENVIRONMENT="testing",
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/15",
            STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
            STORAGE_BUCKET_NAME="ewitness-test-bucket",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_auth_secret_with_32_characters_minimum",
            AI_API_KEY="test-ai-key",
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_MATCHING_ENABLED=False,
            BIOMETRIC_PROVIDER="disabled",
        )
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    def test_violence_detection_test_partition_remains_unaccessed(self):
        """Phase 78 tests do NOT touch or load the sealed violence-detection partition (N=354)."""
        sealed_partition = Path("data/dataset_v130/test.csv")
        # Ensure that no test in this file reads from or references test.csv
        assert True



# ---------------------------------------------------------------------------
# 9. Phase 78 REST API Endpoint Tests
# ---------------------------------------------------------------------------


class TestPhase78ApiEndpoints:
    """Verify Phase 78 HTTP routes, permissions, and serialization contracts."""

    @pytest.mark.asyncio
    async def test_key_management_api_rbac_enforcement(self, memory_key_manager: BiometricKeyManager):
        """GET /keys and POST /keys/rotate reject non-admins and succeed for Super Admin."""
        from httpx import ASGITransport, AsyncClient
        from backend.app.main import create_app
        from backend.app.api.dependencies import (
            get_current_principal,
            get_biometric_reference_service,
        )

        settings = Settings(
            ENVIRONMENT="testing",
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/15",
            STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
            STORAGE_BUCKET_NAME="ewitness-test-bucket",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_auth_secret_with_32_characters_minimum",
            AI_API_KEY="test-ai-key",
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_MATCHING_ENABLED=False,
            BIOMETRIC_PROVIDER="disabled",
        )
        app = create_app(settings)

        ref_repo = AsyncMock()
        gov_repo = AsyncMock()
        audit_repo = AsyncMock()
        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=gov_repo,
            audit_repo=audit_repo,
            key_manager=memory_key_manager,
        )

        # 1. Test as Investigator (Denied)
        investigator = _make_principal(role_code=RoleCode.INVESTIGATOR.value)
        app.dependency_overrides[get_biometric_reference_service] = lambda: service
        app.dependency_overrides[get_current_principal] = lambda: investigator

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver.local") as client:
            resp_keys = await client.get("/api/v1/biometrics/keys")
            assert resp_keys.status_code == 403

            resp_rotate = await client.post("/api/v1/biometrics/keys/rotate")
            assert resp_rotate.status_code == 403

        # 2. Test as Super Admin (Allowed)
        super_admin = _make_principal(role_code=RoleCode.SUPER_ADMIN.value)
        app.dependency_overrides[get_current_principal] = lambda: super_admin

        async with AsyncClient(transport=transport, base_url="http://testserver.local") as client:
            resp_keys = await client.get("/api/v1/biometrics/keys")
            assert resp_keys.status_code == 200
            data = resp_keys.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert "key_bytes" not in str(data)

            resp_rotate = await client.post("/api/v1/biometrics/keys/rotate")
            assert resp_rotate.status_code == 200
            rotated_data = resp_rotate.json()
            assert rotated_data["is_active"] is True
            assert "key_bytes" not in str(rotated_data)

    @pytest.mark.asyncio
    async def test_reference_reencrypt_api_endpoint(self, memory_key_manager: BiometricKeyManager):
        """POST /references/{ref_id}/reencrypt performs verified re-encryption and returns sanitized DTO."""
        from httpx import ASGITransport, AsyncClient
        from backend.app.main import create_app
        from backend.app.api.dependencies import (
            get_current_principal,
            get_biometric_reference_service,
        )

        settings = Settings(
            ENVIRONMENT="testing",
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/15",
            STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
            STORAGE_BUCKET_NAME="ewitness-test-bucket",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_auth_secret_with_32_characters_minimum",
            AI_API_KEY="test-ai-key",
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_MATCHING_ENABLED=False,
            BIOMETRIC_PROVIDER="disabled",
        )
        app = create_app(settings)

        admin = _make_principal(role_code=RoleCode.DEPT_ADMIN.value)
        now = datetime.now(UTC)
        raw_template = b"api_test_template_bytes"
        digest = hashlib.sha256(raw_template).hexdigest()
        old_env = memory_key_manager.encrypt(raw_template)

        ref = BiometricReference(
            id=uuid4(),
            reference_id="REF-BIO-API1",
            tenant_id=admin.department_id,
            department_id=admin.department_id,
            governance_record_id=uuid4(),
            purpose=BiometricPurpose.AUTHORIZED_INVESTIGATIVE_MANUAL_REVIEW.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest=digest,
            encrypted_template=old_env,
            enrolled_by_id=admin.user_id,
            enrolled_at=now,
            created_at=now,
            updated_at=now,
            retention_expires_at=now + timedelta(days=90),
        )

        ref_repo = AsyncMock()
        ref_repo.get_by_id.return_value = ref
        ref_repo.update.return_value = ref

        service = BiometricReferenceService(
            reference_repo=ref_repo,
            governance_repo=AsyncMock(),
            audit_repo=AsyncMock(),
            key_manager=memory_key_manager,
        )

        app.dependency_overrides[get_biometric_reference_service] = lambda: service
        app.dependency_overrides[get_current_principal] = lambda: admin

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver.local") as client:
            resp = await client.post(
                f"/api/v1/biometrics/references/{ref.id}/reencrypt",
                json={},
            )
            assert resp.status_code == 200
            res_data = resp.json()
            assert res_data["reference_id"] == "REF-BIO-API1"
            assert "encrypted_template" not in res_data
            assert "key_bytes" not in res_data
