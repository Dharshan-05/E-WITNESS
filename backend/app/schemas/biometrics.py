"""Pydantic schemas for Biometric Governance, Reference Registry, and Face Detection (Phases 71-75).

Enforces:
- Strict validation of purpose, lawful basis, and versioned notices.
- Complete exclusion of raw biometric material or encrypted templates from ordinary read schemas.
- Mandatory advisory disclaimer inclusion in face detection responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_services.face_detection.evaluation import (
    DETECTION_EVALUATION_ADVISORY_DISCLAIMER,
    FAIRNESS_NOT_ESTABLISHED_DISCLAIMER,
)
from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
)
from backend.app.core.biometrics import (
    BIOMETRIC_ADVISORY_DISCLAIMER,
    BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER,
    BiometricHumanVerdict,
    BiometricLawfulBasis,
    BiometricPurpose,
    GovernanceStatus,
    validate_biometric_purpose,
)


class BiometricGovernanceCreate(BaseModel):
    """Payload to register a new biometric governance, assessment, and consent record."""

    model_config = ConfigDict(extra="forbid")

    purpose: BiometricPurpose
    lawful_basis: BiometricLawfulBasis
    policy_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    notice_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    subject_user_id: UUID | None = None
    retention_days: int = Field(default=90, ge=1, le=365)
    consent_confirmed: bool = False
    legal_review_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("purpose")
    @classmethod
    def check_purpose(cls, value: BiometricPurpose) -> BiometricPurpose:
        validate_biometric_purpose(value.value)
        return value


class BiometricGovernanceReviewRequest(BaseModel):
    """Payload to record legal and operational review decision for a governance record."""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="Verdict: 'approved', 'rejected', or 'no_go'")
    legal_review_notes: str = Field(min_length=5, max_length=2000)

    @field_validator("decision")
    @classmethod
    def check_decision(cls, value: str) -> str:
        clean = value.strip().lower()
        if clean not in {
            GovernanceStatus.APPROVED.value,
            GovernanceStatus.REJECTED.value,
            GovernanceStatus.NO_GO.value,
        }:
            raise ValueError(f"Decision must be 'approved', 'rejected', or 'no_go'; got '{value}'.")
        return clean


class BiometricGovernanceRead(BaseModel):
    """Public read model for biometric governance records."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    department_id: UUID
    policy_version: str
    purpose: str
    lawful_basis: str
    notice_version: str
    subject_user_id: UUID | None
    status: str
    consent_status: str | None
    consented_at: datetime | None
    withdrawn_at: datetime | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    legal_review_notes: str | None
    retention_days: int
    retention_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BiometricConsentWithdrawRequest(BaseModel):
    """Request to withdraw consent for biometric processing."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class BiometricReferenceCreate(BaseModel):
    """Payload to enroll an approved biometric reference into the registry."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    purpose: BiometricPurpose
    template_digest: str = Field(min_length=64, max_length=64, description="64-char SHA-256 digest")
    subject_user_id: UUID | None = None
    encrypted_template: str | None = Field(
        default=None, description="Encrypted template ciphertext if stored"
    )
    provenance_evidence_id: UUID | None = None
    enrollment_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("purpose")
    @classmethod
    def check_purpose(cls, value: BiometricPurpose) -> BiometricPurpose:
        validate_biometric_purpose(value.value)
        return value

    @field_validator("template_digest")
    @classmethod
    def check_digest(cls, value: str) -> str:
        clean = value.strip().lower()
        if len(clean) != 64 or not all(c in "0123456789abcdef" for c in clean):
            raise ValueError(
                "template_digest must be a valid 64-character lowercase hex SHA-256 string."
            )
        return clean


class BiometricReferenceRead(BaseModel):
    """Public read model for biometric reference metadata.

    Security Guarantee: Never exposes raw template or encrypted template payloads.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference_id: str
    tenant_id: UUID
    department_id: UUID
    subject_user_id: UUID | None
    governance_record_id: UUID
    purpose: str
    status: str
    template_digest: str
    provenance_evidence_id: UUID | None
    enrollment_notes: str | None
    enrolled_by_id: UUID
    enrolled_at: datetime
    revoked_by_id: UUID | None
    revoked_at: datetime | None
    revocation_reason: str | None
    retention_expires_at: datetime
    created_at: datetime
    updated_at: datetime


class BiometricReferenceRevokeRequest(BaseModel):
    """Request to revoke an active biometric reference."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class DetectedFaceRead(BaseModel):
    """Individual face bounding box and localization confidence."""

    bounding_box: tuple[float, float, float, float]
    confidence: float
    landmarks: dict[str, tuple[float, float]] | None = None


class FaceDetectionRequest(BaseModel):
    """Payload to request face bounding box detection."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    image_base64: str | None = Field(default=None, description="Base64-encoded image bytes")
    evidence_id: UUID | None = Field(
        default=None, description="Optional linked evidence attachment identifier for scoping"
    )

    @model_validator(mode="after")
    def validate_source(self) -> FaceDetectionRequest:
        if not self.image_base64 and not self.evidence_id:
            raise ValueError("Either image_base64 or evidence_id must be provided.")
        return self


class FaceDetectionResponse(BaseModel):
    """Structured response from face detection endpoint."""

    detected_faces: list[DetectedFaceRead]
    face_count: int
    image_width: int
    image_height: int
    model_name: str
    model_version: str
    inference_latency_ms: float
    disclaimer: str = BIOMETRIC_ADVISORY_DISCLAIMER
    metadata: dict[str, str] = Field(default_factory=dict)


class FaceRedactionRequest(BaseModel):
    """Payload to request privacy-preserving face redaction on an image."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    image_base64: str | None = Field(default=None, description="Base64-encoded image bytes")
    evidence_id: UUID | None = Field(
        default=None, description="Optional linked evidence attachment identifier for scoping"
    )
    style: str = Field(
        default="solid_box",
        description="Redaction style: solid_box, blur, or pixelate",
    )
    min_confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum detection confidence"
    )
    padding_ratio: float = Field(
        default=0.1, ge=0.0, le=0.5, description="Bounding box expansion padding ratio"
    )
    consolidate_overlapping: bool = Field(
        default=False,
        description="Consolidate overlapping face bounding boxes into unified bounding envelopes prior to redaction",
    )

    @model_validator(mode="after")
    def validate_source(self) -> FaceRedactionRequest:
        if not self.image_base64 and not self.evidence_id:
            raise ValueError("Either image_base64 or evidence_id must be provided.")
        if self.style not in {"solid_box", "blur", "pixelate"}:
            raise ValueError("style must be one of: solid_box, blur, pixelate.")
        return self


class FaceRedactionResponse(BaseModel):
    """Structured response from face redaction endpoint."""

    redacted_image_base64: str
    redacted_faces_count: int
    image_format: str
    image_width: int
    image_height: int
    style: str
    disclaimer: str
    is_redacted: bool = False
    requires_human_review: bool = False
    review_reason: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PhotometricQualityRequest(BaseModel):
    """Payload to request non-identifying photometric quality assessment on an image (Phase 76)."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    image_base64: str | None = Field(default=None, description="Base64-encoded image bytes")
    evidence_id: UUID | None = Field(
        default=None, description="Optional linked evidence attachment identifier for scoping"
    )

    @model_validator(mode="after")
    def validate_source(self) -> PhotometricQualityRequest:
        if not self.image_base64 and not self.evidence_id:
            raise ValueError("Either image_base64 or evidence_id must be provided.")
        return self


class PhotometricQualityResponse(BaseModel):
    """Structured response from photometric quality assessment endpoint (Phase 76)."""

    sharpness_score: float = Field(ge=0.0, le=1.0)
    exposure_score: float = Field(ge=0.0, le=1.0)
    contrast_score: float = Field(ge=0.0, le=1.0)
    underexposed_fraction: float = Field(ge=0.0, le=1.0)
    overexposed_fraction: float = Field(ge=0.0, le=1.0)
    clipped_fraction: float = Field(ge=0.0, le=1.0)
    quality_status: str
    requires_human_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    raw_metrics: dict[str, float] = Field(default_factory=dict)
    image_width: int
    image_height: int
    image_format: str
    metric_version: str = "1.0.0"
    disclaimer: str


class RedactionGeometryRequest(BaseModel):
    """Payload to request geometry verification and consolidation for face redaction boxes (Phase 76)."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    image_width: int = Field(gt=0, le=4096)
    image_height: int = Field(gt=0, le=4096)
    detected_faces: list[DetectedFaceRead]
    padding_ratio: float = Field(default=0.10, ge=0.0, le=0.50)
    consolidate_overlapping: bool = True


class RedactionGeometryResponse(BaseModel):
    """Structured response from redaction geometry verification endpoint (Phase 76)."""

    geometry_valid: bool
    total_boxes: int
    valid_box_count: int
    invalid_box_count: int
    overlap_count: int
    clipped_box_count: int
    consolidated_boxes: list[tuple[float, float, float, float]] = Field(default_factory=list)
    landmark_coverage_valid: bool
    requires_human_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    geometry_version: str = "1.0.0"
    disclaimer: str


class PaginatedBiometricGovernanceRead(BaseModel):
    """Paginated collection of biometric governance records."""

    items: list[BiometricGovernanceRead]
    total: int
    limit: int
    offset: int


class PaginatedBiometricReferenceRead(BaseModel):
    """Paginated collection of biometric references."""

    items: list[BiometricReferenceRead]
    total: int
    limit: int
    offset: int


class FaceMatchRequest(BaseModel):
    """Payload to request advisory biometric face matching between probe and reference."""

    model_config = ConfigDict(extra="forbid")

    governance_record_id: UUID
    probe_image_base64: str = Field(
        min_length=1, description="Base64-encoded probe face image bytes"
    )
    reference_id: UUID | None = Field(
        default=None, description="UUID of registered biometric reference"
    )
    reference_image_base64: str | None = Field(
        default=None, description="Optional base64-encoded reference face image bytes"
    )
    incident_id: UUID | None = Field(
        default=None, description="Optional linked incident identifier"
    )

    @model_validator(mode="after")
    def validate_reference_source(self) -> FaceMatchRequest:
        if self.reference_id is None and not self.reference_image_base64:
            raise ValueError("Either reference_id or reference_image_base64 must be provided.")
        return self


class FaceMatchResponse(BaseModel):
    """Structured response from face matching endpoint."""

    similarity_score: float
    verdict: str
    uncertainty_lower_bound: float
    uncertainty_upper_bound: float
    probe_image_hash: str
    verification_review_id: UUID | None = None
    model_name: str
    model_version: str
    latency_ms: float
    disclaimer: str = BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER
    metadata: dict[str, Any] = Field(default_factory=dict)


class BiometricVerificationReviewCreate(BaseModel):
    """Payload for an authorized human reviewer recording a verification determination (Phase 77)."""

    model_config = ConfigDict(extra="forbid")

    human_verdict: BiometricHumanVerdict
    review_notes: str | None = Field(default=None, max_length=2000)
    override_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_override(self) -> BiometricVerificationReviewCreate:
        if self.human_verdict == BiometricHumanVerdict.REJECTED_OVERRIDE and not (
            self.override_reason and self.override_reason.strip()
        ):
            raise ValueError(
                "override_reason is strictly required when human_verdict is 'rejected_override'."
            )
        return self


class BiometricVerificationReviewRead(BaseModel):
    """Public read model for biometric verification review records."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    department_id: UUID
    incident_id: UUID | None
    reference_id: UUID | None
    probe_image_hash: str
    candidate_similarity: float
    uncertainty_lower_bound: float
    uncertainty_upper_bound: float
    automated_verdict: str
    human_verdict: str
    reviewer_id: UUID | None
    reviewed_at: datetime | None
    review_notes: str | None
    override_reason: str | None
    is_override: bool
    disclaimer: str = BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER
    created_at: datetime
    updated_at: datetime


class PaginatedBiometricVerificationReviewRead(BaseModel):
    """Paginated collection of biometric verification reviews."""

    items: list[BiometricVerificationReviewRead]
    total: int
    limit: int
    offset: int


class BiometricEvaluationSummaryRead(BaseModel):
    """Public read model summarizing biometric accuracy, fairness, and PAD benchmarks (Phase 79)."""

    model_name: str
    model_version: str
    total_comparisons: int
    fta_rate: float
    eer: float
    eer_threshold: float
    operational_fmr_at_085: float
    operational_fnmr_at_085: float
    max_demographic_disparity_ratio: float
    disclaimer: str
    pad_summary: dict[str, Any] | None = None
    subgroups: list[dict[str, Any]] = Field(default_factory=list)


class BiometricRetentionCleanupResponse(BaseModel):
    """Public read model summarizing biometric retention expiry cleanup (Phase 73)."""

    expired_references_count: int
    expired_governance_records_count: int
    purged_at: datetime
    message: str


# ---------------------------------------------------------------------------
# Biometric Evidence Quality & Redaction Review Schemas (Phase 77)
# ---------------------------------------------------------------------------


class BiometricQualityReviewCreate(BaseModel):
    """Payload to trigger unified review decision evaluation and persist review item."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID | None = None
    governance_record_id: UUID | None = None
    detection_failed: bool = False
    redaction_failed: bool = False
    redacted_faces_count: int | None = Field(default=None, ge=0)
    detected_faces_count: int | None = Field(default=None, ge=0)
    has_partial_redaction: bool = False
    has_missing_landmarks: bool = False
    quality_result: dict[str, Any] | None = None
    geometry_result: dict[str, Any] | None = None
    original_evidence_hash: str | None = Field(default=None, min_length=64, max_length=64)
    redacted_artifact_hash: str | None = Field(default=None, min_length=64, max_length=64)


class BiometricQualityReviewAssignRequest(BaseModel):
    """Payload to assign a review item to an authorized reviewer."""

    model_config = ConfigDict(extra="forbid")

    reviewer_id: UUID


class BiometricQualityReviewVerdictRequest(BaseModel):
    """Payload for recording authorized human review determination."""

    model_config = ConfigDict(extra="forbid")

    determination: str = Field(description="Determination: 'approved', 'rejected', or 're_redaction_requested'")
    notes: str | None = Field(default=None, max_length=2000)
    justification: str | None = Field(default=None, max_length=2000)

    @field_validator("determination")
    @classmethod
    def check_determination(cls, value: str) -> str:
        clean = value.strip().lower()
        valid = {d.value for d in HumanReviewDetermination}
        if clean not in valid:
            raise ValueError(f"determination must be one of: {sorted(valid)}; got '{value}'.")
        return clean

    @model_validator(mode="after")
    def validate_justification_for_rejection_or_re_redaction(self) -> BiometricQualityReviewVerdictRequest:
        if self.determination in {
            HumanReviewDetermination.REJECTED.value,
            HumanReviewDetermination.RE_REDACTION_REQUESTED.value,
        } and not (self.justification and self.justification.strip()):
            raise ValueError(
                f"justification is strictly required when determination is '{self.determination}'."
            )
        return self


class BiometricQualityReviewEscalateRequest(BaseModel):
    """Payload to escalate a review item to supervisory/admin review."""

    model_config = ConfigDict(extra="forbid")

    escalation_reason: str = Field(min_length=5, max_length=2000)


class BiometricQualityReviewReopenRequest(BaseModel):
    """Payload to administratively reopen a completed review item."""

    model_config = ConfigDict(extra="forbid")

    reopen_reason: str = Field(min_length=5, max_length=2000)


class BiometricQualityReviewRead(BaseModel):
    """Public read model for biometric evidence quality and redaction review records."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    department_id: UUID
    evidence_id: UUID | None
    governance_record_id: UUID | None
    status: str
    unified_decision: str
    review_reasons: list[str]
    component_versions: dict[str, str]
    photometric_metrics: dict[str, float]
    geometry_metrics: dict[str, Any]
    assigned_reviewer_id: UUID | None
    assigned_at: datetime | None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    human_determination: str | None
    reviewer_notes: str | None
    escalation_reason: str | None
    reopen_reason: str | None
    original_evidence_hash: str | None
    redacted_artifact_hash: str | None
    disclaimer: str
    created_at: datetime
    updated_at: datetime


class PaginatedBiometricQualityReviewRead(BaseModel):
    """Paginated collection of biometric quality reviews."""

    items: list[BiometricQualityReviewRead]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Biometric Template Encryption & Key Management Schemas (Phase 78)
# ---------------------------------------------------------------------------


class BiometricKeyMetadataRead(BaseModel):
    """Sanitized public read model for a biometric encryption key (Phase 78)."""

    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(..., description="Unique key identifier.")
    status: str = Field(..., description="Lifecycle status (active, rotated, revoked, retired, disabled).")
    algorithm: str = Field(default="AES-256-GCM", description="Cryptographic algorithm.")
    version: int = Field(default=1, description="Key version number.")
    created_at: datetime = Field(..., description="Key creation timestamp in UTC.")
    rotated_at: datetime | None = Field(default=None, description="Timestamp when key was rotated.")
    revoked_at: datetime | None = Field(default=None, description="Timestamp when key was revoked.")
    retired_at: datetime | None = Field(default=None, description="Timestamp when key was retired.")
    is_active: bool = Field(default=False, description="Whether this key is the active encryption key.")
    disclaimer: str = Field(
        default=BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER,
        description="Statutory legal disclaimer.",
    )


class BiometricReferenceReencryptRequest(BaseModel):
    """Request payload for re-encrypting a stored biometric reference (Phase 78)."""

    model_config = ConfigDict(extra="forbid")

    target_key_id: str | None = Field(
        default=None,
        description="Target key ID to re-encrypt under. If omitted, re-encrypts under active key.",
    )


class BiometricBatchReencryptRequest(BaseModel):
    """Request payload for batch re-encryption of biometric references (Phase 78)."""

    model_config = ConfigDict(extra="forbid")

    target_key_id: str | None = Field(
        default=None,
        description="Target key ID to re-encrypt under. If omitted, re-encrypts under active key.",
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Batch size for iterative re-encryption.",
    )


class BiometricBatchReencryptResponse(BaseModel):
    """Response payload summarizing batch re-encryption outcome (Phase 78)."""

    model_config = ConfigDict(extra="forbid")

    total_scanned: int = Field(..., description="Total reference records scanned.")
    reencrypted_count: int = Field(..., description="Number of references successfully re-encrypted.")
    skipped_count: int = Field(..., description="Number of references already under target key.")
    error_count: int = Field(..., description="Number of reference re-encryption failures.")
    target_key_id: str = Field(..., description="Target key ID used for re-encryption.")
    disclaimer: str = Field(
        default=BIOMETRIC_MATCHING_ADVISORY_DISCLAIMER,
        description="Statutory legal disclaimer.",
    )


# ---------------------------------------------------------------------------
# Face Detection Robustness & Fairness Evaluation Schemas (Phase 79)
# ---------------------------------------------------------------------------


class DetectionMetricsRead(BaseModel):
    """Detection performance metrics measured against synthetic ground truth."""

    model_config = ConfigDict(extra="forbid")

    total_ground_truth: int = Field(..., description="Total ground truth faces in evaluation.")
    total_detected: int = Field(..., description="Total bounding boxes detected.")
    true_positives: int = Field(..., description="Ground truth faces matched by detection.")
    false_positives: int = Field(..., description="Detections not matching any ground truth face.")
    false_negatives: int = Field(..., description="Ground truth faces missed by detector.")
    precision: float = Field(..., description="Precision score [0.0, 1.0].")
    recall: float = Field(..., description="Recall score [0.0, 1.0].")
    miss_rate: float = Field(..., description="Miss rate (FN / GT) [0.0, 1.0].")
    f1_score: float = Field(..., description="F1 harmonic mean score [0.0, 1.0].")
    mean_iou: float = Field(..., description="Mean Intersection-over-Union for true positives.")


class RedactionVerificationMetricsRead(BaseModel):
    """Verification metrics for privacy redaction coverage and failure detection."""

    model_config = ConfigDict(extra="forbid")

    total_faces_targeted: int = Field(..., description="Total ground truth faces targeted.")
    successful_redactions: int = Field(..., description="Faces fully covered by redaction mask.")
    partial_redactions_detected: int = Field(..., description="Faces partially covered by mask.")
    failed_redactions_detected: int = Field(..., description="Faces missed entirely by mask.")
    coverage_rate: float = Field(..., description="Redaction coverage rate [0.0, 1.0].")
    zero_detection_triggered_review_count: int = Field(
        ...,
        description="Number of zero-detection scenarios safely triggering human review.",
    )


class ConditionRobustnessResultRead(BaseModel):
    """Robustness evaluation result under a specific technical image condition."""

    model_config = ConfigDict(extra="forbid")

    condition_name: str = Field(..., description="Condition name (e.g., blur, low_light, compression).")
    sample_count: int = Field(..., description="Number of test samples evaluated.")
    metrics: DetectionMetricsRead = Field(..., description="Detection performance under this condition.")
    redaction_coverage: float = Field(..., description="Redaction coverage rate under this condition.")
    human_review_required_rate: float = Field(
        ...,
        description="Fraction of images requiring mandatory human review.",
    )
    notes: str = Field(..., description="Technical notes and diagnostic observations.")


class TechnicalSubgroupDisparityRead(BaseModel):
    """Disparity analysis across non-identifying technical image categories."""

    model_config = ConfigDict(extra="forbid")

    subgroup_name: str = Field(..., description="Technical subgroup name (e.g., resolution, contrast).")
    sample_count: int = Field(..., description="Number of samples evaluated.")
    recall: float = Field(..., description="Detection recall for this subgroup.")
    precision: float = Field(..., description="Detection precision for this subgroup.")
    miss_rate: float = Field(..., description="Detection miss rate for this subgroup.")
    disparity_ratio: float = Field(
        ...,
        description="Disparity ratio relative to standard baseline recall.",
    )


class InputIntegrityCheckResultRead(BaseModel):
    """Result of testing an input integrity, malformed payload, or adversarial boundary."""

    model_config = ConfigDict(extra="forbid")

    test_case_name: str = Field(..., description="Test case name.")
    category: str = Field(..., description="Threat category (e.g., resource_exhaustion, malformed_payload).")
    expected_behavior: str = Field(..., description="Expected safe behavior / error code.")
    observed_outcome: str = Field(..., description="Observed system outcome.")
    passed: bool = Field(..., description="Whether the integrity safeguard passed.")
    details: str = Field(..., description="Technical details of the test execution.")


class FaceDetectionRobustnessAuditRead(BaseModel):
    """Comprehensive Phase 79 audit report evaluating detection, robustness, fairness, and input integrity."""

    model_config = ConfigDict(extra="forbid")

    audit_version: str = Field(default="1.0.0", description="Audit schema version.")
    baseline_metrics: DetectionMetricsRead = Field(..., description="Baseline detection metrics on synthetic ground truth.")
    redaction_metrics: RedactionVerificationMetricsRead = Field(..., description="Baseline privacy redaction coverage.")
    condition_evaluations: list[ConditionRobustnessResultRead] = Field(
        ...,
        description="Performance under controlled perturbations (blur, low light, overexposure, compression).",
    )
    technical_subgroups: list[TechnicalSubgroupDisparityRead] = Field(
        ...,
        description="Disparities across non-identifying technical tiers (resolution, contrast).",
    )
    input_integrity_checks: list[InputIntegrityCheckResultRead] = Field(
        ...,
        description="Input integrity and spoof resistance test results.",
    )
    fairness_status: str = Field(
        default="NOT ESTABLISHED",
        description="Demographic fairness verification status.",
    )
    fairness_disclaimer: str = Field(
        default=FAIRNESS_NOT_ESTABLISHED_DISCLAIMER,
        description="Mandatory disclaimer stating demographic fairness cannot be claimed.",
    )
    disclaimer: str = Field(
        default=DETECTION_EVALUATION_ADVISORY_DISCLAIMER,
        description="Mandatory advisory disclaimer.",
    )
