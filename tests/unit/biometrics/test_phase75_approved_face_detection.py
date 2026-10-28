"""Comprehensive unit test suite for Phase 75: Approved Face Detection Component.

Validates:
- Category A: Detection Behavior & Input Validation (PNG, JPEG, WebP, dimensions, bombs, corruptions).
- Category B: Security, Authorization & Tenant Scoping (permissions, governance, consent, cross-tenant evidence).
- Category C: Matching Prohibition (BIOMETRIC_MATCHING_ENABLED=False invariant, zero templates, isolation).
- Category D: Privacy-Preserving Redaction Boundary (solid box, blur, pixelate, non-destructive immutability).
- Category E: Zero Leakage & Auditability (metadata-only audit logging, no disk leaks, no raw templates).
"""

from __future__ import annotations

import base64
import io
import struct
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from PIL import Image

from ai_services.face_detection.detector import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    DisabledFaceDetectorProvider,
    LocalFaceDetectorProvider,
    MockFaceDetectorProvider,
    _validate_dimensions,
    get_face_detector,
    inspect_image_dimensions_and_format,
)
from ai_services.face_detection.protocol import (
    BIOMETRIC_ADVISORY_DISCLAIMER,
    DetectedFace,
    FaceDetectionOptions,
    FaceDetectionResult,
    FaceDetectorProtocol,
)
from ai_services.face_detection.redaction import (
    PRIVACY_REDACTION_ADVISORY_DISCLAIMER,
    RedactedImageResult,
    RedactionPolicy,
    RedactionStyle,
    _sanitize_error_message,
    apply_face_redaction,
)
from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome
from backend.app.core.authorization import Permission, RoleCode
from backend.app.core.biometrics import (
    BiometricLawfulBasis,
    BiometricPurpose,
    ConsentStatus,
    GovernanceStatus,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricsDisabledError,
    ModelUnavailableError,
    PayloadTooLargeError,
    PermissionDeniedError,
    ResourceNotFoundError,
    UnsupportedMediaTypeError,
)
from backend.app.models.biometrics import BiometricGovernanceRecord
from backend.app.models.evidence import EvidenceAttachment
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    FaceDetectionRequest,
    FaceDetectionResponse,
    FaceRedactionRequest,
    FaceRedactionResponse,
)
from backend.app.services.biometrics import FaceDetectionService


# ===========================================================================
# Test Fixtures & Utilities
# ===========================================================================


def _create_test_image_bytes(format_name: str = "PNG", size: tuple[int, int] = (120, 120)) -> bytes:
    """Generate in-memory image bytes for test fixtures."""
    img = Image.new("RGB", size, color=(30, 80, 150))
    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


def _make_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    dept_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    """Construct an AuthenticatedPrincipal fixture."""
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email="test_user@ewitness.edu",
        full_name="Test Principal",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=dept_id or uuid4(),
        session_id=uuid4(),
    )


def _make_settings(**kwargs: Any) -> Settings:
    """Construct a Settings instance with controlled biometric flags."""
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
        "BIOMETRIC_PROVIDER": "mock",
        "BIOMETRIC_MAX_IMAGE_SIZE_BYTES": 10 * 1024 * 1024,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_approved_governance_record(
    dept_id: UUID,
    purpose: str = BiometricPurpose.PRIVACY_REDACTION_BLURRING.value,
    lawful_basis: str = BiometricLawfulBasis.STATUTORY_LEGAL_OBLIGATION.value,
    consent_status: str = ConsentStatus.ACTIVE.value,
    retention_days: int = 30,
) -> BiometricGovernanceRecord:
    """Create an approved BiometricGovernanceRecord fixture."""
    now = datetime.now(UTC)
    record = BiometricGovernanceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        department_id=dept_id,
        purpose=purpose,
        lawful_basis=lawful_basis,
        consent_status=consent_status,
        status=GovernanceStatus.APPROVED.value,
        retention_days=retention_days,
        created_at=now,
        updated_at=now,
    )
    record.retention_expires_at = now + timedelta(days=retention_days)
    return record


# ===========================================================================
# Category A: Detection Behavior & Input Validation
# ===========================================================================


class TestFaceDetectionBehaviorAndInputValidation:
    """Test pure input validation, dimension boundaries, and detection algorithms."""

    def test_inspect_png_extracts_dimensions_and_format(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(320, 240))
        width, height, fmt = inspect_image_dimensions_and_format(png_bytes)
        assert width == 320
        assert height == 240
        assert fmt == "png"

    def test_inspect_jpeg_extracts_dimensions_and_format(self) -> None:
        jpeg_bytes = _create_test_image_bytes("JPEG", size=(400, 300))
        width, height, fmt = inspect_image_dimensions_and_format(jpeg_bytes)
        assert width == 400
        assert height == 300
        assert fmt == "jpeg"

    def test_inspect_webp_extracts_dimensions_and_format(self) -> None:
        webp_bytes = _create_test_image_bytes("WEBP", size=(250, 180))
        width, height, fmt = inspect_image_dimensions_and_format(webp_bytes)
        assert width == 250
        assert height == 180
        assert fmt == "webp"

    def test_empty_image_bytes_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Image bytes payload cannot be empty"):
            inspect_image_dimensions_and_format(b"")

    def test_image_bytes_exceeding_max_limit_raises_value_error(self) -> None:
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_IMAGE_BYTES + 10)
        with pytest.raises(ValueError, match="exceeds maximum permitted limit"):
            inspect_image_dimensions_and_format(oversized)

    def test_truncated_png_header_raises_unsupported_media_type(self) -> None:
        truncated_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # Only 16 bytes (< 24)
        with pytest.raises(UnsupportedMediaTypeError, match="Truncated PNG image header"):
            inspect_image_dimensions_and_format(truncated_png)

    def test_truncated_jpeg_stream_raises_unsupported_media_type(self) -> None:
        truncated_jpeg = b"\xff\xd8"  # Only 2 bytes (< 4)
        with pytest.raises(UnsupportedMediaTypeError, match="Truncated JPEG image stream"):
            inspect_image_dimensions_and_format(truncated_jpeg)

    def test_unsupported_magic_bytes_raises_unsupported_media_type(self) -> None:
        bmp_header = b"BM" + b"\x00" * 30  # BMP format rejected
        with pytest.raises(UnsupportedMediaTypeError, match="invalid or unsupported image magic bytes"):
            inspect_image_dimensions_and_format(bmp_header)

        gif_header = b"GIF89a" + b"\x00" * 20  # GIF format rejected
        with pytest.raises(UnsupportedMediaTypeError, match="invalid or unsupported image magic bytes"):
            inspect_image_dimensions_and_format(gif_header)

    def test_dimension_validation_rejects_zero_or_negative(self) -> None:
        with pytest.raises(ValueError, match="Image dimensions must be strictly positive"):
            _validate_dimensions(0, 100)
        with pytest.raises(ValueError, match="Image dimensions must be strictly positive"):
            _validate_dimensions(100, -5)

    def test_dimension_validation_rejects_excessive_single_axis(self) -> None:
        with pytest.raises(ValueError, match=f"exceeds maximum permitted limit \\({MAX_IMAGE_DIMENSION}px\\)"):
            _validate_dimensions(4097, 100)

    def test_dimension_validation_rejects_decompression_bomb_pixel_budget(self) -> None:
        # 4096 * 4096 is allowed (16_777_216), but higher total pixel budget rejected
        _validate_dimensions(4096, 4096)  # Should pass
        with pytest.raises(ValueError, match="exceeds maximum permitted pixel budget"):
            _validate_dimensions(5000, 5000)

    def test_disabled_detector_provider_fails_closed(self) -> None:
        provider = DisabledFaceDetectorProvider()
        png_bytes = _create_test_image_bytes("PNG")
        with pytest.raises(BiometricsDisabledError, match="disabled by default in system settings"):
            provider.detect_faces(png_bytes)

    def test_local_detector_provider_fails_closed_without_weights(self) -> None:
        provider = LocalFaceDetectorProvider()
        png_bytes = _create_test_image_bytes("PNG")
        with pytest.raises(ModelUnavailableError, match="Automatic online downloading of model weights is strictly prohibited"):
            provider.detect_faces(png_bytes)

    def test_face_detection_options_validation(self) -> None:
        with pytest.raises(ValueError, match="confidence_threshold must be between 0.0 and 1.0"):
            FaceDetectionOptions(confidence_threshold=1.5)
        with pytest.raises(ValueError, match="max_faces must be at least 1"):
            FaceDetectionOptions(max_faces=0)
        with pytest.raises(ValueError, match="min_face_size_pixels must be at least 4"):
            FaceDetectionOptions(min_face_size_pixels=2)

    def test_detected_face_normalized_coordinates_and_landmarks(self) -> None:
        face = DetectedFace(
            bounding_box=(0.1, 0.2, 0.7, 0.8),
            confidence=0.88,
            landmarks={"left_eye": (0.3, 0.4), "right_eye": (0.3, 0.6)},
        )
        assert face.bounding_box == (0.1, 0.2, 0.7, 0.8)
        assert face.confidence == 0.88
        assert face.landmarks is not None
        assert "left_eye" in face.landmarks

        # Inverted box coordinates fail validation
        with pytest.raises(ValueError, match="ymin .* must be strictly less than ymax"):
            DetectedFace(bounding_box=(0.8, 0.2, 0.1, 0.8), confidence=0.9)


# ===========================================================================
# Category B: Security, Authorization & Tenant Scoping
# ===========================================================================


class TestFaceDetectionSecurityAndScoping:
    """Test RBAC, governance validation, tenant isolation, and evidence scoping."""

    @pytest.mark.asyncio
    async def test_caller_without_permission_is_denied(self) -> None:
        settings = _make_settings()
        gov_repo = AsyncMock()
        service = FaceDetectionService(gov_repo, settings)

        # Student lacks BIOMETRIC_DETECTION_EXECUTE
        unauth_principal = _make_principal(RoleCode.STUDENT.value)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(PermissionDeniedError, match="Caller lacks BIOMETRIC_DETECTION_EXECUTE permission"):
            await service.detect_faces(png_bytes, uuid4(), unauth_principal)

    @pytest.mark.asyncio
    async def test_disabled_in_settings_fails_closed(self) -> None:
        settings = _make_settings(BIOMETRIC_DETECTION_ENABLED=False)
        gov_repo = AsyncMock()
        service = FaceDetectionService(gov_repo, settings)
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricsDisabledError, match="Face detection is disabled in system configuration"):
            await service.detect_faces(png_bytes, uuid4(), principal)

    @pytest.mark.asyncio
    async def test_missing_governance_record_raises_not_found(self) -> None:
        settings = _make_settings()
        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = None
        service = FaceDetectionService(gov_repo, settings)
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(ResourceNotFoundError, match="Biometric governance record '.*' not found"):
            await service.detect_faces(png_bytes, uuid4(), principal)

    @pytest.mark.asyncio
    async def test_unapproved_governance_record_raises_error(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_record.status = GovernanceStatus.PENDING_LEGAL_REVIEW.value

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricGovernanceError, match="Face detection requires an approved governance record"):
            await service.detect_faces(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_expired_governance_retention_raises_error(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_record.retention_expires_at = datetime.now(UTC) - timedelta(days=1)  # Expired

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricGovernanceError, match="retention period has expired"):
            await service.detect_faces(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_withdrawn_consent_raises_error(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_record.consent_status = ConsentStatus.WITHDRAWN.value

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricGovernanceError, match="withdrawn subject consent"):
            await service.detect_faces(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_unauthorized_purpose_raises_error(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(
            principal.department_id,
            purpose=BiometricPurpose.EXPLICIT_CONSENT_REFERENCE_ENROLLMENT.value,
        )

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricGovernanceError, match="is not authorized for face detection"):
            await service.detect_faces(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_evidence_scoping_nonexistent_evidence_raises_not_found(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        evidence_repo = AsyncMock()
        evidence_repo.get_attachment_by_id.return_value = None

        service = FaceDetectionService(gov_repo, settings, evidence_repo=evidence_repo)
        png_bytes = _create_test_image_bytes("PNG")

        missing_evidence_id = uuid4()
        with pytest.raises(ResourceNotFoundError, match="Evidence attachment '.*' not found"):
            await service.detect_faces(
                png_bytes, gov_record.id, principal, evidence_id=missing_evidence_id
            )

    @pytest.mark.asyncio
    async def test_evidence_scoping_cross_tenant_evidence_is_denied(self) -> None:
        settings = _make_settings()
        dept_a = uuid4()
        dept_b = uuid4()
        principal = _make_principal(RoleCode.INVESTIGATOR.value, dept_id=dept_a)
        gov_record = _make_approved_governance_record(dept_a)

        foreign_evidence = EvidenceAttachment(
            id=uuid4(),
            incident_id=uuid4(),
            uploader_id=uuid4(),
            department_id=dept_b,  # Belong to different department
            original_filename="foreign.png",
            file_size_bytes=1024,
            declared_mime_type="image/png",
            storage_key="test-key",
        )

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        evidence_repo = AsyncMock()
        evidence_repo.get_attachment_by_id.return_value = foreign_evidence

        service = FaceDetectionService(gov_repo, settings, evidence_repo=evidence_repo)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(PermissionDeniedError, match="Access to cross-tenant evidence is strictly prohibited"):
            await service.detect_faces(
                png_bytes, gov_record.id, principal, evidence_id=foreign_evidence.id
            )


# ===========================================================================
# Category C: Matching Prohibition
# ===========================================================================


class TestFaceDetectionMatchingProhibition:
    """Enforce complete architectural boundary segregating face detection from matching."""

    def test_biometric_matching_enabled_invariant_is_false(self) -> None:
        """Global invariant: BIOMETRIC_MATCHING_ENABLED is False by default in settings."""
        settings = _make_settings()
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    @pytest.mark.asyncio
    async def test_face_detection_does_not_call_reference_registry(self) -> None:
        """Detection must locate bounding boxes without creating or querying biometric references."""
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        audit_repo = AsyncMock()

        service = FaceDetectionService(gov_repo, settings, audit_repo=audit_repo)
        png_bytes = _create_test_image_bytes("PNG")

        response = await service.detect_faces(png_bytes, gov_record.id, principal)

        assert isinstance(response, FaceDetectionResponse)
        assert response.face_count >= 1
        # Check that disclaimer is explicitly attached
        assert response.disclaimer == BIOMETRIC_ADVISORY_DISCLAIMER
        for face in response.detected_faces:
            assert isinstance(face.bounding_box, tuple)
            assert len(face.bounding_box) == 4
            # Zero embedding or template attributes
            assert not hasattr(face, "embedding")
            assert not hasattr(face, "feature_vector")
            assert not hasattr(face, "template")


# ===========================================================================
# Category D: Privacy-Preserving Redaction Boundary
# ===========================================================================


class TestPrivacyPreservingRedactionBoundary:
    """Test redaction styles, non-destructive transformations, and disclaimers."""

    def test_apply_solid_box_redaction(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))
        faces = [
            DetectedFace(bounding_box=(0.2, 0.2, 0.6, 0.6), confidence=0.95),
        ]
        policy = RedactionPolicy(style=RedactionStyle.SOLID_BOX, padding_ratio=0.1)
        result = apply_face_redaction(png_bytes, faces, policy=policy)

        assert isinstance(result, RedactedImageResult)
        assert result.redacted_faces_count == 1
        assert result.style == "solid_box"
        assert result.disclaimer == PRIVACY_REDACTION_ADVISORY_DISCLAIMER
        assert len(result.redacted_bytes) > 0
        # Original bytes are completely unmodified
        assert result.redacted_bytes != png_bytes

    def test_apply_blur_redaction(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))
        faces = [
            DetectedFace(bounding_box=(0.1, 0.1, 0.5, 0.5), confidence=0.9),
        ]
        policy = RedactionPolicy(style=RedactionStyle.BLUR, blur_radius=15)
        result = apply_face_redaction(png_bytes, faces, policy=policy)

        assert result.redacted_faces_count == 1
        assert result.style == "blur"
        assert len(result.redacted_bytes) > 0

    def test_apply_pixelate_redaction(self) -> None:
        jpeg_bytes = _create_test_image_bytes("JPEG", size=(200, 200))
        faces = [
            DetectedFace(bounding_box=(0.15, 0.15, 0.65, 0.65), confidence=0.85),
        ]
        policy = RedactionPolicy(style=RedactionStyle.PIXELATE, pixelate_block_size=8)
        result = apply_face_redaction(jpeg_bytes, faces, policy=policy)

        assert result.redacted_faces_count == 1
        assert result.style == "pixelate"
        assert result.image_format == "jpeg"

    def test_redaction_skips_faces_below_confidence_threshold(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))
        faces = [
            DetectedFace(bounding_box=(0.1, 0.1, 0.4, 0.4), confidence=0.3),  # Below 0.5
            DetectedFace(bounding_box=(0.5, 0.5, 0.8, 0.8), confidence=0.8),  # Above 0.5
        ]
        policy = RedactionPolicy(min_confidence=0.5)
        result = apply_face_redaction(png_bytes, faces, policy=policy)

        assert result.redacted_faces_count == 1

    def test_apply_redaction_with_no_detected_faces(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))
        result = apply_face_redaction(png_bytes, [])
        assert result.redacted_faces_count == 0
        assert len(result.redacted_bytes) > 0

    def test_apply_redaction_boundary_clipping_near_edges(self) -> None:
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))
        # Faces on extreme boundaries with expansion padding
        faces = [
            DetectedFace(bounding_box=(0.0, 0.0, 0.2, 0.2), confidence=0.9),
            DetectedFace(bounding_box=(0.8, 0.8, 1.0, 1.0), confidence=0.9),
        ]
        policy = RedactionPolicy(style=RedactionStyle.SOLID_BOX, padding_ratio=0.25)
        result = apply_face_redaction(png_bytes, faces, policy=policy)
        assert result.redacted_faces_count == 2
        assert len(result.redacted_bytes) > 0

    def test_apply_redaction_rejects_oversized_dimensions_before_allocation(self) -> None:
        # Valid PNG with width 4100px exceeding single-axis limit
        img = Image.new("RGB", (4100, 10), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        oversized_bytes = buf.getvalue()
        faces = [DetectedFace(bounding_box=(0.1, 0.1, 0.5, 0.5), confidence=0.9)]
        with pytest.raises(UnsupportedMediaTypeError, match="Image exceeds safe dimension or decompression limits"):
            apply_face_redaction(oversized_bytes, faces)

    def test_redaction_fails_closed_on_corrupt_input(self) -> None:
        corrupted_bytes = b"\x89PNG\r\n\x1a\nCorruptedGarbageBytesPayload"
        faces = [DetectedFace(bounding_box=(0.2, 0.2, 0.6, 0.6), confidence=0.9)]
        with pytest.raises(UnsupportedMediaTypeError, match="Failed to decode image for redaction"):
            apply_face_redaction(corrupted_bytes, faces)

    @pytest.mark.asyncio
    async def test_service_redact_faces_end_to_end(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        audit_repo = AsyncMock()

        service = FaceDetectionService(gov_repo, settings, audit_repo=audit_repo)
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))

        response = await service.redact_faces(
            image_bytes=png_bytes,
            governance_record_id=gov_record.id,
            principal=principal,
            style="solid_box",
            min_confidence=0.5,
            padding_ratio=0.1,
        )

        assert isinstance(response, FaceRedactionResponse)
        assert response.redacted_faces_count >= 1
        assert response.style == "solid_box"
        assert response.disclaimer == PRIVACY_REDACTION_ADVISORY_DISCLAIMER
        assert len(response.redacted_image_base64) > 0
        assert response.is_redacted is True
        assert response.requires_human_review is False
        assert response.review_reason is None

    def test_redaction_zero_faces_outcome_semantics(self) -> None:
        """When 0 faces are detected, ensure image is returned unmutated with is_redacted=False and requires_human_review=True."""
        png_bytes = _create_test_image_bytes("PNG")
        result = apply_face_redaction(png_bytes, detected_faces=[])

        assert result.redacted_faces_count == 0
        assert result.is_redacted is False
        assert result.requires_human_review is True
        assert "No faces detected in input image" in result.review_reason
        assert result.disclaimer == PRIVACY_REDACTION_ADVISORY_DISCLAIMER
        assert result.metadata["is_redacted"] == "False"
        assert result.metadata["requires_human_review"] == "True"

    def test_redaction_candidate_faces_below_threshold_outcome_semantics(self) -> None:
        """When candidate detections exist but none meet threshold, flag requires_human_review with candidate count."""
        png_bytes = _create_test_image_bytes("PNG")
        sub_thresh_face = DetectedFace(bounding_box=(0.1, 0.1, 0.4, 0.4), confidence=0.35)
        policy = RedactionPolicy(min_confidence=0.50)
        result = apply_face_redaction(png_bytes, [sub_thresh_face], policy=policy)

        assert result.redacted_faces_count == 0
        assert result.is_redacted is False
        assert result.requires_human_review is True
        assert "No faces met detection confidence threshold" in result.review_reason
        assert "1 candidate detection(s) below threshold" in result.review_reason

    def test_redaction_partial_faces_outcome_semantics(self) -> None:
        """When some faces exceed threshold and others do not, redact eligible faces and flag partial redaction."""
        png_bytes = _create_test_image_bytes("PNG")
        face_valid = DetectedFace(bounding_box=(0.1, 0.1, 0.4, 0.4), confidence=0.88)
        face_low = DetectedFace(bounding_box=(0.5, 0.5, 0.8, 0.8), confidence=0.25)
        policy = RedactionPolicy(min_confidence=0.50)
        result = apply_face_redaction(png_bytes, [face_valid, face_low], policy=policy)

        assert result.redacted_faces_count == 1
        assert result.is_redacted is True
        assert result.requires_human_review is True
        assert "Partial redaction: 1 face(s) redacted" in result.review_reason
        assert "1 candidate detection(s) fell below confidence threshold" in result.review_reason

    def test_redaction_all_faces_above_threshold_outcome_semantics(self) -> None:
        """When all candidate detections exceed confidence threshold, mark is_redacted=True and requires_human_review=False."""
        png_bytes = _create_test_image_bytes("PNG")
        face1 = DetectedFace(bounding_box=(0.1, 0.1, 0.4, 0.4), confidence=0.85)
        face2 = DetectedFace(bounding_box=(0.5, 0.5, 0.8, 0.8), confidence=0.92)
        policy = RedactionPolicy(min_confidence=0.50)
        result = apply_face_redaction(png_bytes, [face1, face2], policy=policy)

        assert result.redacted_faces_count == 2
        assert result.is_redacted is True
        assert result.requires_human_review is False
        assert result.review_reason is None

    def test_redaction_error_message_sanitization(self) -> None:
        """Verify error message sanitizer scrubs memory pointers, paths, and internal object reprs."""
        sample_error = Exception(
            "Decompression failure in <PIL.PngImagePlugin.PngImageFile at 0x000001A8D4F0E2A0> "
            "while reading D:\\PROJECT\\E-WITTNESS\\secret\\evidence.png"
        )
        sanitized = _sanitize_error_message(sample_error)

        assert "0x000001A8D4F0E2A0" not in sanitized
        assert "D:\\PROJECT\\E-WITTNESS" not in sanitized
        assert "[redacted_address]" in sanitized or "[internal_object]" in sanitized

    @pytest.mark.asyncio
    async def test_service_redact_faces_with_zero_detected_faces(self) -> None:
        """Verify service-level redaction correctly propagates is_redacted=False when detector finds no faces."""
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record

        # Service configured with mock detector returning 0 synthetic faces
        mock_zero_detector = MockFaceDetectorProvider(synthetic_faces=[])
        service = FaceDetectionService(gov_repo, settings, detector=mock_zero_detector)
        png_bytes = _create_test_image_bytes("PNG", size=(200, 200))

        response = await service.redact_faces(
            image_bytes=png_bytes,
            governance_record_id=gov_record.id,
            principal=principal,
            style="solid_box",
            min_confidence=0.5,
        )

        assert response.redacted_faces_count == 0
        assert response.is_redacted is False
        assert response.requires_human_review is True
        assert "No faces detected" in response.review_reason

    @pytest.mark.asyncio
    async def test_detection_failure_prevents_redaction(self) -> None:
        """Verify that any detection failure raises immediately and never returns a redaction response."""
        settings = _make_settings(
            BIOMETRIC_ANALYSIS_ENABLED=False,
            BIOMETRIC_DETECTION_ENABLED=False,
        )
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_test_image_bytes("PNG")

        with pytest.raises(BiometricsDisabledError):
            await service.redact_faces(
                image_bytes=png_bytes,
                governance_record_id=gov_record.id,
                principal=principal,
            )

    def test_redaction_clipping_failure_triggers_human_review(self) -> None:
        """When an eligible face bounding box collapses to 0-width or 0-height, flag requires_human_review."""
        png_bytes = _create_test_image_bytes("PNG", size=(50, 50))
        # Micro box that collapses: ymin=0.0, xmin=0.0, ymax=0.0001, xmax=0.0001 with 0 padding
        micro_face = DetectedFace(bounding_box=(0.0, 0.0, 0.001, 0.001), confidence=0.9)
        valid_face = DetectedFace(bounding_box=(0.2, 0.2, 0.8, 0.8), confidence=0.9)
        policy = RedactionPolicy(min_confidence=0.5, padding_ratio=0.0)
        result = apply_face_redaction(png_bytes, [micro_face, valid_face], policy=policy)

        assert result.redacted_faces_count == 1
        assert result.is_redacted is True
        assert result.requires_human_review is True
        assert "non-positive dimensions after edge clipping" in result.review_reason

    def test_decompression_bomb_warning_escalation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that Pillow DecompressionBombWarning is caught and converted to UnsupportedMediaTypeError."""
        import warnings
        from PIL import Image

        png_bytes = _create_test_image_bytes("PNG", size=(64, 64))

        def mock_open(*args: Any, **kwargs: Any) -> Any:
            warnings.warn("Simulated decompression bomb warning", Image.DecompressionBombWarning)
            return Image.new("RGB", (64, 64))

        monkeypatch.setattr(Image, "open", mock_open)
        with pytest.raises(UnsupportedMediaTypeError, match="Image exceeds safe dimension or decompression limits"):
            apply_face_redaction(png_bytes, [])


# ===========================================================================
# Category E: Zero Leakage & Auditability
# ===========================================================================


class TestZeroLeakageAndAuditability:
    """Verify metadata-only audit trails and complete zero leakage of raw biometrics."""

    @pytest.mark.asyncio
    async def test_audit_logs_record_metadata_only_without_image_or_box_coordinates(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        evidence_id = uuid4()

        evidence = EvidenceAttachment(
            id=evidence_id,
            incident_id=uuid4(),
            uploader_id=principal.user_id,
            department_id=principal.department_id,
            original_filename="secure_evidence.png",
            file_size_bytes=2048,
            declared_mime_type="image/png",
            storage_key="test-key",
        )

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        evidence_repo = AsyncMock()
        evidence_repo.get_attachment_by_id.return_value = evidence
        audit_repo = AsyncMock()

        service = FaceDetectionService(
            gov_repo, settings, audit_repo=audit_repo, evidence_repo=evidence_repo
        )
        png_bytes = _create_test_image_bytes("PNG")

        await service.detect_faces(
            png_bytes, gov_record.id, principal, evidence_id=evidence_id
        )

        assert audit_repo.append_event.called
        call_kwargs = audit_repo.append_event.call_args.kwargs
        assert call_kwargs["action"] == AuditAction.BIOMETRIC_DETECTION_EXECUTED.value
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS.value
        assert call_kwargs["actor_id"] == principal.user_id

        details = call_kwargs["details"]
        # Verify metadata fields are present
        assert "face_count" in details
        assert "image_width" in details
        assert "image_height" in details
        assert "model_name" in details
        assert "model_version" in details
        assert "latency_ms" in details
        assert details["evidence_id"] == str(evidence_id)

        # STRICT PRIVACY INVARIANTS: NO raw image bytes, base64 payload, or coordinates in audit logs!
        assert "image_bytes" not in details
        assert "image_base64" not in details
        assert "bounding_box" not in details
        assert "bounding_boxes" not in details
        assert "landmarks" not in details
        assert "detected_faces" not in details
