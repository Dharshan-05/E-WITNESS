"""Redaction geometry verification and overlap consolidation module (Phase 76).

Enforces:
- Non-identifying mathematical verification of normalized bounding-box geometry and landmark coverage.
- Validation of coordinate boundaries, ordering, area positivity, and edge clipping.
- Overlap detection (Intersection-over-Union, IoU) and consolidation to ensure protected regions never shrink.
- Complete segregation from biometric recognition: zero embeddings, zero descriptors, zero identity templates.
- Explicit human review triggers for invalid, clipped, degenerate, or atypical aspect ratio boxes.
- Mandatory advisory disclaimer: geometry verification does not certify complete concealment or identity protection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Final

from ai_services.face_detection.detector import MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS, _validate_dimensions
from ai_services.face_detection.protocol import DetectedFace

REDACTION_GEOMETRY_ADVISORY_DISCLAIMER: Final[str] = (
    "REDACTION GEOMETRY ADVISORY: Geometry verification evaluates mathematical bounds, overlap, "
    "and landmark coverage of detected regions. It does not verify facial identity or guarantee that "
    "all identifying visual features in the scene have been detected or redacted."
)


@dataclass(frozen=True)
class RedactionGeometryPolicy:
    """Configurable heuristics governing bounding box validation and overlap consolidation."""

    padding_ratio: float = 0.10
    min_aspect_ratio: float = 0.35  # Width / Height lower bound heuristic
    max_aspect_ratio: float = 2.85  # Width / Height upper bound heuristic
    overlap_iou_threshold: float = 0.15  # IoU threshold for considering two boxes overlapping
    consolidate_overlapping: bool = True  # Whether to merge overlapping boxes into bounding envelopes

    def __post_init__(self) -> None:
        if not (0.0 <= self.padding_ratio <= 0.5):
            raise ValueError("padding_ratio must be between 0.0 and 0.5.")
        if self.min_aspect_ratio <= 0.0 or self.max_aspect_ratio <= self.min_aspect_ratio:
            raise ValueError("Invalid aspect ratio bounds: min must be > 0 and < max.")
        if not (0.0 <= self.overlap_iou_threshold <= 1.0):
            raise ValueError("overlap_iou_threshold must be between 0.0 and 1.0.")


@dataclass(frozen=True)
class RedactionGeometryVerificationResult:
    """Structured result of a redaction geometry evaluation."""

    geometry_valid: bool
    total_boxes: int
    valid_box_count: int
    invalid_box_count: int
    overlap_count: int
    clipped_box_count: int
    consolidated_boxes: list[tuple[float, float, float, float]]
    landmark_coverage_valid: bool
    requires_human_review: bool
    review_reasons: list[str]
    geometry_version: str = "1.0.0"
    disclaimer: str = REDACTION_GEOMETRY_ADVISORY_DISCLAIMER

    def __post_init__(self) -> None:
        if self.total_boxes < 0 or self.valid_box_count < 0 or self.invalid_box_count < 0:
            raise ValueError("Box counts cannot be negative.")


def compute_box_iou(
    box_a: tuple[float, float, float, float],
    box_b: tuple[float, float, float, float],
) -> float:
    """Compute Intersection-over-Union (IoU) between two normalized boxes (ymin, xmin, ymax, xmax)."""
    ymin_a, xmin_a, ymax_a, xmax_a = box_a
    ymin_b, xmin_b, ymax_b, xmax_b = box_b

    # Determine intersection rectangle
    int_ymin = max(ymin_a, ymin_b)
    int_xmin = max(xmin_a, xmin_b)
    int_ymax = min(ymax_a, ymax_b)
    int_xmax = min(xmax_a, xmax_b)

    if int_ymin >= int_ymax or int_xmin >= int_xmax:
        return 0.0

    int_area = (int_ymax - int_ymin) * (int_xmax - int_xmin)
    area_a = (ymax_a - ymin_a) * (xmax_a - xmin_a)
    area_b = (ymax_b - ymin_b) * (xmax_b - xmin_b)

    union_area = area_a + area_b - int_area
    if union_area <= 0.0:
        return 0.0

    iou = int_area / union_area
    return max(0.0, min(1.0, float(iou)))


def consolidate_overlapping_boxes(
    boxes: list[tuple[float, float, float, float]],
    iou_threshold: float = 0.15,
) -> tuple[list[tuple[float, float, float, float]], int]:
    """Consolidate overlapping bounding boxes into unified bounding envelopes using connected components.

    Returns:
        tuple of (consolidated_boxes, overlap_pair_count).
    """
    if not boxes:
        return [], 0

    n = len(boxes)
    # Adjacency graph for connected components
    adj: list[list[int]] = [[] for _ in range(n)]
    overlap_pairs = 0

    for i in range(n):
        for j in range(i + 1, n):
            iou = compute_box_iou(boxes[i], boxes[j])
            if iou >= iou_threshold:
                adj[i].append(j)
                adj[j].append(i)
                overlap_pairs += 1

    visited = [False] * n
    consolidated: list[tuple[float, float, float, float]] = []

    for i in range(n):
        if visited[i]:
            continue

        # BFS / DFS to collect all boxes in this connected component
        component: list[int] = []
        queue = [i]
        visited[i] = True

        while queue:
            curr = queue.pop(0)
            component.append(curr)
            for neighbor in adj[curr]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)

        # Merge all boxes in the component into their minimal enclosing bounding envelope
        c_ymin = min(boxes[idx][0] for idx in component)
        c_xmin = min(boxes[idx][1] for idx in component)
        c_ymax = max(boxes[idx][2] for idx in component)
        c_xmax = max(boxes[idx][3] for idx in component)

        consolidated.append((c_ymin, c_xmin, c_ymax, c_xmax))

    return consolidated, overlap_pairs


def verify_redaction_geometry(
    detected_faces: list[DetectedFace],
    image_width: int,
    image_height: int,
    policy: RedactionGeometryPolicy | None = None,
) -> RedactionGeometryVerificationResult:
    """Verify geometrical integrity, aspect ratios, edge clipping, and landmark coverage of face boxes.

    Raises:
        ValueError: If image dimensions violate safe bounds.
    """
    _validate_dimensions(image_width, image_height)
    pol = policy or RedactionGeometryPolicy()

    review_reasons: list[str] = []
    valid_boxes: list[tuple[float, float, float, float]] = []
    invalid_box_count = 0
    clipped_box_count = 0
    landmark_coverage_valid = True

    if len(detected_faces) == 0:
        return RedactionGeometryVerificationResult(
            geometry_valid=True,
            total_boxes=0,
            valid_box_count=0,
            invalid_box_count=0,
            overlap_count=0,
            clipped_box_count=0,
            consolidated_boxes=[],
            landmark_coverage_valid=True,
            requires_human_review=False,
            review_reasons=[],
            geometry_version="1.0.0",
        )

    seen_boxes: set[tuple[float, float, float, float]] = set()

    for idx, face in enumerate(detected_faces):
        box = face.bounding_box
        ymin, xmin, ymax, xmax = box

        # 1. Finite coordinate check
        if not (
            math.isfinite(ymin)
            and math.isfinite(xmin)
            and math.isfinite(ymax)
            and math.isfinite(xmax)
        ):
            invalid_box_count += 1
            review_reasons.append(f"Box {idx} contains non-finite (NaN or Inf) coordinates.")
            continue

        # 2. Coordinate ordering check
        if ymin >= ymax or xmin >= xmax:
            invalid_box_count += 1
            review_reasons.append(
                f"Box {idx} has invalid ordering: ymin ({ymin}) >= ymax ({ymax}) or xmin ({xmin}) >= xmax ({xmax})."
            )
            continue

        # 3. Normalized boundaries and edge clipping check
        is_clipped = False
        c_ymin = max(0.0, ymin)
        c_xmin = max(0.0, xmin)
        c_ymax = min(1.0, ymax)
        c_xmax = min(1.0, xmax)

        if c_ymin != ymin or c_xmin != xmin or c_ymax != ymax or c_xmax != xmax:
            is_clipped = True
            clipped_box_count += 1

        # Check for positive area after clipping
        clipped_w = c_xmax - c_xmin
        clipped_h = c_ymax - c_ymin
        if clipped_w <= 0.0 or clipped_h <= 0.0:
            invalid_box_count += 1
            review_reasons.append(f"Box {idx} has non-positive area after boundary clipping.")
            continue

        clipped_box = (c_ymin, c_xmin, c_ymax, c_xmax)

        # 4. Duplicate box detection
        rounded_box = (
            round(c_ymin, 5),
            round(c_xmin, 5),
            round(c_ymax, 5),
            round(c_xmax, 5),
        )
        if rounded_box in seen_boxes:
            review_reasons.append(f"Box {idx} is a duplicate of a previously inspected bounding box.")
        seen_boxes.add(rounded_box)

        # 5. Aspect ratio heuristic check
        aspect_ratio = clipped_w / clipped_h
        if aspect_ratio < pol.min_aspect_ratio or aspect_ratio > pol.max_aspect_ratio:
            review_reasons.append(
                f"Box {idx} has unusual aspect ratio ({aspect_ratio:.2f}); heuristic bounds are "
                f"[{pol.min_aspect_ratio:.2f}, {pol.max_aspect_ratio:.2f}]."
            )

        # 6. Landmark coverage check if landmarks are provided
        if face.landmarks:
            # Padded box envelope
            pad_x = clipped_w * pol.padding_ratio
            pad_y = clipped_h * pol.padding_ratio
            padded_ymin = max(0.0, c_ymin - pad_y)
            padded_xmin = max(0.0, c_xmin - pad_x)
            padded_ymax = min(1.0, c_ymax + pad_y)
            padded_xmax = min(1.0, c_xmax + pad_x)

            for lm_name, coords in face.landmarks.items():
                if len(coords) != 2:
                    landmark_coverage_valid = False
                    review_reasons.append(f"Box {idx} landmark '{lm_name}' has invalid dimension (expected 2).")
                    continue
                ly, lx = coords
                if not (math.isfinite(ly) and math.isfinite(lx)):
                    landmark_coverage_valid = False
                    review_reasons.append(f"Box {idx} landmark '{lm_name}' contains non-finite coordinates.")
                    continue
                if not (0.0 <= ly <= 1.0 and 0.0 <= lx <= 1.0):
                    landmark_coverage_valid = False
                    review_reasons.append(
                        f"Box {idx} landmark '{lm_name}' ({ly:.3f}, {lx:.3f}) is outside normalized [0.0, 1.0] bounds."
                    )
                    continue

                # Check if landmark is inside padded box
                if not (padded_ymin <= ly <= padded_ymax and padded_xmin <= lx <= padded_xmax):
                    landmark_coverage_valid = False
                    review_reasons.append(
                        f"Box {idx} landmark '{lm_name}' ({ly:.3f}, {lx:.3f}) falls outside padded redaction envelope "
                        f"[{padded_ymin:.3f}, {padded_xmin:.3f}, {padded_ymax:.3f}, {padded_xmax:.3f}]."
                    )

        valid_boxes.append(clipped_box)

    # 7. Overlap analysis and consolidation
    if pol.consolidate_overlapping:
        consolidated_boxes, overlap_count = consolidate_overlapping_boxes(
            valid_boxes, iou_threshold=pol.overlap_iou_threshold
        )
    else:
        consolidated_boxes = valid_boxes
        _, overlap_count = consolidate_overlapping_boxes(
            valid_boxes, iou_threshold=pol.overlap_iou_threshold
        )

    if overlap_count > 0:
        review_reasons.append(
            f"Detected {overlap_count} overlapping box pair(s) with IoU >= {pol.overlap_iou_threshold:.2f}."
        )

    geometry_valid = (invalid_box_count == 0) and landmark_coverage_valid
    requires_human_review = (
        not geometry_valid
        or len(review_reasons) > 0
        or clipped_box_count > 0
    )

    return RedactionGeometryVerificationResult(
        geometry_valid=geometry_valid,
        total_boxes=len(detected_faces),
        valid_box_count=len(valid_boxes),
        invalid_box_count=invalid_box_count,
        overlap_count=overlap_count,
        clipped_box_count=clipped_box_count,
        consolidated_boxes=consolidated_boxes,
        landmark_coverage_valid=landmark_coverage_valid,
        requires_human_review=requires_human_review,
        review_reasons=review_reasons,
        geometry_version="1.0.0",
        disclaimer=REDACTION_GEOMETRY_ADVISORY_DISCLAIMER,
    )
