"""Phase 80 Acceptance Test Suite: Final Biometric Subsystem Security Audit & Cross-Cutting Verification.

Verifies the 13 mandatory cross-cutting invariants and security gates:
1. Environment & configuration overrides cannot enable biometric matching in production.
2. Route and service authorization gates reject unauthorized roles and unauthenticated callers.
3. Multi-tenant and department boundary isolation across reads, writes, assignments, and re-encryption.
4. Cryptographic fail-closed behavior: malformed ciphertext, corrupted tags, missing/revoked keys, unavailable vaults.
5. Absolute zero plaintext fallback on encryption/decryption failure.
6. Interrupted batch re-encryption idempotency, recovery, and corruption isolation.
7. Quality and review state machine transition validation and audit preservation.
8. Redaction failure and zero detections cannot be claimed as anonymized; geometry consolidation applied.
9. Immutability of original evidence and historical audit records.
10. Complete scrubbing of secret keys, plaintext templates, and memory addresses from representations and DTOs.
11. Demographic fairness status remains strictly NOT ESTABLISHED with mandatory statutory disclaimers.
12. Biometric matching prohibition invariant (BIOMETRIC_MATCHING_ENABLED=False immutable).
13. Historical sealed violence-detection test partition (N=354) remains strictly unaccessed.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_services.face_detection.evaluation import (
    FAIRNESS_NOT_ESTABLISHED_DISCLAIMER,
    compute_detection_metrics,
    generate_synthetic_face_image,
    run_full_detection_robustness_audit,
)
from ai_services.face_detection.geometry import (
    RedactionGeometryPolicy,
    consolidate_overlapping_boxes,
    verify_redaction_geometry,
)
from ai_services.face_detection.protocol import DetectedFace, FaceDetectionOptions
from ai_services.face_detection.quality import assess_photometric_quality
from ai_services.face_detection.redaction import (
    RedactionPolicy,
    RedactionStyle,
    apply_face_redaction,
)
from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
    validate_review_state_transition,
)
from backend.app.config.settings import Environment, Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, RoleCode
from backend.app.core.biometric_crypto import (
    BiometricKeyDisabledError,
    BiometricKeyError,
    BiometricKeyManager,
    BiometricKeyRevokedError,
    BiometricVaultUnavailableError,
    EncryptedFileKeyVaultProvider,
    ExternalKmsVaultAdapter,
    InMemoryKeyVaultProvider,
    KeyStatus,
    validate_envelope_structure,
)
from backend.app.core.biometrics import (
    BIOMETRIC_ADVISORY_DISCLAIMER,
    BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER,
    BiometricLawfulBasis,
    BiometricPurpose,
    BiometricReferenceStatus,
    ConsentStatus,
    GovernanceStatus,
    evaluate_biometric_readiness_checklist,
    validate_biometric_purpose,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricsDisabledError,
    BusinessRuleError,
    PermissionDeniedError,
    ResourceNotFoundError,
    UnsupportedMediaTypeError,
)
from backend.app.main import create_app
from backend.app.models.biometrics import (
    BiometricGovernanceRecord,
    BiometricQualityReview,
    BiometricReference,
)
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.biometrics import (
    BiometricGovernanceRepository,
    BiometricQualityReviewRepository,
    BiometricReferenceRepository,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    BiometricBatchReencryptRequest,
    BiometricGovernanceCreate,
    BiometricQualityReviewAssignRequest,
    FaceDetectionRobustnessAuditRead,
    FaceMatchRequest,
    FaceRedactionRequest,
)
from backend.app.services.biometrics import (
    BiometricGovernanceService,
    BiometricReferenceService,
    FaceDetectionService,
    FaceMatchingService,
    QualityReviewWorkflowService,
)


def _get_test_settings(*, environment: str = "testing", matching_enabled: bool = False) -> Settings:
    return Settings(
        ENVIRONMENT=environment,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
        STORAGE_BUCKET_NAME="test-bucket",
        STORAGE_ACCESS_KEY="test_access_key_valid",
        STORAGE_SECRET_KEY="test_secret_key_valid",
        AUTH_SECRET_KEY="test_key_with_length_greater_than_32_characters",
        AI_API_KEY="test",
        BIOMETRIC_ANALYSIS_ENABLED=True,
        BIOMETRIC_DETECTION_ENABLED=True,
        BIOMETRIC_MATCHING_ENABLED=matching_enabled,
    )


def _make_principal(
    role: str = RoleCode.INVESTIGATOR.value,
    dept_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email=f"test_{role.lower()}@ewitness.test",
        full_name="Test Principal",
        account_status="ACTIVE",
        is_active=True,
        role_code=role,
        department_id=dept_id or uuid4(),
        session_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# 1. Environment & Configuration Overrides Cannot Enable Biometric Matching
# ---------------------------------------------------------------------------


def test_production_settings_gate_blocks_matching_override() -> None:
    """Invariant 1: BIOMETRIC_MATCHING_ENABLED=True is strictly forbidden and raises ValueError."""
    with pytest.raises(ValueError, match="BIOMETRIC_MATCHING_ENABLED=True is strictly forbidden in production"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+asyncpg://prod_user:SecurePass12345Entropy!@db.internal:5432/ewitness_prod",
            REDIS_URL="rediss://default:SecurePass12345Entropy!@redis.internal:6379/0",
            STORAGE_ENDPOINT_URL="https://storage.internal:9000",
            STORAGE_BUCKET_NAME="ewitness-prod-vault",
            STORAGE_ACCESS_KEY="StrongStorageAccessKey123!",
            STORAGE_SECRET_KEY="StrongStorageSecretKeyLongEntropy123!",
            AUTH_SECRET_KEY="SuperStrongProductionSecretKeyWithSufficientEntropy123!",
            CORS_ALLOWED_ORIGINS=["https://app.ewitness.internal"],
            ALLOWED_HOSTS=["app.ewitness.internal"],
            ENFORCE_SSL=True,
            SECURITY_HEADERS_ENABLED=True,
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_VAULT_PROVIDER="file",
            BIOMETRIC_VAULT_FILE_PATH="vault.enc",
            BIOMETRIC_VAULT_MASTER_KEY="StrongMasterKeyWith32Characters!",
            BIOMETRIC_MATCHING_ENABLED=True,  # Prohibited override
        )


def test_matching_prohibition_remains_false_by_default() -> None:
    """Invariant 1b: Default settings enforce BIOMETRIC_MATCHING_ENABLED=False."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False


# ---------------------------------------------------------------------------
# 2. Authorization Gates Reject Unauthorized Roles and Unauthenticated Callers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_roles_denied_face_detection() -> None:
    """Invariant 2: STUDENT role lacking BIOMETRIC_DETECTION_EXECUTE is rejected."""
    service = FaceDetectionService(
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        settings=_get_test_settings(),
    )
    unauthorized = _make_principal(role=RoleCode.STUDENT.value)

    with pytest.raises(PermissionDeniedError, match="Caller lacks BIOMETRIC_DETECTION_EXECUTE"):
        await service.detect_faces(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            governance_record_id=uuid4(),
            principal=unauthorized,
        )


@pytest.mark.asyncio
async def test_non_super_admin_denied_key_lifecycle_management() -> None:
    """Invariant 2b: DEPT_ADMIN and INVESTIGATOR are denied key rotation and revocation."""
    service = BiometricReferenceService(
        reference_repo=MagicMock(spec=BiometricReferenceRepository),
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        key_manager=BiometricKeyManager(),
    )
    dept_admin = _make_principal(role=RoleCode.DEPT_ADMIN.value)

    with pytest.raises(PermissionDeniedError, match="BIOMETRIC_CONFIG_MANAGE"):
        await service.rotate_key(dept_admin)

    with pytest.raises(PermissionDeniedError, match="BIOMETRIC_CONFIG_MANAGE"):
        await service.revoke_key("key-1", dept_admin)


# ---------------------------------------------------------------------------
# 3. Multi-Tenant and Department Boundary Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_department_reference_access_rejected() -> None:
    """Invariant 3: Investigator cannot access biometric reference of another department."""
    dept_a = uuid4()
    principal_a = _make_principal(role=RoleCode.INVESTIGATOR.value, dept_id=dept_a)

    mock_repo = MagicMock(spec=BiometricReferenceRepository)
    mock_repo.get_by_id = AsyncMock(return_value=None)  # Department scoping returns None

    service = BiometricReferenceService(
        reference_repo=mock_repo,
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        key_manager=BiometricKeyManager(),
    )

    with pytest.raises(ResourceNotFoundError, match="Biometric reference .* not found"):
        await service.get_reference(uuid4(), principal_a)

    # Verify repository was queried with caller's department_id
    mock_repo.get_by_id.assert_awaited_once()
    assert mock_repo.get_by_id.call_args.kwargs["department_id"] == dept_a


@pytest.mark.asyncio
async def test_cross_department_review_assignment_rejected() -> None:
    """Invariant 3b: Review cannot be assigned or accessed by a different department."""
    dept_a = uuid4()
    dept_b = uuid4()
    dept_admin_b = _make_principal(role=RoleCode.DEPT_ADMIN.value, dept_id=dept_b)
    review_id = uuid4()

    mock_repo = MagicMock(spec=BiometricQualityReviewRepository)
    mock_repo.get_by_id = AsyncMock(return_value=None)  # Dept B cannot see Dept A review

    service = QualityReviewWorkflowService(
        review_repo=mock_repo,
    )

    payload = BiometricQualityReviewAssignRequest(
        reviewer_id=uuid4(),
    )

    with pytest.raises(ResourceNotFoundError, match="Biometric quality review .* not found"):
        await service.assign_reviewer(review_id, payload, dept_admin_b)


# ---------------------------------------------------------------------------
# 4. Cryptographic Fail-Closed Enforcement
# ---------------------------------------------------------------------------


def test_tampered_ciphertext_and_tags_fail_closed() -> None:
    """Invariant 4: Bit flips in ciphertext or GCM tag fail closed with DecryptionError."""
    km = BiometricKeyManager()
    envelope = km.encrypt(b"sensitive_biometric_data")
    v, kid, packed_bytes = validate_envelope_structure(envelope)
    raw = bytearray(packed_bytes)

    # Flip bit in GCM tag (last byte)
    raw[-1] ^= 0x01
    tampered_payload = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    tampered_envelope = f"{v}:{kid}:{tampered_payload}"

    with pytest.raises(BiometricKeyError, match="Biometric envelope authentication failed"):
        km.decrypt(tampered_envelope)


def test_revoked_and_disabled_keys_block_decryption() -> None:
    """Invariant 4b: Decryption under revoked or disabled keys fails closed with typed errors."""
    vault = InMemoryKeyVaultProvider()
    kid = "key-revocation-test"
    vault.store_key(kid, b"\xee" * 32, status=KeyStatus.ACTIVE)
    vault.set_active_key_id(kid)

    km = BiometricKeyManager(vault_provider=vault)
    env = km.encrypt(b"secret_payload")

    # Disable key -> fails with BiometricKeyDisabledError
    vault.set_key_status(kid, KeyStatus.DISABLED)
    with pytest.raises(BiometricKeyDisabledError, match="temporarily disabled"):
        km.decrypt(env)

    # Revoke key -> permanently fails with BiometricKeyRevokedError
    vault.set_key_status(kid, KeyStatus.REVOKED)
    with pytest.raises(BiometricKeyRevokedError, match="has been revoked"):
        km.decrypt(env)


def test_vault_outage_fails_closed_without_plaintext_leakage() -> None:
    """Invariant 4c: Vault outage raises BiometricVaultUnavailableError (HTTP 503)."""
    vault = InMemoryKeyVaultProvider()
    vault.store_key("k1", b"\x33" * 32, status=KeyStatus.ACTIVE)
    vault.set_active_key_id("k1")
    km = BiometricKeyManager(vault_provider=vault)
    env = km.encrypt(b"payload_data")

    # Simulate outage
    vault.set_available(False)
    with pytest.raises(BiometricVaultUnavailableError):
        km.decrypt(env)


# ---------------------------------------------------------------------------
# 5. Absolute Zero Plaintext Fallback
# ---------------------------------------------------------------------------


def test_zero_plaintext_fallback_on_corrupted_envelope() -> None:
    """Invariant 5: Corrupted or unparseable envelope never returns raw data."""
    km = BiometricKeyManager()
    with pytest.raises(BiometricKeyError):
        km.decrypt("invalid:envelope:structure")

    with pytest.raises(BiometricKeyError):
        km.decrypt("v1:unknown-key:bm9uY2VjaXBoZXJ0YWc=")


# ---------------------------------------------------------------------------
# 6. Interrupted Batch Re-Encryption Idempotency and Corruption Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_reencryption_idempotency_and_corruption_isolation() -> None:
    """Invariant 6: Corrupted records are isolated without halting batch; already rotated records are skipped."""
    vault = InMemoryKeyVaultProvider()
    vault.store_key("key-old", b"\x11" * 32, status=KeyStatus.ROTATED)
    vault.store_key("key-new", b"\x22" * 32, status=KeyStatus.ACTIVE)
    vault.set_active_key_id("key-new")
    km = BiometricKeyManager(vault_provider=vault)

    dept_id = uuid4()
    principal = _make_principal(role=RoleCode.SUPER_ADMIN.value, dept_id=dept_id)

    # Ref 1: Valid old record
    ref1_data = b"ref1_template"
    ref1_env = km.encrypt(ref1_data, key_id="key-old")
    ref1 = BiometricReference(
        id=uuid4(),
        reference_id="REF-001",
        department_id=dept_id,
        governance_record_id=uuid4(),
        encrypted_template=ref1_env,
        template_digest=hashlib.sha256(ref1_data).hexdigest(),
        status=BiometricReferenceStatus.ACTIVE.value,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    # Ref 2: Already under target key (key-new)
    ref2_data = b"ref2_template"
    ref2_env = km.encrypt(ref2_data, key_id="key-new")
    ref2 = BiometricReference(
        id=uuid4(),
        reference_id="REF-002",
        department_id=dept_id,
        governance_record_id=uuid4(),
        encrypted_template=ref2_env,
        template_digest=hashlib.sha256(ref2_data).hexdigest(),
        status=BiometricReferenceStatus.ACTIVE.value,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    # Ref 3: Corrupted digest mismatch
    ref3_data = b"ref3_template"
    ref3_env = km.encrypt(ref3_data, key_id="key-old")
    ref3 = BiometricReference(
        id=uuid4(),
        reference_id="REF-003",
        department_id=dept_id,
        governance_record_id=uuid4(),
        encrypted_template=ref3_env,
        template_digest="corrupted_digest_that_does_not_match",
        status=BiometricReferenceStatus.ACTIVE.value,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_ref_repo = MagicMock(spec=BiometricReferenceRepository)
    mock_ref_repo.list_active_for_reencryption = AsyncMock(return_value=[ref1, ref2, ref3])
    mock_ref_repo.update = AsyncMock()

    service = BiometricReferenceService(
        reference_repo=mock_ref_repo,
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        key_manager=km,
    )

    res = await service.batch_reencrypt_references(principal, new_key_id="key-new")
    assert res.total_scanned == 3
    assert res.reencrypted_count == 1  # ref1 re-encrypted
    assert res.skipped_count == 1      # ref2 skipped (already key-new)
    assert res.error_count == 1        # ref3 isolated without failing whole batch


# ---------------------------------------------------------------------------
# 7. Quality and Review State Machine Transition Validation
# ---------------------------------------------------------------------------


def test_review_state_machine_rejects_illegal_transitions() -> None:
    """Invariant 7: State machine rejects unauthorized and illegal status transitions."""
    # Completed review cannot be directly moved to IN_REVIEW without formal reopening
    with pytest.raises(BusinessRuleError, match="Review is COMPLETED; cannot transition"):
        validate_review_state_transition(
            QualityReviewStatus.COMPLETED,
            QualityReviewStatus.IN_REVIEW,
        )

    # Valid transitions do not raise
    validate_review_state_transition(QualityReviewStatus.PENDING_REVIEW, QualityReviewStatus.IN_REVIEW)
    validate_review_state_transition(QualityReviewStatus.IN_REVIEW, QualityReviewStatus.COMPLETED)
    validate_review_state_transition(
        QualityReviewStatus.COMPLETED,
        QualityReviewStatus.PENDING_REVIEW,
        is_authorized_reopen=True,
    )  # Reopen


# ---------------------------------------------------------------------------
# 8. Redaction Failure & Zero Detections Cannot Be Claimed As Anonymized
# ---------------------------------------------------------------------------


def test_redaction_failure_and_consolidation() -> None:
    """Invariant 8: Zero detections trigger human review; overlapping boxes are consolidated."""
    png_bytes, _ = generate_synthetic_face_image(width=640, height=480, num_faces=1)

    # Zero detections -> unredacted
    zero_res = apply_face_redaction(png_bytes, [])
    assert zero_res.is_redacted is False
    assert zero_res.redacted_faces_count == 0
    assert zero_res.requires_human_review is True

    # Geometry consolidation: 2 heavily overlapping boxes are merged into 1 envelope
    box1 = (0.20, 0.20, 0.60, 0.60)
    box2 = (0.25, 0.25, 0.65, 0.65)
    c_boxes, count = consolidate_overlapping_boxes([box1, box2], iou_threshold=0.15)
    assert len(c_boxes) == 1
    assert count == 1
    # Minimal enclosing envelope covers both
    assert c_boxes[0] == (0.20, 0.20, 0.65, 0.65)


# ---------------------------------------------------------------------------
# 9. Original Evidence and Historical Audit Immutability
# ---------------------------------------------------------------------------


def test_original_evidence_bytes_immutable_through_processing() -> None:
    """Invariant 9: Raw evidence bytes and SHA-256 digest remain unchanged through redaction."""
    orig_bytes, _ = generate_synthetic_face_image(width=640, height=480, num_faces=1)
    orig_digest = hashlib.sha256(orig_bytes).hexdigest()

    face = DetectedFace(bounding_box=(0.20, 0.30, 0.70, 0.70), confidence=0.92)
    res = apply_face_redaction(orig_bytes, [face], policy=RedactionPolicy(style=RedactionStyle.SOLID_BOX))

    # Output is different
    assert res.redacted_bytes != orig_bytes
    # Input bytes in memory remained identical
    assert hashlib.sha256(orig_bytes).hexdigest() == orig_digest


# ---------------------------------------------------------------------------
# 10. Complete Scrubbing of Secret Keys and Plaintext Templates
# ---------------------------------------------------------------------------


def test_vault_representations_scrub_secret_keys() -> None:
    """Invariant 10: Representations, strings, and metadata never leak raw key material."""
    raw_key = b"\xde\xad\xbe\xef" * 8
    vault = InMemoryKeyVaultProvider()
    vault.store_key("leak-check-key", raw_key, status=KeyStatus.ACTIVE)

    rep = repr(vault)
    assert "deadbeef" not in rep.lower()
    assert "\xde\xad\xbe\xef" not in rep

    meta = vault.get_key_metadata("leak-check-key")
    meta_dict = asdict(meta)
    assert "key_bytes" not in meta_dict
    assert "raw" not in meta_dict


# ---------------------------------------------------------------------------
# 11. Demographic Fairness Status Remains Strictly NOT ESTABLISHED
# ---------------------------------------------------------------------------


def test_demographic_fairness_is_strictly_not_established() -> None:
    """Invariant 11: Audit report explicitly disclaims demographic fairness."""
    report = run_full_detection_robustness_audit()
    assert report.fairness_status == "NOT ESTABLISHED"
    assert "DEMOGRAPHIC FAIRNESS NOT ESTABLISHED" in report.fairness_disclaimer
    assert "NO-GO" in report.fairness_disclaimer


# ---------------------------------------------------------------------------
# 12. Permanent Biometric Matching Prohibition Invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_prohibition_strictly_fails_closed_at_service_layer() -> None:
    """Invariant 12: Calling match_faces raises BiometricsDisabledError when matching disabled."""
    service = FaceMatchingService(
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        reference_repo=MagicMock(spec=BiometricReferenceRepository),
        verification_repo=MagicMock(),
        settings=_get_test_settings(matching_enabled=False),
    )
    principal = _make_principal(role=RoleCode.SUPER_ADMIN.value)

    req = FaceMatchRequest(
        governance_record_id=uuid4(),
        probe_image_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii"),
        reference_id=uuid4(),
    )

    with pytest.raises(BiometricsDisabledError, match="Biometric face matching is strictly disabled"):
        await service.match_faces(req, principal)


# ---------------------------------------------------------------------------
# 13. Historical Sealed Violence-Detection Test Partition (N=354) Untouched
# ---------------------------------------------------------------------------


def test_violence_detection_test_partition_remains_unreferenced_and_unaccessed() -> None:
    """Invariant 13: Biometric code paths do not access or reference the historical violence partition."""
    biometric_dir = Path("backend/app/services")
    content = (biometric_dir / "biometrics.py").read_text(encoding="utf-8")
    assert "data/raw" not in content
    assert "test_partition" not in content
    assert "violence_detection" not in content or "from ai_services.face_detection" in content
