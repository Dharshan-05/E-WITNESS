"""Face detection quality, robustness, fairness limitations, and spoof-resistance evaluation module (Phase 79).

Enforces:
- Empirical detection recall, precision, and IoU evaluation on synthetic ground-truth fixtures.
- Perturbation robustness assessment across controlled imaging conditions:
  blur, low light, overexposure, compression, and partial occlusion.
- Non-identifying technical subgroup disparity evaluation (resolution, contrast, exposure tiers).
- Mandatory FAIRNESS NOT ESTABLISHED disclosure: demographic fairness across human protected classes
  cannot be claimed using synthetic geometric fixtures or imaging conditions.
- Input-integrity and spoof-resistance evaluation: decompression bombs, malformed streams,
  deceptive headers, out-of-range coordinates, and contradictory review states.
- Fail-closed safeguards: unredacted evidence is never marked as redacted; zero-detection requires human review.
- Segregation invariant: zero biometric matching, zero embedding generation, zero identity search.
"""

from __future__ import annotations

import io
import math
import struct
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Final

from PIL import Image, ImageDraw, ImageFilter

from ai_services.face_detection.detector import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    MockFaceDetectorProvider,
    _validate_dimensions,
    inspect_image_dimensions_and_format,
)
from ai_services.face_detection.geometry import (
    RedactionGeometryPolicy,
    compute_box_iou,
    verify_redaction_geometry,
)
from ai_services.face_detection.protocol import DetectedFace, FaceDetectionOptions
from ai_services.face_detection.quality import (
    PhotometricQualityThresholds,
    assess_photometric_quality,
)
from ai_services.face_detection.redaction import (
    RedactedImageResult,
    RedactionPolicy,
    RedactionStyle,
    apply_face_redaction,
)
from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
    evaluate_unified_review_decision,
)
from backend.app.core.exceptions import UnsupportedMediaTypeError

FAIRNESS_NOT_ESTABLISHED_DISCLAIMER: Final[str] = (
    "DEMOGRAPHIC FAIRNESS NOT ESTABLISHED: Demographic parity across human protected classes "
    "(such as race, gender, age, or ethnicity) cannot be evaluated, verified, or claimed using "
    "synthetic test fixtures or technical image perturbations. E-WITNESS does not possess or evaluate "
    "real-subject demographic biometric datasets. Operational fairness across human subpopulations "
    "remains strictly NOT ESTABLISHED, and production deployment is NO-GO."
)

DETECTION_EVALUATION_ADVISORY_DISCLAIMER: Final[str] = (
    "DETECTION & REDACTION EVALUATION ADVISORY: This assessment measures synthetic technical "
    "robustness, mathematical box geometry, and input integrity only. It does NOT establish real-world "
    "surveillance performance, facial recognition capability, or absolute privacy anonymization. "
    "Automated biometric matching remains permanently disabled under policy."
)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionMetrics:
    """Detection performance metrics measured against synthetic ground truth."""

    total_ground_truth: int
    total_detected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    miss_rate: float
    f1_score: float
    mean_iou: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RedactionVerificationMetrics:
    """Verification metrics for privacy redaction coverage and failure detection."""

    total_faces_targeted: int
    successful_redactions: int
    partial_redactions_detected: int
    failed_redactions_detected: int
    coverage_rate: float
    zero_detection_triggered_review_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConditionRobustnessResult:
    """Robustness evaluation result under a specific technical image condition."""

    condition_name: str
    sample_count: int
    metrics: DetectionMetrics
    redaction_coverage: float
    human_review_required_rate: float
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TechnicalSubgroupDisparity:
    """Disparity analysis across non-identifying technical image categories."""

    subgroup_name: str
    sample_count: int
    recall: float
    precision: float
    miss_rate: float
    disparity_ratio: float  # Min recall / max recall relative to baseline

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputIntegrityCheckResult:
    """Result of testing an input integrity, malformed payload, or adversarial boundary."""

    test_case_name: str
    category: str
    expected_behavior: str
    observed_outcome: str
    passed: bool
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FaceDetectionRobustnessAuditReport:
    """Comprehensive Phase 79 audit report evaluating detection, robustness, fairness, and input integrity."""

    audit_version: str
    baseline_metrics: DetectionMetrics
    redaction_metrics: RedactionVerificationMetrics
    condition_evaluations: list[ConditionRobustnessResult]
    technical_subgroups: list[TechnicalSubgroupDisparity]
    input_integrity_checks: list[InputIntegrityCheckResult]
    fairness_status: str = "NOT ESTABLISHED"
    fairness_disclaimer: str = FAIRNESS_NOT_ESTABLISHED_DISCLAIMER
    disclaimer: str = DETECTION_EVALUATION_ADVISORY_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Synthetic Test Image Generators
# ---------------------------------------------------------------------------


def generate_synthetic_face_image(
    width: int = 640,
    height: int = 480,
    *,
    num_faces: int = 1,
    fill_color: tuple[int, int, int] = (140, 140, 140),
    face_color: tuple[int, int, int] = (210, 180, 150),
) -> tuple[bytes, list[tuple[float, float, float, float]]]:
    """Generate a reproducible synthetic test image with non-identifying geometric face representations.

    Returns:
        tuple[bytes, list[tuple[float, float, float, float]]]: (png_bytes, list_of_ground_truth_boxes)
    """
    img = Image.new("RGB", (width, height), fill_color)
    draw = ImageDraw.Draw(img)
    ground_truth_boxes: list[tuple[float, float, float, float]] = []

    if num_faces == 1:
        # Single center face
        ymin, xmin, ymax, xmax = 0.20, 0.30, 0.70, 0.70
        ground_truth_boxes.append((ymin, xmin, ymax, xmax))
        px_ymin, px_xmin = int(ymin * height), int(xmin * width)
        px_ymax, px_xmax = int(ymax * height), int(xmax * width)
        draw.ellipse([px_xmin, px_ymin, px_xmax, px_ymax], fill=face_color, outline=(40, 40, 40), width=2)
        # Eye spots
        eye_y = int(ymin * height + 0.3 * (ymax - ymin) * height)
        draw.ellipse([int(xmin * width + 0.25 * (xmax - xmin) * width), eye_y, int(xmin * width + 0.35 * (xmax - xmin) * width), eye_y + 10], fill=(20, 20, 20))
        draw.ellipse([int(xmin * width + 0.65 * (xmax - xmin) * width), eye_y, int(xmin * width + 0.75 * (xmax - xmin) * width), eye_y + 10], fill=(20, 20, 20))
    elif num_faces == 2:
        # Two side-by-side faces
        box1 = (0.25, 0.15, 0.65, 0.45)
        box2 = (0.25, 0.55, 0.65, 0.85)
        ground_truth_boxes.extend([box1, box2])
        for ymin, xmin, ymax, xmax in [box1, box2]:
            draw.ellipse(
                [int(xmin * width), int(ymin * height), int(xmax * width), int(ymax * height)],
                fill=face_color,
                outline=(40, 40, 40),
                width=2,
            )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), ground_truth_boxes


def apply_image_perturbation(
    png_bytes: bytes,
    condition: str,
) -> bytes:
    """Apply a controlled technical imaging perturbation to a synthetic PNG image."""
    with Image.open(io.BytesIO(png_bytes)) as img:
        work = img.copy()

    if condition == "blur":
        work = work.filter(ImageFilter.GaussianBlur(radius=8))
    elif condition == "low_light":
        # Scale brightness down to 20%
        work = work.point(lambda p: int(p * 0.20))
    elif condition == "overexposure":
        # Scale brightness up and saturate
        work = work.point(lambda p: min(255, int(p * 2.2)))
    elif condition == "compression":
        # Simulate aggressive JPEG re-compression artifacts
        buf_jpg = io.BytesIO()
        work.save(buf_jpg, format="JPEG", quality=15)
        buf_jpg.seek(0)
        with Image.open(buf_jpg) as recompressed:
            work = recompressed.copy()
    elif condition == "partial_occlusion":
        # Overlay opaque block over top half of image
        draw = ImageDraw.Draw(work)
        w, h = work.size
        draw.rectangle([int(w * 0.25), int(h * 0.20), int(w * 0.75), int(h * 0.45)], fill=(10, 10, 10))

    out_buf = io.BytesIO()
    work.save(out_buf, format="PNG")
    return out_buf.getvalue()


# ---------------------------------------------------------------------------
# Evaluation Math & Metrics
# ---------------------------------------------------------------------------


def compute_detection_metrics(
    ground_truth_boxes: list[tuple[float, float, float, float]],
    detected_faces: list[DetectedFace],
    iou_threshold: float = 0.5,
) -> DetectionMetrics:
    """Calculate detection recall, precision, miss rate, F1 score, and mean IoU.

    Uses Hungarian or greedy IoU matching between ground-truth and detected bounding boxes.
    """
    total_gt = len(ground_truth_boxes)
    total_det = len(detected_faces)

    if total_gt == 0 and total_det == 0:
        return DetectionMetrics(
            total_ground_truth=0,
            total_detected=0,
            true_positives=0,
            false_positives=0,
            false_negatives=0,
            precision=1.0,
            recall=1.0,
            miss_rate=0.0,
            f1_score=1.0,
            mean_iou=1.0,
        )

    matched_gt: set[int] = set()
    matched_det: set[int] = set()
    ious: list[float] = []

    # Greedy IoU matching: evaluate highest-confidence detections first to handle duplicate candidate boxes
    indexed_detections = sorted(
        enumerate(detected_faces),
        key=lambda item: item[1].confidence,
        reverse=True,
    )
    for d_idx, det in indexed_detections:
        best_iou = 0.0
        best_gt_idx = -1
        for g_idx, gt in enumerate(ground_truth_boxes):
            if g_idx in matched_gt:
                continue
            iou = compute_box_iou(det.bounding_box, gt)
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = g_idx

        if best_iou >= iou_threshold and best_gt_idx >= 0:
            matched_gt.add(best_gt_idx)
            matched_det.add(d_idx)
            ious.append(best_iou)

    tp = len(matched_gt)
    fp = total_det - tp
    fn = total_gt - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / total_gt if total_gt > 0 else 0.0
    miss_rate = fn / total_gt if total_gt > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    mean_iou = sum(ious) / len(ious) if ious else 0.0

    return DetectionMetrics(
        total_ground_truth=total_gt,
        total_detected=total_det,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        miss_rate=round(miss_rate, 4),
        f1_score=round(f1, 4),
        mean_iou=round(mean_iou, 4),
    )


def verify_redaction_coverage(
    ground_truth_boxes: list[tuple[float, float, float, float]],
    redacted_result: RedactedImageResult,
    detected_faces: list[DetectedFace],
    min_coverage_threshold: float = 0.85,
) -> RedactionVerificationMetrics:
    """Verify that every ground truth face region is covered by the redaction operation."""
    total_targeted = len(ground_truth_boxes)
    if total_targeted == 0:
        return RedactionVerificationMetrics(
            total_faces_targeted=0,
            successful_redactions=0,
            partial_redactions_detected=0,
            failed_redactions_detected=0,
            coverage_rate=1.0,
            zero_detection_triggered_review_count=1 if redacted_result.requires_human_review else 0,
        )

    # Check that redaction reported at least 1 face redacted
    if not redacted_result.is_redacted or redacted_result.redacted_faces_count == 0:
        return RedactionVerificationMetrics(
            total_faces_targeted=total_targeted,
            successful_redactions=0,
            partial_redactions_detected=0,
            failed_redactions_detected=total_targeted,
            coverage_rate=0.0,
            zero_detection_triggered_review_count=1 if redacted_result.requires_human_review else 0,
        )

    # Measure coverage between detected redacted boxes and ground truth boxes
    covered_faces = 0
    partial_faces = 0
    for gt in ground_truth_boxes:
        max_overlap = 0.0
        for det in detected_faces:
            iou = compute_box_iou(det.bounding_box, gt)
            if iou > max_overlap:
                max_overlap = iou
        if max_overlap >= min_coverage_threshold:
            covered_faces += 1
        elif max_overlap > 0.10:
            partial_faces += 1

    failed = total_targeted - (covered_faces + partial_faces)
    coverage_rate = covered_faces / total_targeted if total_targeted > 0 else 0.0

    return RedactionVerificationMetrics(
        total_faces_targeted=total_targeted,
        successful_redactions=covered_faces,
        partial_redactions_detected=partial_faces,
        failed_redactions_detected=failed,
        coverage_rate=round(coverage_rate, 4),
        zero_detection_triggered_review_count=1 if redacted_result.requires_human_review else 0,
    )


# ---------------------------------------------------------------------------
# Full Evaluation Engine
# ---------------------------------------------------------------------------


def run_full_detection_robustness_audit() -> FaceDetectionRobustnessAuditReport:
    """Execute a comprehensive, reproducible detection and redaction robustness audit on synthetic fixtures."""
    # 1. Baseline Evaluation
    baseline_bytes, gt_boxes = generate_synthetic_face_image(width=640, height=480, num_faces=1)
    mock_detector = MockFaceDetectorProvider()

    base_det = mock_detector.detect_faces(baseline_bytes)
    base_metrics = compute_detection_metrics(gt_boxes, base_det.detected_faces)

    base_redaction = apply_face_redaction(baseline_bytes, base_det.detected_faces)
    base_redaction_metrics = verify_redaction_coverage(gt_boxes, base_redaction, base_det.detected_faces)

    # 2. Perturbation Robustness Evaluations
    conditions = ["blur", "low_light", "overexposure", "compression", "partial_occlusion"]
    condition_results: list[ConditionRobustnessResult] = []

    for cond in conditions:
        perturbed_bytes = apply_image_perturbation(baseline_bytes, cond)
        photo_quality = assess_photometric_quality(perturbed_bytes)

        # In mock detector, detection succeeds based on image header
        det_result = mock_detector.detect_faces(perturbed_bytes)
        cond_metrics = compute_detection_metrics(gt_boxes, det_result.detected_faces)

        redaction_res = apply_face_redaction(perturbed_bytes, det_result.detected_faces)
        red_metrics = verify_redaction_coverage(gt_boxes, redaction_res, det_result.detected_faces)

        # Evaluate unified decision to see if human review was triggered
        geom_res = verify_redaction_geometry(
            image_width=det_result.image_width,
            image_height=det_result.image_height,
            detected_faces=det_result.detected_faces,
        )
        decision, reasons = evaluate_unified_review_decision(
            detection_failed=False,
            redaction_failed=False,
            redacted_faces_count=redaction_res.redacted_faces_count,
            detected_faces_count=det_result.face_count,
            quality_result=photo_quality,
            geometry_result=geom_res,
        )

        review_req_rate = 1.0 if decision != UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW else 0.0

        condition_results.append(
            ConditionRobustnessResult(
                condition_name=cond,
                sample_count=1,
                metrics=cond_metrics,
                redaction_coverage=red_metrics.coverage_rate,
                human_review_required_rate=review_req_rate,
                notes=f"Photometric status: {photo_quality.quality_status.value}; decision: {decision.value}",
            )
        )

    # 3. Technical Subgroup Disparities (Non-identifying technical tiers)
    subgroups = [
        ("high_resolution_1080p", 1920, 1080, (140, 140, 140)),
        ("standard_resolution_480p", 640, 480, (140, 140, 140)),
        ("low_resolution_240p", 320, 240, (140, 140, 140)),
        ("high_contrast_scene", 640, 480, (30, 30, 30)),
        ("low_contrast_scene", 640, 480, (190, 190, 190)),
    ]
    subgroup_disparities: list[TechnicalSubgroupDisparity] = []

    for name, w, h, bg in subgroups:
        sub_bytes, sub_gt = generate_synthetic_face_image(width=w, height=h, fill_color=bg)
        sub_det = mock_detector.detect_faces(sub_bytes)
        sub_m = compute_detection_metrics(sub_gt, sub_det.detected_faces)

        # Disparity ratio relative to baseline recall
        disp_ratio = sub_m.recall / base_metrics.recall if base_metrics.recall > 0 else 1.0

        subgroup_disparities.append(
            TechnicalSubgroupDisparity(
                subgroup_name=name,
                sample_count=1,
                recall=sub_m.recall,
                precision=sub_m.precision,
                miss_rate=sub_m.miss_rate,
                disparity_ratio=round(disp_ratio, 4),
            )
        )

    # 4. Input Integrity & Spoof Resistance Checks
    integrity_checks: list[InputIntegrityCheckResult] = []

    # Check A: Malformed PNG header
    try:
        inspect_image_dimensions_and_format(b"\x89PNG\r\n\x1a\nTRUNCATED")
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="truncated_png_header",
                category="malformed_payload",
                expected_behavior="UnsupportedMediaTypeError",
                observed_outcome="Allowed",
                passed=False,
                details="Failed to fail closed on truncated PNG header.",
            )
        )
    except UnsupportedMediaTypeError as exc:
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="truncated_png_header",
                category="malformed_payload",
                expected_behavior="UnsupportedMediaTypeError",
                observed_outcome=f"Rejected safely: {type(exc).__name__}",
                passed=True,
                details="Truncated header rejected before memory allocation.",
            )
        )

    # Check B: Decompression Bomb Header
    fake_bomb = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", 8192, 8192, 8, 2, 0, 0, 0)
        + b"\x00\x00\x00\x00"
    )
    try:
        inspect_image_dimensions_and_format(fake_bomb)
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="decompression_bomb_dimension_check",
                category="resource_exhaustion",
                expected_behavior="ValueError (pixel budget exceeded)",
                observed_outcome="Allowed",
                passed=False,
                details="Decompression bomb dimensions bypassed pre-check.",
            )
        )
    except ValueError as exc:
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="decompression_bomb_dimension_check",
                category="resource_exhaustion",
                expected_behavior="ValueError (pixel budget exceeded)",
                observed_outcome=f"Rejected safely: {type(exc).__name__}",
                passed=True,
                details="Pre-allocation pixel budget check caught 8192x8192 bomb.",
            )
        )

    # Check C: Deceptive Extension / Non-image magic bytes
    try:
        inspect_image_dimensions_and_format(b"THIS_IS_NOT_AN_IMAGE_PAYLOAD")
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="deceptive_extension_text_payload",
                category="input_spoofing",
                expected_behavior="UnsupportedMediaTypeError",
                observed_outcome="Allowed",
                passed=False,
                details="Non-image payload accepted.",
            )
        )
    except UnsupportedMediaTypeError as exc:
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="deceptive_extension_text_payload",
                category="input_spoofing",
                expected_behavior="UnsupportedMediaTypeError",
                observed_outcome=f"Rejected safely: {type(exc).__name__}",
                passed=True,
                details="Non-image payload failed magic bytes inspection.",
            )
        )

    # Check D: Out-of-range bounding box coordinates
    try:
        invalid_face = DetectedFace(
            bounding_box=(-0.10, 0.20, 1.50, 0.80),
            confidence=0.90,
        )
        geom_check = verify_redaction_geometry(
            image_width=640,
            image_height=480,
            detected_faces=[invalid_face],
        )
        passed_coord = (not geom_check.geometry_valid) and geom_check.requires_human_review
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="out_of_range_bounding_box",
                category="coordinate_integrity",
                expected_behavior="ValueError on construction or geometry_valid=False",
                observed_outcome=f"valid={geom_check.geometry_valid}, review={geom_check.requires_human_review}",
                passed=passed_coord,
                details="Out-of-range normalized box coordinates flagged for mandatory review.",
            )
        )
    except ValueError as exc:
        integrity_checks.append(
            InputIntegrityCheckResult(
                test_case_name="out_of_range_bounding_box",
                category="coordinate_integrity",
                expected_behavior="ValueError on construction or geometry_valid=False",
                observed_outcome=f"Rejected safely on instantiation: {exc}",
                passed=True,
                details="DetectedFace post-init validation rejected non-normalized coordinates.",
            )
        )

    # Check E: Zero detection requires human review
    zero_redaction = apply_face_redaction(baseline_bytes, [])
    passed_zero = (not zero_redaction.is_redacted) and zero_redaction.requires_human_review
    integrity_checks.append(
        InputIntegrityCheckResult(
            test_case_name="zero_faces_detected_behavior",
            category="human_review_safeguard",
            expected_behavior="is_redacted=False and requires_human_review=True",
            observed_outcome=f"is_redacted={zero_redaction.is_redacted}, review={zero_redaction.requires_human_review}",
            passed=passed_zero,
            details="Zero detected faces triggers mandatory human inspection; not claimed as anonymized.",
        )
    )

    return FaceDetectionRobustnessAuditReport(
        audit_version="1.0.0",
        baseline_metrics=base_metrics,
        redaction_metrics=base_redaction_metrics,
        condition_evaluations=condition_results,
        technical_subgroups=subgroup_disparities,
        input_integrity_checks=integrity_checks,
        fairness_status="NOT ESTABLISHED",
    )
