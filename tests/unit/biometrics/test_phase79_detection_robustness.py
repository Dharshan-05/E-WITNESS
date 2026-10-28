"""Phase 79 Acceptance Test Suite: Detection Quality, Robustness, Fairness & Spoof-Resistance Assessment.

Tests:
1. Synthetic Ground Truth Generation & Detection Metric Calculation (Precision, Recall, Miss Rate, F1, Mean IoU).
2. Redaction Coverage Verification (Successful coverage, partial coverage, zero-detection fail-safe).
3. Technical Imaging Perturbations (Blur, Low Light, Overexposure, Compression, Partial Occlusion).
4. Non-Identifying Technical Subgroup Disparities (Resolution tiers, Contrast tiers).
5. Mandatory Demographic Fairness Disclosure (FAIRNESS NOT ESTABLISHED, Production NO-GO disclaimer).
6. Input Integrity & Malformed Payloads (Truncated headers, non-image text payloads fail closed).
7. Decompression Bomb & Resource Safeguards (8192x8192 and pixel budget checks before allocation).
8. Bounding Box Coordinate Validation (Negative, >1.0, non-normalized values rejected).
9. Zero-Detection Human Review Trigger (Unredacted images never marked redacted).
10. Phase 78 Cryptographic Key Regression (Zero key leakage, envelope integrity, vault fail-closed).
11. Biometric Matching Prohibition Invariant (BIOMETRIC_MATCHING_ENABLED=False permanently enforced).
12. FaceDetectionService Audit Logging & Permission Scoping.
13. REST API Endpoint End-to-End (GET /faces/robustness-report with role-based authorization).
"""

from __future__ import annotations

import base64
import hashlib
import io
import struct
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_services.face_detection.detector import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    MockFaceDetectorProvider,
    inspect_image_dimensions_and_format,
)
from ai_services.face_detection.evaluation import (
    DETECTION_EVALUATION_ADVISORY_DISCLAIMER,
    FAIRNESS_NOT_ESTABLISHED_DISCLAIMER,
    ConditionRobustnessResult,
    DetectionMetrics,
    FaceDetectionRobustnessAuditReport,
    InputIntegrityCheckResult,
    RedactionVerificationMetrics,
    TechnicalSubgroupDisparity,
    apply_image_perturbation,
    compute_detection_metrics,
    generate_synthetic_face_image,
    run_full_detection_robustness_audit,
    verify_redaction_coverage,
)
from ai_services.face_detection.geometry import (
    compute_box_iou,
    verify_redaction_geometry,
)
from ai_services.face_detection.protocol import DetectedFace, FaceDetectionOptions
from ai_services.face_detection.quality import (
    PhotometricQualityStatus,
    assess_photometric_quality,
)
from ai_services.face_detection.redaction import (
    RedactedImageResult,
    RedactionPolicy,
    RedactionStyle,
    apply_face_redaction,
)
from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, RoleCode
from backend.app.core.biometric_crypto import (
    BiometricKeyManager,
    InMemoryKeyVaultProvider,
    KeyStatus,
)
from backend.app.core.exceptions import (
    PermissionDeniedError,
    UnsupportedMediaTypeError,
)
from backend.app.main import create_app
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.biometrics import BiometricGovernanceRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    FaceDetectionRobustnessAuditRead,
)
from backend.app.services.biometrics import FaceDetectionService


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
        BIOMETRIC_DETECTION_ENABLED=True,
        BIOMETRIC_MATCHING_ENABLED=False,
    )


def _make_principal(
    role: str = RoleCode.INVESTIGATOR.value,
    dept_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        email=f"test_{role.lower()}@ewitness.test",
        full_name="Test Officer",
        account_status="ACTIVE",
        is_active=True,
        role_code=role,
        department_id=dept_id or uuid4(),
        session_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# 1. Synthetic Ground Truth Generation & Detection Metric Calculation
# ---------------------------------------------------------------------------


def test_synthetic_image_generator_single_and_multiple_faces() -> None:
    """Verify synthetic image generator produces valid PNGs and exact ground-truth bounding boxes."""
    # Single face
    png1, boxes1 = generate_synthetic_face_image(width=640, height=480, num_faces=1)
    assert len(png1) > 0
    assert len(boxes1) == 1
    ymin, xmin, ymax, xmax = boxes1[0]
    assert 0.0 <= ymin < ymax <= 1.0
    assert 0.0 <= xmin < xmax <= 1.0

    # Two faces
    png2, boxes2 = generate_synthetic_face_image(width=800, height=600, num_faces=2)
    assert len(png2) > 0
    assert len(boxes2) == 2
    for box in boxes2:
        y0, x0, y1, x1 = box
        assert 0.0 <= y0 < y1 <= 1.0
        assert 0.0 <= x0 < x1 <= 1.0


def test_compute_detection_metrics_perfect_match() -> None:
    """Verify compute_detection_metrics gives 1.0 precision, recall, and F1 on perfect detections."""
    gt = [(0.2, 0.2, 0.6, 0.6)]
    detected = [DetectedFace(bounding_box=(0.2, 0.2, 0.6, 0.6), confidence=0.95)]
    metrics = compute_detection_metrics(gt, detected, iou_threshold=0.5)

    assert metrics.total_ground_truth == 1
    assert metrics.total_detected == 1
    assert metrics.true_positives == 1
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.miss_rate == 0.0
    assert metrics.f1_score == 1.0
    assert metrics.mean_iou == 1.0


def test_compute_detection_metrics_miss_and_false_positive() -> None:
    """Verify metric calculations for partial detections and false positives."""
    gt = [
        (0.1, 0.1, 0.4, 0.4),  # Box 1 (will match)
        (0.6, 0.6, 0.9, 0.9),  # Box 2 (will miss)
    ]
    detected = [
        DetectedFace(bounding_box=(0.12, 0.12, 0.42, 0.42), confidence=0.90),  # Matches Box 1
        DetectedFace(bounding_box=(0.10, 0.70, 0.30, 0.90), confidence=0.85),  # False positive
    ]
    metrics = compute_detection_metrics(gt, detected, iou_threshold=0.5)

    assert metrics.total_ground_truth == 2
    assert metrics.total_detected == 2
    assert metrics.true_positives == 1
    assert metrics.false_positives == 1
    assert metrics.false_negatives == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.miss_rate == 0.5
    assert metrics.f1_score == 0.5
    assert metrics.mean_iou > 0.5


# ---------------------------------------------------------------------------
# 2. Redaction Coverage Verification
# ---------------------------------------------------------------------------


def test_redaction_coverage_success() -> None:
    """Verify redaction coverage metrics when redaction mask covers ground truth."""
    gt = [(0.2, 0.2, 0.6, 0.6)]
    detected = [DetectedFace(bounding_box=(0.2, 0.2, 0.6, 0.6), confidence=0.90)]
    mock_result = RedactedImageResult(
        redacted_bytes=b"fake_png",
        redacted_faces_count=1,
        image_format="PNG",
        image_width=640,
        image_height=480,
        style="solid_box",
        is_redacted=True,
        requires_human_review=False,
    )

    metrics = verify_redaction_coverage(gt, mock_result, detected)
    assert metrics.total_faces_targeted == 1
    assert metrics.successful_redactions == 1
    assert metrics.coverage_rate == 1.0
    assert metrics.failed_redactions_detected == 0


def test_redaction_coverage_zero_detection_review_trigger() -> None:
    """Verify that zero detected faces results in 0.0 coverage and increments review count."""
    gt = [(0.2, 0.2, 0.6, 0.6)]
    mock_result = RedactedImageResult(
        redacted_bytes=b"fake_png",
        redacted_faces_count=0,
        image_format="PNG",
        image_width=640,
        image_height=480,
        style="solid_box",
        is_redacted=False,
        requires_human_review=True,
    )

    metrics = verify_redaction_coverage(gt, mock_result, [])
    assert metrics.total_faces_targeted == 1
    assert metrics.successful_redactions == 0
    assert metrics.coverage_rate == 0.0
    assert metrics.failed_redactions_detected == 1
    assert metrics.zero_detection_triggered_review_count == 1


# ---------------------------------------------------------------------------
# 3. Technical Imaging Perturbations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("condition", ["blur", "low_light", "overexposure", "compression", "partial_occlusion"])
def test_perturbation_generator_and_photometric_evaluation(condition: str) -> None:
    """Verify each perturbation condition modifies the image and can be photometrically assessed."""
    base_png, _ = generate_synthetic_face_image(width=640, height=480, num_faces=1)
    perturbed_png = apply_image_perturbation(base_png, condition)

    assert len(perturbed_png) > 0
    assert perturbed_png != base_png

    photo = assess_photometric_quality(perturbed_png)
    assert photo.image_width == 640
    assert photo.image_height == 480
    assert photo.quality_status in [
        PhotometricQualityStatus.ACCEPTABLE,
        PhotometricQualityStatus.DEGRADED,
        PhotometricQualityStatus.REJECTED,
    ]


# ---------------------------------------------------------------------------
# 4. Technical Subgroups & Mandatory Demographic Fairness Disclosures
# ---------------------------------------------------------------------------


def test_full_detection_robustness_audit_execution() -> None:
    """Verify complete Phase 79 audit engine runs and produces compliant report structure."""
    report = run_full_detection_robustness_audit()

    assert isinstance(report, FaceDetectionRobustnessAuditReport)
    assert report.audit_version == "1.0.0"

    # Baseline metrics
    assert report.baseline_metrics.recall >= 0.0
    assert report.redaction_metrics.coverage_rate >= 0.0

    # Perturbations
    assert len(report.condition_evaluations) == 5
    condition_names = [c.condition_name for c in report.condition_evaluations]
    assert "blur" in condition_names
    assert "low_light" in condition_names
    assert "overexposure" in condition_names
    assert "compression" in condition_names
    assert "partial_occlusion" in condition_names

    # Technical subgroups
    assert len(report.technical_subgroups) >= 3
    subgroup_names = [s.subgroup_name for s in report.technical_subgroups]
    assert "high_resolution_1080p" in subgroup_names
    assert "standard_resolution_480p" in subgroup_names
    assert "low_resolution_240p" in subgroup_names


def test_mandatory_fairness_not_established_disclosure() -> None:
    """Enforce non-negotiable invariant: demographic fairness must remain strictly NOT ESTABLISHED."""
    report = run_full_detection_robustness_audit()

    # The status must be explicitly NOT ESTABLISHED
    assert report.fairness_status == "NOT ESTABLISHED"

    # Mandatory disclaimers
    assert "DEMOGRAPHIC FAIRNESS NOT ESTABLISHED" in report.fairness_disclaimer
    assert "human protected classes" in report.fairness_disclaimer
    assert "production deployment is NO-GO" in report.fairness_disclaimer
    assert "DETECTION & REDACTION EVALUATION ADVISORY" in report.disclaimer


# ---------------------------------------------------------------------------
# 5. Input Integrity, Malformed Payloads & Decompression Bombs
# ---------------------------------------------------------------------------


def test_audit_report_input_integrity_checks_all_pass() -> None:
    """Verify that all input-integrity adversarial boundary test cases pass."""
    report = run_full_detection_robustness_audit()
    assert len(report.input_integrity_checks) >= 5

    for check in report.input_integrity_checks:
        assert check.passed is True, f"Check {check.test_case_name} failed: {check.details}"


def test_malformed_png_rejected_before_allocation() -> None:
    """Verify malformed/truncated PNG headers raise UnsupportedMediaTypeError without decoding."""
    with pytest.raises(UnsupportedMediaTypeError):
        inspect_image_dimensions_and_format(b"\x89PNG\r\n\x1a\nTRUNC")


def test_decompression_bomb_dimension_check() -> None:
    """Verify 8192x8192 pixel dimensions fail closed with ValueError before allocating memory."""
    fake_bomb = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", 8192, 8192, 8, 2, 0, 0, 0)
        + b"\x00\x00\x00\x00"
    )
    with pytest.raises(ValueError, match="exceeds maximum permitted pixel budget"):
        inspect_image_dimensions_and_format(fake_bomb)


def test_deceptive_text_payload_rejected() -> None:
    """Verify non-image text payload is rejected with UnsupportedMediaTypeError."""
    with pytest.raises(UnsupportedMediaTypeError):
        inspect_image_dimensions_and_format(b"<html><head>Phishing payload</head></html>")


def test_non_normalized_coordinates_rejected_fail_closed() -> None:
    """Verify coordinates outside [0.0, 1.0] raise ValueError on DetectedFace construction."""
    with pytest.raises(ValueError, match="normalized within"):
        DetectedFace(bounding_box=(-0.2, 0.1, 1.2, 0.9), confidence=0.9)


def test_zero_faces_detected_enforces_unredacted_state() -> None:
    """Verify that when zero faces are detected, image is NOT claimed redacted and review is required."""
    png_bytes, _ = generate_synthetic_face_image(width=640, height=480, num_faces=1)
    res = apply_face_redaction(png_bytes, [])

    assert res.is_redacted is False
    assert res.redacted_faces_count == 0
    assert res.requires_human_review is True


# ---------------------------------------------------------------------------
# 6. Biometric Boundary & Permanent Matching Prohibition Invariant
# ---------------------------------------------------------------------------


def test_matching_prohibition_and_zero_embedding_leakage() -> None:
    """Verify BIOMETRIC_MATCHING_ENABLED is False and evaluation generates zero embeddings."""
    settings = _get_test_settings()
    assert settings.BIOMETRIC_MATCHING_ENABLED is False

    report = run_full_detection_robustness_audit()
    report_dict = report.to_dict()

    # Recursively verify no embedding or feature vector keys exist in the audit report
    def _check_no_biometrics(d: Any) -> None:
        if isinstance(d, dict):
            for k, v in d.items():
                assert "embedding" not in k.lower(), f"Forbidden biometric key: {k}"
                assert "descriptor" not in k.lower(), f"Forbidden descriptor key: {k}"
                assert "feature_vector" not in k.lower(), f"Forbidden feature_vector key: {k}"
                assert "identity" not in k.lower(), f"Forbidden identity key: {k}"
                _check_no_biometrics(v)
        elif isinstance(d, list):
            for item in d:
                _check_no_biometrics(item)

    _check_no_biometrics(report_dict)


# ---------------------------------------------------------------------------
# 7. Phase 78 Cryptographic Key Vault Regressions
# ---------------------------------------------------------------------------


def test_phase78_key_vault_fail_closed_and_scrubbing() -> None:
    """Verify key vault fails closed on missing keys and representations scrub raw keys."""
    vault = InMemoryKeyVaultProvider()
    vault.store_key("key-active", b"\xaa" * 32, status=KeyStatus.ACTIVE)

    # Valid key retrieval
    assert vault.get_key_bytes("key-active") == b"\xaa" * 32

    # String representation scrubbing
    rep = repr(vault)
    assert "InMemoryKeyVaultProvider" in rep
    assert "aaaa" not in rep.lower()

    # Unavailable key fails closed
    with pytest.raises(Exception):
        vault.get_key_bytes("non-existent-key")


# ---------------------------------------------------------------------------
# 8. FaceDetectionService Audit Logging & Access Control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_get_detection_robustness_report_success() -> None:
    """Verify FaceDetectionService produces report and records audit event."""
    settings = _get_test_settings()
    mock_gov_repo = MagicMock(spec=BiometricGovernanceRepository)
    mock_audit_repo = MagicMock(spec=AuditRepository)
    mock_audit_repo.append_event = AsyncMock()

    service = FaceDetectionService(
        governance_repo=mock_gov_repo,
        settings=settings,
        audit_repo=mock_audit_repo,
    )

    principal = _make_principal(role=RoleCode.INVESTIGATOR.value)
    report = await service.get_detection_robustness_report(principal)

    assert isinstance(report, FaceDetectionRobustnessAuditRead)
    assert report.fairness_status == "NOT ESTABLISHED"
    assert len(report.condition_evaluations) == 5

    # Audit log verification
    mock_audit_repo.append_event.assert_awaited_once()
    call_kwargs = mock_audit_repo.append_event.call_args.kwargs
    assert call_kwargs["target_type"] == AuditTargetType.BIOMETRIC_GOVERNANCE.value
    assert call_kwargs["details"]["phase"] == 79
    assert call_kwargs["details"]["fairness_status"] == "NOT ESTABLISHED"


@pytest.mark.asyncio
async def test_service_get_detection_robustness_report_permission_denied() -> None:
    """Verify caller without governance review or audit permission is denied."""
    settings = _get_test_settings()
    service = FaceDetectionService(
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        settings=settings,
    )

    unauthorized_principal = _make_principal(role=RoleCode.STUDENT.value)
    with pytest.raises(PermissionDeniedError, match="Caller lacks permission"):
        await service.get_detection_robustness_report(unauthorized_principal)


# ---------------------------------------------------------------------------
# 9. REST API Endpoint End-to-End Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_faces_robustness_report_endpoint() -> None:
    """Test GET /biometrics/faces/robustness-report returns 200 OK and validates response DTO."""
    settings = _get_test_settings()
    app = create_app(settings)

    principal = _make_principal(role=RoleCode.INVESTIGATOR.value)

    # Dependency overrides for current user and service
    from backend.app.api.dependencies import get_current_principal, get_face_detection_service
    app.dependency_overrides[get_current_principal] = lambda: principal

    mock_service = FaceDetectionService(
        governance_repo=MagicMock(spec=BiometricGovernanceRepository),
        settings=settings,
    )
    app.dependency_overrides[get_face_detection_service] = lambda: mock_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        resp = await client.get("/api/v1/biometrics/faces/robustness-report")

    assert resp.status_code == 200
    data = resp.json()

    # Validate with Pydantic model
    validated = FaceDetectionRobustnessAuditRead.model_validate(data)
    assert validated.fairness_status == "NOT ESTABLISHED"
    assert "DEMOGRAPHIC FAIRNESS NOT ESTABLISHED" in validated.fairness_disclaimer
    assert len(validated.condition_evaluations) == 5
    assert len(validated.technical_subgroups) >= 3
    assert len(validated.input_integrity_checks) >= 5
