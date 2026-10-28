"""Domain services for Biometric Governance, Reference Registry, and Face Detection (Phases 71-75).

Enforces:
- Deny-by-default access control and department/tenant isolation.
- Pre-condition checks requiring affirmative governance and unrevoked consent.
- Complete cascading revocation upon consent withdrawal.
- Zero raw biometric data leakage into audit logs or API read responses.
- Fail-closed face detection execution under approved governance records only.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ai_services.face_detection.evaluation import run_full_detection_robustness_audit
from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
    evaluate_unified_review_decision,
    validate_review_state_transition,
)
from ai_services.face_detection.detector import get_face_detector
from ai_services.face_detection.geometry import (
    RedactionGeometryPolicy,
    compute_box_iou,
    consolidate_overlapping_boxes,
    verify_redaction_geometry,
)
from ai_services.face_detection.protocol import DetectedFace, FaceDetectionOptions
from ai_services.face_detection.quality import (
    PhotometricQualityThresholds,
    assess_photometric_quality,
)
from ai_services.face_detection.redaction import (
    apply_face_redaction,
    RedactionPolicy,
    RedactionStyle,
)
from ai_services.face_matching.evaluation import (
    evaluate_biometric_matching_benchmark,
)
from ai_services.face_matching.protocol import FaceFeatureVector, get_face_matcher
from ai_services.face_matching.quality import assess_face_image_quality
from backend.app.config.settings import Settings
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_any_permission, has_permission
from backend.app.core.identity import RoleCode
from backend.app.core.biometric_crypto import (
    ENVELOPE_VERSION,
    BiometricKeyManager,
    BiometricKeyManagerProtocol,
    get_biometric_key_manager,
    validate_envelope_structure,
)
from backend.app.core.biometrics import (
    BIOMETRIC_ADVISORY_DISCLAIMER,
    BiometricHumanVerdict,
    BiometricLawfulBasis,
    BiometricMatchVerdict,
    BiometricPurpose,
    BiometricReferenceStatus,
    ConsentStatus,
    GovernanceStatus,
    validate_biometric_purpose,
)
from backend.app.core.exceptions import (
    BiometricGovernanceError,
    BiometricQualityError,
    BiometricsDisabledError,
    BusinessRuleError,
    PayloadTooLargeError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.models.biometrics import (
    BiometricQualityReview,
    BiometricGovernanceRecord,
    BiometricReference,
    BiometricVerificationReview,
)
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.biometrics import (
    BiometricQualityReviewRepository,
    BiometricGovernanceRepository,
    BiometricReferenceRepository,
    BiometricVerificationRepository,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    BiometricQualityReviewAssignRequest,
    BiometricQualityReviewCreate,
    BiometricQualityReviewEscalateRequest,
    BiometricQualityReviewRead,
    BiometricQualityReviewReopenRequest,
    BiometricQualityReviewVerdictRequest,
    PaginatedBiometricQualityReviewRead,
    BiometricConsentWithdrawRequest,
    BiometricRetentionCleanupResponse,
    BiometricEvaluationSummaryRead,
    BiometricGovernanceCreate,
    BiometricGovernanceRead,
    BiometricGovernanceReviewRequest,
    BiometricReferenceCreate,
    BiometricReferenceRead,
    BiometricReferenceRevokeRequest,
    BiometricBatchReencryptResponse,
    BiometricKeyMetadataRead,
    BiometricVerificationReviewCreate,
    BiometricVerificationReviewRead,
    DetectedFaceRead,
    FaceDetectionResponse,
    FaceRedactionResponse,
    FaceMatchRequest,
    FaceMatchResponse,
    FaceDetectionRobustnessAuditRead,
    PhotometricQualityResponse,
    RedactionGeometryResponse,
    PaginatedBiometricGovernanceRead,
    PaginatedBiometricReferenceRead,
    PaginatedBiometricVerificationReviewRead,
)


class BiometricGovernanceService:
    """Service managing biometric processing feasibility, legal reviews, and consent."""

    def __init__(
        self,
        governance_repo: BiometricGovernanceRepository,
        reference_repo: BiometricReferenceRepository,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self.governance_repo = governance_repo
        self.reference_repo = reference_repo
        self.audit_repo = audit_repo

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        audit_repo: AuditRepository | None = None,
    ) -> BiometricGovernanceService:
        """Construct BiometricGovernanceService bound to session."""
        return cls(
            governance_repo=BiometricGovernanceRepository(session),
            reference_repo=BiometricReferenceRepository(session),
            audit_repo=audit_repo or AuditRepository(session),
        )

    async def create_governance_record(
        self,
        request: BiometricGovernanceCreate,
        principal: AuthenticatedPrincipal,
    ) -> BiometricGovernanceRead:
        """Create a new biometric governance assessment and consent record (Phase 73)."""
        validate_biometric_purpose(request.purpose.value)

        # Authorization: Dept admin or super admin, or self-service if own consent
        is_self = (
            request.subject_user_id is not None and request.subject_user_id == principal.user_id
        )
        can_manage = has_any_permission(
            principal.role,
            [Permission.BIOMETRIC_GOVERNANCE_REVIEW, Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT],
        ) or (is_self and has_permission(principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_OWN))

        if not can_manage:
            raise PermissionDeniedError(
                "Caller lacks authorization to register biometric governance records.",
                code="BIOMETRIC_GOVERNANCE_DENIED",
            )

        # Enforce consent validation rules
        consent_status: str | None = None
        consented_at: datetime | None = None

        if request.lawful_basis.value == "explicit_consent":
            if not request.consent_confirmed:
                raise BiometricGovernanceError(
                    "Affirmative consent confirmation is required when lawful basis is 'explicit_consent'."
                )
            if not request.subject_user_id:
                raise BiometricGovernanceError(
                    "A subject_user_id is required when registering explicit consent."
                )
            consent_status = ConsentStatus.ACTIVE.value
            consented_at = datetime.now(UTC)

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=request.retention_days)

        record = BiometricGovernanceRecord(
            tenant_id=principal.department_id,
            department_id=principal.department_id,
            policy_version=request.policy_version,
            purpose=request.purpose.value,
            lawful_basis=request.lawful_basis.value,
            notice_version=request.notice_version,
            subject_user_id=request.subject_user_id,
            status=GovernanceStatus.PENDING_LEGAL_REVIEW.value,
            consent_status=consent_status,
            consented_at=consented_at,
            retention_days=request.retention_days,
            retention_expires_at=expires_at,
            legal_review_notes=request.legal_review_notes,
        )

        persisted = await self.governance_repo.create(record)

        if self.audit_repo:
            action = (
                AuditAction.BIOMETRIC_CONSENT_GRANTED.value
                if consent_status == ConsentStatus.ACTIVE.value
                else AuditAction.BIOMETRIC_POLICY_EVALUATED.value
            )
            await self.audit_repo.append_event(
                action=action,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id=str(persisted.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "purpose": persisted.purpose,
                    "lawful_basis": persisted.lawful_basis,
                    "status": persisted.status,
                    "consent_status": persisted.consent_status,
                },
            )

        return BiometricGovernanceRead.model_validate(persisted)

    async def review_governance_record(
        self,
        record_id: UUID,
        request: BiometricGovernanceReviewRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricGovernanceRead:
        """Record formal legal or administrative review verdict for a governance record (Phase 71 & 73)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_GOVERNANCE_REVIEW):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_GOVERNANCE_REVIEW permission.",
                code="BIOMETRIC_REVIEW_DENIED",
            )

        record = await self.governance_repo.get_by_id(
            record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        old_status = record.status
        record.status = request.decision
        record.approved_by_id = principal.user_id
        record.approved_at = datetime.now(UTC)
        record.legal_review_notes = request.legal_review_notes

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_POLICY_EVALUATED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=record.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id=str(record.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "old_status": old_status,
                    "new_status": request.decision,
                    "decision": request.decision,
                },
            )

        return BiometricGovernanceRead.model_validate(record)

    async def withdraw_consent(
        self,
        record_id: UUID,
        request: BiometricConsentWithdrawRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricGovernanceRead:
        """Handle consent withdrawal and propagate cascading revocation to references (Phase 73)."""
        record = await self.governance_repo.get_by_id(
            record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        is_subject = (
            record.subject_user_id is not None and record.subject_user_id == principal.user_id
        )
        can_withdraw = is_subject or has_permission(
            principal.role, Permission.BIOMETRIC_GOVERNANCE_REVIEW
        )
        if not can_withdraw:
            raise PermissionDeniedError(
                "Only the data subject or an authorized reviewer can withdraw biometric consent.",
                code="CONSENT_WITHDRAWAL_DENIED",
            )

        # Idempotent return if already withdrawn
        if record.consent_status == ConsentStatus.WITHDRAWN.value:
            return BiometricGovernanceRead.model_validate(record)

        now = datetime.now(UTC)
        record.consent_status = ConsentStatus.WITHDRAWN.value
        record.withdrawn_at = now
        record.status = GovernanceStatus.REVOKED.value

        # Cascade revocation to all active references tied to this governance authorization
        active_refs = await self.reference_repo.list_active_by_governance_record(record_id)
        for ref in active_refs:
            ref.status = BiometricReferenceStatus.REVOKED.value
            ref.revoked_by_id = principal.user_id
            ref.revoked_at = now
            ref.revocation_reason = (
                f"Consent withdrawn by subject: {request.reason or 'User requested'}"
            )
            ref.encrypted_template = None  # Securely wipe ciphertext

            if self.audit_repo:
                await self.audit_repo.append_event(
                    action=AuditAction.BIOMETRIC_REFERENCE_REVOKED.value,
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    department_id=ref.department_id,
                    target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                    target_id=str(ref.id),
                    outcome=AuditOutcome.SUCCESS.value,
                    details={
                        "reference_id": ref.reference_id,
                        "reason": "Consent withdrawal cascade",
                        "governance_record_id": str(record.id),
                    },
                )

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_CONSENT_REVOKED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=record.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id=str(record.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "reason": request.reason,
                    "revoked_references_count": len(active_refs),
                },
            )

        return BiometricGovernanceRead.model_validate(record)

    async def get_governance_record(
        self,
        record_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> BiometricGovernanceRead:
        """Retrieve single governance record with department isolation."""
        record = await self.governance_repo.get_by_id(
            record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )
        now = datetime.now(UTC)
        rec_exp = getattr(record, "retention_expires_at", None)
        if (
            record.consent_status == ConsentStatus.ACTIVE.value
            and isinstance(rec_exp, datetime)
            and rec_exp <= now
        ):
            record.consent_status = ConsentStatus.EXPIRED.value

        return BiometricGovernanceRead.model_validate(record)

    async def cleanup_expired_governance(
        self,
        principal: AuthenticatedPrincipal,
        *,
        department_id: UUID | None = None,
    ) -> int:
        """Scan and transition expired active consent records to EXPIRED status, cascading to references (Phase 73)."""
        is_global = has_any_permission(
            principal.role,
            [Permission.BIOMETRIC_CONFIG_MANAGE, Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL],
        )
        if not is_global and not has_permission(
            principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT
        ):
            raise PermissionDeniedError(
                "Caller lacks permission to execute biometric retention cleanup.",
                code="BIOMETRIC_RETENTION_DENIED",
            )

        scoped_dept = None if is_global else principal.department_id
        if is_global and department_id is not None:
            scoped_dept = department_id

        now = datetime.now(UTC)
        expired_records = await self.governance_repo.list_expired_active(now, department_id=scoped_dept)
        count = 0
        for record in expired_records:
            record.consent_status = ConsentStatus.EXPIRED.value
            count += 1
            active_refs = await self.reference_repo.list_active_by_governance_record(record.id)
            for ref in active_refs:
                ref.status = BiometricReferenceStatus.EXPIRED.value
                ref.encrypted_template = None  # Cryptographic erasure: purge ciphertext
                ref.revoked_at = now
                ref.revocation_reason = "Retention expired: consent expired"

                if self.audit_repo:
                    await self.audit_repo.append_event(
                        action=AuditAction.BIOMETRIC_REFERENCE_REVOKED.value,
                        actor_id=principal.user_id,
                        actor_role=principal.role_code,
                        department_id=ref.department_id,
                        target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                        target_id=str(ref.id),
                        outcome=AuditOutcome.SUCCESS.value,
                        details={
                            "reference_id": ref.reference_id,
                            "reason": "Retention expiry cascade",
                            "governance_record_id": str(record.id),
                        },
                    )

            if self.audit_repo:
                await self.audit_repo.append_event(
                    action=AuditAction.BIOMETRIC_CONSENT_REVOKED.value,
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    department_id=record.department_id,
                    target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                    target_id=str(record.id),
                    outcome=AuditOutcome.SUCCESS.value,
                    details={
                        "reason": "Retention expired",
                        "revoked_references_count": len(active_refs),
                    },
                )
        return count

    async def list_governance_records(
        self,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedBiometricGovernanceRead:
        """List governance records for authenticated department."""
        dept_id = principal.department_id
        items = await self.governance_repo.list_for_department(
            department_id=dept_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await self.governance_repo.count_for_department(
            department_id=dept_id,
            status=status,
        )
        return PaginatedBiometricGovernanceRead(
            items=[BiometricGovernanceRead.model_validate(i) for i in items],
            total=total,
            limit=limit,
            offset=offset,
        )


class BiometricReferenceService:
    """Service managing restricted biometric reference enrollment and lifecycle (Phase 74)."""

    def __init__(
        self,
        reference_repo: BiometricReferenceRepository,
        governance_repo: BiometricGovernanceRepository,
        audit_repo: AuditRepository | None = None,
        evidence_repo: EvidenceRepository | None = None,
        key_manager: BiometricKeyManagerProtocol | None = None,
    ) -> None:
        self.reference_repo = reference_repo
        self.governance_repo = governance_repo
        self.audit_repo = audit_repo
        self.evidence_repo = evidence_repo
        self.key_manager = key_manager

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        audit_repo: AuditRepository | None = None,
        evidence_repo: EvidenceRepository | None = None,
        key_manager: BiometricKeyManagerProtocol | None = None,
    ) -> BiometricReferenceService:
        """Construct BiometricReferenceService bound to session."""
        return cls(
            reference_repo=BiometricReferenceRepository(session),
            governance_repo=BiometricGovernanceRepository(session),
            audit_repo=audit_repo or AuditRepository(session),
            evidence_repo=evidence_repo or EvidenceRepository(session),
            key_manager=key_manager or get_biometric_key_manager(),
        )

    async def enroll_reference(
        self,
        request: BiometricReferenceCreate,
        principal: AuthenticatedPrincipal,
    ) -> BiometricReferenceRead:
        """Enroll an approved biometric reference into the restricted registry (Phase 74)."""
        is_self = (
            request.subject_user_id is not None and request.subject_user_id == principal.user_id
        )
        can_manage = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT,
                Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL,
            ],
        ) or (is_self and has_permission(principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_OWN))

        if not can_manage:
            raise PermissionDeniedError(
                "Caller lacks authorization to enroll biometric references.",
                code="BIOMETRIC_ENROLLMENT_DENIED",
            )

        # Validate that the governance record is approved and active
        gov_record = await self.governance_repo.get_by_id(
            request.governance_record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if gov_record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{request.governance_record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        if gov_record.status != GovernanceStatus.APPROVED.value:
            raise BiometricGovernanceError(
                f"Cannot enroll reference under unapproved governance record (status: '{gov_record.status}').",
                code="GOVERNANCE_NOT_APPROVED",
            )

        if gov_record.consent_status == ConsentStatus.WITHDRAWN.value:
            raise BiometricGovernanceError(
                "Cannot enroll reference under withdrawn consent.",
                code="CONSENT_WITHDRAWN",
            )

        now = datetime.now(UTC)
        gov_exp = getattr(gov_record, "retention_expires_at", None)
        if isinstance(gov_exp, datetime) and gov_exp <= now:
            raise BiometricGovernanceError(
                f"Cannot enroll reference under expired governance record (expired at: {gov_record.retention_expires_at.isoformat()}).",
                code="RETENTION_EXPIRED",
            )

        if gov_record.lawful_basis == BiometricLawfulBasis.EXPLICIT_CONSENT.value:
            if gov_record.consent_status != ConsentStatus.ACTIVE.value:
                raise BiometricGovernanceError(
                    f"Enrollment requires active consent when lawful basis is explicit_consent; current status is '{gov_record.consent_status}'.",
                    code="CONSENT_NOT_ACTIVE",
                )

        # Fail-closed verification: subject user ID must match governance record subject if set
        if gov_record.subject_user_id is not None:
            if request.subject_user_id != gov_record.subject_user_id:
                raise BiometricGovernanceError(
                    f"Subject user ID '{request.subject_user_id}' does not match governance record subject '{gov_record.subject_user_id}'.",
                    code="SUBJECT_MISMATCH",
                )

        # Fail-closed verification: enrollment purpose must match governance record purpose
        if request.purpose.value != gov_record.purpose:
            raise BiometricGovernanceError(
                f"Enrollment purpose '{request.purpose.value}' does not match governance record purpose '{gov_record.purpose}'.",
                code="PURPOSE_MISMATCH",
            )

        # Evidence provenance verification: ensure provenance evidence exists and belongs to the same department
        if request.provenance_evidence_id is not None and self.evidence_repo is not None:
            evidence = await self.evidence_repo.get_attachment_by_id(request.provenance_evidence_id)
            if evidence is None:
                raise ResourceNotFoundError(
                    f"Provenance evidence attachment '{request.provenance_evidence_id}' not found.",
                    code="EVIDENCE_NOT_FOUND",
                )
            if (
                evidence.department_id != principal.department_id
                and principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"}
            ):
                raise PermissionDeniedError(
                    "Provenance evidence attachment belongs to a different department/tenant.",
                    code="CROSS_TENANT_EVIDENCE_FORBIDDEN",
                )

        # Envelope encryption and digest integrity verification
        if request.encrypted_template is not None:
            if request.encrypted_template.startswith(f"{ENVELOPE_VERSION}:") or (
                ":" in request.encrypted_template and request.encrypted_template.startswith("v")
            ):
                if self.key_manager is not None:
                    decrypted_bytes = self.key_manager.decrypt(request.encrypted_template)
                    computed_digest = hashlib.sha256(decrypted_bytes).hexdigest()
                    if computed_digest != request.template_digest:
                        raise BiometricGovernanceError(
                            f"Template digest '{request.template_digest}' does not match SHA-256 of decrypted template ('{computed_digest}').",
                            code="TEMPLATE_DIGEST_MISMATCH",
                        )
                else:
                    validate_envelope_structure(request.encrypted_template)

        expires_at = now + timedelta(days=gov_record.retention_days)
        opaque_id = f"REF-BIO-{uuid4().hex[:12].upper()}"

        reference = BiometricReference(
            reference_id=opaque_id,
            tenant_id=principal.department_id,
            department_id=principal.department_id,
            subject_user_id=request.subject_user_id,
            governance_record_id=request.governance_record_id,
            purpose=request.purpose.value,
            status=BiometricReferenceStatus.ACTIVE.value,
            template_digest=request.template_digest,
            encrypted_template=request.encrypted_template,
            provenance_evidence_id=request.provenance_evidence_id,
            enrollment_notes=request.enrollment_notes,
            enrolled_by_id=principal.user_id,
            enrolled_at=now,
            retention_expires_at=expires_at,
        )

        persisted = await self.reference_repo.create(reference)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_REFERENCE_ENROLLED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                target_id=str(persisted.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "reference_id": persisted.reference_id,
                    "purpose": persisted.purpose,
                    "template_digest": persisted.template_digest,
                    "governance_record_id": str(persisted.governance_record_id),
                },
            )

        return BiometricReferenceRead.model_validate(persisted)

    async def revoke_reference(
        self,
        reference_id: UUID,
        request: BiometricReferenceRevokeRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricReferenceRead:
        """Revoke an active biometric reference (Phase 74)."""
        reference = await self.reference_repo.get_by_id(
            reference_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if reference is None:
            raise ResourceNotFoundError(
                f"Biometric reference '{reference_id}' not found.",
                code="BIOMETRIC_REFERENCE_NOT_FOUND",
            )

        is_self = (
            reference.subject_user_id is not None and reference.subject_user_id == principal.user_id
        )
        can_manage = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT,
                Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL,
            ],
        ) or (is_self and has_permission(principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_OWN))

        if not can_manage:
            raise PermissionDeniedError(
                "Caller lacks authorization to revoke this biometric reference.",
                code="BIOMETRIC_REVOCATION_DENIED",
            )

        # Idempotent return if already revoked
        if reference.status == BiometricReferenceStatus.REVOKED.value:
            return BiometricReferenceRead.model_validate(reference)

        now = datetime.now(UTC)
        reference.status = BiometricReferenceStatus.REVOKED.value
        reference.revoked_by_id = principal.user_id
        reference.revoked_at = now
        reference.revocation_reason = request.reason
        reference.encrypted_template = None  # Securely purge ciphertext

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_REFERENCE_REVOKED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=reference.department_id,
                target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                target_id=str(reference.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "reference_id": reference.reference_id,
                    "reason": request.reason,
                },
            )

        return BiometricReferenceRead.model_validate(reference)

    async def get_reference(
        self,
        reference_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> BiometricReferenceRead:
        """Retrieve biometric reference metadata without exposing template payload."""
        reference = await self.reference_repo.get_by_id(
            reference_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if reference is None:
            raise ResourceNotFoundError(
                f"Biometric reference '{reference_id}' not found.",
                code="BIOMETRIC_REFERENCE_NOT_FOUND",
            )

        is_self = (
            reference.subject_user_id is not None and reference.subject_user_id == principal.user_id
        )
        can_read = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_REFERENCE_READ_DEPT,
                Permission.BIOMETRIC_REFERENCE_READ_GLOBAL,
            ],
        ) or (is_self and has_permission(principal.role, Permission.BIOMETRIC_REFERENCE_READ_OWN))

        if not can_read:
            raise PermissionDeniedError(
                "Caller lacks authorization to view this biometric reference.",
                code="BIOMETRIC_READ_DENIED",
            )

        now = datetime.now(UTC)
        ref_exp = getattr(reference, "retention_expires_at", None)
        if (
            reference.status == BiometricReferenceStatus.ACTIVE.value
            and isinstance(ref_exp, datetime)
            and ref_exp <= now
        ):
            reference.status = BiometricReferenceStatus.EXPIRED.value
            reference.encrypted_template = None  # Securely purge ciphertext
            reference.revoked_at = now
            reference.revocation_reason = "Retention expired"

        return BiometricReferenceRead.model_validate(reference)

    async def reencrypt_reference(
        self,
        reference_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        new_key_id: str | None = None,
    ) -> BiometricReferenceRead:
        """Re-encrypt an active biometric reference under a rotated or designated active key (Phase 78)."""
        can_manage = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT,
                Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL,
                Permission.BIOMETRIC_CONFIG_MANAGE,
            ],
        )
        if not can_manage:
            raise PermissionDeniedError(
                "Caller lacks authorization to re-encrypt biometric references.",
                code="BIOMETRIC_REENCRYPTION_DENIED",
            )

        reference = await self.reference_repo.get_by_id(
            reference_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if reference is None:
            raise ResourceNotFoundError(
                f"Biometric reference '{reference_id}' not found.",
                code="BIOMETRIC_REFERENCE_NOT_FOUND",
            )

        if reference.status != BiometricReferenceStatus.ACTIVE.value:
            raise BiometricGovernanceError(
                f"Cannot re-encrypt reference in status '{reference.status}'. Only active references may be re-encrypted.",
                code="REFERENCE_NOT_ACTIVE",
            )

        if not reference.encrypted_template:
            raise BiometricGovernanceError(
                "Reference has no encrypted template to re-encrypt (cryptographically erased or missing).",
                code="ENCRYPTED_TEMPLATE_MISSING",
            )

        if self.key_manager is None:
            raise BiometricKeyError(
                "Key manager is not configured. Cannot perform reference re-encryption."
            )

        old_envelope = reference.encrypted_template
        old_version, old_key_id, _ = validate_envelope_structure(old_envelope)

        target_key_id = new_key_id or self.key_manager.active_key_id
        if not target_key_id:
            raise BiometricKeyError("No active encryption key available for re-encryption.")

        # Re-encrypt
        new_envelope = self.key_manager.reencrypt(
            old_envelope,
            new_key_id=target_key_id,
        )

        # Verification: decrypt newly produced envelope and verify digest matches stored template_digest
        decrypted_verify = self.key_manager.decrypt(new_envelope)
        computed_digest = hashlib.sha256(decrypted_verify).hexdigest()
        if computed_digest != reference.template_digest:
            raise BiometricGovernanceError(
                "Post-re-encryption integrity verification failed: decrypted digest does not match template_digest.",
                code="REENCRYPTION_VERIFICATION_FAILED",
            )

        reference.encrypted_template = new_envelope
        reference.updated_at = datetime.now(UTC)
        await self.reference_repo.update(reference)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_REFERENCE_REENCRYPTED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=reference.department_id,
                target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                target_id=str(reference.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "reference_id": reference.reference_id,
                    "old_key_id": old_key_id,
                    "new_key_id": target_key_id,
                    "template_digest": reference.template_digest,
                },
            )

        return BiometricReferenceRead.model_validate(reference)

    async def batch_reencrypt_references(
        self,
        principal: AuthenticatedPrincipal,
        *,
        department_id: UUID | None = None,
        new_key_id: str | None = None,
        batch_size: int = 50,
    ) -> BiometricBatchReencryptResponse:
        """Batch re-encrypt active references under the active key (Phase 78). Idempotent and recoverable."""
        is_global = has_permission(principal.role, Permission.BIOMETRIC_CONFIG_MANAGE) or has_permission(
            principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL
        )
        if not is_global and not has_permission(principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT):
            raise PermissionDeniedError(
                "Caller lacks permission for batch reference re-encryption.",
                code="BATCH_REENCRYPTION_DENIED",
            )

        scoped_dept = None if is_global else principal.department_id
        if is_global and department_id is not None:
            scoped_dept = department_id

        if self.key_manager is None:
            raise BiometricKeyError("Key manager is not configured.")

        target_key = new_key_id or self.key_manager.active_key_id
        if not target_key:
            raise BiometricKeyError("No active key available for batch re-encryption.")

        refs = await self.reference_repo.list_active_for_reencryption(
            department_id=scoped_dept,
            limit=batch_size,
        )

        total_scanned = len(refs)
        reencrypted_count = 0
        skipped_count = 0
        error_count = 0

        now = datetime.now(UTC)
        for ref in refs:
            if not ref.encrypted_template:
                skipped_count += 1
                continue
            try:
                _, cur_key_id, _ = validate_envelope_structure(ref.encrypted_template)
                if cur_key_id == target_key:
                    # Already encrypted under target key; idempotent skip
                    skipped_count += 1
                    continue

                new_env = self.key_manager.reencrypt(ref.encrypted_template, new_key_id=target_key)
                dec = self.key_manager.decrypt(new_env)
                if hashlib.sha256(dec).hexdigest() != ref.template_digest:
                    error_count += 1
                    continue

                ref.encrypted_template = new_env
                ref.updated_at = now
                await self.reference_repo.update(ref)
                reencrypted_count += 1

                if self.audit_repo:
                    await self.audit_repo.append_event(
                        action=AuditAction.BIOMETRIC_REFERENCE_REENCRYPTED.value,
                        actor_id=principal.user_id,
                        actor_role=principal.role_code,
                        department_id=ref.department_id,
                        target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                        target_id=str(ref.id),
                        outcome=AuditOutcome.SUCCESS.value,
                        details={
                            "reference_id": ref.reference_id,
                            "old_key_id": cur_key_id,
                            "new_key_id": target_key,
                        },
                    )
            except Exception:
                error_count += 1

        return BiometricBatchReencryptResponse(
            total_scanned=total_scanned,
            reencrypted_count=reencrypted_count,
            skipped_count=skipped_count,
            error_count=error_count,
            target_key_id=target_key,
        )

    def list_keys(self, principal: AuthenticatedPrincipal) -> list[BiometricKeyMetadataRead]:
        """List metadata for all biometric encryption keys (Phase 78)."""
        can_view = has_any_permission(
            principal.role,
            [Permission.BIOMETRIC_CONFIG_MANAGE, Permission.BIOMETRIC_AUDIT_READ],
        )
        if not can_view:
            raise PermissionDeniedError(
                "Caller lacks authorization to view biometric key metadata.",
                code="BIOMETRIC_KEY_METADATA_DENIED",
            )
        if self.key_manager is None:
            raise BiometricKeyError("Key manager is not configured.")

        active_id = self.key_manager.active_key_id
        keys = self.key_manager.list_keys()
        return [
            BiometricKeyMetadataRead(
                key_id=k.key_id,
                status=k.status.value,
                algorithm=k.algorithm,
                version=k.version,
                created_at=k.created_at,
                rotated_at=k.rotated_at,
                revoked_at=k.revoked_at,
                retired_at=k.retired_at,
                is_active=(k.key_id == active_id),
            )
            for k in keys
        ]

    def get_key_metadata(self, key_id: str, principal: AuthenticatedPrincipal) -> BiometricKeyMetadataRead:
        """Get sanitized metadata for a single biometric key (Phase 78)."""
        can_view = has_any_permission(
            principal.role,
            [Permission.BIOMETRIC_CONFIG_MANAGE, Permission.BIOMETRIC_AUDIT_READ],
        )
        if not can_view:
            raise PermissionDeniedError(
                "Caller lacks authorization to view biometric key metadata.",
                code="BIOMETRIC_KEY_METADATA_DENIED",
            )
        if self.key_manager is None:
            raise BiometricKeyError("Key manager is not configured.")

        k = self.key_manager.get_key_metadata(key_id)
        active_id = self.key_manager.active_key_id
        return BiometricKeyMetadataRead(
            key_id=k.key_id,
            status=k.status.value,
            algorithm=k.algorithm,
            version=k.version,
            created_at=k.created_at,
            rotated_at=k.rotated_at,
            revoked_at=k.revoked_at,
            retired_at=k.retired_at,
            is_active=(k.key_id == active_id),
        )

    async def rotate_key(
        self,
        principal: AuthenticatedPrincipal,
        *,
        new_key_id: str | None = None,
    ) -> BiometricKeyMetadataRead:
        """Rotate the active biometric encryption key (Phase 78). Restricted to super admin."""
        if not has_permission(principal.role, Permission.BIOMETRIC_CONFIG_MANAGE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_CONFIG_MANAGE permission to rotate encryption keys.",
                code="KEY_ROTATION_DENIED",
            )
        if self.key_manager is None:
            raise BiometricKeyError("Key manager is not configured.")

        old_active = self.key_manager.active_key_id
        new_id = self.key_manager.rotate_key(new_key_id)
        meta = self.key_manager.get_key_metadata(new_id)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_KEY_ROTATED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_KEY.value,
                target_id=new_id,
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "old_key_id": old_active,
                    "new_key_id": new_id,
                    "version": meta.version,
                },
            )

        return BiometricKeyMetadataRead(
            key_id=meta.key_id,
            status=meta.status.value,
            algorithm=meta.algorithm,
            version=meta.version,
            created_at=meta.created_at,
            rotated_at=meta.rotated_at,
            revoked_at=meta.revoked_at,
            retired_at=meta.retired_at,
            is_active=True,
        )

    async def revoke_key(
        self,
        key_id: str,
        principal: AuthenticatedPrincipal,
    ) -> BiometricKeyMetadataRead:
        """Revoke a biometric encryption key (Phase 78). Restricted to super admin."""
        if not has_permission(principal.role, Permission.BIOMETRIC_CONFIG_MANAGE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_CONFIG_MANAGE permission to revoke encryption keys.",
                code="KEY_REVOCATION_DENIED",
            )
        if self.key_manager is None:
            raise BiometricKeyError("Key manager is not configured.")

        self.key_manager.revoke_key(key_id)
        meta = self.key_manager.get_key_metadata(key_id)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_KEY_REVOKED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_KEY.value,
                target_id=key_id,
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "key_id": key_id,
                    "status": meta.status.value,
                },
            )

        return BiometricKeyMetadataRead(
            key_id=meta.key_id,
            status=meta.status.value,
            algorithm=meta.algorithm,
            version=meta.version,
            created_at=meta.created_at,
            rotated_at=meta.rotated_at,
            revoked_at=meta.revoked_at,
            retired_at=meta.retired_at,
            is_active=False,
        )

    async def cleanup_expired_references(
        self,
        principal: AuthenticatedPrincipal,
        *,
        department_id: UUID | None = None,
    ) -> int:
        """Scan and transition expired active references to EXPIRED status, purging templates (Phase 73)."""
        is_global = has_any_permission(
            principal.role,
            [Permission.BIOMETRIC_CONFIG_MANAGE, Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL],
        )
        if not is_global and not has_permission(
            principal.role, Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT
        ):
            raise PermissionDeniedError(
                "Caller lacks permission to execute biometric retention cleanup.",
                code="BIOMETRIC_RETENTION_DENIED",
            )

        scoped_dept = None if is_global else principal.department_id
        if is_global and department_id is not None:
            scoped_dept = department_id

        now = datetime.now(UTC)
        expired_refs = await self.reference_repo.list_expired_active(now, department_id=scoped_dept)
        count = 0
        for ref in expired_refs:
            ref.status = BiometricReferenceStatus.EXPIRED.value
            ref.encrypted_template = None  # Cryptographic erasure
            ref.revoked_at = now
            ref.revocation_reason = "Retention expired"
            count += 1

            if self.audit_repo:
                await self.audit_repo.append_event(
                    action=AuditAction.BIOMETRIC_REFERENCE_REVOKED.value,
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    department_id=ref.department_id,
                    target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                    target_id=str(ref.id),
                    outcome=AuditOutcome.SUCCESS.value,
                    details={
                        "reference_id": ref.reference_id,
                        "reason": "Retention expiry cleanup",
                    },
                )
        return count

    async def list_references(
        self,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedBiometricReferenceRead:
        """List references scoped to department."""
        dept_id = principal.department_id
        items = await self.reference_repo.list_for_department(
            department_id=dept_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await self.reference_repo.count_for_department(
            department_id=dept_id,
            status=status,
        )
        return PaginatedBiometricReferenceRead(
            items=[BiometricReferenceRead.model_validate(i) for i in items],
            total=total,
            limit=limit,
            offset=offset,
        )


class FaceDetectionService:
    """Service executing approved face detection and privacy-preserving redaction under verified governance (Phase 75)."""

    def __init__(
        self,
        governance_repo: BiometricGovernanceRepository,
        settings: Settings,
        audit_repo: AuditRepository | None = None,
        evidence_repo: EvidenceRepository | None = None,
        detector: FaceDetectorProtocol | None = None,
    ) -> None:
        self.governance_repo = governance_repo
        self.settings = settings
        self.audit_repo = audit_repo
        self.evidence_repo = evidence_repo
        self.detector = detector

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings,
        *,
        audit_repo: AuditRepository | None = None,
        evidence_repo: EvidenceRepository | None = None,
    ) -> FaceDetectionService:
        """Construct FaceDetectionService bound to session and settings."""
        return cls(
            governance_repo=BiometricGovernanceRepository(session),
            settings=settings,
            audit_repo=audit_repo or AuditRepository(session),
            evidence_repo=evidence_repo or EvidenceRepository(session),
        )

    async def detect_faces(
        self,
        image_bytes: bytes,
        governance_record_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        evidence_id: UUID | None = None,
        options: FaceDetectionOptions | None = None,
    ) -> FaceDetectionResponse:
        """Execute face bounding-box detection (Phase 75)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_DETECTION_EXECUTE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_DETECTION_EXECUTE permission.",
                code="FACE_DETECTION_DENIED",
            )

        # Fail closed if disabled in settings
        if (
            not self.settings.BIOMETRIC_ANALYSIS_ENABLED
            or not self.settings.BIOMETRIC_DETECTION_ENABLED
        ):
            raise BiometricsDisabledError(
                "Face detection is disabled in system configuration.",
                code="BIOMETRICS_DISABLED",
            )

        if len(image_bytes) > self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES:
            raise PayloadTooLargeError(
                f"Image payload size ({len(image_bytes)} bytes) exceeds the maximum allowed limit "
                f"({self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES} bytes).",
                code="PAYLOAD_TOO_LARGE",
            )

        # Validate approved governance authorization
        gov_record = await self.governance_repo.get_by_id(
            governance_record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if gov_record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{governance_record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        if gov_record.status != GovernanceStatus.APPROVED.value:
            raise BiometricGovernanceError(
                f"Face detection requires an approved governance record; current status is '{gov_record.status}'.",
                code="GOVERNANCE_NOT_APPROVED",
            )

        now = datetime.now(UTC)
        gov_exp = getattr(gov_record, "retention_expires_at", None)
        if isinstance(gov_exp, datetime) and gov_exp <= now:
            raise BiometricGovernanceError(
                "Biometric governance record retention period has expired.",
                code="RETENTION_EXPIRED",
            )

        if gov_record.consent_status == ConsentStatus.WITHDRAWN.value:
            raise BiometricGovernanceError(
                "Face detection cannot be executed under withdrawn subject consent.",
                code="CONSENT_WITHDRAWN",
            )

        if (
            gov_record.lawful_basis == BiometricLawfulBasis.EXPLICIT_CONSENT.value
            and gov_record.consent_status != ConsentStatus.ACTIVE.value
        ):
            raise BiometricGovernanceError(
                "Face detection requires active subject consent when lawful basis is explicit_consent.",
                code="CONSENT_NOT_ACTIVE",
            )

        permitted_purposes = {
            BiometricPurpose.PRIVACY_REDACTION_BLURRING.value,
            BiometricPurpose.AUTHORIZED_INVESTIGATIVE_MANUAL_REVIEW.value,
            BiometricPurpose.TESTING_SYNTHETIC_BENCHMARK.value,
        }
        if gov_record.purpose not in permitted_purposes:
            raise BiometricGovernanceError(
                f"Governance record purpose '{gov_record.purpose}' is not authorized for face detection.",
                code="UNAUTHORIZED_BIOMETRIC_PURPOSE",
            )

        # Scoped evidence verification
        if evidence_id is not None and self.evidence_repo is not None:
            attachment = await self.evidence_repo.get_attachment_by_id(evidence_id)
            if attachment is None:
                raise ResourceNotFoundError(
                    f"Evidence attachment '{evidence_id}' not found.",
                    code="EVIDENCE_NOT_FOUND",
                )
            if (
                principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"}
                and attachment.department_id != principal.department_id
            ):
                raise PermissionDeniedError(
                    "Access to cross-tenant evidence is strictly prohibited.",
                    code="CROSS_TENANT_ACCESS_DENIED",
                )

        # Instantiate face detector provider if not injected
        detector = self.detector or get_face_detector(
            enabled=self.settings.BIOMETRIC_DETECTION_ENABLED,
            provider=self.settings.BIOMETRIC_PROVIDER,
        )

        result = detector.detect_faces(image_bytes, options=options)

        if self.audit_repo:
            details = {
                "face_count": result.face_count,
                "image_width": result.image_width,
                "image_height": result.image_height,
                "model_name": result.model_name,
                "model_version": result.model_version,
                "latency_ms": result.inference_latency_ms,
            }
            if evidence_id is not None:
                details["evidence_id"] = str(evidence_id)

            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_DETECTION_EXECUTED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id=str(gov_record.id),
                outcome=AuditOutcome.SUCCESS.value,
                details=details,
            )

        return FaceDetectionResponse(
            detected_faces=[
                DetectedFaceRead(
                    bounding_box=f.bounding_box,
                    confidence=f.confidence,
                    landmarks=f.landmarks,
                )
                for f in result.detected_faces
            ],
            face_count=result.face_count,
            image_width=result.image_width,
            image_height=result.image_height,
            model_name=result.model_name,
            model_version=result.model_version,
            inference_latency_ms=result.inference_latency_ms,
            disclaimer=result.disclaimer,
            metadata=result.metadata,
        )

    async def redact_faces(
        self,
        image_bytes: bytes,
        governance_record_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        evidence_id: UUID | None = None,
        style: str = "solid_box",
        min_confidence: float = 0.5,
        padding_ratio: float = 0.1,
        consolidate_overlapping: bool = False,
    ) -> FaceRedactionResponse:
        """Execute privacy-preserving face redaction on image bytes (Phase 75)."""
        # Capture all candidate detections (confidence >= 0.0) so apply_face_redaction
        # can inspect for low-confidence candidate detections below min_confidence
        detection_response = await self.detect_faces(
            image_bytes=image_bytes,
            governance_record_id=governance_record_id,
            principal=principal,
            evidence_id=evidence_id,
            options=FaceDetectionOptions(
                confidence_threshold=0.0,
            ),
        )

        detected_faces = [
            DetectedFace(
                bounding_box=f.bounding_box,
                confidence=f.confidence,
                landmarks=f.landmarks,
            )
            for f in detection_response.detected_faces
        ]

        if consolidate_overlapping and detected_faces:
            boxes = [f.bounding_box for f in detected_faces]
            c_boxes, _ = consolidate_overlapping_boxes(boxes, iou_threshold=0.15)
            c_faces: list[DetectedFace] = []
            for c_b in c_boxes:
                c_conf = 0.0
                c_landmarks: dict[str, tuple[float, float]] = {}
                for orig in detected_faces:
                    if compute_box_iou(orig.bounding_box, c_b) > 0.0:
                        c_conf = max(c_conf, orig.confidence)
                        if orig.landmarks:
                            c_landmarks.update(orig.landmarks)
                c_faces.append(
                    DetectedFace(
                        bounding_box=c_b,
                        confidence=c_conf if c_conf > 0.0 else 0.90,
                        landmarks=c_landmarks if c_landmarks else None,
                    )
                )
            detected_faces = c_faces

        style_enum = (
            RedactionStyle(style)
            if style in RedactionStyle._value2member_map_
            else RedactionStyle.SOLID_BOX
        )
        policy = RedactionPolicy(
            min_confidence=min_confidence,
            padding_ratio=padding_ratio,
            style=style_enum,
        )
        redacted_result = apply_face_redaction(
            image_bytes=image_bytes,
            detected_faces=detected_faces,
            policy=policy,
        )

        return FaceRedactionResponse(
            redacted_image_base64=base64.b64encode(redacted_result.redacted_bytes).decode("ascii"),
            redacted_faces_count=redacted_result.redacted_faces_count,
            image_format=redacted_result.image_format,
            image_width=redacted_result.image_width,
            image_height=redacted_result.image_height,
            style=redacted_result.style,
            disclaimer=redacted_result.disclaimer,
            is_redacted=redacted_result.is_redacted,
            requires_human_review=redacted_result.requires_human_review,
            review_reason=redacted_result.review_reason,
            metadata=redacted_result.metadata,
        )

    async def assess_image_quality(
        self,
        image_bytes: bytes,
        governance_record_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        evidence_id: UUID | None = None,
        thresholds: PhotometricQualityThresholds | None = None,
    ) -> PhotometricQualityResponse:
        """Assess non-identifying photometric quality of an evidence image (Phase 76)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_DETECTION_EXECUTE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_DETECTION_EXECUTE permission.",
                code="FACE_DETECTION_DENIED",
            )

        if not self.settings.BIOMETRIC_ANALYSIS_ENABLED:
            raise BiometricsDisabledError(
                "Biometric analysis is disabled in system configuration.",
                code="BIOMETRICS_DISABLED",
            )

        if len(image_bytes) > self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES:
            raise PayloadTooLargeError(
                f"Image payload size ({len(image_bytes)} bytes) exceeds the maximum allowed limit "
                f"({self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES} bytes).",
                code="PAYLOAD_TOO_LARGE",
            )

        # Validate approved governance authorization
        gov_record = await self.governance_repo.get_by_id(
            governance_record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if gov_record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{governance_record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        if gov_record.status != GovernanceStatus.APPROVED.value:
            raise BiometricGovernanceError(
                f"Governance record '{governance_record_id}' is not approved (current status: '{gov_record.status}').",
                code="GOVERNANCE_NOT_APPROVED",
            )

        now = datetime.now(UTC)
        gov_exp = getattr(gov_record, "retention_expires_at", None)
        if isinstance(gov_exp, datetime) and gov_exp <= now:
            raise BiometricGovernanceError(
                f"Governance record has expired (expired at: {gov_record.retention_expires_at.isoformat()}).",
                code="RETENTION_EXPIRED",
            )

        if gov_record.consent_status == ConsentStatus.WITHDRAWN.value:
            raise BiometricGovernanceError(
                "Consent has been withdrawn for this governance record.",
                code="CONSENT_WITHDRAWN",
            )

        # Scoped evidence verification
        if evidence_id is not None and self.evidence_repo is not None:
            attachment = await self.evidence_repo.get_attachment_by_id(evidence_id)
            if attachment is None:
                raise ResourceNotFoundError(
                    f"Evidence attachment '{evidence_id}' not found.",
                    code="EVIDENCE_NOT_FOUND",
                )
            if (
                principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"}
                and attachment.department_id != principal.department_id
            ):
                raise PermissionDeniedError(
                    "Access to cross-tenant evidence is strictly prohibited.",
                    code="CROSS_TENANT_ACCESS_DENIED",
                )

        result = assess_photometric_quality(image_bytes, thresholds=thresholds)

        if self.audit_repo:
            details = {
                "quality_status": result.quality_status.value,
                "sharpness_score": result.sharpness_score,
                "exposure_score": result.exposure_score,
                "contrast_score": result.contrast_score,
                "requires_human_review": result.requires_human_review,
                "image_width": result.image_width,
                "image_height": result.image_height,
            }
            if evidence_id is not None:
                details["evidence_id"] = str(evidence_id)

            await self.audit_repo.append_event(
                action="evidence:quality:evaluated",
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id=str(gov_record.id),
                outcome=AuditOutcome.SUCCESS.value,
                details=details,
            )

        return PhotometricQualityResponse(
            sharpness_score=result.sharpness_score,
            exposure_score=result.exposure_score,
            contrast_score=result.contrast_score,
            underexposed_fraction=result.underexposed_fraction,
            overexposed_fraction=result.overexposed_fraction,
            clipped_fraction=result.clipped_fraction,
            quality_status=result.quality_status.value,
            requires_human_review=result.requires_human_review,
            review_reasons=result.review_reasons,
            raw_metrics=result.raw_metrics,
            image_width=result.image_width,
            image_height=result.image_height,
            image_format=result.image_format,
            metric_version=result.metric_version,
            disclaimer=result.disclaimer,
        )

    async def verify_geometry(
        self,
        detected_faces: list[DetectedFace],
        image_width: int,
        image_height: int,
        governance_record_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        padding_ratio: float = 0.10,
        consolidate_overlapping: bool = True,
    ) -> RedactionGeometryResponse:
        """Verify geometry and overlap consolidation of detected face bounding boxes (Phase 76)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_DETECTION_EXECUTE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_DETECTION_EXECUTE permission.",
                code="FACE_DETECTION_DENIED",
            )

        # Validate approved governance authorization
        gov_record = await self.governance_repo.get_by_id(
            governance_record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if gov_record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{governance_record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        if gov_record.status != GovernanceStatus.APPROVED.value:
            raise BiometricGovernanceError(
                f"Governance record '{governance_record_id}' is not approved (current status: '{gov_record.status}').",
                code="GOVERNANCE_NOT_APPROVED",
            )

        pol = RedactionGeometryPolicy(
            padding_ratio=padding_ratio,
            consolidate_overlapping=consolidate_overlapping,
        )
        result = verify_redaction_geometry(
            detected_faces=detected_faces,
            image_width=image_width,
            image_height=image_height,
            policy=pol,
        )

        return RedactionGeometryResponse(
            geometry_valid=result.geometry_valid,
            total_boxes=result.total_boxes,
            valid_box_count=result.valid_box_count,
            invalid_box_count=result.invalid_box_count,
            overlap_count=result.overlap_count,
            clipped_box_count=result.clipped_box_count,
            consolidated_boxes=result.consolidated_boxes,
            landmark_coverage_valid=result.landmark_coverage_valid,
            requires_human_review=result.requires_human_review,
            review_reasons=result.review_reasons,
            geometry_version=result.geometry_version,
            disclaimer=result.disclaimer,
        )

    async def get_detection_robustness_report(
        self,
        principal: AuthenticatedPrincipal,
    ) -> FaceDetectionRobustnessAuditRead:
        """Execute Phase 79 comprehensive detection quality, robustness, and input-integrity audit."""
        if not has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
                Permission.BIOMETRIC_AUDIT_READ,
                Permission.BIOMETRIC_DETECTION_EXECUTE,
            ],
        ):
            raise PermissionDeniedError(
                "Caller lacks permission to access face detection robustness reports.",
                code="DETECTION_REPORT_DENIED",
            )

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_POLICY_EVALUATED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                target_id="phase79-detection-robustness",
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "operation": "get_detection_robustness_report",
                    "phase": 79,
                    "fairness_status": "NOT ESTABLISHED",
                },
            )

        report = run_full_detection_robustness_audit()
        return FaceDetectionRobustnessAuditRead.model_validate(report.to_dict())


class FaceMatchingService:
    """Service executing advisory biometric matching with uncertainty bands and fail-closed controls (Phase 76-78)."""

    def __init__(
        self,
        governance_repo: BiometricGovernanceRepository,
        reference_repo: BiometricReferenceRepository,
        verification_repo: BiometricVerificationRepository,
        settings: Settings,
        audit_repo: AuditRepository | None = None,
        key_manager: BiometricKeyManager | None = None,
    ) -> None:
        self.governance_repo = governance_repo
        self.reference_repo = reference_repo
        self.verification_repo = verification_repo
        self.settings = settings
        self.audit_repo = audit_repo
        self.key_manager = key_manager or get_biometric_key_manager()

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings,
        *,
        audit_repo: AuditRepository | None = None,
        key_manager: BiometricKeyManager | None = None,
    ) -> FaceMatchingService:
        return cls(
            governance_repo=BiometricGovernanceRepository(session),
            reference_repo=BiometricReferenceRepository(session),
            verification_repo=BiometricVerificationRepository(session),
            settings=settings,
            audit_repo=audit_repo or AuditRepository(session),
            key_manager=key_manager,
        )

    async def match_faces(
        self,
        payload: FaceMatchRequest,
        principal: AuthenticatedPrincipal,
    ) -> FaceMatchResponse:
        """Execute biometric face matching with uncertainty bands and audit logging (Phase 76 & 77)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_MATCHING_EXECUTE):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_MATCHING_EXECUTE permission.",
                code="BIOMETRIC_MATCHING_DENIED",
            )

        if (
            not self.settings.BIOMETRIC_ANALYSIS_ENABLED
            or not self.settings.BIOMETRIC_MATCHING_ENABLED
        ):
            raise BiometricsDisabledError(
                "Biometric face matching is strictly disabled in system settings. "
                "Automated matching is prohibited in production and requires explicit legal approval.",
                code="BIOMETRIC_MATCHING_DISABLED",
            )

        try:
            probe_bytes = base64.b64decode(payload.probe_image_base64)
        except Exception as exc:
            raise BusinessRuleError("Invalid base64 encoding for probe image.") from exc

        if len(probe_bytes) > self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES:
            raise PayloadTooLargeError(
                f"Probe image size ({len(probe_bytes)} bytes) exceeds maximum limit "
                f"({self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES} bytes).",
                code="PAYLOAD_TOO_LARGE",
            )

        gov_record = await self.governance_repo.get_by_id(
            payload.governance_record_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if gov_record is None:
            raise ResourceNotFoundError(
                f"Biometric governance record '{payload.governance_record_id}' not found.",
                code="GOVERNANCE_RECORD_NOT_FOUND",
            )

        if gov_record.status != GovernanceStatus.APPROVED.value:
            raise BiometricGovernanceError(
                f"Face matching requires an approved governance record; current status is '{gov_record.status}'.",
                code="GOVERNANCE_NOT_APPROVED",
            )

        now = datetime.now(UTC)
        gov_exp = getattr(gov_record, "retention_expires_at", None)
        if isinstance(gov_exp, datetime) and gov_exp <= now:
            raise BiometricGovernanceError(
                "Governance record retention period has expired.",
                code="RETENTION_EXPIRED",
            )

        if gov_record.consent_status == ConsentStatus.WITHDRAWN.value:
            raise BiometricGovernanceError(
                "Face matching cannot be executed under withdrawn subject consent.",
                code="CONSENT_WITHDRAWN",
            )

        if (
            gov_record.lawful_basis == BiometricLawfulBasis.EXPLICIT_CONSENT.value
            and gov_record.consent_status != ConsentStatus.ACTIVE.value
        ):
            raise BiometricGovernanceError(
                "Face matching requires active subject consent when lawful basis is explicit_consent.",
                code="CONSENT_NOT_ACTIVE",
            )

        permitted_purposes = {
            BiometricPurpose.AUTHORIZED_INVESTIGATIVE_MANUAL_REVIEW.value,
            BiometricPurpose.TESTING_SYNTHETIC_BENCHMARK.value,
        }
        if gov_record.purpose not in permitted_purposes:
            raise BiometricGovernanceError(
                f"Governance purpose '{gov_record.purpose}' is not authorized for face matching.",
                code="UNAUTHORIZED_BIOMETRIC_PURPOSE",
            )

        probe_quality = assess_face_image_quality(probe_bytes)
        if not probe_quality.is_acceptable:
            if self.audit_repo:
                await self.audit_repo.append_event(
                    action=AuditAction.BIOMETRIC_QUALITY_FAILED.value,
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    department_id=principal.department_id,
                    target_type=AuditTargetType.BIOMETRIC_GOVERNANCE.value,
                    target_id=str(gov_record.id),
                    outcome=AuditOutcome.FAILURE.value,
                    details={
                        "reason": probe_quality.reason,
                        "quality_status": probe_quality.status.value,
                    },
                )
            raise BiometricQualityError(
                f"Probe image quality check failed: {probe_quality.reason}",
                code="PROBE_IMAGE_QUALITY_INSUFFICIENT",
            )

        probe_hash = hashlib.sha256(probe_bytes).hexdigest()

        matcher = get_face_matcher(
            enabled=self.settings.BIOMETRIC_MATCHING_ENABLED,
            provider=self.settings.BIOMETRIC_PROVIDER,
        )
        probe_vector = matcher.extract_features(probe_bytes)

        ref_vector: FaceFeatureVector | None = None
        ref_record_id: UUID | None = None

        if payload.reference_id is not None:
            ref = await self.reference_repo.get_by_id(
                payload.reference_id,
                department_id=principal.department_id
                if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"}
                else None,
            )
            if ref is None:
                raise ResourceNotFoundError(
                    f"Biometric reference '{payload.reference_id}' not found.",
                    code="BIOMETRIC_REFERENCE_NOT_FOUND",
                )
            if ref.status != BiometricReferenceStatus.ACTIVE.value:
                raise BiometricGovernanceError(
                    f"Biometric reference '{ref.reference_id}' is not active (status: {ref.status}).",
                    code="BIOMETRIC_REFERENCE_INACTIVE",
                )
            ref_exp = getattr(ref, "retention_expires_at", None)
            if (isinstance(ref_exp, datetime) and ref_exp <= now) or ref.status == BiometricReferenceStatus.EXPIRED.value:
                raise BiometricGovernanceError(
                    f"Biometric reference '{ref.reference_id}' retention period has expired.",
                    code="BIOMETRIC_REFERENCE_EXPIRED",
                )
            ref_record_id = ref.id

            if ref.encrypted_template:
                decrypted_raw = self.key_manager.decrypt(ref.encrypted_template)

                if self.audit_repo:
                    await self.audit_repo.append_event(
                        action=AuditAction.BIOMETRIC_KEY_ACCESSED.value,
                        actor_id=principal.user_id,
                        actor_role=principal.role_code,
                        department_id=principal.department_id,
                        target_type=AuditTargetType.BIOMETRIC_REFERENCE.value,
                        target_id=str(ref.id),
                        outcome=AuditOutcome.SUCCESS.value,
                        details={"reference_id": ref.reference_id},
                    )

                try:
                    parsed = json.loads(decrypted_raw.decode("utf-8"))
                    if isinstance(parsed, list):
                        ref_vector = FaceFeatureVector(
                            vector=[float(x) for x in parsed],
                            dimension=len(parsed),
                            model_name=probe_vector.model_name,
                            model_version=probe_vector.model_version,
                        )
                except Exception:
                    ref_vector = matcher.extract_features(decrypted_raw)

            elif payload.reference_image_base64:
                ref_bytes = base64.b64decode(payload.reference_image_base64)
                ref_quality = assess_face_image_quality(ref_bytes)
                if not ref_quality.is_acceptable:
                    raise BiometricQualityError(
                        f"Reference image quality check failed: {ref_quality.reason}",
                        code="REFERENCE_IMAGE_QUALITY_INSUFFICIENT",
                    )
                ref_vector = matcher.extract_features(ref_bytes)
            else:
                raise BiometricGovernanceError(
                    "Selected biometric reference has no stored template and no reference image was provided.",
                    code="REFERENCE_TEMPLATE_MISSING",
                )

        elif payload.reference_image_base64:
            try:
                ref_bytes = base64.b64decode(payload.reference_image_base64)
            except Exception as exc:
                raise BusinessRuleError("Invalid base64 encoding for reference image.") from exc
            if len(ref_bytes) > self.settings.BIOMETRIC_MAX_IMAGE_SIZE_BYTES:
                raise PayloadTooLargeError("Reference image size exceeds limit.")
            ref_quality = assess_face_image_quality(ref_bytes)
            if not ref_quality.is_acceptable:
                raise BiometricQualityError(
                    f"Reference image quality check failed: {ref_quality.reason}",
                    code="REFERENCE_IMAGE_QUALITY_INSUFFICIENT",
                )
            ref_vector = matcher.extract_features(ref_bytes)

        if ref_vector is None:
            raise BusinessRuleError("Unable to derive reference features for matching.")

        match_result = matcher.match_faces(probe_vector, ref_vector)

        tenant_id = principal.department_id or gov_record.tenant_id
        department_id = principal.department_id or gov_record.department_id
        review_record = BiometricVerificationReview(
            id=uuid4(),
            tenant_id=tenant_id,
            department_id=department_id,
            incident_id=payload.incident_id,
            reference_id=ref_record_id,
            probe_image_hash=probe_hash,
            candidate_similarity=match_result.similarity_score,
            uncertainty_lower_bound=match_result.uncertainty_lower_bound,
            uncertainty_upper_bound=match_result.uncertainty_upper_bound,
            automated_verdict=match_result.verdict.value,
            human_verdict=BiometricHumanVerdict.INCONCLUSIVE_DISMISSED.value,
            is_override=False,
        )
        created_review = await self.verification_repo.create(review_record)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_MATCHING_EXECUTED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_VERIFICATION.value,
                target_id=str(created_review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "similarity_score": match_result.similarity_score,
                    "verdict": match_result.verdict.value,
                    "probe_hash": probe_hash,
                    "model_name": match_result.model_name,
                    "latency_ms": match_result.comparison_latency_ms,
                },
            )

        return FaceMatchResponse(
            similarity_score=match_result.similarity_score,
            verdict=match_result.verdict.value,
            uncertainty_lower_bound=match_result.uncertainty_lower_bound,
            uncertainty_upper_bound=match_result.uncertainty_upper_bound,
            probe_image_hash=probe_hash,
            verification_review_id=created_review.id,
            model_name=match_result.model_name,
            model_version=match_result.model_version,
            latency_ms=match_result.comparison_latency_ms,
            disclaimer=match_result.disclaimer,
            metadata=match_result.metadata,
        )


class BiometricVerificationService:
    """Service managing authorized human review and oversight of biometric candidates (Phase 77)."""

    def __init__(
        self,
        verification_repo: BiometricVerificationRepository,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self.verification_repo = verification_repo
        self.audit_repo = audit_repo

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        audit_repo: AuditRepository | None = None,
    ) -> BiometricVerificationService:
        return cls(
            verification_repo=BiometricVerificationRepository(session),
            audit_repo=audit_repo or AuditRepository(session),
        )

    async def get_review(
        self,
        review_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> BiometricVerificationReviewRead:
        """Fetch a single biometric verification review record."""
        review = await self.verification_repo.get_by_id(
            review_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric verification review '{review_id}' not found.",
                code="VERIFICATION_REVIEW_NOT_FOUND",
            )
        return BiometricVerificationReviewRead.model_validate(review)

    async def list_reviews(
        self,
        principal: AuthenticatedPrincipal,
        *,
        incident_id: UUID | None = None,
        is_override: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedBiometricVerificationReviewRead:
        """List biometric verification review records scoped to department."""
        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        items = await self.verification_repo.list_for_department(
            department_id=dept_id,
            incident_id=incident_id,
            is_override=is_override,
            limit=limit,
            offset=offset,
        )
        total = await self.verification_repo.count_for_department(
            department_id=dept_id,
            incident_id=incident_id,
            is_override=is_override,
        )
        return PaginatedBiometricVerificationReviewRead(
            items=[BiometricVerificationReviewRead.model_validate(r) for r in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def record_human_verdict(
        self,
        review_id: UUID,
        payload: BiometricVerificationReviewCreate,
        principal: AuthenticatedPrincipal,
    ) -> BiometricVerificationReviewRead:
        """Record authorized human determination with override audit logging (Phase 77)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_VERIFICATION_REVIEW):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_VERIFICATION_REVIEW permission.",
                code="VERIFICATION_REVIEW_DENIED",
            )

        review = await self.verification_repo.get_by_id(
            review_id,
            department_id=principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None,
        )
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric verification review '{review_id}' not found.",
                code="VERIFICATION_REVIEW_NOT_FOUND",
            )

        is_override = False
        if (
            payload.human_verdict == BiometricHumanVerdict.REJECTED_OVERRIDE
            or (
                review.automated_verdict == BiometricMatchVerdict.MATCH_CANDIDATE.value
                and payload.human_verdict == BiometricHumanVerdict.VERIFIED_NON_MATCH
            )
            or (
                review.automated_verdict == BiometricMatchVerdict.NON_MATCH_CANDIDATE.value
                and payload.human_verdict == BiometricHumanVerdict.VERIFIED_MATCH
            )
        ):
            is_override = True

        if is_override and not (payload.override_reason and payload.override_reason.strip()):
            raise BusinessRuleError(
                "A documented override_reason is strictly required when overruling automated candidate results.",
                code="OVERRIDE_REASON_REQUIRED",
            )

        review.human_verdict = payload.human_verdict.value
        review.reviewer_id = principal.user_id
        review.reviewed_at = datetime.now(UTC)
        review.review_notes = payload.review_notes
        review.override_reason = payload.override_reason
        review.is_override = is_override

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_VERIFICATION_RECORDED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_VERIFICATION.value,
                target_id=str(review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "human_verdict": payload.human_verdict.value,
                    "automated_verdict": review.automated_verdict,
                    "is_override": is_override,
                },
            )

        return BiometricVerificationReviewRead.model_validate(review)


class BiometricEvaluationService:
    """Service generating reproducible biometric evaluation summaries on synthetic benchmarks (Phase 79)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_evaluation_report(
        self,
        principal: AuthenticatedPrincipal,
    ) -> BiometricEvaluationSummaryRead:
        """Generate evaluation benchmark summary with explicit synthetic disclaimers."""
        if not has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
                Permission.BIOMETRIC_MATCHING_EXECUTE,
                Permission.BIOMETRIC_VERIFICATION_REVIEW,
            ],
        ):
            raise PermissionDeniedError(
                "Caller lacks permission to access biometric evaluation reports.",
                code="EVALUATION_REPORT_DENIED",
            )

        pairs = [
            (True, 0.95),
            (True, 0.92),
            (True, 0.88),
            (True, 0.86),
            (True, 0.78),
            (False, 0.15),
            (False, 0.22),
            (False, 0.35),
            (False, 0.55),
            (False, 0.68),
        ]
        subgroups = {
            "synthetic_subgroup_alpha": [(True, 0.92), (True, 0.88), (False, 0.20), (False, 0.30)],
            "synthetic_subgroup_beta": [(True, 0.90), (True, 0.85), (False, 0.25), (False, 0.35)],
        }
        pad_data = (50, 1, 50, 2)

        rep = evaluate_biometric_matching_benchmark(
            comparison_pairs=pairs,
            model_name="mock-face-matcher",
            model_version="1.0.0-test",
            failed_acquisitions=2,
            total_acquisition_attempts=12,
            presentation_attack_data=pad_data,
            subgroup_comparisons=subgroups,
        )

        pad_summary = None
        if rep.pad_metrics:
            pad_summary = {
                "apcer": rep.pad_metrics.apcer,
                "bpcer": rep.pad_metrics.bpcer,
                "total_attacks": rep.pad_metrics.total_attack_presentations,
                "total_bona_fide": rep.pad_metrics.total_bona_fide_presentations,
            }

        subgroup_data = [
            {
                "subgroup_name": s.subgroup_name,
                "sample_count": s.sample_count,
                "subgroup_fmr": s.subgroup_fmr,
                "subgroup_fnmr": s.subgroup_fnmr,
            }
            for s in rep.demographic_disparities
        ]

        return BiometricEvaluationSummaryRead(
            model_name=rep.model_name,
            model_version=rep.model_version,
            total_comparisons=rep.total_comparisons,
            fta_rate=rep.fta_rate,
            eer=rep.eer,
            eer_threshold=rep.eer_threshold,
            operational_fmr_at_085=rep.operational_fmr_at_085,
            operational_fnmr_at_085=rep.operational_fnmr_at_085,
            max_demographic_disparity_ratio=rep.max_demographic_disparity_ratio,
            disclaimer=rep.disclaimer,
            pad_summary=pad_summary,
            subgroups=subgroup_data,
        )


class QualityReviewWorkflowService:
    """Service managing evidence quality and redaction human review workflow (Phase 77).

    Enforces:
    - Department and tenant isolation.
    - RBAC: requires BIOMETRIC_VERIFICATION_REVIEW for review assignments and verdicts.
    - Permitted state machine transitions with fail-closed validation.
    - Rejection of invalid transitions and completed review lock.
    - Deterministic review decision evaluation based on Phase 75 & 76 outputs.
    - Complete metadata persistence with zero raw image bytes or biometric embeddings.
    - Immutable audit trails for creation, assignment, determination, escalation, and reopen.
    """

    def __init__(
        self,
        review_repo: BiometricQualityReviewRepository,
        audit_repo: AuditRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.review_repo = review_repo
        self.audit_repo = audit_repo
        self.settings = settings

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        audit_repo: AuditRepository | None = None,
    ) -> QualityReviewWorkflowService:
        """Construct QualityReviewWorkflowService bound to session."""
        return cls(
            review_repo=BiometricQualityReviewRepository(session),
            audit_repo=audit_repo or AuditRepository(session),
            settings=settings,
        )

    async def create_review_item(
        self,
        payload: BiometricQualityReviewCreate,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Create a new human review item from quality, geometry, and detection outcomes (Phase 77)."""
        can_create = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_DETECTION_EXECUTE,
                Permission.BIOMETRIC_VERIFICATION_REVIEW,
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
            ],
        )
        if not can_create:
            raise PermissionDeniedError(
                "Caller lacks required permission to create biometric quality review items.",
                code="CREATE_QUALITY_REVIEW_DENIED",
            )

        # 1. Deterministic evaluation of review decision
        decision, reasons = evaluate_unified_review_decision(
            detection_failed=payload.detection_failed,
            redaction_failed=payload.redaction_failed,
            redacted_faces_count=payload.redacted_faces_count,
            detected_faces_count=payload.detected_faces_count,
            quality_result=payload.quality_result,
            geometry_result=payload.geometry_result,
            has_partial_redaction=payload.has_partial_redaction,
            has_missing_landmarks=payload.has_missing_landmarks,
        )

        # Extract photometric and geometry metrics safely (metadata only)
        photometric_metrics: dict[str, float] = {}
        if isinstance(payload.quality_result, dict):
            raw_m = payload.quality_result.get("raw_metrics", {})
            if isinstance(raw_m, dict):
                photometric_metrics = {str(k): float(v) for k, v in raw_m.items() if isinstance(v, (int, float))}
            for k in ("sharpness_score", "exposure_score", "contrast_score", "clipped_fraction"):
                val = payload.quality_result.get(k)
                if isinstance(val, (int, float)):
                    photometric_metrics[k] = float(val)

        geometry_metrics: dict[str, Any] = {}
        if isinstance(payload.geometry_result, dict):
            for k in ("box_count", "overlap_clusters_count", "uncovered_landmarks_count", "is_valid", "geometry_status"):
                if k in payload.geometry_result:
                    geometry_metrics[k] = payload.geometry_result[k]

        component_versions = {
            "detector": "mock-detector-1.0",
            "quality": "1.0.0",
            "geometry": "1.0.0",
            "workflow": "1.0.0",
        }

        review = BiometricQualityReview(
            id=uuid4(),
            tenant_id=principal.department_id or uuid4(),
            department_id=principal.department_id,
            evidence_id=payload.evidence_id,
            governance_record_id=payload.governance_record_id,
            status=QualityReviewStatus.PENDING_REVIEW.value,
            unified_decision=decision.value,
            review_reasons=reasons,
            component_versions=component_versions,
            photometric_metrics=photometric_metrics,
            geometry_metrics=geometry_metrics,
            original_evidence_hash=payload.original_evidence_hash,
            redacted_artifact_hash=payload.redacted_artifact_hash,
            disclaimer=BIOMETRIC_ADVISORY_DISCLAIMER,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        created = await self.review_repo.create(review)

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_QUALITY_REVIEW_CREATED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value,
                target_id=str(created.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "unified_decision": decision.value,
                    "status": created.status,
                    "reasons_count": len(reasons),
                    "evidence_id": str(payload.evidence_id) if payload.evidence_id else None,
                },
            )

        return BiometricQualityReviewRead.model_validate(created)

    async def get_review(
        self,
        review_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Fetch a single biometric quality review record."""
        can_view = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_VERIFICATION_REVIEW,
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
                Permission.BIOMETRIC_AUDIT_READ,
            ],
        )
        if not can_view:
            raise PermissionDeniedError(
                "Caller lacks permission to view biometric quality review records.",
                code="VIEW_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        review = await self.review_repo.get_by_id(review_id, department_id=dept_id)
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric quality review '{review_id}' not found.",
                code="QUALITY_REVIEW_NOT_FOUND",
            )
        return BiometricQualityReviewRead.model_validate(review)

    async def list_reviews(
        self,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
        assigned_reviewer_id: UUID | None = None,
        evidence_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedBiometricQualityReviewRead:
        """List biometric quality review records scoped to department."""
        can_list = has_any_permission(
            principal.role,
            [
                Permission.BIOMETRIC_VERIFICATION_REVIEW,
                Permission.BIOMETRIC_GOVERNANCE_REVIEW,
                Permission.BIOMETRIC_AUDIT_READ,
            ],
        )
        if not can_list:
            raise PermissionDeniedError(
                "Caller lacks permission to list biometric quality review records.",
                code="LIST_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        items = await self.review_repo.list_for_department(
            department_id=dept_id,
            status=status,
            assigned_reviewer_id=assigned_reviewer_id,
            evidence_id=evidence_id,
            limit=limit,
            offset=offset,
        )
        total = await self.review_repo.count_for_department(
            department_id=dept_id,
            status=status,
            assigned_reviewer_id=assigned_reviewer_id,
            evidence_id=evidence_id,
        )
        return PaginatedBiometricQualityReviewRead(
            items=[BiometricQualityReviewRead.model_validate(r) for r in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def assign_reviewer(
        self,
        review_id: UUID,
        payload: BiometricQualityReviewAssignRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Assign review item to authorized reviewer and transition to IN_REVIEW (Phase 77)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_VERIFICATION_REVIEW):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_VERIFICATION_REVIEW permission to assign reviews.",
                code="ASSIGN_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        review = await self.review_repo.get_by_id(review_id, department_id=dept_id)
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric quality review '{review_id}' not found.",
                code="QUALITY_REVIEW_NOT_FOUND",
            )

        # Idempotency check: already assigned to same reviewer in IN_REVIEW
        if (
            review.assigned_reviewer_id == payload.reviewer_id
            and review.status == QualityReviewStatus.IN_REVIEW.value
        ):
            return BiometricQualityReviewRead.model_validate(review)

        # State transition validation
        validate_review_state_transition(
            QualityReviewStatus(review.status),
            QualityReviewStatus.IN_REVIEW,
        )

        review.assigned_reviewer_id = payload.reviewer_id
        review.assigned_at = datetime.now(UTC)
        review.status = QualityReviewStatus.IN_REVIEW.value

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_QUALITY_REVIEW_ASSIGNED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value,
                target_id=str(review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "reviewer_id": str(payload.reviewer_id),
                    "status": review.status,
                },
            )

        return BiometricQualityReviewRead.model_validate(review)

    async def record_human_verdict(
        self,
        review_id: UUID,
        payload: BiometricQualityReviewVerdictRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Record human determination and advance review state machine (Phase 77)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_VERIFICATION_REVIEW):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_VERIFICATION_REVIEW permission to record determinations.",
                code="VERDICT_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        review = await self.review_repo.get_by_id(review_id, department_id=dept_id)
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric quality review '{review_id}' not found.",
                code="QUALITY_REVIEW_NOT_FOUND",
            )

        # Caller must be assigned reviewer, or Dept Admin, or Super Admin
        is_assigned = (
            review.assigned_reviewer_id is not None
            and review.assigned_reviewer_id == principal.user_id
        )
        is_admin = principal.role_code in {"DEPT_ADMIN", "SUPER_ADMIN", RoleCode.DEPT_ADMIN.value, RoleCode.SUPER_ADMIN.value}
        if not is_assigned and not is_admin:
            raise PermissionDeniedError(
                "Only the assigned reviewer or a department administrator may record review determination.",
                code="NOT_ASSIGNED_REVIEWER",
            )

        # Determine target state machine status
        if payload.determination == HumanReviewDetermination.APPROVED.value:
            target_status = QualityReviewStatus.COMPLETED
        elif payload.determination == HumanReviewDetermination.REJECTED.value:
            target_status = QualityReviewStatus.COMPLETED
        elif payload.determination == HumanReviewDetermination.RE_REDACTION_REQUESTED.value:
            target_status = QualityReviewStatus.NEEDS_REDACTION
        else:
            raise BusinessRuleError(
                f"Unknown determination '{payload.determination}'.",
                code="INVALID_DETERMINATION",
            )

        # Validate state machine transition
        validate_review_state_transition(
            QualityReviewStatus(review.status),
            target_status,
        )

        review.status = target_status.value
        review.human_determination = payload.determination
        review.reviewed_by_id = principal.user_id
        review.reviewed_at = datetime.now(UTC)
        review.reviewer_notes = payload.notes or payload.justification

        if payload.determination == HumanReviewDetermination.APPROVED.value:
            review.unified_decision = UnifiedReviewDecision.REVIEW_COMPLETED.value

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_QUALITY_REVIEW_VERDICT.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value,
                target_id=str(review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "determination": payload.determination,
                    "status": review.status,
                    "has_notes": bool(review.reviewer_notes),
                },
            )

        return BiometricQualityReviewRead.model_validate(review)

    async def escalate_review(
        self,
        review_id: UUID,
        payload: BiometricQualityReviewEscalateRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Escalate review to supervisory or administrative review (Phase 77)."""
        if not has_permission(principal.role, Permission.BIOMETRIC_VERIFICATION_REVIEW):
            raise PermissionDeniedError(
                "Caller lacks BIOMETRIC_VERIFICATION_REVIEW permission to escalate reviews.",
                code="ESCALATE_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        review = await self.review_repo.get_by_id(review_id, department_id=dept_id)
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric quality review '{review_id}' not found.",
                code="QUALITY_REVIEW_NOT_FOUND",
            )

        validate_review_state_transition(
            QualityReviewStatus(review.status),
            QualityReviewStatus.ESCALATED,
        )

        review.status = QualityReviewStatus.ESCALATED.value
        review.escalation_reason = payload.escalation_reason

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_QUALITY_REVIEW_ESCALATED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value,
                target_id=str(review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "status": review.status,
                    "escalation_reason_length": len(payload.escalation_reason),
                },
            )

        return BiometricQualityReviewRead.model_validate(review)

    async def reopen_review(
        self,
        review_id: UUID,
        payload: BiometricQualityReviewReopenRequest,
        principal: AuthenticatedPrincipal,
    ) -> BiometricQualityReviewRead:
        """Administratively reopen a COMPLETED review item (Phase 77)."""
        is_admin = principal.role_code in {"DEPT_ADMIN", "SUPER_ADMIN", RoleCode.DEPT_ADMIN.value, RoleCode.SUPER_ADMIN.value} or has_permission(
            principal.role, Permission.BIOMETRIC_GOVERNANCE_REVIEW
        )
        if not is_admin:
            raise PermissionDeniedError(
                "Only administrative roles with BIOMETRIC_GOVERNANCE_REVIEW may reopen completed reviews.",
                code="REOPEN_QUALITY_REVIEW_DENIED",
            )

        dept_id = principal.department_id if principal.role_code not in {RoleCode.SUPER_ADMIN.value, "SUPER_ADMIN"} else None
        review = await self.review_repo.get_by_id(review_id, department_id=dept_id)
        if review is None:
            raise ResourceNotFoundError(
                f"Biometric quality review '{review_id}' not found.",
                code="QUALITY_REVIEW_NOT_FOUND",
            )

        validate_review_state_transition(
            QualityReviewStatus(review.status),
            QualityReviewStatus.PENDING_REVIEW,
            is_authorized_reopen=True,
        )

        review.status = QualityReviewStatus.PENDING_REVIEW.value
        review.reopen_reason = payload.reopen_reason
        review.assigned_reviewer_id = None
        review.assigned_at = None
        review.human_determination = None

        if self.audit_repo:
            await self.audit_repo.append_event(
                action=AuditAction.BIOMETRIC_QUALITY_REVIEW_REOPENED.value,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                department_id=principal.department_id,
                target_type=AuditTargetType.BIOMETRIC_QUALITY_REVIEW.value,
                target_id=str(review.id),
                outcome=AuditOutcome.SUCCESS.value,
                details={
                    "status": review.status,
                    "reopen_reason_length": len(payload.reopen_reason),
                },
            )

        return BiometricQualityReviewRead.model_validate(review)
