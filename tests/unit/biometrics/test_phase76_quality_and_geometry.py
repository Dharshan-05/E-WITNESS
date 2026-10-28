"""Comprehensive unit test suite for Phase 76: Non-Biometric Evidence Quality & Redaction Geometry.

Validates:
- Category A: Photometric Evidence Quality Assessment (sharpness, exposure, contrast, clipping, normalization, finite guarantees).
- Category B: Quality Failure Modes & Decompression Bomb Protection (empty, malformed, decompression bombs, warning escalation).
- Category C: Redaction Geometry Verification (boundaries, ordering, edge clipping, aspect ratio heuristics, duplicate detection).
- Category D: Overlap Analysis & Unified Envelope Consolidation (IoU calculation, union envelopes, no shrinking).
- Category E: Landmark Coverage Verification (within padded box, outside box, non-finite / invalid landmark coordinates).
- Category F: Service Integration & Security Scoping (governance validation, permissions, tenant scoping, audit logging).
- Category G: Mandatory Invariants (BIOMETRIC_MATCHING_ENABLED=False, zero embeddings, test partition isolation).
"""

from __future__ import annotations

import base64
import io
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import numpy as np
from PIL import Image, ImageFilter
import pytest

from ai_services.face_detection.detector import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    _validate_dimensions,
)
from ai_services.face_detection.geometry import (
    REDACTION_GEOMETRY_ADVISORY_DISCLAIMER,
    RedactionGeometryPolicy,
    RedactionGeometryVerificationResult,
    compute_box_iou,
    consolidate_overlapping_boxes,
    verify_redaction_geometry,
)
from ai_services.face_detection.protocol import DetectedFace
from ai_services.face_detection.quality import (
    PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER,
    PhotometricQualityResult,
    PhotometricQualityStatus,
    PhotometricQualityThresholds,
    assess_photometric_quality,
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
    PayloadTooLargeError,
    PermissionDeniedError,
    ResourceNotFoundError,
    UnsupportedMediaTypeError,
)
from backend.app.models.biometrics import BiometricGovernanceRecord
from backend.app.models.evidence import EvidenceAttachment
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    DetectedFaceRead,
    PhotometricQualityRequest,
    PhotometricQualityResponse,
    RedactionGeometryRequest,
    RedactionGeometryResponse,
)
from backend.app.services.biometrics import FaceDetectionService


# ===========================================================================
# Synthetic Fixtures & Helpers
# ===========================================================================


def _create_synthetic_image(
    size: tuple[int, int] = (200, 200),
    pattern: str = "sharp_checkerboard",
    format_name: str = "PNG",
) -> bytes:
    """Generate deterministic synthetic image bytes for testing."""
    w, h = size
    buf = io.BytesIO()

    if pattern == "uniform_gray":
        arr = np.full((h, w), 128, dtype=np.uint8)
        img = Image.fromarray(arr, mode="L")
    elif pattern == "pure_black":
        arr = np.zeros((h, w), dtype=np.uint8)
        img = Image.fromarray(arr, mode="L")
    elif pattern == "pure_white":
        arr = np.full((h, w), 255, dtype=np.uint8)
        img = Image.fromarray(arr, mode="L")
    elif pattern == "severely_blurred":
        # Create checkerboard and blur it heavily
        checker = (np.indices((h, w)).sum(axis=0) % 2) * 255
        base = Image.fromarray(checker.astype(np.uint8), mode="L")
        img = base.filter(ImageFilter.GaussianBlur(radius=15))
    elif pattern == "sharp_checkerboard":
        # Block size 16 checkerboard: high contrast, high sharpness
        block_size = 16
        y, x = np.indices((h, w))
        checker = (((y // block_size) + (x // block_size)) % 2) * 255
        img = Image.fromarray(checker.astype(np.uint8), mode="L")
    elif pattern == "extreme_clipping":
        # Half 0 and half 255
        arr = np.zeros((h, w), dtype=np.uint8)
        arr[:, w // 2 :] = 255
        img = Image.fromarray(arr, mode="L")
    elif pattern == "high_contrast_natural":
        # Gradient with textured stripes
        x = np.linspace(0, 255, w, dtype=np.uint8)
        arr = np.tile(x, (h, 1))
        img = Image.fromarray(arr, mode="L")
    elif pattern == "well_exposed_textured":
        # Natural sharp scene: step stripe pattern between 40 and 200 without pixel clipping
        y, x = np.indices((h, w))
        stripe = ((x // 4) % 2) * 160 + 40
        img = Image.fromarray(stripe.astype(np.uint8), mode="L")
    else:
        img = Image.new("RGB", size, color=(100, 150, 200))

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
        email="auditor_test@ewitness.edu",
        full_name="Quality Auditor",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=dept_id or uuid4(),
        session_id=uuid4(),
    )


def _make_settings(**kwargs: Any) -> Settings:
    """Construct Settings with controlled biometric flags."""
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


def _make_approved_governance_record(dept_id: UUID) -> BiometricGovernanceRecord:
    """Create an approved BiometricGovernanceRecord fixture."""
    now = datetime.now(UTC)
    record = BiometricGovernanceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        department_id=dept_id,
        purpose=BiometricPurpose.PRIVACY_REDACTION_BLURRING.value,
        lawful_basis=BiometricLawfulBasis.STATUTORY_LEGAL_OBLIGATION.value,
        consent_status=ConsentStatus.ACTIVE.value,
        policy_version="1.0.0",
        notice_version="1.0.0",
        status=GovernanceStatus.APPROVED.value,
        approved_by_id=uuid4(),
        approved_at=now - timedelta(days=1),
        retention_days=30,
        retention_expires_at=now + timedelta(days=29),
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    return record


# ===========================================================================
# Category A: Photometric Evidence Quality Assessment
# ===========================================================================


class TestPhotometricQualityAssessment:
    """Verify non-identifying photometric quality measurements and normalization."""

    def test_sharp_image_yields_high_sharpness_and_acceptable_status(self) -> None:
        image_bytes = _create_synthetic_image(size=(128, 128), pattern="well_exposed_textured")
        result = assess_photometric_quality(image_bytes)

        assert isinstance(result, PhotometricQualityResult)
        assert result.image_width == 128
        assert result.image_height == 128
        assert result.sharpness_score > 0.15
        assert result.raw_metrics["raw_laplacian_variance"] > 100.0
        assert result.quality_status == PhotometricQualityStatus.ACCEPTABLE
        assert result.requires_human_review is False
        assert len(result.review_reasons) == 0
        assert result.disclaimer == PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER

    def test_blurred_image_triggers_low_sharpness_review(self) -> None:
        image_bytes = _create_synthetic_image(size=(128, 128), pattern="severely_blurred")
        result = assess_photometric_quality(image_bytes)

        assert result.raw_metrics["raw_laplacian_variance"] < 100.0
        assert result.sharpness_score < 0.20
        assert result.requires_human_review is True
        assert any("Low sharpness / high blur" in r for r in result.review_reasons)
        assert result.quality_status in (PhotometricQualityStatus.DEGRADED, PhotometricQualityStatus.REJECTED)

    def test_pure_black_image_triggers_severe_underexposure_and_clipping(self) -> None:
        image_bytes = _create_synthetic_image(size=(100, 100), pattern="pure_black")
        result = assess_photometric_quality(image_bytes)

        assert result.underexposed_fraction == 1.0
        assert result.clipped_fraction == 1.0
        assert result.exposure_score == 0.0
        assert result.contrast_score == 0.0
        assert result.requires_human_review is True
        assert result.quality_status == PhotometricQualityStatus.REJECTED
        assert any("Excessive underexposure" in r for r in result.review_reasons)
        assert any("Severe pixel clipping" in r for r in result.review_reasons)

    def test_pure_white_image_triggers_severe_overexposure_and_clipping(self) -> None:
        image_bytes = _create_synthetic_image(size=(100, 100), pattern="pure_white")
        result = assess_photometric_quality(image_bytes)

        assert result.overexposed_fraction == 1.0
        assert result.clipped_fraction == 1.0
        assert result.exposure_score == 0.0
        assert result.contrast_score == 0.0
        assert result.requires_human_review is True
        assert result.quality_status == PhotometricQualityStatus.REJECTED
        assert any("Excessive overexposure" in r for r in result.review_reasons)

    def test_uniform_gray_image_triggers_low_contrast_and_zero_sharpness(self) -> None:
        image_bytes = _create_synthetic_image(size=(100, 100), pattern="uniform_gray")
        result = assess_photometric_quality(image_bytes)

        assert result.raw_metrics["raw_laplacian_variance"] == 0.0
        assert result.sharpness_score == 0.0
        assert result.contrast_score == 0.0
        assert result.requires_human_review is True
        assert any("Low dynamic range / flat contrast" in r for r in result.review_reasons)

    def test_all_normalized_scores_are_finite_and_bounded_in_unit_interval(self) -> None:
        patterns = ["sharp_checkerboard", "severely_blurred", "pure_black", "pure_white", "uniform_gray", "high_contrast_natural"]
        for pat in patterns:
            data = _create_synthetic_image(size=(64, 64), pattern=pat)
            res = assess_photometric_quality(data)
            for score in [res.sharpness_score, res.exposure_score, res.contrast_score, res.underexposed_fraction, res.overexposed_fraction, res.clipped_fraction]:
                assert math.isfinite(score)
                assert 0.0 <= score <= 1.0

    def test_deterministic_output_for_identical_inputs(self) -> None:
        img_bytes = _create_synthetic_image(size=(120, 120), pattern="high_contrast_natural")
        res1 = assess_photometric_quality(img_bytes)
        res2 = assess_photometric_quality(img_bytes)

        assert res1.sharpness_score == res2.sharpness_score
        assert res1.exposure_score == res2.exposure_score
        assert res1.contrast_score == res2.contrast_score
        assert res1.raw_metrics == res2.raw_metrics
        assert res1.review_reasons == res2.review_reasons


# ===========================================================================
# Category B: Quality Failure Modes & Decompression Bomb Protection
# ===========================================================================


class TestPhotometricQualityFailureModes:
    """Verify fail-closed error handling and resource boundaries."""

    def test_empty_image_payload_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Image bytes payload cannot be empty"):
            assess_photometric_quality(b"")

    def test_oversized_payload_raises_value_error(self) -> None:
        huge_payload = b"0" * (MAX_IMAGE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum permitted limit"):
            assess_photometric_quality(huge_payload)

    def test_unsupported_image_format_raises_unsupported_media_type(self) -> None:
        text_payload = b"Plain text file that is not an image at all."
        with pytest.raises(UnsupportedMediaTypeError, match="invalid or unsupported image magic bytes"):
            assess_photometric_quality(text_payload)

    def test_corrupt_png_header_raises_unsupported_media_type(self) -> None:
        corrupt_png = b"\x89PNG\r\n\x1a\n" + b"CorruptGarbageData"
        with pytest.raises(UnsupportedMediaTypeError):
            assess_photometric_quality(corrupt_png)

    def test_oversized_dimensions_rejected_before_raster_allocation(self) -> None:
        # 4097 x 10 image (exceeds MAX_IMAGE_DIMENSION of 4096)
        img = Image.new("RGB", (4097, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        oversized_bytes = buf.getvalue()

        with pytest.raises(UnsupportedMediaTypeError, match="Image exceeds safe dimension or decompression limits"):
            assess_photometric_quality(oversized_bytes)

    def test_decompression_bomb_warning_escalates_to_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that Pillow DecompressionBombWarning escalates to UnsupportedMediaTypeError."""
        import warnings
        data = _create_synthetic_image(size=(64, 64), pattern="uniform_gray")

        def mock_open(*args: Any, **kwargs: Any) -> Any:
            warnings.warn("Simulated bomb in quality module", Image.DecompressionBombWarning)
            return Image.new("RGB", (64, 64))

        monkeypatch.setattr(Image, "open", mock_open)
        with pytest.raises(UnsupportedMediaTypeError, match="Image exceeds safe dimension or decompression limits"):
            assess_photometric_quality(data)


# ===========================================================================
# Category C: Redaction Geometry Verification
# ===========================================================================


class TestRedactionGeometryVerification:
    """Verify mathematical boundary and coordinate checks for face redaction boxes."""

    def test_valid_normalized_boxes_pass_verification(self) -> None:
        faces = [
            DetectedFace(bounding_box=(0.10, 0.20, 0.40, 0.50), confidence=0.92),
            DetectedFace(bounding_box=(0.60, 0.65, 0.90, 0.85), confidence=0.88),
        ]
        result = verify_redaction_geometry(faces, image_width=640, image_height=480)

        assert isinstance(result, RedactionGeometryVerificationResult)
        assert result.geometry_valid is True
        assert result.total_boxes == 2
        assert result.valid_box_count == 2
        assert result.invalid_box_count == 0
        assert result.clipped_box_count == 0
        assert result.overlap_count == 0
        assert result.requires_human_review is False
        assert result.disclaimer == REDACTION_GEOMETRY_ADVISORY_DISCLAIMER

    def test_empty_face_list_returns_valid_zero_geometry(self) -> None:
        result = verify_redaction_geometry([], image_width=640, image_height=480)

        assert result.geometry_valid is True
        assert result.total_boxes == 0
        assert result.valid_box_count == 0
        assert result.requires_human_review is False
        assert len(result.consolidated_boxes) == 0

    def test_atypical_aspect_ratio_heuristic_flags_review(self) -> None:
        # Extremely wide box: width = 0.8, height = 0.1 -> AR = 8.0 (exceeds max 2.85)
        face_wide = DetectedFace(bounding_box=(0.40, 0.10, 0.50, 0.90), confidence=0.90)
        policy = RedactionGeometryPolicy(min_aspect_ratio=0.35, max_aspect_ratio=2.85)
        result = verify_redaction_geometry([face_wide], image_width=640, image_height=480, policy=policy)

        assert result.geometry_valid is True
        assert result.requires_human_review is True
        assert any("unusual aspect ratio" in r for r in result.review_reasons)

    def test_duplicate_boxes_are_detected_and_flagged(self) -> None:
        box = (0.20, 0.20, 0.60, 0.60)
        faces = [
            DetectedFace(bounding_box=box, confidence=0.90),
            DetectedFace(bounding_box=box, confidence=0.85),
        ]
        result = verify_redaction_geometry(faces, image_width=640, image_height=480)

        assert result.requires_human_review is True
        assert any("duplicate of a previously inspected" in r for r in result.review_reasons)

    def test_image_dimensions_validated_against_limits(self) -> None:
        faces = [DetectedFace(bounding_box=(0.1, 0.1, 0.5, 0.5), confidence=0.9)]
        with pytest.raises(ValueError, match="must be strictly positive"):
            verify_redaction_geometry(faces, image_width=0, image_height=480)

        with pytest.raises(ValueError, match="exceeds maximum permitted limit"):
            verify_redaction_geometry(faces, image_width=5000, image_height=480)


# ===========================================================================
# Category D: Overlap Analysis & Unified Envelope Consolidation
# ===========================================================================


class TestOverlapAnalysisAndConsolidation:
    """Verify IoU calculation and unified bounding envelope consolidation without shrinking."""

    def test_compute_box_iou_disjoint_returns_zero(self) -> None:
        box_a = (0.0, 0.0, 0.2, 0.2)
        box_b = (0.5, 0.5, 0.7, 0.7)
        assert compute_box_iou(box_a, box_b) == 0.0

    def test_compute_box_iou_identical_returns_one(self) -> None:
        box = (0.1, 0.1, 0.5, 0.5)
        assert pytest.approx(compute_box_iou(box, box), rel=1e-5) == 1.0

    def test_compute_box_iou_partial_overlap_known_fraction(self) -> None:
        # Box A: [0, 0, 2, 2] -> area 4
        # Box B: [1, 1, 3, 3] -> area 4
        # Intersection: [1, 1, 2, 2] -> area 1
        # Union: 4 + 4 - 1 = 7 -> IoU = 1/7 ~= 0.142857
        box_a = (0.0, 0.0, 0.2, 0.2)
        box_b = (0.1, 0.1, 0.3, 0.3)
        expected_iou = 0.01 / (0.04 + 0.04 - 0.01)
        assert pytest.approx(compute_box_iou(box_a, box_b), rel=1e-5) == expected_iou

    def test_consolidate_overlapping_boxes_merges_clusters(self) -> None:
        # Two heavily overlapping boxes:
        # A: [0.1, 0.1, 0.4, 0.4]
        # B: [0.2, 0.2, 0.5, 0.5]
        # Merged envelope must be: [0.1, 0.1, 0.5, 0.5]
        boxes = [
            (0.1, 0.1, 0.4, 0.4),
            (0.2, 0.2, 0.5, 0.5),
            (0.7, 0.7, 0.9, 0.9),  # Disjoint box
        ]
        consolidated, overlap_count = consolidate_overlapping_boxes(boxes, iou_threshold=0.10)

        assert overlap_count == 1
        assert len(consolidated) == 2
        # Check merged envelope covers both A and B completely
        merged = next(b for b in consolidated if b[0] == 0.1)
        assert merged == (0.1, 0.1, 0.5, 0.5)
        # Check disjoint box preserved
        disjoint = next(b for b in consolidated if b[0] == 0.7)
        assert disjoint == (0.7, 0.7, 0.9, 0.9)

    def test_consolidation_guarantees_zero_shrinking_of_protected_area(self) -> None:
        box1 = (0.10, 0.15, 0.45, 0.50)
        box2 = (0.20, 0.25, 0.60, 0.70)
        faces = [
            DetectedFace(bounding_box=box1, confidence=0.9),
            DetectedFace(bounding_box=box2, confidence=0.9),
        ]
        result = verify_redaction_geometry(faces, image_width=500, image_height=500)

        assert result.overlap_count >= 1
        assert len(result.consolidated_boxes) == 1
        c_ymin, c_xmin, c_ymax, c_xmax = result.consolidated_boxes[0]

        # Consolidated envelope MUST be >= the outer extent of both boxes
        assert c_ymin <= min(box1[0], box2[0])
        assert c_xmin <= min(box1[1], box2[1])
        assert c_ymax >= max(box1[2], box2[2])
        assert c_xmax >= max(box1[3], box2[3])


# ===========================================================================
# Category E: Landmark Coverage Verification
# ===========================================================================


class TestLandmarkCoverageVerification:
    """Verify facial landmarks fall within padded and clipped bounding envelopes."""

    def test_landmarks_within_box_pass_verification(self) -> None:
        face = DetectedFace(
            bounding_box=(0.20, 0.20, 0.60, 0.60),
            confidence=0.95,
            landmarks={
                "left_eye": (0.35, 0.35),
                "right_eye": (0.35, 0.45),
                "nose": (0.42, 0.40),
                "mouth": (0.50, 0.40),
            },
        )
        result = verify_redaction_geometry([face], image_width=400, image_height=400)

        assert result.landmark_coverage_valid is True
        assert result.requires_human_review is False

    def test_landmark_outside_box_envelope_fails_verification(self) -> None:
        # Mouth landmark at y=0.75 is outside box [0.20, 0.20, 0.60, 0.60] (with 10% pad: ymax=0.64)
        face = DetectedFace(
            bounding_box=(0.20, 0.20, 0.60, 0.60),
            confidence=0.95,
            landmarks={
                "left_eye": (0.35, 0.35),
                "mouth": (0.75, 0.40),  # Exposed!
            },
        )
        policy = RedactionGeometryPolicy(padding_ratio=0.05)
        result = verify_redaction_geometry([face], image_width=400, image_height=400, policy=policy)

        assert result.landmark_coverage_valid is False
        assert result.geometry_valid is False
        assert result.requires_human_review is True
        assert any("falls outside padded redaction envelope" in r for r in result.review_reasons)

    def test_non_finite_or_out_of_bounds_landmarks_flag_review(self) -> None:
        face_nan = DetectedFace(
            bounding_box=(0.2, 0.2, 0.6, 0.6),
            confidence=0.9,
            landmarks={"left_eye": (float("nan"), 0.3)},
        )
        result = verify_redaction_geometry([face_nan], image_width=400, image_height=400)

        assert result.landmark_coverage_valid is False
        assert result.requires_human_review is True
        assert any("non-finite coordinates" in r for r in result.review_reasons)

    def test_faces_without_landmarks_default_to_valid(self) -> None:
        face_no_lm = DetectedFace(bounding_box=(0.2, 0.2, 0.6, 0.6), confidence=0.9, landmarks=None)
        result = verify_redaction_geometry([face_no_lm], image_width=400, image_height=400)

        assert result.landmark_coverage_valid is True


# ===========================================================================
# Category F: Service Integration & Security Scoping
# ===========================================================================


class TestServiceIntegrationAndSecurityScoping:
    """Verify service-layer authorization, governance checks, tenant isolation, and audit trails."""

    @pytest.mark.asyncio
    async def test_quality_service_fails_when_biometrics_disabled(self) -> None:
        settings = _make_settings(BIOMETRIC_ANALYSIS_ENABLED=False, BIOMETRIC_DETECTION_ENABLED=False)
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_synthetic_image()

        with pytest.raises(BiometricsDisabledError, match="Biometric analysis is disabled"):
            await service.assess_image_quality(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_quality_service_denies_caller_without_permission(self) -> None:
        settings = _make_settings()
        # STUDENT role does not possess BIOMETRIC_DETECTION_EXECUTE
        principal = _make_principal(RoleCode.STUDENT.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_repo = AsyncMock()
        service = FaceDetectionService(gov_repo, settings)
        png_bytes = _create_synthetic_image()

        with pytest.raises(PermissionDeniedError, match="Caller lacks BIOMETRIC_DETECTION_EXECUTE"):
            await service.assess_image_quality(png_bytes, gov_record.id, principal)

    @pytest.mark.asyncio
    async def test_quality_service_denies_cross_tenant_evidence(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)

        other_dept_id = uuid4()
        evidence = EvidenceAttachment(
            id=uuid4(),
            incident_id=uuid4(),
            uploader_id=uuid4(),
            department_id=other_dept_id,  # Cross-tenant!
            original_filename="confidential.png",
            file_size_bytes=1024,
            declared_mime_type="image/png",
            storage_key="test-key",
        )

        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        evidence_repo = AsyncMock()
        evidence_repo.get_attachment_by_id.return_value = evidence

        service = FaceDetectionService(gov_repo, settings, evidence_repo=evidence_repo)
        png_bytes = _create_synthetic_image()

        with pytest.raises(PermissionDeniedError, match="Access to cross-tenant evidence is strictly prohibited"):
            await service.assess_image_quality(png_bytes, gov_record.id, principal, evidence_id=evidence.id)

    @pytest.mark.asyncio
    async def test_quality_service_records_metadata_only_audit_log(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record
        audit_repo = AsyncMock()

        service = FaceDetectionService(gov_repo, settings, audit_repo=audit_repo)
        png_bytes = _create_synthetic_image(size=(128, 128), pattern="sharp_checkerboard")

        response = await service.assess_image_quality(png_bytes, gov_record.id, principal)
        assert isinstance(response, PhotometricQualityResponse)
        assert response.sharpness_score > 0.0

        assert audit_repo.append_event.called
        call_kwargs = audit_repo.append_event.call_args.kwargs
        assert call_kwargs["action"] == "evidence:quality:evaluated"
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS.value
        details = call_kwargs["details"]
        assert "sharpness_score" in details
        assert "quality_status" in details
        # Verify strict privacy invariants in audit log
        assert "image_bytes" not in details
        assert "image_base64" not in details

    @pytest.mark.asyncio
    async def test_geometry_service_verifies_faces_end_to_end(self) -> None:
        settings = _make_settings()
        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record = _make_approved_governance_record(principal.department_id)
        gov_repo = AsyncMock()
        gov_repo.get_by_id.return_value = gov_record

        service = FaceDetectionService(gov_repo, settings)
        faces = [
            DetectedFace(bounding_box=(0.1, 0.1, 0.4, 0.4), confidence=0.9),
            DetectedFace(bounding_box=(0.2, 0.2, 0.5, 0.5), confidence=0.85),
        ]
        response = await service.verify_geometry(
            detected_faces=faces,
            image_width=400,
            image_height=400,
            governance_record_id=gov_record.id,
            principal=principal,
        )

        assert isinstance(response, RedactionGeometryResponse)
        assert response.geometry_valid is True
        assert response.total_boxes == 2
        assert response.overlap_count == 1
        assert len(response.consolidated_boxes) == 1
        assert response.consolidated_boxes[0] == (0.1, 0.1, 0.5, 0.5)

    @pytest.mark.asyncio
    async def test_api_check_image_quality_endpoint(self) -> None:
        from backend.app.api.v1.biometrics import check_image_quality

        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record_id = uuid4()
        png_bytes = _create_synthetic_image(size=(100, 100))
        b64_str = base64.b64encode(png_bytes).decode("ascii")

        mock_service = AsyncMock()
        mock_service.assess_image_quality.return_value = PhotometricQualityResponse(
            sharpness_score=0.85,
            exposure_score=0.90,
            contrast_score=0.75,
            underexposed_fraction=0.05,
            overexposed_fraction=0.05,
            clipped_fraction=0.02,
            quality_status="acceptable",
            requires_human_review=False,
            review_reasons=[],
            raw_metrics={"raw_laplacian_variance": 600.0},
            image_width=100,
            image_height=100,
            image_format="png",
            metric_version="1.0.0",
            disclaimer=PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER,
        )

        req = PhotometricQualityRequest(
            governance_record_id=gov_record_id,
            image_base64=b64_str,
        )
        resp = await check_image_quality(req, principal, mock_service)
        assert resp.quality_status == "acceptable"
        assert resp.sharpness_score == 0.85
        assert mock_service.assess_image_quality.called

    @pytest.mark.asyncio
    async def test_api_verify_geometry_endpoint(self) -> None:
        from backend.app.api.v1.biometrics import verify_geometry_endpoint

        principal = _make_principal(RoleCode.INVESTIGATOR.value)
        gov_record_id = uuid4()

        mock_service = AsyncMock()
        mock_service.verify_geometry.return_value = RedactionGeometryResponse(
            geometry_valid=True,
            total_boxes=1,
            valid_box_count=1,
            invalid_box_count=0,
            overlap_count=0,
            clipped_box_count=0,
            consolidated_boxes=[(0.1, 0.1, 0.5, 0.5)],
            landmark_coverage_valid=True,
            requires_human_review=False,
            review_reasons=[],
            geometry_version="1.0.0",
            disclaimer=REDACTION_GEOMETRY_ADVISORY_DISCLAIMER,
        )

        req = RedactionGeometryRequest(
            governance_record_id=gov_record_id,
            image_width=200,
            image_height=200,
            detected_faces=[
                DetectedFaceRead(
                    bounding_box=(0.1, 0.1, 0.5, 0.5),
                    confidence=0.9,
                )
            ],
        )
        resp = await verify_geometry_endpoint(req, principal, mock_service)
        assert resp.geometry_valid is True
        assert resp.total_boxes == 1
        assert mock_service.verify_geometry.called


# ===========================================================================
# Category G: Mandatory Invariants
# ===========================================================================


class TestPhase76MandatoryInvariants:
    """Verify system-wide safety invariants remain non-negotiable."""

    def test_biometric_matching_enabled_remains_false(self) -> None:
        settings = _make_settings()
        assert settings.BIOMETRIC_MATCHING_ENABLED is False

    def test_no_facial_embeddings_or_templates_created(self) -> None:
        """Verify that quality and geometry components produce zero high-dimensional vector representations."""
        img_bytes = _create_synthetic_image()
        quality_res = assess_photometric_quality(img_bytes)
        geom_res = verify_redaction_geometry([], 100, 100)

        assert not hasattr(quality_res, "embedding")
        assert not hasattr(quality_res, "feature_vector")
        assert not hasattr(quality_res, "template")
        assert not hasattr(geom_res, "embedding")
        assert not hasattr(geom_res, "descriptor")
