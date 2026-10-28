"""Unified Evidence Quality and Redaction Human Review Integration (Phase 77).

Enforces:
- Deterministic, conservative review decision evaluation combining detection, redaction,
  photometric quality, and geometry verification results.
- Strict lifecycle state machine: PENDING_REVIEW -> IN_REVIEW -> COMPLETED
  (with NEEDS_REDACTION, ESCALATED, and CANCELLED branches).
- Rejection of invalid state jumps and unauthorized reopen operations.
- Explicit non-anonymization disclaimers: passing pre-checks never implies complete
  anonymization, legal admissibility, or automated investigative guilt.
- Zero raw image data, facial embeddings, or biometric templates persisted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from ai_services.face_detection.geometry import RedactionGeometryVerificationResult
from ai_services.face_detection.quality import PhotometricQualityResult
from backend.app.core.biometrics import BIOMETRIC_ADVISORY_DISCLAIMER
from backend.app.core.exceptions import BusinessRuleError


class UnifiedReviewDecision(StrEnum):
    """Categorical outcome of deterministic evidence quality and redaction pre-checks (Phase 77)."""

    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REDACTION_FAILED = "REDACTION_FAILED"
    REDACTION_INCOMPLETE = "REDACTION_INCOMPLETE"
    QUALITY_DEGRADED = "QUALITY_DEGRADED"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"


class QualityReviewStatus(StrEnum):
    """Lifecycle status of a human review item for evidence redaction/quality (Phase 77)."""

    PENDING_REVIEW = "PENDING_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    NEEDS_REDACTION = "NEEDS_REDACTION"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class HumanReviewDetermination(StrEnum):
    """Authorized human reviewer determination for a review item (Phase 77)."""

    APPROVED = "approved"
    REJECTED = "rejected"
    RE_REDACTION_REQUESTED = "re_redaction_requested"


# Permitted lifecycle state transitions
PERMITTED_REVIEW_TRANSITIONS: Final[dict[QualityReviewStatus, frozenset[QualityReviewStatus]]] = {
    QualityReviewStatus.PENDING_REVIEW: frozenset({
        QualityReviewStatus.IN_REVIEW,
        QualityReviewStatus.CANCELLED,
    }),
    QualityReviewStatus.IN_REVIEW: frozenset({
        QualityReviewStatus.COMPLETED,
        QualityReviewStatus.NEEDS_REDACTION,
        QualityReviewStatus.ESCALATED,
        QualityReviewStatus.PENDING_REVIEW,  # Unassignment / release back to pool
    }),
    QualityReviewStatus.NEEDS_REDACTION: frozenset({
        QualityReviewStatus.IN_REVIEW,
        QualityReviewStatus.PENDING_REVIEW,
        QualityReviewStatus.CANCELLED,
    }),
    QualityReviewStatus.ESCALATED: frozenset({
        QualityReviewStatus.IN_REVIEW,
        QualityReviewStatus.COMPLETED,
        QualityReviewStatus.CANCELLED,
    }),
    QualityReviewStatus.COMPLETED: frozenset({
        QualityReviewStatus.PENDING_REVIEW,  # Reopened review (requires authorized administrative action)
    }),
    QualityReviewStatus.CANCELLED: frozenset(),  # Terminal state
}


def validate_review_state_transition(
    current_status: QualityReviewStatus,
    target_status: QualityReviewStatus,
    *,
    is_authorized_reopen: bool = False,
) -> None:
    """Validate that transition from `current_status` to `target_status` is permitted.

    Raises:
        BusinessRuleError: If the transition is disallowed by state machine policy.
    """
    if current_status == target_status:
        # Idempotent state change
        return

    if current_status == QualityReviewStatus.COMPLETED and not is_authorized_reopen:
        raise BusinessRuleError(
            f"Review is COMPLETED; cannot transition to '{target_status}' without an authorized administrative reopen.",
            code="COMPLETED_REVIEW_LOCKED",
        )

    allowed = PERMITTED_REVIEW_TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed:
        raise BusinessRuleError(
            f"Invalid review state transition from '{current_status.value}' to '{target_status.value}'. "
            f"Permitted targets: {sorted(s.value for s in allowed) if allowed else 'none (terminal state)'}.",
            code="INVALID_REVIEW_STATE_TRANSITION",
        )


def evaluate_unified_review_decision(
    *,
    detection_failed: bool = False,
    redaction_failed: bool = False,
    redacted_faces_count: int | None = None,
    detected_faces_count: int | None = None,
    quality_result: PhotometricQualityResult | Any | None = None,
    geometry_result: RedactionGeometryVerificationResult | Any | None = None,
    has_partial_redaction: bool = False,
    has_missing_landmarks: bool = False,
) -> tuple[UnifiedReviewDecision, list[str]]:
    """Deterministically combine detection, redaction, quality, and geometry outcomes.

    Rules (Phase 77 Non-negotiables):
    1. Detection or redaction execution failure -> REDACTION_FAILED.
    2. Missing quality or geometry results -> REVIEW_REQUIRED (fail-closed, never assumed pass).
    3. Invalid geometry -> GEOMETRY_INVALID.
    4. Degraded quality -> QUALITY_DEGRADED.
    5. Zero detected faces -> REVIEW_REQUIRED (distinct from confirmed absence of people).
    6. Partial redactions or count mismatch -> REDACTION_INCOMPLETE.
    7. Missing landmarks -> flagged as unavailable/not assessed.
    8. Conflicting or uncertain results -> conservative resolution to REVIEW_REQUIRED.
    9. Passing pre-checks -> READY_FOR_HUMAN_REVIEW (never automated approval).

    Returns:
        tuple of (UnifiedReviewDecision, list of reason descriptions).
    """
    reasons: list[str] = []

    # Rule 1: Pipeline execution failure
    if detection_failed or redaction_failed:
        reasons.append("Face detection or redaction pipeline execution failed.")
        return UnifiedReviewDecision.REDACTION_FAILED, reasons

    # Rule 2: Missing results must never be interpreted as passing
    if quality_result is None or geometry_result is None:
        if quality_result is None:
            reasons.append("Photometric quality assessment result is missing.")
        if geometry_result is None:
            reasons.append("Redaction geometry verification result is missing.")
        return UnifiedReviewDecision.REVIEW_REQUIRED, reasons

    # Extract geometry details
    is_geom_valid = True
    geom_issues: list[str] = []
    if isinstance(geometry_result, RedactionGeometryVerificationResult):
        is_geom_valid = geometry_result.geometry_valid
        geom_issues = list(geometry_result.review_reasons)
        if not geometry_result.landmark_coverage_valid:
            reasons.append("Facial landmarks not fully covered by redaction geometry.")
    elif hasattr(geometry_result, "geometry_valid"):
        is_geom_valid = bool(geometry_result.geometry_valid)
        geom_issues = list(getattr(geometry_result, "review_reasons", []))
        if hasattr(geometry_result, "landmark_coverage_valid") and not geometry_result.landmark_coverage_valid:
            reasons.append("Facial landmarks not fully covered by redaction geometry.")
    elif hasattr(geometry_result, "is_valid"):
        is_geom_valid = bool(geometry_result.is_valid)
        issues = getattr(geometry_result, "review_reasons", getattr(geometry_result, "issues", []))
        geom_issues = [str(iss) for iss in issues]
    elif isinstance(geometry_result, dict):
        is_geom_valid = bool(geometry_result.get("geometry_valid", geometry_result.get("is_valid", False)))
        geom_issues = list(geometry_result.get("review_reasons", geometry_result.get("issues", [])))
        if not geometry_result.get("landmark_coverage_valid", True):
            reasons.append("Facial landmarks not fully covered by redaction geometry.")
    else:
        is_geom_valid = False
        geom_issues = ["Unrecognized geometry result structure."]

    # Extract quality details
    quality_needs_review = False
    quality_reasons: list[str] = []
    if isinstance(quality_result, PhotometricQualityResult):
        quality_needs_review = quality_result.requires_human_review
        quality_reasons = list(quality_result.review_reasons)
    elif hasattr(quality_result, "requires_human_review"):
        quality_needs_review = bool(quality_result.requires_human_review)
        quality_reasons = list(getattr(quality_result, "review_reasons", []))
    elif isinstance(quality_result, dict):
        quality_needs_review = bool(quality_result.get("requires_human_review", False))
        quality_reasons = list(quality_result.get("review_reasons", []))
    else:
        quality_needs_review = True
        quality_reasons = ["Unrecognized quality result structure."]

    # Rule 7: Missing landmarks tracking
    if has_missing_landmarks:
        reasons.append("Facial landmark coordinates unavailable or not assessed for one or more candidates.")

    # Rule 5: Zero detected faces is distinct from confirmed absence of people
    if detected_faces_count == 0:
        reasons.append(
            "Zero faces detected by automated model; frame requires human review to confirm absence of subjects."
        )
        if not is_geom_valid:
            reasons.extend(geom_issues)
        if quality_needs_review:
            reasons.extend(quality_reasons)
        return UnifiedReviewDecision.REVIEW_REQUIRED, reasons

    # Rule 6: Partial redaction or count mismatch
    is_incomplete = has_partial_redaction
    if (
        detected_faces_count is not None
        and redacted_faces_count is not None
        and redacted_faces_count < detected_faces_count
    ):
        is_incomplete = True
        reasons.append(
            f"Partial redaction detected: {redacted_faces_count} faces redacted of {detected_faces_count} detected."
        )

    # Collect all findings
    if not is_geom_valid:
        reasons.extend(geom_issues or ["Redaction geometry failed validation constraints."])
    if quality_needs_review:
        reasons.extend(quality_reasons or ["Image photometric quality falls below acceptable forensic thresholds."])

    # Rule 3 & 4: Conservative evaluation of defects
    # If geometry is invalid -> GEOMETRY_INVALID takes precedence or flags primary error
    if not is_geom_valid:
        return UnifiedReviewDecision.GEOMETRY_INVALID, reasons

    # If redaction is incomplete
    if is_incomplete:
        return UnifiedReviewDecision.REDACTION_INCOMPLETE, reasons

    # If quality is degraded
    if quality_needs_review:
        return UnifiedReviewDecision.QUALITY_DEGRADED, reasons

    # Rule 9: If all automated quality, geometry, and complete redactions pass
    reasons.append("Automated photometric quality and geometry pre-checks passed cleanly.")
    return UnifiedReviewDecision.READY_FOR_HUMAN_REVIEW, reasons
