"""Biometric Privacy, Governance, Reference Registry, and Face Detection API routes (Phases 71-75).

Enforces:
- Tenant and department boundary isolation on every operation.
- Purpose-binding and affirmative legal governance prerequisites.
- Automatic cascading reference revocation upon subject consent withdrawal.
- Zero raw biometric template or embedding disclosure in API responses.
- Fail-closed execution for face detection without persistent image storage.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ai_services.face_detection.protocol import DetectedFace
from backend.app.api.dependencies import (
    BiometricEvaluationServiceDep,
    BiometricGovernanceServiceDep,
    BiometricReferenceServiceDep,
    BiometricVerificationServiceDep,
    QualityReviewWorkflowServiceDep,
    CurrentUserDep,
    FaceDetectionServiceDep,
    FaceMatchingServiceDep,
    require_permission,
    require_any_permission,
)
from backend.app.core.authorization import Permission
from backend.app.core.exceptions import BusinessRuleError
from backend.app.schemas.biometrics import (
    BiometricConsentWithdrawRequest,
    BiometricRetentionCleanupResponse,
    BiometricEvaluationSummaryRead,
    BiometricGovernanceCreate,
    BiometricGovernanceRead,
    BiometricGovernanceReviewRequest,
    BiometricReferenceCreate,
    BiometricReferenceRead,
    BiometricBatchReencryptRequest,
    BiometricBatchReencryptResponse,
    BiometricKeyMetadataRead,
    BiometricReferenceReencryptRequest,
    BiometricReferenceRevokeRequest,
    BiometricVerificationReviewCreate,
    BiometricVerificationReviewRead,
    FaceDetectionRequest,
    FaceDetectionResponse,
    FaceDetectionRobustnessAuditRead,
    FaceRedactionRequest,
    FaceRedactionResponse,
    FaceMatchRequest,
    FaceMatchResponse,
    PhotometricQualityRequest,
    PhotometricQualityResponse,
    RedactionGeometryRequest,
    RedactionGeometryResponse,
    PaginatedBiometricGovernanceRead,
    PaginatedBiometricReferenceRead,
    PaginatedBiometricVerificationReviewRead,
    BiometricQualityReviewAssignRequest,
    BiometricQualityReviewCreate,
    BiometricQualityReviewEscalateRequest,
    BiometricQualityReviewRead,
    BiometricQualityReviewReopenRequest,
    BiometricQualityReviewVerdictRequest,
    PaginatedBiometricQualityReviewRead,
)

router = APIRouter(prefix="/biometrics", tags=["Biometrics & Face Detection"])


# ---------------------------------------------------------------------------
# Biometric Governance & Feasibility Endpoints (Phases 71 & 73)
# ---------------------------------------------------------------------------


@router.post(
    "/governance",
    response_model=BiometricGovernanceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new biometric processing governance assessment or consent record",
)
async def create_governance_record(
    payload: BiometricGovernanceCreate,
    principal: CurrentUserDep,
    service: BiometricGovernanceServiceDep,
) -> BiometricGovernanceRead:
    """Create a new biometric governance and consent record."""
    return await service.create_governance_record(payload, principal)


@router.get(
    "/governance",
    response_model=PaginatedBiometricGovernanceRead,
    status_code=status.HTTP_200_OK,
    summary="List biometric governance records for authenticated department",
)
async def list_governance_records(
    principal: CurrentUserDep,
    service: BiometricGovernanceServiceDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedBiometricGovernanceRead:
    """List biometric governance records with optional status filtering."""
    return await service.list_governance_records(
        principal,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/governance/{record_id}",
    response_model=BiometricGovernanceRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single biometric governance record",
)
async def get_governance_record(
    record_id: UUID,
    principal: CurrentUserDep,
    service: BiometricGovernanceServiceDep,
) -> BiometricGovernanceRead:
    """Retrieve details for a specific biometric governance record."""
    return await service.get_governance_record(record_id, principal)


@router.post(
    "/governance/{record_id}/review",
    response_model=BiometricGovernanceRead,
    status_code=status.HTTP_200_OK,
    summary="Submit formal review decision for biometric governance record",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_GOVERNANCE_REVIEW))],
)
async def review_governance_record(
    record_id: UUID,
    payload: BiometricGovernanceReviewRequest,
    principal: CurrentUserDep,
    service: BiometricGovernanceServiceDep,
) -> BiometricGovernanceRead:
    """Record legal or operational approval, rejection, or NO-GO decision."""
    return await service.review_governance_record(record_id, payload, principal)


@router.post(
    "/governance/{record_id}/withdraw",
    response_model=BiometricGovernanceRead,
    status_code=status.HTTP_200_OK,
    summary="Withdraw biometric consent and trigger cascading revocation",
)
async def withdraw_consent(
    record_id: UUID,
    payload: BiometricConsentWithdrawRequest,
    principal: CurrentUserDep,
    service: BiometricGovernanceServiceDep,
) -> BiometricGovernanceRead:
    """Withdraw consent, halting future processing and revoking active references."""
    return await service.withdraw_consent(record_id, payload, principal)


# ---------------------------------------------------------------------------
# Restricted Biometric Reference Registry Endpoints (Phase 74)
# ---------------------------------------------------------------------------


@router.post(
    "/references",
    response_model=BiometricReferenceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll approved biometric reference into restricted registry",
)
async def enroll_reference(
    payload: BiometricReferenceCreate,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricReferenceRead:
    """Enroll a biometric reference under an approved governance record."""
    return await service.enroll_reference(payload, principal)


@router.get(
    "/references",
    response_model=PaginatedBiometricReferenceRead,
    status_code=status.HTTP_200_OK,
    summary="List biometric references scoped to department",
)
async def list_references(
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedBiometricReferenceRead:
    """List biometric references metadata without exposing template payloads."""
    return await service.list_references(
        principal,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/references/{reference_id}",
    response_model=BiometricReferenceRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve biometric reference metadata",
)
async def get_reference(
    reference_id: UUID,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricReferenceRead:
    """Retrieve metadata for a single biometric reference without template payload."""
    return await service.get_reference(reference_id, principal)


@router.post(
    "/references/{reference_id}/revoke",
    response_model=BiometricReferenceRead,
    status_code=status.HTTP_200_OK,
    summary="Revoke an active biometric reference",
)
async def revoke_reference(
    reference_id: UUID,
    payload: BiometricReferenceRevokeRequest,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricReferenceRead:
    """Revoke a biometric reference and permanently wipe its stored template."""
    return await service.revoke_reference(reference_id, payload, principal)


@router.post(
    "/references/{reference_id}/reencrypt",
    response_model=BiometricReferenceRead,
    status_code=status.HTTP_200_OK,
    summary="Re-encrypt an active biometric reference under active or rotated key (Phase 78)",
)
async def reencrypt_reference(
    reference_id: UUID,
    payload: BiometricReferenceReencryptRequest,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricReferenceRead:
    """Re-encrypt reference under designated active key with post-encryption digest verification."""
    return await service.reencrypt_reference(
        reference_id,
        principal,
        new_key_id=payload.target_key_id,
    )


@router.post(
    "/references/reencrypt-batch",
    response_model=BiometricBatchReencryptResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch re-encrypt active references under active key (Phase 78)",
)
async def batch_reencrypt_references(
    payload: BiometricBatchReencryptRequest,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricBatchReencryptResponse:
    """Batch re-encrypt active references under active key with idempotent skipping."""
    return await service.batch_reencrypt_references(
        principal,
        new_key_id=payload.target_key_id,
        batch_size=payload.batch_size,
    )


# ---------------------------------------------------------------------------
# Biometric Cryptographic Key Management Endpoints (Phase 78)
# ---------------------------------------------------------------------------


@router.get(
    "/keys",
    response_model=list[BiometricKeyMetadataRead],
    status_code=status.HTTP_200_OK,
    summary="List biometric encryption keys metadata (Phase 78)",
)
def list_keys(
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> list[BiometricKeyMetadataRead]:
    """List metadata for all known encryption keys. Strictly excludes raw key material."""
    return service.list_keys(principal)


@router.post(
    "/keys/rotate",
    response_model=BiometricKeyMetadataRead,
    status_code=status.HTTP_200_OK,
    summary="Rotate active biometric encryption key (Phase 78)",
)
async def rotate_key(
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricKeyMetadataRead:
    """Rotate the active encryption key by activating a newly generated key."""
    return await service.rotate_key(principal)


@router.post(
    "/keys/{key_id}/revoke",
    response_model=BiometricKeyMetadataRead,
    status_code=status.HTTP_200_OK,
    summary="Revoke a biometric encryption key (Phase 78)",
)
async def revoke_key(
    key_id: str,
    principal: CurrentUserDep,
    service: BiometricReferenceServiceDep,
) -> BiometricKeyMetadataRead:
    """Revoke a key, causing all future decryption attempts under it to fail closed."""
    return await service.revoke_key(key_id, principal)


# ---------------------------------------------------------------------------
# Biometric Retention & Expiry Cleanup Endpoint (Phase 73)
# ---------------------------------------------------------------------------


@router.post(
    "/retention/cleanup",
    response_model=BiometricRetentionCleanupResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute authorized retention expiry cleanup and cryptographic template purging",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_CONFIG_MANAGE))],
)
async def cleanup_expired_retention(
    principal: CurrentUserDep,
    gov_service: BiometricGovernanceServiceDep,
    ref_service: BiometricReferenceServiceDep,
) -> BiometricRetentionCleanupResponse:
    """Scan and transition expired consent records and biometric references to EXPIRED status.

    Permanently purges encrypted templates (cryptographic erasure).
    """
    expired_gov = await gov_service.cleanup_expired_governance(principal)
    expired_refs = await ref_service.cleanup_expired_references(principal)
    now = datetime.now(UTC)
    return BiometricRetentionCleanupResponse(
        expired_references_count=expired_refs,
        expired_governance_records_count=expired_gov,
        purged_at=now,
        message=(
            f"Retention cleanup complete: {expired_refs} references and {expired_gov} "
            "governance records transitioned to EXPIRED with templates purged."
        ),
    )


# ---------------------------------------------------------------------------
# Approved Face Detection Endpoint (Phase 75)
# ---------------------------------------------------------------------------


@router.post(
    "/detect",
    response_model=FaceDetectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute approved face detection (bounding box localization only)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_DETECTION_EXECUTE))],
)
async def detect_faces(
    request: Request,
    principal: CurrentUserDep,
    service: FaceDetectionServiceDep,
    payload: FaceDetectionRequest | None = None,
    governance_record_id: Annotated[UUID | None, Query()] = None,
) -> FaceDetectionResponse:
    """Detect face bounding boxes under an approved governance record."""
    content_type = request.headers.get("content-type", "")
    evidence_id: UUID | None = None
    if payload is not None:
        rec_id = payload.governance_record_id
        evidence_id = payload.evidence_id
        if not payload.image_base64:
            raise BusinessRuleError("image_base64 is required for direct detection")
        try:
            image_bytes = base64.b64decode(payload.image_base64)
        except Exception as exc:
            raise BusinessRuleError("Invalid base64 encoding for image") from exc
    elif "application/json" in content_type:
        body_json = await request.json()
        req = FaceDetectionRequest(**body_json)
        rec_id = req.governance_record_id
        evidence_id = req.evidence_id
        if not req.image_base64:
            raise BusinessRuleError("image_base64 is required for direct detection")
        try:
            image_bytes = base64.b64decode(req.image_base64)
        except Exception as exc:
            raise BusinessRuleError("Invalid base64 encoding for image") from exc
    else:
        if governance_record_id is None:
            raise BusinessRuleError(
                "governance_record_id query parameter is required when posting raw image bytes"
            )
        rec_id = governance_record_id
        image_bytes = await request.body()

    return await service.detect_faces(image_bytes, rec_id, principal, evidence_id=evidence_id)


@router.post(
    "/redact",
    response_model=FaceRedactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute privacy-preserving face redaction on image",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_DETECTION_EXECUTE))],
)
async def redact_faces(
    payload: FaceRedactionRequest,
    principal: CurrentUserDep,
    service: FaceDetectionServiceDep,
) -> FaceRedactionResponse:
    """Apply privacy-preserving face redaction (solid box, blur, pixelate) under an approved governance record."""
    if not payload.image_base64:
        raise BusinessRuleError("image_base64 is required for face redaction")
    try:
        image_bytes = base64.b64decode(payload.image_base64)
    except Exception as exc:
        raise BusinessRuleError("Invalid base64 encoding for image") from exc

    return await service.redact_faces(
        image_bytes=image_bytes,
        governance_record_id=payload.governance_record_id,
        principal=principal,
        evidence_id=payload.evidence_id,
        style=payload.style,
        min_confidence=payload.min_confidence,
        padding_ratio=payload.padding_ratio,
        consolidate_overlapping=payload.consolidate_overlapping,
    )


@router.post(
    "/faces/quality-check",
    response_model=PhotometricQualityResponse,
    status_code=status.HTTP_200_OK,
    summary="Assess non-identifying photometric quality of an evidence image (Phase 76)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_DETECTION_EXECUTE))],
)
async def check_image_quality(
    payload: PhotometricQualityRequest,
    principal: CurrentUserDep,
    service: FaceDetectionServiceDep,
) -> PhotometricQualityResponse:
    """Assess non-identifying photometric quality (sharpness, exposure, contrast, clipping) under approved governance."""
    if not payload.image_base64:
        raise BusinessRuleError("image_base64 is required for photometric quality evaluation")
    try:
        image_bytes = base64.b64decode(payload.image_base64)
    except Exception as exc:
        raise BusinessRuleError("Invalid base64 encoding for image") from exc

    return await service.assess_image_quality(
        image_bytes=image_bytes,
        governance_record_id=payload.governance_record_id,
        principal=principal,
        evidence_id=payload.evidence_id,
    )


@router.post(
    "/faces/verify-geometry",
    response_model=RedactionGeometryResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify bounding-box geometry and overlap consolidation (Phase 76)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_DETECTION_EXECUTE))],
)
async def verify_geometry_endpoint(
    payload: RedactionGeometryRequest,
    principal: CurrentUserDep,
    service: FaceDetectionServiceDep,
) -> RedactionGeometryResponse:
    """Verify geometrical integrity, aspect ratios, and landmark coverage for face redaction boxes."""
    faces = [
        DetectedFace(
            bounding_box=f.bounding_box,
            confidence=f.confidence,
            landmarks=f.landmarks,
        )
        for f in payload.detected_faces
    ]
    return await service.verify_geometry(
        detected_faces=faces,
        image_width=payload.image_width,
        image_height=payload.image_height,
        governance_record_id=payload.governance_record_id,
        principal=principal,
        padding_ratio=payload.padding_ratio,
        consolidate_overlapping=payload.consolidate_overlapping,
    )


@router.get(
    "/faces/robustness-report",
    response_model=FaceDetectionRobustnessAuditRead,
    status_code=status.HTTP_200_OK,
    summary="Get face detection quality, robustness, and input-integrity evaluation report (Phase 79)",
    dependencies=[
        Depends(
            require_any_permission(
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
                Permission.BIOMETRIC_AUDIT_READ,
                Permission.BIOMETRIC_DETECTION_EXECUTE,
            )
        )
    ],
)
async def get_face_detection_robustness_report(
    principal: CurrentUserDep,
    service: FaceDetectionServiceDep,
) -> FaceDetectionRobustnessAuditRead:
    """Retrieve comprehensive Phase 79 face detection robustness, fairness limitation, and input-integrity report."""
    return await service.get_detection_robustness_report(principal=principal)


# ---------------------------------------------------------------------------
# Evidence Quality & Redaction Human Review Endpoints (Phase 77)
# ---------------------------------------------------------------------------


@router.post(
    "/faces/reviews",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new evidence quality and redaction human review item (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_DETECTION_EXECUTE))],
)
async def create_quality_review_item(
    payload: BiometricQualityReviewCreate,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Evaluate unified review decision and persist an auditable human review item."""
    return await service.create_review_item(payload, principal)


@router.get(
    "/faces/reviews",
    response_model=PaginatedBiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="List evidence quality and redaction review records for authenticated department (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def list_quality_reviews(
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    assigned_reviewer_id: Annotated[UUID | None, Query()] = None,
    evidence_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedBiometricQualityReviewRead:
    """List quality and redaction review items with optional status, reviewer, and evidence filters."""
    return await service.list_reviews(
        principal,
        status=status_filter,
        assigned_reviewer_id=assigned_reviewer_id,
        evidence_id=evidence_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/faces/reviews/{review_id}",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single evidence quality and redaction review item (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def get_quality_review(
    review_id: UUID,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Fetch details, component versions, and evaluation metrics for a specific review item."""
    return await service.get_review(review_id, principal)


@router.post(
    "/faces/reviews/{review_id}/assign",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Assign review item to an authorized reviewer (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def assign_quality_review(
    review_id: UUID,
    payload: BiometricQualityReviewAssignRequest,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Assign review item to authorized reviewer and advance status to IN_REVIEW."""
    return await service.assign_reviewer(review_id, payload, principal)


@router.post(
    "/faces/reviews/{review_id}/verdict",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Record authorized human review determination (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def record_quality_review_verdict(
    review_id: UUID,
    payload: BiometricQualityReviewVerdictRequest,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Record human reviewer determination (approved, rejected, re_redaction_requested) with audit trail."""
    return await service.record_human_verdict(review_id, payload, principal)


@router.post(
    "/faces/reviews/{review_id}/escalate",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Escalate review item to supervisory review (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def escalate_quality_review(
    review_id: UUID,
    payload: BiometricQualityReviewEscalateRequest,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Escalate review item with documented escalation reason."""
    return await service.escalate_review(review_id, payload, principal)


@router.post(
    "/faces/reviews/{review_id}/reopen",
    response_model=BiometricQualityReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Administratively reopen a COMPLETED review item (Phase 77)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_GOVERNANCE_REVIEW))],
)
async def reopen_quality_review(
    review_id: UUID,
    payload: BiometricQualityReviewReopenRequest,
    principal: CurrentUserDep,
    service: QualityReviewWorkflowServiceDep,
) -> BiometricQualityReviewRead:
    """Administratively transition a completed review back to PENDING_REVIEW."""
    return await service.reopen_review(review_id, payload, principal)


# ---------------------------------------------------------------------------
# Biometric Face Matching Endpoint (Phase 76)
# ---------------------------------------------------------------------------


@router.post(
    "/match",
    response_model=FaceMatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute advisory biometric face matching (prohibited in production)",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_MATCHING_EXECUTE))],
)
async def match_faces(
    payload: FaceMatchRequest,
    principal: CurrentUserDep,
    service: FaceMatchingServiceDep,
) -> FaceMatchResponse:
    """Execute advisory biometric matching between probe and reference.

    Fails closed when matching is disabled in configuration (default).
    """
    return await service.match_faces(payload, principal)


# ---------------------------------------------------------------------------
# Biometric Human Verification & Oversight Endpoints (Phase 77)
# ---------------------------------------------------------------------------


@router.post(
    "/verifications/{review_id}/review",
    response_model=BiometricVerificationReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Record authorized human review determination for a match candidate",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def record_human_verdict(
    review_id: UUID,
    payload: BiometricVerificationReviewCreate,
    principal: CurrentUserDep,
    service: BiometricVerificationServiceDep,
) -> BiometricVerificationReviewRead:
    """Record qualified human reviewer verdict with mandatory override justification if applicable."""
    return await service.record_human_verdict(review_id, payload, principal)


@router.get(
    "/verifications/{review_id}",
    response_model=BiometricVerificationReviewRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single biometric verification review record",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def get_verification_review(
    review_id: UUID,
    principal: CurrentUserDep,
    service: BiometricVerificationServiceDep,
) -> BiometricVerificationReviewRead:
    """Retrieve details for a specific biometric verification review."""
    return await service.get_review(review_id, principal)


@router.get(
    "/verifications",
    response_model=PaginatedBiometricVerificationReviewRead,
    status_code=status.HTTP_200_OK,
    summary="List biometric verification review records for authenticated department",
    dependencies=[Depends(require_permission(Permission.BIOMETRIC_VERIFICATION_REVIEW))],
)
async def list_verification_reviews(
    principal: CurrentUserDep,
    service: BiometricVerificationServiceDep,
    incident_id: Annotated[UUID | None, Query()] = None,
    is_override: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedBiometricVerificationReviewRead:
    """List biometric verification review records with optional filtering."""
    return await service.list_reviews(
        principal,
        incident_id=incident_id,
        is_override=is_override,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Biometric Accuracy, Fairness & PAD Evaluation Endpoint (Phase 79)
# ---------------------------------------------------------------------------


@router.get(
    "/evaluation-report",
    response_model=BiometricEvaluationSummaryRead,
    status_code=status.HTTP_200_OK,
    summary="Retrieve biometric accuracy, fairness, and presentation-attack benchmark report",
)
async def get_evaluation_report(
    principal: CurrentUserDep,
    service: BiometricEvaluationServiceDep,
) -> BiometricEvaluationSummaryRead:
    """Retrieve benchmark performance metrics with explicit synthetic limitation warnings."""
    return await service.get_evaluation_report(principal)
