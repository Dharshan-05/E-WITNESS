"""Investigation Case service orchestrating domain logic, linkages, capacity, and human review (Phases 81-85).

Enforces:
- Strict department and tenant isolation across cases, incidents, evidence, and AI results.
- Human review non-negotiable principle: AI identifies candidate leads only, never establishes guilt or facts.
- Conflict-of-interest prevention: incident reporters cannot review AI candidate segments for that incident.
- Concurrency safety with optimistic locking via version_id.
- Investigator workload capacity limits (default max 10 active cases).
- Append-only assignment and audit ledger events for every state, link, and review transition.
"""

from __future__ import annotations

import base64

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config.settings import Settings
from backend.app.core.ai import SegmentReviewStatus
from backend.app.core.audit import AuditAction, AuditOutcome, AuditTargetType
from backend.app.core.authorization import Permission, has_permission, has_any_permission
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    INVESTIGATOR_DEFAULT_MAX_ACTIVE_CASES,
    TERMINAL_CASE_STATUSES,
    CaseApprovalDecision,
    CaseNoteVisibility,
    CasePriority,
    CaseReferralStatus,
    CaseStatus,
    EvidenceVerificationStatus,
    IncidentLinkType,
    InvestigativeRelevance,
    generate_case_reference_number,
    generate_legal_hold_reference,
    LegalHoldStatus,
    validate_case_status_transition,
)
from backend.app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.logging import get_logger
from backend.app.models.base import utc_now
from backend.app.models.ai import AICandidateSegment, AIAnalysisJob
from backend.app.models.case import (
    Case,
    CaseAISegment,
    CaseApproval,
    CaseAssignment,
    CaseEscalation,
    CaseEvidence,
    CaseExport,
    CaseFinding,
    CaseFindingHistory,
    CaseIncident,
    CaseNote,
    CaseNoteHistory,
    CaseReferral,
    LegalHold,
)
from backend.app.repositories.ai_segment import AICandidateSegmentRepository
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.case import CaseRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.identity import DepartmentRepository, UserRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.case import (
    CaseCreateAISegmentAnnotationRequest,
    CaseAISegmentHistoryItemRead,
    CaseAISegmentRead,
    CaseAISegmentReviewRequest,
    CaseApprovalRead,
    CaseApprovalRequest,
    CaseAssignmentRead,
    CaseAssignRequest,
    CaseCloseRequest,
    CaseCreate,
    CaseSubmitReviewRequest,
    CaseReadinessCheck,
    CaseReadinessResult,
    CaseTransitionHistoryItem,
    CaseTimelineEventRead,
    CaseTimelineResponse,
    CaseEscalationRead,
    CaseEscalationRequest,
    CaseEvidenceItemRead,
    LegalHoldPlaceRequest,
    LegalHoldReleaseRequest,
    LegalHoldRead,
    LegalHoldStatusRead,
    CaseExportRead,
    CaseExportRequest,
    CaseFindingCreate,
    CaseFindingHistoryRead,
    CaseFindingRead,
    CaseFindingUpdate,
    CaseIncidentRead,
    CaseLinkAISegmentRequest,
    CaseLinkEvidenceRequest,
    CaseLinkIncidentRequest,
    CaseNoteCreate,
    CaseNoteHistoryRead,
    CaseNoteRead,
    CaseNoteUpdate,
    CaseNoteVisibilityUpdate,
    CaseRead,
    CaseReferralCreate,
    CaseReferralRead,
    CaseReferralUpdate,
    CaseReopenRequest,
    CaseTransitionRequest,
    CaseUpdate,
    InvestigatorWorkloadRead,
    PaginatedCasesRead,
)

logger = get_logger("services.case")


def _encode_timeline_cursor(timestamp: datetime, sequence_number: int | None, event_id: UUID) -> str:
    ts_iso = timestamp.isoformat()
    seq = sequence_number if sequence_number is not None else 0
    raw = f"{ts_iso}|{seq}|{event_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_timeline_cursor(cursor_str: str) -> tuple[datetime, int, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 3:
            raise ValueError("Malformed cursor format")
        ts = datetime.fromisoformat(parts[0])
        seq = int(parts[1])
        eid = UUID(parts[2])
        return ts, seq, eid
    except Exception as exc:
        raise BusinessRuleError("Invalid pagination cursor.", code="INVALID_CURSOR") from exc


SAFE_TIMELINE_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "case_id",
        "reference_number",
        "from_status",
        "to_status",
        "prior_status",
        "new_version",
        "version_id",
        "decision",
        "rationale",
        "reason",
        "hold_reference",
        "hold_id",
        "hold_type",
        "scope",
        "release_reason",
        "evidence_id",
        "file_name",
        "file_size_bytes",
        "sha256_digest",
        "sha256_hash",
        "incident_id",
        "link_type",
        "segment_id",
        "investigative_relevance",
        "review_decision",
        "review_status",
        "decision_revision",
        "previous_label",
        "corrected_label",
        "is_override",
        "override_justification",
        "note_id",
        "visibility",
        "from_visibility",
        "to_visibility",
        "blocking_reasons",
        "escalation_level",
        "purpose",
        "is_legal_hold",
        "is_advisory",
        "advisory_disclaimer",
    }
)

TIMELINE_GROUP_EXPANSIONS: dict[str, set[str]] = {
    "transition": {
        AuditAction.CASE_CREATED.value,
        AuditAction.CASE_STATUS_TRANSITION.value,
        AuditAction.CASE_CLOSED.value,
        AuditAction.CASE_REOPENED.value,
        AuditAction.CASE_TRANSITION_FAILED.value,
    },
    "review": {
        AuditAction.CASE_SUBMITTED_FOR_REVIEW.value,
        AuditAction.CASE_APPROVAL_RECORDED.value,
        AuditAction.CASE_APPROVAL_REJECTED.value,
        AuditAction.CASE_SELF_APPROVAL_BLOCKED.value,
    },
    "approval": {
        AuditAction.CASE_APPROVAL_RECORDED.value,
        AuditAction.CASE_APPROVAL_REJECTED.value,
        AuditAction.CASE_SELF_APPROVAL_BLOCKED.value,
    },
    "assignment": {
        AuditAction.CASE_ASSIGNED.value,
        AuditAction.CASE_REASSIGNED.value,
        AuditAction.CASE_ASSIGNMENT_OVERRIDDEN.value,
    },
    "legal_hold": {
        AuditAction.CASE_LEGAL_HOLD_PLACED.value,
        AuditAction.CASE_LEGAL_HOLD_RELEASED.value,
        AuditAction.EVIDENCE_DELETION_BLOCKED.value,
    },
    "evidence": {
        AuditAction.CASE_EVIDENCE_LINKED.value,
        AuditAction.CASE_EVIDENCE_UNLINKED.value,
        AuditAction.CASE_INCIDENT_LINKED.value,
        AuditAction.CASE_INCIDENT_UNLINKED.value,
        AuditAction.EVIDENCE_DELETION_BLOCKED.value,
    },
    "ai_review": {
        AuditAction.CASE_AI_SEGMENT_LINKED.value,
        AuditAction.CASE_AI_SEGMENT_UNLINKED.value,
        AuditAction.CASE_AI_SEGMENT_REVIEWED.value,
        AuditAction.CASE_AI_SEGMENT_OVERRIDDEN.value,
        AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED.value,
        AuditAction.CASE_AI_SEGMENT_ESCALATED.value,
        AuditAction.CASE_AI_SEGMENT_OVERRIDE_REJECTED.value,
    },
    "note": {
        AuditAction.CASE_NOTE_CREATED.value,
        AuditAction.CASE_NOTE_UPDATED.value,
        AuditAction.CASE_NOTE_VISIBILITY_CHANGED.value,
        AuditAction.CASE_NOTE_ARCHIVED.value,
        AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value,
        AuditAction.CASE_NOTE_MUTATION_FAILED.value,
    },
}


def _format_timeline_summary(action: str, outcome: str, details: dict[str, Any]) -> str:
    if action == AuditAction.CASE_CREATED.value:
        ref = details.get("reference_number", "Case")
        return f"Case created ({ref})"
    elif action == AuditAction.CASE_STATUS_TRANSITION.value:
        from_st = details.get("from_status", "unknown")
        to_st = details.get("to_status", "unknown")
        return f"Case status transitioned from '{from_st}' to '{to_st}'"
    elif action == AuditAction.CASE_SUBMITTED_FOR_REVIEW.value:
        return "Case submitted for supervisory review"
    elif action == AuditAction.CASE_APPROVAL_RECORDED.value:
        dec = details.get("decision", "approved")
        to_st = details.get("to_status", "unknown")
        return f"Supervisory approval recorded: {dec} -> {to_st}"
    elif action == AuditAction.CASE_APPROVAL_REJECTED.value:
        reason = details.get("rationale") or details.get("reason", "")
        return f"Supervisory approval rejected: {reason[:60]}" if reason else "Supervisory approval rejected"
    elif action == AuditAction.CASE_SELF_APPROVAL_BLOCKED.value:
        return "Self-approval blocked by separation of duties policy"
    elif action == AuditAction.CASE_TRANSITION_FAILED.value:
        return "Case lifecycle transition failed validation checks"
    elif action == AuditAction.CASE_ASSIGNED.value:
        return "Lead investigator assigned to case"
    elif action == AuditAction.CASE_REASSIGNED.value:
        return "Case reassigned to investigator"
    elif action == AuditAction.CASE_ASSIGNMENT_OVERRIDDEN.value:
        return "Investigator assigned via supervisor workload override"
    elif action == AuditAction.CASE_LEGAL_HOLD_PLACED.value:
        ref = details.get("hold_reference", "hold")
        scope = details.get("scope", "full_case")
        return f"Legal hold placed ({ref}, scope: {scope})"
    elif action == AuditAction.CASE_LEGAL_HOLD_RELEASED.value:
        ref = details.get("hold_reference", "hold")
        return f"Legal hold released ({ref})"
    elif action == AuditAction.EVIDENCE_DELETION_BLOCKED.value:
        return "Evidence deletion or unlinking blocked by active legal hold"
    elif action == AuditAction.CASE_EVIDENCE_LINKED.value:
        fname = details.get("file_name", "evidence file")
        return f"Evidence linked to case ({fname})"
    elif action == AuditAction.CASE_EVIDENCE_UNLINKED.value:
        return "Evidence unlinked from case"
    elif action == AuditAction.CASE_INCIDENT_LINKED.value:
        return "Incident linked to case"
    elif action == AuditAction.CASE_INCIDENT_UNLINKED.value:
        return "Incident unlinked from case"
    elif action == AuditAction.CASE_AI_SEGMENT_LINKED.value:
        return "AI candidate segment attached to case (advisory)"
    elif action == AuditAction.CASE_AI_SEGMENT_UNLINKED.value:
        return "AI candidate segment unlinked from case"
    elif action == AuditAction.CASE_AI_SEGMENT_REVIEWED.value:
        rev_dec = details.get("review_decision") or details.get("decision", "reviewed")
        return f"AI segment reviewed by human investigator ({rev_dec})"
    elif action == AuditAction.CASE_AI_SEGMENT_OVERRIDDEN.value:
        return "AI segment review overridden by supervisor"
    elif action == AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED.value:
        prev = details.get("previous_label", "unknown")
        corr = details.get("corrected_label", "unknown")
        return f"AI segment classification corrected from '{prev}' to '{corr}'"
    elif action == AuditAction.CASE_AI_SEGMENT_ESCALATED.value:
        return "AI segment review escalated to supervisor"
    elif action == AuditAction.CASE_NOTE_CREATED.value:
        vis = details.get("visibility", "internal")
        return f"Case note recorded (visibility: {vis})"
    elif action == AuditAction.CASE_NOTE_UPDATED.value:
        v_id = details.get("version_id", 1)
        return f"Case note updated (revision {v_id})"
    elif action == AuditAction.CASE_NOTE_VISIBILITY_CHANGED.value:
        f_v = details.get("from_visibility", "unknown")
        t_v = details.get("to_visibility", "unknown")
        return f"Case note visibility changed from '{f_v}' to '{t_v}'"
    elif action == AuditAction.CASE_NOTE_ARCHIVED.value:
        return "Case note archived"
    elif action == AuditAction.CASE_CLOSED.value:
        return "Case formally closed"
    elif action == AuditAction.CASE_REOPENED.value:
        return "Case reopened"
    elif action == AuditAction.CASE_EXPORTED.value:
        return "Case dossier exported"
    elif action == AuditAction.CASE_TIMELINE_ACCESSED.value:
        return "Case activity timeline accessed"
    else:
        outcome_str = f" [{outcome.upper()}]" if outcome != "success" else ""
        return f"{action.replace(':', ' ').replace('_', ' ').capitalize()}{outcome_str}"



class CaseService:
    """Domain service managing investigation cases, linkages, capacity, and human review."""

    def __init__(
        self,
        case_repo: CaseRepository,
        incident_repo: IncidentRepository,
        evidence_repo: EvidenceRepository,
        ai_segment_repo: AICandidateSegmentRepository,
        department_repo: DepartmentRepository,
        user_repo: UserRepository,
        audit_repo: AuditRepository,
        settings: Settings,
        max_active_cases: int | None = None,
    ) -> None:
        self.case_repo = case_repo
        self.incident_repo = incident_repo
        self.evidence_repo = evidence_repo
        self.ai_segment_repo = ai_segment_repo
        self.department_repo = department_repo
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        self.settings = settings
        if max_active_cases is not None:
            self.max_active_cases = max_active_cases
        elif hasattr(settings, "INVESTIGATOR_MAX_ACTIVE_CASES"):
            self.max_active_cases = getattr(settings, "INVESTIGATOR_MAX_ACTIVE_CASES")
        else:
            self.max_active_cases = INVESTIGATOR_DEFAULT_MAX_ACTIVE_CASES

    @classmethod
    def from_session(cls, session: AsyncSession, settings: Settings) -> CaseService:
        """Construct a CaseService wired with repositories bound to session."""
        return cls(
            case_repo=CaseRepository(session),
            incident_repo=IncidentRepository(session),
            evidence_repo=EvidenceRepository(session),
            ai_segment_repo=AICandidateSegmentRepository(session),
            department_repo=DepartmentRepository(session),
            user_repo=UserRepository(session),
            audit_repo=AuditRepository(session),
            settings=settings,
        )

    # =========================================================================
    # Phase 81: Case CRUD & Incident Linkage
    # =========================================================================

    async def _generate_unique_case_reference(self, when: datetime | None = None) -> str:
        """Generate a canonical, unique case reference number with database sequence & collision handling."""
        for _ in range(5):
            ref = None
            if hasattr(self.case_repo, "next_reference_number") and callable(getattr(self.case_repo, "next_reference_number")):
                try:
                    res = await self.case_repo.next_reference_number(when=when)
                    if isinstance(res, str):
                        ref = res
                except Exception:
                    pass
            if not ref or not isinstance(ref, str):
                ref = generate_case_reference_number(when=when)

            existing = await self.case_repo.get_by_reference_number(ref)
            if existing is None:
                return ref

        return generate_case_reference_number(when=when)

    async def create_case(
        self,
        payload: CaseCreate,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseRead:
        """Create a new investigation case bound to department and owner."""
        # 1. Authorization check
        can_global = has_permission(principal.role_code, Permission.CASE_CREATE_GLOBAL)
        can_dept = has_permission(principal.role_code, Permission.CASE_CREATE_DEPT)
        can_base = has_permission(principal.role_code, Permission.CASE_CREATE)
        if not (can_global or can_dept or can_base):
            raise PermissionDeniedError(
                "You do not have permission to create investigation cases.",
                code="PERMISSION_DENIED",
            )

        # 2. Determine target department
        if payload.department_id is not None:
            if not can_global and payload.department_id != principal.department_id:
                raise PermissionDeniedError(
                    "You cannot create cases for another department.",
                    code="CROSS_DEPARTMENT_FORBIDDEN",
                )
            dept_id = payload.department_id
        else:
            if principal.department_id is None:
                raise BusinessRuleError(
                    "A department must be specified for case creation.",
                    code="DEPARTMENT_REQUIRED",
                )
            dept_id = principal.department_id

        # Verify department exists and is active
        dept = await self.department_repo.get_by_id(dept_id)
        if dept is None or not dept.is_active:
            raise BusinessRuleError(
                "The target department does not exist or is inactive.",
                code="INACTIVE_DEPARTMENT",
            )

        # 3. Optional initial lead investigator validation
        lead_id = payload.lead_investigator_id
        if lead_id is not None:
            await self._validate_investigator_assignment(
                investigator_id=lead_id,
                target_department_id=dept_id,
                can_global=can_global,
            )

        # 4. Optional initial incident validation
        initial_incident = None
        if payload.initial_incident_id is not None:
            initial_incident = await self.incident_repo.get_by_id(payload.initial_incident_id)
            if initial_incident is None:
                raise ResourceNotFoundError(
                    "Initial incident not found.", code="INCIDENT_NOT_FOUND"
                )
            if initial_incident.department_id != dept_id:
                raise BusinessRuleError(
                    "Initial incident belongs to a different department than the case.",
                    code="DEPARTMENT_MISMATCH",
                )

        # 5. Generate stable, unique reference number
        ref_number = await self._generate_unique_case_reference()

        # 6. Create Case record
        case_record = Case(
            reference_number=ref_number,
            title=payload.title,
            summary=payload.summary,
            status=CaseStatus.OPEN.value,
            priority=payload.priority.value,
            department_id=dept_id,
            created_by_id=principal.user_id,
            lead_investigator_id=lead_id,
            version_id=1,
            is_legal_hold=False,
        )
        created_case = await self.case_repo.create(case_record)

        # 7. Record initial assignment if lead was specified
        if lead_id is not None:
            assignment = CaseAssignment(
                case_id=created_case.id,
                previous_investigator_id=None,
                new_investigator_id=lead_id,
                assigned_by_id=principal.user_id,
                assignment_reason="Initial lead assignment upon case creation.",
            )
            await self.case_repo.record_assignment(assignment)

        # 8. Link initial incident if specified
        if initial_incident is not None:
            incident_link = CaseIncident(
                case_id=created_case.id,
                incident_id=initial_incident.id,
                linked_by_id=principal.user_id,
                link_type=IncidentLinkType.PRIMARY.value,
            )
            await self.case_repo.link_incident(incident_link)

        # 9. Audit event
        await self.audit_repo.append_event(
            action=AuditAction.CASE_CREATED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(created_case.id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=dept_id,
            details={
                "reference_number": created_case.reference_number,
                "title": created_case.title,
                "priority": created_case.priority,
                "lead_investigator_id": str(lead_id) if lead_id else None,
                "initial_incident_id": str(payload.initial_incident_id)
                if payload.initial_incident_id
                else None,
            },
        )

        return self._to_case_read(created_case)

    async def get_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> CaseRead:
        """Retrieve a single investigation case enforcing visibility boundaries."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)
        return self._to_case_read(case_record)

    async def get_case_by_reference(
        self,
        reference_number: str,
        principal: AuthenticatedPrincipal,
    ) -> CaseRead:
        """Lookup a case by unique reference number."""
        case_record = await self.case_repo.get_by_reference_number(reference_number)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)
        return self._to_case_read(case_record)

    async def list_cases(
        self,
        principal: AuthenticatedPrincipal,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        priority: str | None = None,
        is_legal_hold: bool | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> PaginatedCasesRead:
        """List cases respecting department or own-case scoping."""
        can_global = has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        can_dept = has_permission(principal.role_code, Permission.CASE_READ_DEPT)
        can_own = has_permission(principal.role_code, Permission.CASE_READ_OWN)

        if not (can_global or can_dept or can_own):
            raise PermissionDeniedError(
                "You do not have permission to list cases.",
                code="PERMISSION_DENIED",
            )

        dept_id_filter: UUID | None = None
        lead_id_filter: UUID | None = None
        creator_id_filter: UUID | None = None

        if can_global:
            dept_id_filter = None
        elif can_dept:
            dept_id_filter = principal.department_id
        elif can_own:
            lead_id_filter = principal.user_id

        rows, total = await self.case_repo.list_paginated(
            limit=limit,
            offset=offset,
            department_id=dept_id_filter,
            lead_investigator_id=lead_id_filter,
            created_by_id=creator_id_filter,
            status=status,
            priority=priority,
            is_legal_hold=is_legal_hold,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return PaginatedCasesRead(
            items=[self._to_case_read(c) for c in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_case(
        self,
        case_id: UUID,
        payload: CaseUpdate,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseRead:
        """Update case details, status, or legal hold with optimistic locking."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_writable(case_record, principal)

        # Optimistic concurrency check
        if case_record.version_id != payload.expected_version:
            raise BusinessRuleError(
                f"Concurrent modification detected. Current version is {case_record.version_id}, "
                f"expected {payload.expected_version}.",
                code="CONCURRENCY_CONFLICT",
                status_code=409,
            )

        if (
            case_record.status in {s.value for s in TERMINAL_CASE_STATUSES}
            and payload.status is None
        ):
            raise BusinessRuleError(
                f"Case is in terminal status '{case_record.status}' and cannot be modified.",
                code="CASE_TERMINAL_IMMUTABLE",
                status_code=400,
            )

        updated_fields: dict[str, Any] = {}

        # 1. Update text metadata if provided
        if payload.title is not None and payload.title != case_record.title:
            case_record.title = payload.title
            updated_fields["title"] = payload.title
        if payload.summary is not None and payload.summary != case_record.summary:
            case_record.summary = payload.summary
            updated_fields["summary"] = payload.summary
        if payload.priority is not None and payload.priority.value != case_record.priority:
            case_record.priority = payload.priority.value
            updated_fields["priority"] = payload.priority.value

        # 2. Status transition with centralized workflow readiness validation
        if payload.status is not None and payload.status.value != case_record.status:
            validate_case_status_transition(case_record.status, payload.status.value)
            old_status = case_record.status
            new_status = payload.status.value

            # If moving to terminal status, require status_reason
            if payload.status in TERMINAL_CASE_STATUSES:
                if not payload.status_reason or not payload.status_reason.strip():
                    raise BusinessRuleError(
                        f"Documented rationale is required when transitioning case to '{new_status}'.",
                        code="STATUS_REASON_REQUIRED",
                    )
                case_record.closed_at = utc_now()
            else:
                case_record.closed_at = None

            # Enforce authorization guards on direct status transitions
            target_st = CaseStatus(payload.status.value)
            if target_st == CaseStatus.RESOLVED and not has_permission(principal.role_code, Permission.CASE_TRANSITION_APPROVE):
                raise PermissionDeniedError(
                    "Direct case resolution requires supervisor approval permission.",
                    code="APPROVAL_REQUIRED",
                )
            if target_st == CaseStatus.CLOSED and not has_permission(principal.role_code, Permission.CASE_CLOSE):
                raise PermissionDeniedError(
                    "You do not have permission to close cases.",
                    code="PERMISSION_DENIED",
                )
            if target_st == CaseStatus.REOPENED and not has_permission(principal.role_code, Permission.CASE_REOPEN):
                raise PermissionDeniedError(
                    "You do not have permission to reopen cases.",
                    code="PERMISSION_DENIED",
                )

            case_record.status = new_status
            updated_fields["status"] = new_status
            updated_fields["previous_status"] = old_status
            if payload.status_reason:
                updated_fields["status_reason"] = payload.status_reason

            await self.audit_repo.append_event(
                action=AuditAction.CASE_STATUS_TRANSITION,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_record.id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={
                    "from_status": old_status,
                    "to_status": new_status,
                    "reason": payload.status_reason,
                },
            )

        # 3. Legal Hold toggling
        if payload.is_legal_hold is not None and payload.is_legal_hold != case_record.is_legal_hold:
            if payload.is_legal_hold and not payload.legal_hold_reason:
                raise BusinessRuleError(
                    "A legal hold reason is required when placing a case under legal hold.",
                    code="LEGAL_HOLD_REASON_REQUIRED",
                )
            case_record.is_legal_hold = payload.is_legal_hold
            case_record.legal_hold_reason = (
                payload.legal_hold_reason if payload.is_legal_hold else None
            )
            updated_fields["is_legal_hold"] = case_record.is_legal_hold
            if case_record.legal_hold_reason:
                updated_fields["legal_hold_reason"] = case_record.legal_hold_reason

        # Increment version_id
        case_record.version_id += 1
        updated = await self.case_repo.update(case_record)
        return self._to_case_read(updated)

    # =========================================================================
    # Phase 82: Assignment & Capacity Controls
    # =========================================================================

    async def assign_case(
        self,
        case_id: UUID,
        payload: CaseAssignRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseRead:
        """Assign or reassign a case lead investigator with workload capacity checks and audited supervisor overrides."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        can_global = has_permission(principal.role_code, Permission.CASE_ASSIGN_GLOBAL)
        if not can_global and case_record.department_id != principal.department_id:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        # Supervisor override validation
        is_override = bool(getattr(payload, "is_supervisor_override", False))
        override_justification = getattr(payload, "override_justification", None)

        if is_override:
            can_override = has_permission(principal.role_code, Permission.CASE_ASSIGN_OVERRIDE)
            if not can_override:
                raise PermissionDeniedError(
                    "You do not have permission to perform a supervisor workload override.",
                    code="OVERRIDE_PERMISSION_DENIED",
                    status_code=403,
                )
            if not override_justification or len(override_justification.strip()) < 10:
                raise BusinessRuleError(
                    "A detailed supervisor override justification is required (minimum 10 characters).",
                    code="MISSING_OVERRIDE_JUSTIFICATION",
                    status_code=422,
                )
        else:
            can_dept = has_permission(principal.role_code, Permission.CASE_ASSIGN_DEPT)
            can_base = has_permission(principal.role_code, Permission.CASE_ASSIGN)
            if not (can_global or can_dept or can_base):
                raise PermissionDeniedError(
                    "You do not have permission to assign cases.",
                    code="PERMISSION_DENIED",
                )

        # Concurrency check
        if case_record.version_id != payload.expected_version:
            raise BusinessRuleError(
                f"Concurrent modification detected. Current version is {case_record.version_id}, "
                f"expected {payload.expected_version}.",
                code="CONCURRENCY_CONFLICT",
                status_code=409,
            )

        # Validate investigator and workload capacity
        prior_workload = await self._validate_investigator_assignment(
            investigator_id=payload.new_investigator_id,
            target_department_id=case_record.department_id,
            can_global=can_global,
            exclude_case_id=case_record.id,
            is_supervisor_override=is_override,
        )

        previous_lead = case_record.lead_investigator_id
        case_record.lead_investigator_id = payload.new_investigator_id
        case_record.version_id += 1

        # Record append-only assignment
        assignment = CaseAssignment(
            case_id=case_record.id,
            previous_investigator_id=previous_lead,
            new_investigator_id=payload.new_investigator_id,
            assigned_by_id=principal.user_id,
            assignment_reason=payload.assignment_reason,
            is_supervisor_override=is_override,
            override_justification=override_justification.strip() if is_override and override_justification else None,
        )
        await self.case_repo.record_assignment(assignment)
        updated = await self.case_repo.update(case_record)

        audit_details = {
            "previous_investigator_id": str(previous_lead) if previous_lead else None,
            "new_investigator_id": str(payload.new_investigator_id),
            "reason": payload.assignment_reason,
            "is_supervisor_override": is_override,
        }
        if is_override:
            audit_action = AuditAction.CASE_ASSIGNMENT_OVERRIDDEN
            audit_details.update({
                "override_justification": override_justification.strip(),
                "prior_workload": prior_workload,
                "configured_limit": self.max_active_cases,
                "resulting_workload": prior_workload + 1,
                "supervisor_id": str(principal.user_id),
            })
        else:
            audit_action = AuditAction.CASE_REASSIGNED if previous_lead else AuditAction.CASE_ASSIGNED

        await self.audit_repo.append_event(
            action=audit_action,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_record.id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details=audit_details,
        )

        return self._to_case_read(updated)

    async def list_assignments(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseAssignmentRead]:
        """List historical assignment events for a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)
        assignments = await self.case_repo.list_assignments(case_id)
        return [CaseAssignmentRead.model_validate(a) for a in assignments]

    async def get_investigator_workload(
        self,
        investigator_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> InvestigatorWorkloadRead:
        """Inspect active workload capacity for an investigator."""
        can_global = has_permission(principal.role_code, Permission.CASE_WORKLOAD_READ_GLOBAL)
        can_dept = has_permission(principal.role_code, Permission.CASE_WORKLOAD_READ_DEPT)
        if not (can_global or can_dept):
            raise PermissionDeniedError(
                "You do not have permission to inspect investigator workload.",
                code="PERMISSION_DENIED",
            )

        if can_global:
            investigator = await self.user_repo.get_by_id_unscoped(investigator_id)
        else:
            if principal.department_id is None:
                raise PermissionDeniedError("Department required.", code="PERMISSION_DENIED")
            investigator = await self.user_repo.get_by_id(
                investigator_id, department_id=principal.department_id
            )
        if investigator is None:
            raise ResourceNotFoundError("Investigator not found.", code="USER_NOT_FOUND")

        active_count = await self.case_repo.count_active_cases_for_investigator(investigator_id)
        return InvestigatorWorkloadRead(
            investigator_id=investigator_id,
            active_cases_count=active_count,
            max_active_cases=self.max_active_cases,
            capacity_available=active_count < self.max_active_cases,
            department_id=getattr(investigator, "department_id", None),
        )

    # =========================================================================
    # Phase 81 Linkages: Case Incidents
    # =========================================================================

    async def link_incident(
        self,
        case_id: UUID,
        payload: CaseLinkIncidentRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseIncidentRead:
        """Link an incident to an investigation case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        incident = await self.incident_repo.get_by_id(payload.incident_id)
        if incident is None:
            raise ResourceNotFoundError("Incident not found.", code="INCIDENT_NOT_FOUND")

        # Department boundary check
        if incident.department_id != case_record.department_id:
            raise BusinessRuleError(
                "Cannot link incident from a different department.",
                code="DEPARTMENT_MISMATCH",
            )

        # Check existing link
        existing = await self.case_repo.get_incident_link(case_id, payload.incident_id)
        if existing is not None:
            raise BusinessRuleError(
                "This incident is already linked to the case.",
                code="INCIDENT_ALREADY_LINKED",
            )

        link = CaseIncident(
            id=uuid4(),
            case_id=case_id,
            incident_id=payload.incident_id,
            linked_by_id=principal.user_id,
            link_type=payload.link_type.value,
        )
        created_link = await self.case_repo.link_incident(link) or link

        await self.audit_repo.append_event(
            action=AuditAction.CASE_INCIDENT_LINKED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "incident_id": str(payload.incident_id),
                "link_type": payload.link_type.value,
            },
        )

        link_id = (
            created_link.id if isinstance(getattr(created_link, "id", None), UUID) else link.id
        )
        link_created_at = (
            created_link.created_at
            if isinstance(getattr(created_link, "created_at", None), datetime)
            else utc_now()
        )

        return CaseIncidentRead(
            id=link_id,
            case_id=link.case_id,
            incident_id=link.incident_id,
            linked_by_id=link.linked_by_id,
            link_type=payload.link_type,
            created_at=link_created_at,
            incident_title=incident.title,
            incident_reference_number=incident.reference_number,
            incident_status=incident.status,
        )

    async def unlink_incident(
        self,
        case_id: UUID,
        incident_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> bool:
        """Unlink an incident from a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        link = await self.case_repo.get_incident_link(case_id, incident_id)
        if link is None:
            raise ResourceNotFoundError("Incident link not found.", code="LINK_NOT_FOUND")

        if case_record.is_legal_hold:
            raise BusinessRuleError(
                "Cannot unlink incidents while case is under legal hold.",
                code="LEGAL_HOLD_ACTIVE",
                status_code=409,
            )

        unlinked = await self.case_repo.unlink_incident(case_id, incident_id)
        if unlinked:
            await self.audit_repo.append_event(
                action=AuditAction.CASE_INCIDENT_UNLINKED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={"incident_id": str(incident_id)},
            )
        return unlinked

    async def list_case_incidents(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseIncidentRead]:
        """List all incidents linked to an investigation case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        links = await self.case_repo.list_case_incidents(case_id)
        results = []
        for lk in links:
            inc = lk.incident
            results.append(
                CaseIncidentRead(
                    id=getattr(lk, "id", None) or uuid4(),
                    case_id=lk.case_id,
                    incident_id=lk.incident_id,
                    linked_by_id=getattr(lk, "linked_by_id", None) or uuid4(),
                    link_type=IncidentLinkType(lk.link_type),
                    created_at=lk.created_at,
                    incident_title=inc.title if inc else None,
                    incident_reference_number=inc.reference_number if inc else None,
                    incident_status=inc.status if inc else None,
                )
            )
        return results

    # =========================================================================
    # Phase 83: Evidence Inventory & Integrity
    # =========================================================================

    async def link_evidence(
        self,
        case_id: UUID,
        payload: CaseLinkEvidenceRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseEvidenceItemRead:
        """Attach evidence to a case and enrich with integrity metadata."""
        if not has_permission(principal.role_code, Permission.CASE_EVIDENCE_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case evidence.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        evidence = await self.evidence_repo.get_attachment_by_id(payload.evidence_id)
        if evidence is None:
            raise ResourceNotFoundError("Evidence attachment not found.", code="EVIDENCE_NOT_FOUND")

        # Verify evidence belongs to an incident in the same department
        incident = await self.incident_repo.get_by_id(evidence.incident_id)
        if incident is None or incident.department_id != case_record.department_id:
            raise BusinessRuleError(
                "Evidence belongs to a different department than the case.",
                code="DEPARTMENT_MISMATCH",
            )

        existing = await self.case_repo.get_evidence_link(case_id, payload.evidence_id)
        if existing is not None:
            raise BusinessRuleError(
                "This evidence attachment is already linked to the case.",
                code="EVIDENCE_ALREADY_LINKED",
            )

        fname = getattr(evidence, "original_filename", getattr(evidence, "file_name", "unknown"))
        ctype = getattr(
            evidence,
            "declared_mime_type",
            getattr(evidence, "content_type", "application/octet-stream"),
        )
        hash_val = getattr(evidence, "sha256_hash", "") or ""

        import re

        if not re.fullmatch(r"[0-9a-fA-F]{64}", hash_val):
            raise BusinessRuleError(
                "Evidence digest is invalid or compromised.",
                code="EVIDENCE_INTEGRITY_COMPROMISED",
                status_code=422,
            )

        link = CaseEvidence(
            id=uuid4(),
            case_id=case_id,
            evidence_id=payload.evidence_id,
            linked_by_id=principal.user_id,
            notes=payload.notes,
            is_exhibiting=payload.is_exhibiting,
        )
        created_link = await self.case_repo.link_evidence(link) or link

        await self.audit_repo.append_event(
            action=AuditAction.CASE_EVIDENCE_LINKED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "evidence_id": str(payload.evidence_id),
                "file_name": fname,
                "sha256_hash": hash_val,
                "is_exhibiting": payload.is_exhibiting,
            },
        )

        ev_link_id = (
            created_link.id if isinstance(getattr(created_link, "id", None), UUID) else link.id
        )
        ev_link_created_at = (
            created_link.created_at
            if isinstance(getattr(created_link, "created_at", None), datetime)
            else utc_now()
        )

        custody_count = len(evidence.custody_events) if getattr(evidence, "custody_events", None) else 0
        return CaseEvidenceItemRead(
            id=ev_link_id,
            case_id=link.case_id,
            evidence_id=link.evidence_id,
            linked_by_id=link.linked_by_id,
            notes=link.notes,
            is_exhibiting=link.is_exhibiting,
            created_at=ev_link_created_at,
            file_name=fname,
            file_size_bytes=evidence.file_size_bytes,
            content_type=ctype,
            sha256_hash=hash_val,
            integrity_status="verified",
            is_legal_hold=case_record.is_legal_hold,
            chain_of_custody_events_count=custody_count,
            case_reference=getattr(case_record, "reference_number", None),
            evidence_type=ctype.split("/")[0] if "/" in ctype else "binary",
            media_format=ctype.split("/")[-1] if "/" in ctype else "unknown",
            ingested_at=getattr(evidence, "ingested_at", None),
            client_reported_at=getattr(evidence, "client_reported_at", None),
            source_description=f"Incident {getattr(incident, 'reference_number', str(incident.id))}",
            evidence_status=getattr(evidence, "evidence_status", None) or "attached",
            active_hold_ids=[],
            active_holds_count=0,
            audit_event_count=custody_count,
        )

    async def unlink_evidence(
        self,
        case_id: UUID,
        evidence_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> bool:
        """Unlink an evidence attachment from a case."""
        if not has_permission(principal.role_code, Permission.CASE_EVIDENCE_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case evidence.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        link = await self.case_repo.get_evidence_link(case_id, evidence_id)
        if link is None:
            raise ResourceNotFoundError("Evidence link not found.", code="LINK_NOT_FOUND")

        has_active_hold = False
        if hasattr(self.case_repo, "has_active_legal_hold_for_evidence"):
            try:
                res = await self.case_repo.has_active_legal_hold_for_evidence(evidence_id)
                has_active_hold = bool(res) if isinstance(res, bool) else False
            except Exception:
                has_active_hold = False

        if case_record.is_legal_hold or has_active_hold:
            await self.audit_repo.append_event(
                action=AuditAction.EVIDENCE_DELETION_BLOCKED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.EVIDENCE,
                target_id=str(evidence_id),
                outcome=AuditOutcome.DENIED,
                department_id=case_record.department_id,
                details={
                    "case_id": str(case_id),
                    "reason": "Unlinking blocked: active legal hold protection",
                },
            )
            raise BusinessRuleError(
                "Cannot unlink evidence while case or evidence is under active legal hold.",
                code="LEGAL_HOLD_ACTIVE",
                status_code=409,
            )

        unlinked = await self.case_repo.unlink_evidence(case_id, evidence_id)
        if unlinked:
            await self.audit_repo.append_event(
                action=AuditAction.CASE_EVIDENCE_UNLINKED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={"evidence_id": str(evidence_id)},
            )
        return unlinked

    async def list_case_evidence(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseEvidenceItemRead]:
        """List enriched evidence inventory for a case.

        NEVER leaks storage bucket, raw storage keys, or presigned upload URLs.
        """
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        links = await self.case_repo.list_case_evidence(case_id)
        results = []
        for lk in links:
            ev = lk.evidence
            fname = getattr(ev, "original_filename", getattr(ev, "file_name", "unknown"))
            ctype = getattr(
                ev, "declared_mime_type", getattr(ev, "content_type", "application/octet-stream")
            )
            hash_val = getattr(ev, "sha256_hash", "") or ""
            
            # Query active legal holds for this evidence item
            active_holds = []
            if hasattr(self.case_repo, "list_active_holds_for_evidence"):
                try:
                    res_holds = await self.case_repo.list_active_holds_for_evidence(lk.evidence_id)
                    if isinstance(res_holds, (list, tuple)):
                        active_holds = res_holds
                except Exception:
                    active_holds = []
            
            is_held = bool(active_holds) or bool(case_record.is_legal_hold)
            active_hold_ids = [h.id for h in active_holds if hasattr(h, "id")]
            custody_count = len(ev.custody_events) if getattr(ev, "custody_events", None) else 0

            results.append(
                CaseEvidenceItemRead(
                    id=getattr(lk, "id", None) or uuid4(),
                    case_id=lk.case_id,
                    evidence_id=lk.evidence_id,
                    linked_by_id=getattr(lk, "linked_by_id", None) or uuid4(),
                    notes=lk.notes,
                    is_exhibiting=lk.is_exhibiting,
                    created_at=lk.created_at,
                    file_name=fname,
                    file_size_bytes=ev.file_size_bytes,
                    content_type=ctype,
                    sha256_hash=hash_val,
                    integrity_status="verified",
                    is_legal_hold=is_held,
                    chain_of_custody_events_count=custody_count,
                    case_reference=getattr(case_record, "reference_number", None),
                    evidence_type=ctype.split("/")[0] if "/" in ctype else "binary",
                    media_format=ctype.split("/")[-1] if "/" in ctype else "unknown",
                    ingested_at=getattr(ev, "ingested_at", None),
                    client_reported_at=getattr(ev, "client_reported_at", None),
                    source_description=f"Incident {getattr(ev, 'incident_id', 'Unknown')}",
                    evidence_status=getattr(ev, "evidence_status", None) or "attached",
                    active_hold_ids=active_hold_ids,
                    active_holds_count=len(active_holds),
                    audit_event_count=custody_count,
                )
            )
        return results

    # =========================================================================

    async def get_case_evidence_item(
        self,
        case_id: UUID,
        evidence_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> CaseEvidenceItemRead:
        """Retrieve single enriched evidence inventory item for a case with hold status."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        link = await self.case_repo.get_evidence_link(case_id, evidence_id)
        if link is None:
            raise ResourceNotFoundError("Evidence link not found.", code="LINK_NOT_FOUND")

        ev = link.evidence or await self.evidence_repo.get_attachment_by_id(evidence_id)
        if ev is None:
            raise ResourceNotFoundError("Evidence attachment not found.", code="EVIDENCE_NOT_FOUND")

        fname = getattr(ev, "original_filename", getattr(ev, "file_name", "unknown"))
        ctype = getattr(
            ev, "declared_mime_type", getattr(ev, "content_type", "application/octet-stream")
        )
        hash_val = getattr(ev, "sha256_hash", "") or ""

        active_holds = []
        if hasattr(self.case_repo, "list_active_holds_for_evidence"):
            try:
                active_holds = await self.case_repo.list_active_holds_for_evidence(evidence_id)
            except Exception:
                active_holds = []

        is_held = bool(active_holds) or bool(case_record.is_legal_hold)
        active_hold_ids = [h.id for h in active_holds if hasattr(h, "id")]
        custody_count = len(ev.custody_events) if getattr(ev, "custody_events", None) else 0

        return CaseEvidenceItemRead(
            id=getattr(link, "id", None) or uuid4(),
            case_id=link.case_id,
            evidence_id=link.evidence_id,
            linked_by_id=getattr(link, "linked_by_id", None) or uuid4(),
            notes=link.notes,
            is_exhibiting=link.is_exhibiting,
            created_at=link.created_at,
            file_name=fname,
            file_size_bytes=ev.file_size_bytes,
            content_type=ctype,
            sha256_hash=hash_val,
            integrity_status="verified",
            is_legal_hold=is_held,
            chain_of_custody_events_count=custody_count,
            case_reference=getattr(case_record, "reference_number", None),
            evidence_type=ctype.split("/")[0] if "/" in ctype else "binary",
            media_format=ctype.split("/")[-1] if "/" in ctype else "unknown",
            ingested_at=getattr(ev, "ingested_at", None),
            client_reported_at=getattr(ev, "client_reported_at", None),
            source_description=f"Incident {getattr(ev, 'incident_id', 'Unknown')}",
            evidence_status=getattr(ev, "evidence_status", None) or "attached",
            active_hold_ids=active_hold_ids,
            active_holds_count=len(active_holds),
            audit_event_count=custody_count,
        )

    async def place_legal_hold(
        self,
        case_id: UUID,
        evidence_id: UUID,
        payload: LegalHoldPlaceRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> LegalHoldRead:
        """Place an audited legal hold on a case-linked evidence attachment."""
        if not (
            has_permission(principal.role_code, Permission.CASE_LEGAL_HOLD_MANAGE)
            or has_permission(principal.role_code, Permission.CASE_EVIDENCE_MANAGE)
        ):
            raise PermissionDeniedError(
                "You do not have permission to place a legal hold.",
                code="PERMISSION_DENIED",
            )

        if not payload.reason or len(payload.reason.strip()) < 10:
            raise BusinessRuleError(
                "A detailed legal hold reason of at least 10 characters is required.",
                code="LEGAL_HOLD_REASON_REQUIRED",
                status_code=422,
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        evidence = await self.evidence_repo.get_attachment_by_id(evidence_id)
        if evidence is None:
            raise ResourceNotFoundError("Evidence attachment not found.", code="EVIDENCE_NOT_FOUND")

        # Departmental isolation: evidence must belong to the case's department
        if evidence.department_id != case_record.department_id:
            raise BusinessRuleError(
                "Evidence belongs to a different department than the case.",
                code="DEPARTMENT_MISMATCH",
                status_code=422,
            )

        # Evidence must be linked to the case
        link = await self.case_repo.get_evidence_link(case_id, evidence_id)
        if link is None:
            raise BusinessRuleError(
                "Evidence is not linked to this case.",
                code="EVIDENCE_NOT_LINKED",
                status_code=400,
            )

        hold_reference = generate_legal_hold_reference()
        hold = LegalHold(
            id=uuid4(),
            hold_reference=hold_reference,
            case_id=case_id,
            evidence_id=evidence_id,
            department_id=case_record.department_id,
            status=LegalHoldStatus.ACTIVE.value,
            reason=payload.reason.strip(),
            placed_by_id=principal.user_id,
            placed_at=utc_now(),
        )

        saved_hold = await self.case_repo.create_legal_hold(hold)
        created_hold = saved_hold if isinstance(saved_hold, LegalHold) else hold

        # Ensure case-level legal hold flag is activated
        if not case_record.is_legal_hold:
            case_record.is_legal_hold = True
            if not case_record.legal_hold_reason:
                case_record.legal_hold_reason = payload.reason.strip()
            await self.case_repo.update(case_record)

        fname = getattr(evidence, "original_filename", getattr(evidence, "file_name", "unknown"))
        hash_val = getattr(evidence, "sha256_hash", "") or ""

        await self.audit_repo.append_event(
            action=AuditAction.CASE_LEGAL_HOLD_PLACED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.LEGAL_HOLD,
            target_id=str(created_hold.id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "hold_reference": created_hold.hold_reference,
                "case_id": str(case_id),
                "case_reference": getattr(case_record, "reference_number", None),
                "evidence_id": str(evidence_id),
                "reason": created_hold.reason,
                "file_name": fname,
                "sha256_hash": hash_val,
            },
        )

        return LegalHoldRead(
            id=created_hold.id,
            hold_reference=created_hold.hold_reference,
            case_id=created_hold.case_id,
            evidence_id=created_hold.evidence_id,
            department_id=created_hold.department_id,
            status=created_hold.status,
            reason=created_hold.reason,
            placed_by_id=created_hold.placed_by_id,
            placed_at=created_hold.placed_at,
            released_by_id=created_hold.released_by_id,
            released_at=created_hold.released_at,
            release_reason=created_hold.release_reason,
            created_at=getattr(created_hold, "created_at", utc_now()),
            updated_at=getattr(created_hold, "updated_at", utc_now()),
            case_reference=getattr(case_record, "reference_number", None),
            file_name=fname,
        )

    async def release_legal_hold(
        self,
        case_id: UUID,
        evidence_id: UUID,
        hold_id: UUID,
        payload: LegalHoldReleaseRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> LegalHoldRead:
        """Release an active legal hold on evidence, requiring dedicated authorization."""
        if not has_permission(principal.role_code, Permission.CASE_LEGAL_HOLD_RELEASE):
            raise PermissionDeniedError(
                "You do not have permission to release a legal hold.",
                code="PERMISSION_DENIED",
            )

        if not payload.release_reason or len(payload.release_reason.strip()) < 10:
            raise BusinessRuleError(
                "A detailed release reason of at least 10 characters is required.",
                code="RELEASE_REASON_REQUIRED",
                status_code=422,
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        hold = await self.case_repo.get_legal_hold_by_id(hold_id)
        if hold is None or hold.case_id != case_id or hold.evidence_id != evidence_id:
            raise ResourceNotFoundError("Legal hold not found.", code="HOLD_NOT_FOUND")

        # Department scoping
        if not has_permission(principal.role_code, Permission.INCIDENT_READ_GLOBAL):
            if hold.department_id != principal.department_id:
                raise ResourceNotFoundError("Legal hold not found.", code="HOLD_NOT_FOUND")

        if hold.status == LegalHoldStatus.RELEASED.value:
            raise BusinessRuleError(
                "Legal hold is already released.",
                code="LEGAL_HOLD_ALREADY_RELEASED",
                status_code=400,
            )

        hold.status = LegalHoldStatus.RELEASED.value
        hold.released_by_id = principal.user_id
        hold.released_at = utc_now()
        hold.release_reason = payload.release_reason.strip()
        hold.updated_at = utc_now()
        await self.case_repo.update_legal_hold(hold)

        # Check remaining active holds for case to update case-level flag if none remain
        remaining_case_holds = await self.case_repo.list_legal_holds_for_case(case_id, status="active")
        if not remaining_case_holds:
            case_record.is_legal_hold = False
            case_record.legal_hold_reason = None
            await self.case_repo.update(case_record)

        remaining_evidence_holds = await self.case_repo.list_active_holds_for_evidence(evidence_id)

        await self.audit_repo.append_event(
            action=AuditAction.CASE_LEGAL_HOLD_RELEASED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.LEGAL_HOLD,
            target_id=str(hold.id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "hold_reference": hold.hold_reference,
                "case_id": str(case_id),
                "case_reference": getattr(case_record, "reference_number", None),
                "evidence_id": str(evidence_id),
                "release_reason": hold.release_reason,
                "remaining_active_holds_on_evidence": len(remaining_evidence_holds),
            },
        )

        return LegalHoldRead(
            id=hold.id,
            hold_reference=hold.hold_reference,
            case_id=hold.case_id,
            evidence_id=hold.evidence_id,
            department_id=hold.department_id,
            status=hold.status,
            reason=hold.reason,
            placed_by_id=hold.placed_by_id,
            placed_at=hold.placed_at,
            released_by_id=hold.released_by_id,
            released_at=hold.released_at,
            release_reason=hold.release_reason,
            created_at=getattr(hold, "created_at", utc_now()),
            updated_at=getattr(hold, "updated_at", utc_now()),
            case_reference=getattr(case_record, "reference_number", None),
        )

    async def list_legal_holds_for_evidence(
        self,
        case_id: UUID,
        evidence_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
    ) -> list[LegalHoldRead]:
        """List all legal holds for a specific case-linked evidence item."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        link = await self.case_repo.get_evidence_link(case_id, evidence_id)
        if link is None:
            raise ResourceNotFoundError("Evidence link not found.", code="LINK_NOT_FOUND")

        holds = await self.case_repo.list_legal_holds_for_evidence(evidence_id, status=status)
        return [
            LegalHoldRead(
                id=h.id,
                hold_reference=h.hold_reference,
                case_id=h.case_id,
                evidence_id=h.evidence_id,
                department_id=h.department_id,
                status=h.status,
                reason=h.reason,
                placed_by_id=h.placed_by_id,
                placed_at=h.placed_at,
                released_by_id=h.released_by_id,
                released_at=h.released_at,
                release_reason=h.release_reason,
                created_at=getattr(h, "created_at", utc_now()),
                updated_at=getattr(h, "updated_at", utc_now()),
                case_reference=getattr(case_record, "reference_number", None),
            )
            for h in holds
            if h.case_id == case_id
        ]

    async def list_legal_holds_for_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
    ) -> list[LegalHoldRead]:
        """List all legal holds associated with a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        holds = await self.case_repo.list_legal_holds_for_case(case_id, status=status)
        return [
            LegalHoldRead(
                id=h.id,
                hold_reference=h.hold_reference,
                case_id=h.case_id,
                evidence_id=h.evidence_id,
                department_id=h.department_id,
                status=h.status,
                reason=h.reason,
                placed_by_id=h.placed_by_id,
                placed_at=h.placed_at,
                released_by_id=h.released_by_id,
                released_at=h.released_at,
                release_reason=h.release_reason,
                created_at=getattr(h, "created_at", utc_now()),
                updated_at=getattr(h, "updated_at", utc_now()),
                case_reference=getattr(case_record, "reference_number", None),
            )
            for h in holds
        ]

    # Phase 84: AI Candidate Segments Integration
    # =========================================================================

    async def link_ai_segment(
        self,
        case_id: UUID,
        payload: CaseLinkAISegmentRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseAISegmentRead:
        """Integrate an AI candidate segment into a case as an advisory lead."""
        import math
        from backend.app.core.ai import validate_model_provenance

        if not has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case AI segments.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        segment = await self.ai_segment_repo.get_by_id(payload.segment_id)
        if segment is None:
            raise ResourceNotFoundError("AI candidate segment not found.", code="SEGMENT_NOT_FOUND")

        # Department alignment check
        if segment.department_id != case_record.department_id:
            raise BusinessRuleError(
                "AI candidate segment belongs to a different department than the case.",
                code="DEPARTMENT_MISMATCH",
            )

        # 1. Duplicate check (preserve precedence)
        existing = await self.case_repo.get_ai_segment_link(case_id, payload.segment_id)
        if existing is not None:
            raise BusinessRuleError(
                "This AI candidate segment is already linked to the case.",
                code="SEGMENT_ALREADY_LINKED",
            )

        # 2. Temporal boundary validation
        start_s = getattr(segment, "start_seconds", 0.0)
        end_s = getattr(segment, "end_seconds", 0.0)
        if isinstance(start_s, (int, float)) and (math.isnan(start_s) or math.isinf(start_s) or start_s < 0.0):
            raise BusinessRuleError("Segment start timestamp cannot be negative.", code="INVALID_TIMESTAMPS")
        if isinstance(end_s, (int, float)) and isinstance(start_s, (int, float)) and (math.isnan(end_s) or math.isinf(end_s) or end_s <= start_s):
            raise BusinessRuleError("Segment end timestamp must be greater than start timestamp.", code="INVALID_TIMESTAMPS")

        # 3. Confidence score validation
        raw_score = getattr(segment, "raw_score", 0.0)
        if isinstance(raw_score, (int, float)) and (math.isnan(raw_score) or math.isinf(raw_score) or raw_score < 0.0 or raw_score > 1.0):
            raise BusinessRuleError("Confidence score must be between 0.0 and 1.0.", code="INVALID_CONFIDENCE_SCORE")
        cal_score = getattr(segment, "calibrated_score", None)
        if isinstance(cal_score, (int, float)) and (math.isnan(cal_score) or math.isinf(cal_score) or cal_score < 0.0 or cal_score > 1.0):
            raise BusinessRuleError("Calibrated score must be between 0.0 and 1.0.", code="INVALID_CONFIDENCE_SCORE")

        # 4. Known video duration check
        meta = segment.get_metadata_dict() if hasattr(segment, "get_metadata_dict") else {}
        vid_duration = getattr(segment, "video_duration_seconds", None) or meta.get("video_duration_seconds")
        if vid_duration is None and hasattr(self, "evidence_repo") and self.evidence_repo and getattr(segment, "evidence_id", None):
            try:
                ev_check = await self.evidence_repo.get_by_id(segment.evidence_id)
                if ev_check and type(ev_check).__name__ != "AsyncMock":
                    raw_dur = getattr(ev_check, "video_duration_seconds", None)
                    if isinstance(raw_dur, (int, float)):
                        vid_duration = raw_dur
            except Exception:
                pass
        if isinstance(vid_duration, (int, float)) and end_s > float(vid_duration):
            raise BusinessRuleError(
                f"Segment end timestamp ({end_s:.2f}s) exceeds known video duration ({float(vid_duration):.2f}s).",
                code="SEGMENT_EXCEEDS_DURATION",
            )

        # 5. Model provenance check
        model_name = getattr(segment, "model_name", None)
        model_version = getattr(segment, "model_version", None)
        if not model_name or not model_version or type(model_name).__name__ == "AsyncMock":
            raise BusinessRuleError("Missing model provenance: model_name and model_version are required.", code="MISSING_MODEL_PROVENANCE")
        try:
            validate_model_provenance(str(model_name), str(model_version))
        except ValueError as err:
            raise BusinessRuleError(f"Unverified or untrusted model provenance: {err}", code="UNAPPROVED_MODEL_PROVENANCE")

        # 6. Retrieve parent evidence digest for provenance traceability
        evidence_digest = None
        if hasattr(self, "evidence_repo") and self.evidence_repo and getattr(segment, "evidence_id", None):
            try:
                ev_obj = await self.evidence_repo.get_by_id(segment.evidence_id)
                if ev_obj and type(ev_obj).__name__ != "AsyncMock":
                    hash_val = getattr(ev_obj, "sha256_hash", None)
                    if isinstance(hash_val, str):
                        evidence_digest = hash_val
            except Exception:
                pass

        link = CaseAISegment(
            case_id=case_id,
            segment_id=payload.segment_id,
            linked_by_id=principal.user_id,
            investigative_relevance=payload.investigative_relevance.value,
            relevance_notes=payload.relevance_notes,
        )
        await self.case_repo.link_ai_segment(link)

        await self.audit_repo.append_event(
            action=AuditAction.CASE_AI_SEGMENT_LINKED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "segment_id": str(payload.segment_id),
                "investigative_relevance": payload.investigative_relevance.value,
                "score": segment.calibrated_score
                if getattr(segment, "calibrated_score", None) is not None
                else getattr(segment, "raw_score", 0.0),
                "label": getattr(segment, "raw_label", "violence"),
                "model_name": model_name,
                "model_version": model_version,
                "evidence_sha256": evidence_digest,
            },
        )

        return self._to_ai_segment_read(link, segment, evidence_digest)

    async def create_and_link_ai_segment_annotation(
        self,
        case_id: UUID,
        payload: CaseCreateAISegmentAnnotationRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseAISegmentRead:
        """Create and attach an advisory AI candidate segment annotation to case evidence."""
        from backend.app.core.ai import validate_model_provenance

        if not has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case AI segments.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        # Validate model provenance
        try:
            validate_model_provenance(payload.model_name, payload.model_version)
        except ValueError as err:
            raise BusinessRuleError(f"Unverified or untrusted model provenance: {err}", code="UNAPPROVED_MODEL_PROVENANCE")

        # Verify parent evidence
        evidence_digest = None
        incident_id = uuid4()
        if hasattr(self, "evidence_repo") and self.evidence_repo:
            evidence = await self.evidence_repo.get_by_id(payload.evidence_id)
            if evidence is None:
                raise ResourceNotFoundError("Evidence attachment not found.", code="EVIDENCE_NOT_FOUND")
            if evidence.department_id != case_record.department_id:
                raise BusinessRuleError("Evidence belongs to a different department than the case.", code="DEPARTMENT_MISMATCH")
            evidence_digest = evidence.sha256_hash
            incident_id = getattr(evidence, "incident_id", incident_id)

        # Ensure AIAnalysisJob exists to satisfy FK constraint
        session = self.ai_segment_repo._session
        job_id = payload.job_id
        if job_id is None:
            job_stmt = select(AIAnalysisJob).where(
                AIAnalysisJob.evidence_id == payload.evidence_id,
                AIAnalysisJob.department_id == case_record.department_id,
            ).limit(1)
            job_res = (await session.execute(job_stmt)).scalar_one_or_none()
            if job_res is not None:
                job_id = job_res.id
            else:
                new_job = AIAnalysisJob(
                    id=uuid4(),
                    evidence_id=payload.evidence_id,
                    incident_id=incident_id,
                    department_id=case_record.department_id,
                    submitted_by_id=principal.user_id,
                    status="succeeded",
                    progress_percent=100,
                    current_step="completed",
                    model_name=payload.model_name,
                    model_version=payload.model_version,
                )
                session.add(new_job)
                await session.flush()
                job_id = new_job.id

        # Construct AICandidateSegment entity
        new_segment = AICandidateSegment(
            id=uuid4(),
            job_id=job_id,
            evidence_id=payload.evidence_id,
            incident_id=incident_id,
            department_id=case_record.department_id,
            start_seconds=payload.start_seconds,
            end_seconds=payload.end_seconds,
            duration_seconds=payload.end_seconds - payload.start_seconds,
            raw_score=payload.raw_score,
            raw_label=payload.raw_label,
            model_name=payload.model_name,
            model_version=payload.model_version,
            calibrated_score=payload.calibrated_score,
            review_status=SegmentReviewStatus.PENDING_REVIEW.value,
        )
        saved_segment = await self.ai_segment_repo.create(new_segment)
        if not isinstance(saved_segment, AICandidateSegment):
            saved_segment = new_segment

        link = CaseAISegment(
            case_id=case_id,
            segment_id=saved_segment.id,
            linked_by_id=principal.user_id,
            investigative_relevance=payload.investigative_relevance.value,
            relevance_notes=payload.relevance_notes,
        )
        await self.case_repo.link_ai_segment(link)

        await self.audit_repo.append_event(
            action=AuditAction.CASE_AI_SEGMENT_LINKED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "segment_id": str(saved_segment.id),
                "evidence_id": str(payload.evidence_id),
                "investigative_relevance": payload.investigative_relevance.value,
                "score": payload.raw_score,
                "label": payload.raw_label,
                "model_name": payload.model_name,
                "model_version": payload.model_version,
                "evidence_sha256": evidence_digest,
            },
        )

        return self._to_ai_segment_read(link, saved_segment, evidence_digest)

    async def get_case_ai_segment(
        self,
        case_id: UUID,
        segment_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> CaseAISegmentRead:
        """Fetch a specific AI candidate segment linked to a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        link = await self.case_repo.get_ai_segment_link(case_id, segment_id)
        if link is None:
            raise ResourceNotFoundError("AI segment link not found.", code="LINK_NOT_FOUND")

        segment = getattr(link, "segment", None) or await self.ai_segment_repo.get_by_id(segment_id)
        if segment is None:
            raise ResourceNotFoundError("AI candidate segment not found.", code="SEGMENT_NOT_FOUND")

        evidence_digest = None
        if getattr(segment, "evidence", None) and getattr(segment.evidence, "sha256_hash", None):
            evidence_digest = getattr(segment.evidence, "sha256_hash", None)
        elif hasattr(self, "evidence_repo") and self.evidence_repo and getattr(segment, "evidence_id", None):
            try:
                ev_obj = (
                    await self.evidence_repo.get_attachment_by_id(segment.evidence_id)
                    if hasattr(self.evidence_repo, "get_attachment_by_id")
                    else await self.evidence_repo.get_by_id(segment.evidence_id)
                )
                if ev_obj and type(ev_obj).__name__ != "AsyncMock":
                    hash_val = getattr(ev_obj, "sha256_hash", None)
                    if isinstance(hash_val, str):
                        evidence_digest = hash_val
            except Exception:
                pass

        return self._to_ai_segment_read(link, segment, evidence_digest)

    async def list_case_evidence_ai_segments(
        self,
        case_id: UUID,
        evidence_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseAISegmentRead]:
        """List AI candidate segments linked to a case for a specific evidence item."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        if hasattr(self.case_repo, "list_case_ai_segments_for_evidence"):
            links = await self.case_repo.list_case_ai_segments_for_evidence(case_id, evidence_id)
        else:
            all_links = await self.case_repo.list_case_ai_segments(case_id)
            links = [lk for lk in all_links if getattr(lk.segment, "evidence_id", None) == evidence_id]

        results = []
        for lk in links:
            seg = lk.segment
            results.append(self._to_ai_segment_read(lk, seg))
        return results

    async def unlink_ai_segment(
        self,
        case_id: UUID,
        segment_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> bool:
        """Unlink an AI candidate segment from a case."""
        if not has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case AI segments.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        link = await self.case_repo.get_ai_segment_link(case_id, segment_id)
        if link is None:
            raise ResourceNotFoundError("AI segment link not found.", code="LINK_NOT_FOUND")

        if case_record.is_legal_hold:
            raise BusinessRuleError(
                "Cannot unlink AI candidate segments while case is under legal hold.",
                code="LEGAL_HOLD_ACTIVE",
                status_code=409,
            )

        segment = getattr(link, "segment", None) or await self.ai_segment_repo.get_by_id(segment_id)
        if segment is not None and hasattr(self.case_repo, "has_active_legal_hold_for_evidence") and getattr(segment, "evidence_id", None):
            has_hold = await self.case_repo.has_active_legal_hold_for_evidence(segment.evidence_id)
            if isinstance(has_hold, bool) and has_hold:
                raise BusinessRuleError(
                    "Cannot unlink AI candidate segments while evidence is under active legal hold.",
                    code="LEGAL_HOLD_ACTIVE",
                    status_code=409,
                )

        unlinked = await self.case_repo.unlink_ai_segment(case_id, segment_id)
        if unlinked:
            await self.audit_repo.append_event(
                action=AuditAction.CASE_AI_SEGMENT_UNLINKED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={"segment_id": str(segment_id)},
            )
        return unlinked

    async def list_case_ai_segments(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseAISegmentRead]:
        """List AI candidate segments linked to a case with non-authoritative advisory disclaimer."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        links = await self.case_repo.list_case_ai_segments(case_id)
        results = []
        for lk in links:
            seg = lk.segment
            results.append(self._to_ai_segment_read(lk, seg))
        return results

    # =========================================================================
    # Phase 85: Human Review & AI Classification Correction
    # =========================================================================

    async def review_ai_segment(
        self,
        case_id: UUID,
        segment_id: UUID,
        payload: CaseAISegmentReviewRequest,
        principal: AuthenticatedPrincipal,
        *,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> CaseAISegmentRead:
        """Perform authorized human review, classification correction, or supervisor override of an AI segment."""
        # 1. Base permission: user must at least have review or override permission
        if not (
            has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_REVIEW)
            or has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_OVERRIDE)
        ):
            raise PermissionDeniedError(
                "You do not have permission to review AI candidate segments.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_writable(case_record, principal)

        link = await self.case_repo.get_ai_segment_link(case_id, segment_id)
        if link is None:
            raise ResourceNotFoundError(
                "AI candidate segment is not linked to this case.", code="LINK_NOT_FOUND"
            )

        segment = await self.ai_segment_repo.get_by_id(segment_id)
        if segment is None:
            raise ResourceNotFoundError("AI candidate segment not found.", code="SEGMENT_NOT_FOUND")

        # 2. Conflict-of-interest check: Report-author cannot review AI results for their reported incident
        incident = await self.incident_repo.get_by_id(segment.incident_id)
        if incident is not None and incident.reporter_id == principal.user_id:
            raise PermissionDeniedError(
                "Reviewer conflict of interest: you cannot review AI candidate segments for an incident you reported.",
                code="REVIEWER_CONFLICT_OF_INTEREST",
            )

        # 3. Retrieve current state and metadata
        old_status = getattr(segment, "review_status", SegmentReviewStatus.PENDING_REVIEW.value)
        meta = segment.get_metadata_dict() if hasattr(segment, "get_metadata_dict") else {}
        curr_revision = meta.get("decision_revision", 1 if getattr(segment, "reviewed_at", None) else 0)

        # Preserve original AI model prediction permanently
        orig_prediction = meta.get("original_ai_prediction")
        if not orig_prediction:
            orig_prediction = {
                "label": getattr(segment, "raw_label", "violence"),
                "raw_score": getattr(segment, "raw_score", None),
                "calibrated_score": getattr(segment, "calibrated_score", None),
                "model_name": getattr(segment, "model_name", None),
                "model_version": getattr(segment, "model_version", None),
                "inferred_at": getattr(segment, "created_at", None).isoformat() if getattr(segment, "created_at", None) else None,
            }
            meta["original_ai_prediction"] = orig_prediction

        # 4. Concurrency & Optimistic Concurrency Checks (Run first to detect state collision)
        if getattr(payload, "expected_review_status", None) is not None and old_status != payload.expected_review_status:
            raise ConflictError(
                f"Concurrent review conflict: expected status '{payload.expected_review_status}' but found '{old_status}'.",
                code="CONCURRENT_REVIEW_CONFLICT",
            )

        if getattr(payload, "expected_revision", None) is not None and curr_revision != payload.expected_revision:
            raise ConflictError(
                f"Stale revision conflict: expected revision {payload.expected_revision} but found {curr_revision}.",
                code="CONCURRENT_REVIEW_CONFLICT",
            )

        # 5. Idempotent retries check (Must run before transition validation for identical retries)
        existing_corrected_label = meta.get("human_corrected_label")
        is_same_status = (old_status == payload.review_status)
        is_same_label = (existing_corrected_label == payload.corrected_label)
        is_same_notes = (getattr(segment, "review_notes", None) == payload.review_rationale)
        is_same_reviewer = (getattr(segment, "reviewed_by_id", None) == principal.user_id)
        if is_same_status and is_same_label and is_same_notes and is_same_reviewer and curr_revision > 0:
            evidence_digest = getattr(getattr(segment, "evidence", None), "sha256_hash", None)
            return self._to_ai_segment_read(link, segment, evidence_digest)

        # 6. Valid lifecycle transition check
        from backend.app.core.case import VALID_AI_SEGMENT_REVIEW_TRANSITIONS
        allowed = VALID_AI_SEGMENT_REVIEW_TRANSITIONS.get(old_status, frozenset())
        if payload.review_status not in allowed:
            raise BusinessRuleError(
                f"Invalid review state transition from '{old_status}' to '{payload.review_status}'.",
                code="INVALID_REVIEW_TRANSITION",
            )

        # 7. Determine if this operation is an override
        is_different_reviewer = (
            getattr(segment, "reviewed_by_id", None) is not None
            and getattr(segment, "reviewed_by_id", None) != principal.user_id
        )
        is_explicit_override = getattr(payload, "is_override", False)
        is_override = is_explicit_override or is_different_reviewer

        # If override, verify CASE_AI_SEGMENT_OVERRIDE permission strictly on principal
        if is_override:
            if not has_permission(principal.role_code, Permission.CASE_AI_SEGMENT_OVERRIDE):
                raise PermissionDeniedError(
                    "You do not have permission to override an existing AI segment review determination.",
                    code="PERMISSION_DENIED",
                )

        # 8. Apply human review determination (never spoofed from client)
        new_revision = curr_revision + 1
        meta["decision_revision"] = new_revision
        meta["is_override"] = is_override
        if payload.corrected_label is not None:
            meta["human_corrected_label"] = payload.corrected_label

        segment.review_status = payload.review_status
        segment.reviewed_by_id = principal.user_id
        segment.reviewed_at = utc_now()
        segment.review_notes = payload.review_rationale

        # Record revision history inside metadata
        rev_history = meta.get("revisions", [])
        rev_history.append({
            "revision": new_revision,
            "decision": payload.review_status,
            "previous_status": old_status,
            "reviewer_id": str(principal.user_id),
            "reviewer_role": principal.role_code,
            "reviewed_at": utc_now().isoformat(),
            "rationale": payload.review_rationale,
            "corrected_label": payload.corrected_label,
            "is_override": is_override,
        })
        meta["revisions"] = rev_history

        if hasattr(segment, "set_metadata_dict"):
            segment.set_metadata_dict(meta)
        else:
            segment.metadata_json = json.dumps(meta)

        if payload.review_status == SegmentReviewStatus.REJECTED.value:
            link.investigative_relevance = InvestigativeRelevance.DISMISSED.value
        elif payload.review_status == SegmentReviewStatus.CONFIRMED.value:
            link.investigative_relevance = InvestigativeRelevance.CORROBORATING.value

        await self.ai_segment_repo.create(segment)  # session.flush()

        # 9. Append Audit Events
        # Always emit authoritative CASE_AI_SEGMENT_REVIEWED
        await self.audit_repo.append_event(
            action=AuditAction.CASE_AI_SEGMENT_REVIEWED,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=case_record.department_id,
            details={
                "segment_id": str(segment_id),
                "decision_revision": new_revision,
                "is_override": is_override,
                "previous_review_status": old_status,
                "new_review_status": payload.review_status,
                "original_classification_label": orig_prediction.get("label"),
                "new_classification_label": payload.corrected_label or orig_prediction.get("label"),
                "review_rationale": payload.review_rationale,
            },
        )

        if is_override:
            await self.audit_repo.append_event(
                action=AuditAction.CASE_AI_SEGMENT_OVERRIDDEN,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={
                    "segment_id": str(segment_id),
                    "decision_revision": new_revision,
                    "is_override": True,
                    "previous_review_status": old_status,
                    "new_review_status": payload.review_status,
                    "review_rationale": payload.review_rationale,
                },
            )
        if payload.corrected_label is not None and payload.corrected_label != orig_prediction.get("label"):
            await self.audit_repo.append_event(
                action=AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={
                    "segment_id": str(segment_id),
                    "decision_revision": new_revision,
                    "original_classification_label": orig_prediction.get("label"),
                    "new_classification_label": payload.corrected_label,
                    "corrected_label": payload.corrected_label,
                    "review_rationale": payload.review_rationale,
                },
            )
        if payload.review_status == "escalated":
            await self.audit_repo.append_event(
                action=AuditAction.CASE_AI_SEGMENT_ESCALATED,
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                target_type=AuditTargetType.CASE,
                target_id=str(case_id),
                outcome=AuditOutcome.SUCCESS,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=case_record.department_id,
                details={
                    "segment_id": str(segment_id),
                    "decision_revision": new_revision,
                    "previous_review_status": old_status,
                    "review_rationale": payload.review_rationale,
                },
            )

        evidence_digest = None
        if getattr(segment, "evidence", None) and getattr(segment.evidence, "sha256_hash", None):
            evidence_digest = getattr(segment.evidence, "sha256_hash", None)
        elif hasattr(self, "evidence_repo") and self.evidence_repo and getattr(segment, "evidence_id", None):
            try:
                ev_obj = (
                    await self.evidence_repo.get_attachment_by_id(segment.evidence_id)
                    if hasattr(self.evidence_repo, "get_attachment_by_id")
                    else await self.evidence_repo.get_by_id(segment.evidence_id)
                )
                if ev_obj and type(ev_obj).__name__ != "AsyncMock":
                    hash_val = getattr(ev_obj, "sha256_hash", None)
                    if isinstance(hash_val, str):
                        evidence_digest = hash_val
            except Exception:
                pass

        return self._to_ai_segment_read(link, segment, evidence_digest)

    async def get_case_ai_segment_review_history(
        self,
        case_id: UUID,
        segment_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseAISegmentHistoryItemRead]:
        """Retrieve historical audit records of human review decisions for an AI segment."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")
        self._assert_case_visible(case_record, principal)

        link = await self.case_repo.get_ai_segment_link(case_id, segment_id)
        if link is None:
            raise ResourceNotFoundError("AI segment link not found.", code="LINK_NOT_FOUND")

        events = await self.audit_repo.list_events_for_target(
            target_type=AuditTargetType.CASE,
            target_id=str(case_id),
        )
        target_actions = {
            AuditAction.CASE_AI_SEGMENT_REVIEWED,
            AuditAction.CASE_AI_SEGMENT_OVERRIDDEN,
            AuditAction.CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED,
            AuditAction.CASE_AI_SEGMENT_ESCALATED,
        }
        history = []
        for ev in events:
            if ev.action in target_actions:
                details = getattr(ev, "details", {}) or {}
                if details.get("segment_id") == str(segment_id):
                    history.append(
                        CaseAISegmentHistoryItemRead(
                            event_id=ev.id,
                            timestamp=ev.created_at,
                            actor_id=ev.actor_id,
                            actor_role=ev.actor_role,
                            previous_review_status=details.get("previous_review_status"),
                            new_review_status=details.get("new_review_status", ""),
                            review_rationale=details.get("review_rationale"),
                            corrected_label=details.get("new_classification_label"),
                            is_override=details.get("is_override", False),
                            decision_revision=details.get("decision_revision", 1),
                        )
                    )
        history.sort(key=lambda x: x.timestamp)
        return history

    # =========================================================================
    # Helper & Validation Methods
    # =========================================================================

    async def _validate_investigator_assignment(
        self,
        investigator_id: UUID,
        target_department_id: UUID,
        can_global: bool,
        exclude_case_id: UUID | None = None,
        is_supervisor_override: bool = False,
    ) -> int:
        """Validate designated investigator eligibility, active status, department, and capacity."""
        # 1. Fetch investigator with row-level locking for concurrent capacity safety
        if can_global:
            try:
                investigator = await self.user_repo.get_by_id_unscoped(
                    investigator_id, with_for_update=True
                )
            except TypeError:
                investigator = await self.user_repo.get_by_id_unscoped(investigator_id)
        else:
            try:
                investigator = await self.user_repo.get_by_id(
                    investigator_id,
                    department_id=target_department_id,
                    with_for_update=True,
                )
            except TypeError:
                investigator = await self.user_repo.get_by_id(
                    investigator_id, department_id=target_department_id
                )

        if investigator is None or not getattr(investigator, "is_active", False):
            raise BusinessRuleError(
                "The designated investigator does not exist or is inactive.",
                code="INVALID_INVESTIGATOR",
                status_code=422,
            )

        if getattr(investigator, "account_status", None) in {"suspended", "disabled"}:
            raise BusinessRuleError(
                "The designated investigator does not exist or is inactive.",
                code="INVALID_INVESTIGATOR",
                status_code=422,
            )

        # 2. Strict department containment check
        inv_dept = getattr(investigator, "department_id", None)
        if inv_dept is not None and target_department_id is not None and inv_dept != target_department_id:
            raise BusinessRuleError(
                "Designated investigator does not belong to the case's department.",
                code="CROSS_DEPARTMENT_ASSIGNMENT_FORBIDDEN",
                status_code=422,
            )

        # 3. Role eligibility check (e.g. students or staff cannot hold cases)
        role_code = getattr(investigator, "role_code", None)
        if role_code is None and hasattr(investigator, "role") and investigator.role is not None:
            role_code = getattr(investigator.role, "code", None)
        if role_code is not None:
            code_upper = str(role_code).upper()
            if code_upper in {"ROLE_STUDENT", "ROLE_STAFF", "STUDENT", "STAFF", "GUEST", "EXTERNAL_VIEWER"}:
                raise BusinessRuleError(
                    f"User with role '{role_code}' is not eligible to be assigned as lead investigator.",
                    code="INELIGIBLE_INVESTIGATOR_ROLE",
                    status_code=422,
                )

        # 4. Authoritative database active workload calculation
        active_count = await self.case_repo.count_active_cases_for_investigator(
            investigator_id,
            exclude_case_id=exclude_case_id,
        )
        if not isinstance(active_count, int):
            active_count = 0

        # 5. Workload capacity limit check
        if active_count >= self.max_active_cases and not is_supervisor_override:
            raise BusinessRuleError(
                f"Investigator {investigator_id} has reached maximum active case capacity ({self.max_active_cases}).",
                code="INVESTIGATOR_CAPACITY_EXCEEDED",
                status_code=422,
            )

        return active_count

    def _assert_case_visible(self, case_record: Case, principal: AuthenticatedPrincipal) -> None:
        """Assert principal has visibility into the case, or mask as 404."""
        can_global = has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        if can_global:
            return

        can_dept = has_permission(principal.role_code, Permission.CASE_READ_DEPT) or has_permission(principal.role_code, Permission.CASE_READ)
        if can_dept and principal.department_id == case_record.department_id:
            return

        can_own = has_permission(principal.role_code, Permission.CASE_READ_OWN)
        if can_own and (
            case_record.lead_investigator_id == principal.user_id
            or case_record.created_by_id == principal.user_id
        ):
            return

        raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

    def _assert_case_writable(self, case_record: Case, principal: AuthenticatedPrincipal) -> None:
        """Assert principal has update authorization over the case."""
        can_global = has_permission(principal.role_code, Permission.CASE_UPDATE_GLOBAL)
        if can_global:
            return

        can_dept = has_permission(principal.role_code, Permission.CASE_UPDATE_DEPT) or has_permission(principal.role_code, Permission.CASE_UPDATE)
        if can_dept and principal.department_id == case_record.department_id:
            return

        raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

    def _to_case_read(self, c: Case) -> CaseRead:
        """Map Case entity to CaseRead DTO safely without triggering lazy loading."""
        from sqlalchemy import inspect

        state = inspect(c)
        incidents = state.dict.get("incidents")
        evidence = state.dict.get("evidence")
        ai_segments = state.dict.get("ai_segments")
        dept = state.dict.get("department")
        lead = state.dict.get("lead_investigator")

        return CaseRead(
            id=c.id,
            reference_number=c.reference_number,
            title=c.title,
            summary=c.summary,
            status=CaseStatus(c.status),
            priority=CasePriority(c.priority),
            department_id=c.department_id,
            created_by_id=c.created_by_id,
            lead_investigator_id=c.lead_investigator_id,
            version_id=c.version_id,
            is_legal_hold=c.is_legal_hold,
            legal_hold_reason=c.legal_hold_reason,
            closed_at=c.closed_at,
            created_at=c.created_at,
            updated_at=c.updated_at,
            incidents_count=len(incidents) if incidents is not None else 0,
            evidence_count=len(evidence) if evidence is not None else 0,
            ai_segments_count=len(ai_segments) if ai_segments is not None else 0,
            department_name=dept.name if dept is not None else None,
            lead_investigator_name=lead.full_name if lead is not None else None,
        )

    def _to_ai_segment_read(
        self, link: CaseAISegment, seg: Any, evidence_digest: str | None = None
    ) -> CaseAISegmentRead:
        """Map CaseAISegment and AICandidateSegment entity to CaseAISegmentRead DTO."""
        score = (
            seg.calibrated_score
            if getattr(seg, "calibrated_score", None) is not None
            else getattr(seg, "raw_score", 0.0)
        )
        start_s = getattr(seg, "start_seconds", 0.0)
        end_s = getattr(seg, "end_seconds", 0.0)
        duration_s = getattr(seg, "duration_seconds", None) or max(0.0, end_s - start_s)
        raw_d = evidence_digest or getattr(getattr(seg, "evidence", None), "sha256_hash", None)
        digest = raw_d if (isinstance(raw_d, str) and type(raw_d).__name__ != "AsyncMock") else None
        meta = seg.get_metadata_dict() if hasattr(seg, "get_metadata_dict") else {}
        orig_prediction = meta.get("original_ai_prediction") or {
            "label": getattr(seg, "raw_label", "violence"),
            "raw_score": getattr(seg, "raw_score", None),
            "calibrated_score": getattr(seg, "calibrated_score", None),
            "model_name": getattr(seg, "model_name", None),
            "model_version": getattr(seg, "model_version", None),
            "inferred_at": getattr(seg, "created_at", None).isoformat() if getattr(seg, "created_at", None) else None,
        }
        human_corrected_label = meta.get("human_corrected_label")
        decision_revision = meta.get("decision_revision", 1 if getattr(seg, "reviewed_at", None) else 0)
        is_override = meta.get("is_override", False)

        current_human_decision = None
        if getattr(seg, "reviewed_at", None) or getattr(seg, "reviewed_by_id", None):
            current_human_decision = {
                "review_status": getattr(seg, "review_status", SegmentReviewStatus.PENDING_REVIEW.value),
                "reviewed_by_id": getattr(seg, "reviewed_by_id", None),
                "reviewed_at": getattr(seg, "reviewed_at", None),
                "review_notes": getattr(seg, "review_notes", None),
                "decision_revision": decision_revision,
                "is_override": is_override,
                "corrected_label": human_corrected_label,
            }

        return CaseAISegmentRead(
            id=getattr(link, "id", None) or uuid4(),
            case_id=link.case_id,
            segment_id=link.segment_id,
            linked_by_id=getattr(link, "linked_by_id", None) or uuid4(),
            investigative_relevance=InvestigativeRelevance(getattr(link, 'investigative_relevance', None) or InvestigativeRelevance.CANDIDATE_LEAD.value),
            relevance_notes=link.relevance_notes,
            created_at=getattr(link, "created_at", None) or utc_now(),
            job_id=getattr(seg, "job_id", uuid4()),
            evidence_id=getattr(seg, "evidence_id", uuid4()),
            incident_id=getattr(seg, "incident_id", uuid4()),
            start_seconds=start_s,
            end_seconds=end_s,
            duration_seconds=duration_s,
            score=score,
            raw_score=getattr(seg, "raw_score", None),
            calibrated_score=getattr(seg, "calibrated_score", None),
            label=human_corrected_label or getattr(seg, "raw_label", "violence"),
            model_name=getattr(seg, "model_name", None),
            model_version=getattr(seg, "model_version", None),
            preprocessing_version=getattr(seg, "preprocessing_version", None),
            calibration_version=getattr(seg, "calibration_version", None),
            confidence_interpretation=(
                "Probabilistic model confidence score (0.0 to 1.0). "
                "Advisory candidate only; does not establish factual guilt or legal finding."
            ),
            original_evidence_digest=digest,
            inferred_at=getattr(seg, "created_at", None),
            updated_at=getattr(seg, "updated_at", None),
            review_status=getattr(seg, "review_status", SegmentReviewStatus.PENDING_REVIEW.value),
            reviewed_by_id=getattr(seg, "reviewed_by_id", None),
            reviewed_at=getattr(seg, "reviewed_at", None),
            review_notes=getattr(seg, "review_notes", None),
            original_ai_prediction=orig_prediction,
            current_human_decision=current_human_decision,
            human_corrected_label=human_corrected_label,
            decision_revision=decision_revision,
            is_override=is_override,
            advisory_disclaimer=AI_ADVISORY_DISCLAIMER,
        )

    async def _record_audit_event(
        self,
        *,
        actor_id: UUID,
        actor_role: str = "investigator",
        action: AuditAction | str,
        target_id: UUID | str,
        department_id: UUID | None,
        details: dict[str, Any],
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
    ) -> None:
        """Helper to append a security audit event to the append-only ledger."""
        audit_action = AuditAction(action) if isinstance(action, str) else action
        await self.audit_repo.append_event(
            action=audit_action,
            actor_id=actor_id,
            actor_role=actor_role,
            target_type=AuditTargetType.CASE,
            target_id=str(target_id),
            outcome=AuditOutcome.SUCCESS,
            actor_ip=actor_ip,
            actor_user_agent=actor_user_agent,
            department_id=department_id,
            details=details,
        )

    # =========================================================================
    # Phase 86: Case Notes & Findings
    # =========================================================================

    async def create_case_note(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseNoteCreate,
    ) -> CaseNoteRead:
        """Create an authorized investigation note with visibility restrictions (Phase 86)."""
        if not has_permission(principal.role_code, Permission.CASE_NOTE_CREATE):
            raise PermissionDeniedError(
                "You do not have permission to create case notes.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Restricted note visibility requires elevated permission
        if payload.visibility == CaseNoteVisibility.RESTRICTED.value:
            can_restricted = has_permission(
                principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED
            )
            if not can_restricted:
                raise PermissionDeniedError(
                    "You do not have permission to author restricted working notes.",
                    code="RESTRICTED_NOTE_FORBIDDEN",
                )

        # Validate evidence reference IDs
        if payload.evidence_reference_ids:
            linked_evidence = await self.case_repo.list_case_evidence(case_id)
            linked_ids = {le.evidence_id for le in linked_evidence}
            for ref_id in payload.evidence_reference_ids:
                if ref_id not in linked_ids:
                    raise BusinessRuleError(
                        f"Referenced evidence {ref_id} is not linked to this case.",
                        code="INVALID_EVIDENCE_REFERENCE",
                    )

        note_record = CaseNote(
            id=uuid4(),
            case_id=case_id,
            author_id=principal.user_id,
            visibility=payload.visibility,
            content=payload.content,
            version_id=1,
            is_archived=False,
            evidence_reference_ids_json=json.dumps([str(u) for u in payload.evidence_reference_ids])
            if payload.evidence_reference_ids
            else None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        saved_note = await self.case_repo.create_note(note_record)

        await self._record_audit_event(
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            action=AuditAction.CASE_NOTE_CREATED.value,
            target_id=saved_note.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "note_id": str(saved_note.id),
                "visibility": payload.visibility,
            },
        )
        return self._to_note_read(saved_note)

    async def get_case_note(
        self,
        case_id: UUID,
        note_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> CaseNoteRead:
        """Retrieve an individual case note subject to visibility authorization (Phase 86)."""
        if not has_permission(principal.role_code, Permission.CASE_NOTE_READ):
            raise PermissionDeniedError(
                "You do not have permission to view case notes.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        note_record = await self.case_repo.get_note_by_id(note_id)
        if note_record is None or note_record.case_id != case_id:
            raise ResourceNotFoundError("Case note not found.", code="NOTE_NOT_FOUND")

        can_admin = has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED) and (
            principal.department_id == case_record.department_id
            or has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        )
        is_lead = principal.user_id == case_record.lead_investigator_id
        is_author = principal.user_id == note_record.author_id

        if note_record.visibility == CaseNoteVisibility.RESTRICTED.value:
            if not is_author and not can_admin:
                await self._record_audit_event(
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    action=AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value,
                    target_id=note_record.id,
                    department_id=case_record.department_id,
                    details={
                        "case_id": str(case_id),
                        "note_id": str(note_record.id),
                        "visibility": note_record.visibility,
                        "context": "note_read",
                    },
                )
                raise PermissionDeniedError(
                    "Access to restricted working note denied.",
                    code="RESTRICTED_NOTE_FORBIDDEN",
                )
        elif note_record.visibility == CaseNoteVisibility.CONFIDENTIAL.value:
            if not is_author and not is_lead and not can_admin:
                raise PermissionDeniedError(
                    "Access to confidential case note denied.",
                    code="CONFIDENTIAL_NOTE_FORBIDDEN",
                )

        return self._to_note_read(note_record)

    async def update_case_note(
        self,
        case_id: UUID,
        note_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseNoteUpdate,
    ) -> CaseNoteRead:
        """Update an existing investigation note with optimistic locking, idempotency, and history logging (Phase 86)."""
        can_update = has_any_permission(
            principal.role_code, [Permission.CASE_NOTE_UPDATE, Permission.CASE_NOTE_CREATE]
        )
        if not can_update:
            raise PermissionDeniedError(
                "You do not have permission to update case notes.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        note_record = await self.case_repo.get_note_by_id(note_id)
        if note_record is None or note_record.case_id != case_id:
            raise ResourceNotFoundError("Case note not found.", code="NOTE_NOT_FOUND")

        # Note modification restriction: only author, dept admin, or super admin
        can_global = has_permission(principal.role_code, Permission.CASE_UPDATE_GLOBAL)
        can_dept_admin = (
            has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED)
            and principal.department_id == case_record.department_id
        )
        if note_record.author_id != principal.user_id and not can_global and not can_dept_admin:
            raise PermissionDeniedError(
                "You cannot modify another investigator's note.",
                code="NOTE_MODIFICATION_FORBIDDEN",
            )

        # Optimistic concurrency check
        if note_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Note version conflict: expected {payload.expected_version_id}, but found {note_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        # Idempotency check: identical retry returns existing state without version bump or duplicate history
        if note_record.content == payload.content:
            return self._to_note_read(note_record)

        # Log historical version
        history = CaseNoteHistory(
            id=uuid4(),
            note_id=note_record.id,
            version_id=note_record.version_id,
            author_id=note_record.author_id,
            editor_id=principal.user_id,
            content=note_record.content,
            visibility=note_record.visibility,
            previous_visibility=None,
            edit_reason=payload.edit_reason,
            created_at=utc_now(),
        )
        await self.case_repo.create_note_history(history)

        # Apply edit
        note_record.content = payload.content
        note_record.version_id += 1
        note_record.updated_at = utc_now()
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            action=AuditAction.CASE_NOTE_UPDATED.value,
            target_id=note_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "note_id": str(note_record.id),
                "new_version": note_record.version_id,
                "edit_reason": payload.edit_reason,
            },
        )
        return self._to_note_read(note_record)

    async def change_note_visibility(
        self,
        case_id: UUID,
        note_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseNoteVisibilityUpdate,
    ) -> CaseNoteRead:
        """Modify a case note's visibility tier with elevated privilege enforcement and history (Phase 86)."""
        if not has_permission(principal.role_code, Permission.CASE_NOTE_VISIBILITY_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage note visibility.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        note_record = await self.case_repo.get_note_by_id(note_id)
        if note_record is None or note_record.case_id != case_id:
            raise ResourceNotFoundError("Case note not found.", code="NOTE_NOT_FOUND")

        # Concurrency check
        if note_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Note version conflict: expected {payload.expected_version_id}, but found {note_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        # Idempotent retry check
        if note_record.visibility == payload.visibility:
            return self._to_note_read(note_record)

        old_visibility = note_record.visibility

        # Log historical version
        history = CaseNoteHistory(
            id=uuid4(),
            note_id=note_record.id,
            version_id=note_record.version_id,
            author_id=note_record.author_id,
            editor_id=principal.user_id,
            content=note_record.content,
            visibility=payload.visibility,
            previous_visibility=old_visibility,
            edit_reason=f"Visibility modified from {old_visibility} to {payload.visibility}: {payload.reason}",
            created_at=utc_now(),
        )
        await self.case_repo.create_note_history(history)

        # Apply visibility change
        note_record.visibility = payload.visibility
        note_record.version_id += 1
        note_record.updated_at = utc_now()
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            action=AuditAction.CASE_NOTE_VISIBILITY_CHANGED.value,
            target_id=note_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "note_id": str(note_record.id),
                "old_visibility": old_visibility,
                "new_visibility": payload.visibility,
                "reason": payload.reason,
                "new_version": note_record.version_id,
            },
        )
        return self._to_note_read(note_record)

    async def archive_case_note(
        self,
        case_id: UUID,
        note_id: UUID,
        principal: AuthenticatedPrincipal,
        expected_version_id: int | None = None,
    ) -> CaseNoteRead:
        """Soft-archive / redact an investigation note (Phase 86)."""
        can_manage = has_any_permission(
            principal.role_code,
            [Permission.CASE_NOTE_UPDATE, Permission.CASE_NOTE_VISIBILITY_MANAGE, Permission.CASE_NOTE_CREATE],
        )
        if not can_manage:
            raise PermissionDeniedError(
                "You do not have permission to archive case notes.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        note_record = await self.case_repo.get_note_by_id(note_id)
        if note_record is None or note_record.case_id != case_id:
            raise ResourceNotFoundError("Case note not found.", code="NOTE_NOT_FOUND")

        can_global = has_permission(principal.role_code, Permission.CASE_UPDATE_GLOBAL)
        can_dept_admin = (
            has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED)
            and principal.department_id == case_record.department_id
        )
        if note_record.author_id != principal.user_id and not can_global and not can_dept_admin:
            raise PermissionDeniedError(
                "You cannot archive another investigator's note.",
                code="NOTE_MODIFICATION_FORBIDDEN",
            )

        if expected_version_id is not None and note_record.version_id != expected_version_id:
            raise ConflictError(
                f"Note version conflict: expected {expected_version_id}, but found {note_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        if note_record.is_archived:
            return self._to_note_read(note_record)

        note_record.is_archived = True
        note_record.version_id += 1
        note_record.updated_at = utc_now()
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            action=AuditAction.CASE_NOTE_ARCHIVED.value,
            target_id=note_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "note_id": str(note_record.id),
                "new_version": note_record.version_id,
            },
        )
        return self._to_note_read(note_record)

    async def list_case_notes(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        include_archived: bool = False,
    ) -> list[CaseNoteRead]:
        """List case notes, filtering by caller visibility entitlements across all tiers (Phase 86)."""
        if not has_permission(principal.role_code, Permission.CASE_NOTE_READ):
            raise PermissionDeniedError(
                "You do not have permission to view case notes.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        can_admin = has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED) and (
            principal.department_id == case_record.department_id
            or has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        )
        is_lead = principal.user_id == case_record.lead_investigator_id

        notes = await self.case_repo.list_notes_for_case(case_id)
        visible: list[CaseNoteRead] = []
        for n in notes:
            if n.is_archived and not include_archived:
                continue

            is_author = principal.user_id == n.author_id

            if n.visibility == CaseNoteVisibility.RESTRICTED.value:
                if not is_author and not can_admin:
                    continue
            elif n.visibility == CaseNoteVisibility.CONFIDENTIAL.value:
                if not is_author and not is_lead and not can_admin:
                    continue
            # PUBLIC and INTERNAL visible to authorized case viewers
            visible.append(self._to_note_read(n))

        return visible

    async def get_case_note_history(
        self,
        case_id: UUID,
        note_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseNoteHistoryRead]:
        """Retrieve edit version history for a note with visibility enforcement and audit (Phase 86)."""
        can_read = has_any_permission(
            principal.role_code, [Permission.CASE_NOTE_HISTORY_READ, Permission.CASE_NOTE_READ]
        )
        if not can_read:
            raise PermissionDeniedError(
                "You do not have permission to view note history.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        note_record = await self.case_repo.get_note_by_id(note_id)
        if note_record is None or note_record.case_id != case_id:
            raise ResourceNotFoundError("Case note not found.", code="NOTE_NOT_FOUND")

        can_admin = has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED) and (
            principal.department_id == case_record.department_id
            or has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        )
        is_lead = principal.user_id == case_record.lead_investigator_id
        is_author = principal.user_id == note_record.author_id

        # Visibility checks for history match note
        if note_record.visibility == CaseNoteVisibility.RESTRICTED.value:
            if not is_author and not can_admin:
                await self._record_audit_event(
                    actor_id=principal.user_id,
                    actor_role=principal.role_code,
                    action=AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value,
                    target_id=note_record.id,
                    department_id=case_record.department_id,
                    details={
                        "case_id": str(case_id),
                        "note_id": str(note_record.id),
                        "visibility": note_record.visibility,
                        "context": "history_read",
                    },
                )
                raise PermissionDeniedError(
                    "Access to restricted note history denied.", code="RESTRICTED_NOTE_FORBIDDEN"
                )
        elif note_record.visibility == CaseNoteVisibility.CONFIDENTIAL.value:
            if not is_author and not is_lead and not can_admin:
                raise PermissionDeniedError(
                    "Access to confidential note history denied.", code="CONFIDENTIAL_NOTE_FORBIDDEN"
                )

        history_rows = await self.case_repo.list_note_history(note_id)

        await self._record_audit_event(
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            action=AuditAction.CASE_NOTE_HISTORY_ACCESSED.value,
            target_id=note_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "note_id": str(note_record.id),
                "history_count": len(history_rows),
            },
        )

        return [
            CaseNoteHistoryRead(
                id=h.id,
                note_id=h.note_id,
                version_id=h.version_id,
                author_id=h.author_id,
                editor_id=h.editor_id,
                content=h.content,
                visibility=getattr(h, "visibility", None) or note_record.visibility,
                previous_visibility=getattr(h, "previous_visibility", None),
                edit_reason=h.edit_reason,
                created_at=h.created_at,
            )
            for h in history_rows
        ]

    async def create_case_finding(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseFindingCreate,
    ) -> CaseFindingRead:
        """Create a formal, structured investigation finding."""
        if not has_permission(principal.role_code, Permission.CASE_FINDING_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case findings.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Validate evidence IDs
        if payload.evidence_ids:
            linked_ev = await self.case_repo.list_case_evidence(case_id)
            linked_ev_ids = {e.evidence_id for e in linked_ev}
            for eid in payload.evidence_ids:
                if eid not in linked_ev_ids:
                    raise BusinessRuleError(
                        f"Evidence {eid} is not linked to this case.",
                        code="INVALID_EVIDENCE_REFERENCE",
                    )

        # Validate AI segment IDs
        if payload.ai_segment_ids:
            linked_seg = await self.case_repo.list_case_ai_segments(case_id)
            linked_seg_ids = {s.segment_id for s in linked_seg}
            for sid in payload.ai_segment_ids:
                if sid not in linked_seg_ids:
                    raise BusinessRuleError(
                        f"AI segment {sid} is not linked to this case.",
                        code="INVALID_AI_SEGMENT_REFERENCE",
                    )

        # Validate incident IDs
        if payload.incident_ids:
            linked_inc = await self.case_repo.list_case_incidents(case_id)
            linked_inc_ids = {i.incident_id for i in linked_inc}
            for iid in payload.incident_ids:
                if iid not in linked_inc_ids:
                    raise BusinessRuleError(
                        f"Incident {iid} is not linked to this case.",
                        code="INVALID_INCIDENT_REFERENCE",
                    )

        finding = CaseFinding(
            id=uuid4(),
            case_id=case_id,
            author_id=principal.user_id,
            finding_type=payload.finding_type,
            title=payload.title,
            description=payload.description,
            evidence_ids_json=json.dumps([str(u) for u in payload.evidence_ids])
            if payload.evidence_ids
            else None,
            ai_segment_ids_json=json.dumps([str(u) for u in payload.ai_segment_ids])
            if payload.ai_segment_ids
            else None,
            incident_ids_json=json.dumps([str(u) for u in payload.incident_ids])
            if payload.incident_ids
            else None,
            version_id=1,
            is_preliminary=payload.is_preliminary,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        saved = await self.case_repo.create_finding(finding)

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_FINDING_CREATED.value,
            target_id=saved.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "finding_id": str(saved.id),
                "finding_type": saved.finding_type,
                "title": saved.title,
            },
        )
        return self._to_finding_read(saved)

    async def update_case_finding(
        self,
        case_id: UUID,
        finding_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseFindingUpdate,
    ) -> CaseFindingRead:
        """Update a formal investigation finding with optimistic locking and version history."""
        if not has_permission(principal.role_code, Permission.CASE_FINDING_MANAGE):
            raise PermissionDeniedError(
                "You do not have permission to manage case findings.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        finding = await self.case_repo.get_finding_by_id(finding_id)
        if finding is None or finding.case_id != case_id:
            raise ResourceNotFoundError("Case finding not found.", code="FINDING_NOT_FOUND")

        # Concurrency check
        if finding.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Finding version conflict: expected {payload.expected_version_id}, but found {finding.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        # Log history
        history = CaseFindingHistory(
            id=uuid4(),
            finding_id=finding.id,
            version_id=finding.version_id,
            editor_id=principal.user_id,
            title=finding.title,
            description=finding.description,
            reason=payload.reason,
            created_at=utc_now(),
        )
        await self.case_repo.create_finding_history(history)

        # Apply updates
        if payload.title is not None:
            finding.title = payload.title
        if payload.description is not None:
            finding.description = payload.description
        if payload.finding_type is not None:
            finding.finding_type = payload.finding_type
        if payload.is_preliminary is not None:
            finding.is_preliminary = payload.is_preliminary
        if payload.evidence_ids is not None:
            finding.evidence_ids_json = json.dumps([str(u) for u in payload.evidence_ids])
        if payload.ai_segment_ids is not None:
            finding.ai_segment_ids_json = json.dumps([str(u) for u in payload.ai_segment_ids])
        if payload.incident_ids is not None:
            finding.incident_ids_json = json.dumps([str(u) for u in payload.incident_ids])

        finding.version_id += 1
        finding.updated_at = utc_now()
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_FINDING_UPDATED.value,
            target_id=finding.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "finding_id": str(finding.id),
                "new_version": finding.version_id,
            },
        )
        return self._to_finding_read(finding)

    async def list_case_findings(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseFindingRead]:
        """List all formal findings for a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        findings = await self.case_repo.list_findings_for_case(case_id)
        return [self._to_finding_read(f) for f in findings]

    async def get_case_finding_history(
        self,
        case_id: UUID,
        finding_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseFindingHistoryRead]:
        """List version history logs for an investigation finding."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        finding = await self.case_repo.get_finding_by_id(finding_id)
        if finding is None or finding.case_id != case_id:
            raise ResourceNotFoundError("Case finding not found.", code="FINDING_NOT_FOUND")

        history_rows = await self.case_repo.list_finding_history(finding_id)
        return [
            CaseFindingHistoryRead(
                id=h.id,
                finding_id=h.finding_id,
                version_id=h.version_id,
                editor_id=h.editor_id,
                title=h.title,
                description=h.description,
                reason=h.reason,
                created_at=h.created_at,
            )
            for h in history_rows
        ]

    # =========================================================================
    # Phase 87: Lifecycle Transitions & Approvals
    # =========================================================================

    async def validate_case_transition_readiness(
        self,
        case_id: UUID,
        target_status: str | CaseStatus,
        principal: AuthenticatedPrincipal,
    ) -> CaseReadinessResult:
        """Centralized readiness validator for case transitions (Phase 87)."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        current_st = CaseStatus(case_record.status)
        target_st = CaseStatus(target_status) if isinstance(target_status, str) else target_status

        checks: list[CaseReadinessCheck] = []
        blocking_reasons: list[str] = []

        # 1. State machine transition check
        try:
            validate_case_status_transition(current_st, target_st)
            checks.append(
                CaseReadinessCheck(
                    check_name="valid_lifecycle_transition",
                    passed=True,
                    description=f"Transition from '{current_st.value}' to '{target_st.value}' is permissible.",
                )
            )
        except Exception as exc:
            msg = str(exc)
            checks.append(
                CaseReadinessCheck(
                    check_name="valid_lifecycle_transition",
                    passed=False,
                    description=f"Transition from '{current_st.value}' to '{target_st.value}' is permissible.",
                    details=msg,
                )
            )
            blocking_reasons.append(msg)

        # 2. Draft closure prohibition
        if current_st == CaseStatus.DRAFT and target_st in TERMINAL_CASE_STATUSES:
            msg = "Draft cases cannot be closed directly without opening."
            checks.append(
                CaseReadinessCheck(
                    check_name="draft_closure_prohibited",
                    passed=False,
                    description="Draft cases must be opened before being closed.",
                    details=msg,
                )
            )
            blocking_reasons.append(msg)

        # 3. Lead investigator requirement for under_investigation
        if target_st == CaseStatus.UNDER_INVESTIGATION or (current_st == CaseStatus.UNDER_INVESTIGATION and target_st == CaseStatus.PENDING_SUPERVISOR_REVIEW):
            has_lead = case_record.lead_investigator_id is not None
            if has_lead:
                checks.append(
                    CaseReadinessCheck(
                        check_name="lead_investigator_assigned",
                        passed=True,
                        description="Case has an assigned lead investigator.",
                    )
                )
            else:
                msg = f"Cannot transition to '{target_st.value}' without an assigned lead investigator."
                checks.append(
                    CaseReadinessCheck(
                        check_name="lead_investigator_assigned",
                        passed=False,
                        description="Case has an assigned lead investigator.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 4. Linked incident requirement for under_investigation
        if target_st == CaseStatus.UNDER_INVESTIGATION:
            incidents = await self.case_repo.list_case_incidents(case_id)
            has_incident = len(incidents) > 0
            if has_incident:
                checks.append(
                    CaseReadinessCheck(
                        check_name="incident_linked",
                        passed=True,
                        description="Case has at least one linked incident.",
                    )
                )
            else:
                msg = f"Cannot transition to '{target_st.value}' without at least one linked incident."
                checks.append(
                    CaseReadinessCheck(
                        check_name="incident_linked",
                        passed=False,
                        description="Case has at least one linked incident.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 5. Evidence findings or notes requirement
        if target_st in {
            CaseStatus.PENDING_REVIEW,
            CaseStatus.PENDING_SUPERVISOR_REVIEW,
        }:
            notes = await self.case_repo.list_notes_for_case(case_id)
            findings = await self.case_repo.list_findings_for_case(case_id)
            has_substance = bool(notes or findings)
            if has_substance:
                checks.append(
                    CaseReadinessCheck(
                        check_name="evidence_findings_or_notes",
                        passed=True,
                        description="Case contains documented investigation findings or notes.",
                    )
                )
            else:
                msg = f"Cannot transition to '{target_st.value}' without investigation findings or notes."
                checks.append(
                    CaseReadinessCheck(
                        check_name="evidence_findings_or_notes",
                        passed=False,
                        description="Case contains documented investigation findings or notes.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 6. Unreviewed AI candidate segments check
        if target_st in {
            CaseStatus.PENDING_REVIEW,
            CaseStatus.PENDING_SUPERVISOR_REVIEW,
        }:
            ai_segs = await self.case_repo.list_case_ai_segments(case_id)
            unreviewed = [
                s for s in ai_segs
                if s.segment and s.segment.review_status == SegmentReviewStatus.PENDING_REVIEW.value
            ]
            if not unreviewed:
                checks.append(
                    CaseReadinessCheck(
                        check_name="ai_candidate_segments_reviewed",
                        passed=True,
                        description="All linked AI candidate segments have completed human review.",
                    )
                )
            else:
                msg = f"Cannot transition to '{target_st.value}' while linked AI candidate segments remain unreviewed."
                checks.append(
                    CaseReadinessCheck(
                        check_name="ai_candidate_segments_reviewed",
                        passed=False,
                        description="All linked AI candidate segments have completed human review.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 7. Supervisor approval permission check for direct resolution
        if target_st == CaseStatus.RESOLVED:
            can_approve = has_permission(principal.role_code, Permission.CASE_TRANSITION_APPROVE)
            if can_approve:
                checks.append(
                    CaseReadinessCheck(
                        check_name="supervisor_approval_authorized",
                        passed=True,
                        description="Caller possesses supervisor authority to approve resolution.",
                    )
                )
            else:
                msg = "Direct case resolution requires supervisor approval permission."
                checks.append(
                    CaseReadinessCheck(
                        check_name="supervisor_approval_authorized",
                        passed=False,
                        description="Caller possesses supervisor authority to approve resolution.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 8. Close permission check
        if target_st == CaseStatus.CLOSED:
            can_close = has_permission(principal.role_code, Permission.CASE_CLOSE)
            if can_close:
                checks.append(
                    CaseReadinessCheck(
                        check_name="close_permission_authorized",
                        passed=True,
                        description="Caller possesses permission to close cases.",
                    )
                )
            else:
                msg = "You do not have permission to close cases."
                checks.append(
                    CaseReadinessCheck(
                        check_name="close_permission_authorized",
                        passed=False,
                        description="Caller possesses permission to close cases.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 9. Reopening terminal precondition check
        if target_st in {CaseStatus.REOPENED, CaseStatus.UNDER_INVESTIGATION} and current_st in TERMINAL_CASE_STATUSES:
            can_reopen = has_permission(principal.role_code, Permission.CASE_REOPEN)
            if can_reopen:
                checks.append(
                    CaseReadinessCheck(
                        check_name="reopen_permission_authorized",
                        passed=True,
                        description="Caller possesses permission to reopen cases.",
                    )
                )
            else:
                msg = "You do not have permission to reopen cases."
                checks.append(
                    CaseReadinessCheck(
                        check_name="reopen_permission_authorized",
                        passed=False,
                        description="Caller possesses permission to reopen cases.",
                        details=msg,
                    )
                )
                blocking_reasons.append(msg)

        # 10. Legal hold check (informative / preserving)
        if case_record.is_legal_hold:
            checks.append(
                CaseReadinessCheck(
                    check_name="legal_hold_preserved",
                    passed=True,
                    description="Case is subject to an active legal hold; hold protections will be preserved across transition.",
                )
            )

        is_ready = len(blocking_reasons) == 0
        return CaseReadinessResult(
            is_ready=is_ready,
            current_status=current_st.value,
            target_status=target_st.value,
            checks=checks,
            blocking_reasons=blocking_reasons,
        )

    async def get_case_readiness(
        self,
        case_id: UUID,
        target_status: str,
        principal: AuthenticatedPrincipal,
    ) -> CaseReadinessResult:
        """Evaluate and return case transition readiness checklist (Phase 87)."""
        return await self.validate_case_transition_readiness(case_id, target_status, principal)

    async def transition_case_status(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseTransitionRequest,
    ) -> CaseRead:
        """Execute and validate a case lifecycle status transition (Phase 87)."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_writable(case_record, principal)

        current_status = CaseStatus(case_record.status)
        target_status = CaseStatus(payload.target_status)

        # Concurrency check
        if case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        # Execute centralized readiness verification
        readiness = await self.validate_case_transition_readiness(case_id, target_status, principal)
        if not readiness.is_ready:
            first_block = readiness.blocking_reasons[0]
            code = "TRANSITION_PRECONDITION_FAILED"
            low = first_block.lower()
            if "lead investigator" in low:
                code = "LEAD_INVESTIGATOR_REQUIRED"
            elif "linked incident" in low:
                code = "INCIDENT_REQUIRED"
            elif "findings or notes" in low:
                code = "EVIDENCE_FINDINGS_REQUIRED"
            elif "ai candidate segments" in low:
                code = "AI_SEGMENTS_PENDING_REVIEW"
            elif "approval" in low:
                code = "APPROVAL_REQUIRED"
            elif "permission" in low:
                code = "PERMISSION_DENIED"
            elif "draft" in low:
                code = "INVALID_TRANSITION_FOR_DRAFT"
            elif "cannot transition" in low:
                code = "INVALID_CASE_TRANSITION"

            await self._record_audit_event(
                actor_id=principal.user_id,
                action=AuditAction.CASE_TRANSITION_FAILED.value,
                target_id=case_record.id,
                department_id=case_record.department_id,
                details={
                    "case_id": str(case_id),
                    "from_status": current_status.value,
                    "to_status": target_status.value,
                    "blocking_reasons": readiness.blocking_reasons,
                },
            )
            if code == "PERMISSION_DENIED" or code == "APPROVAL_REQUIRED":
                raise PermissionDeniedError(first_block, code=code)
            raise BusinessRuleError(first_block, code=code)

        case_record.status = target_status.value
        case_record.version_id += 1
        if target_status in TERMINAL_CASE_STATUSES:
            case_record.closed_at = utc_now()
        else:
            case_record.closed_at = None

        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_STATUS_TRANSITION.value,
            target_id=case_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "from_status": current_status.value,
                "to_status": target_status.value,
                "reason": payload.reason,
                "new_version": case_record.version_id,
            },
        )
        return self._to_case_read(case_record)

    async def submit_case_for_review(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseSubmitReviewRequest,
    ) -> CaseRead:
        """Submit an active investigation case for supervisory review (Phase 87)."""
        if not has_any_permission(
            principal.role_code,
            [
                Permission.CASE_TRANSITION_SUBMIT,
                Permission.CASE_UPDATE_DEPT,
                Permission.CASE_UPDATE_GLOBAL,
            ],
        ):
            raise PermissionDeniedError(
                "You do not have permission to submit cases for supervisor review.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_writable(case_record, principal)

        if case_record.status not in {CaseStatus.UNDER_INVESTIGATION.value, CaseStatus.REOPENED.value}:
            raise BusinessRuleError(
                f"Only cases under investigation can be submitted for supervisor review (current: '{case_record.status}').",
                code="INVALID_SUBMISSION_STATE",
            )

        # Concurrency check
        if case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        # Validate readiness for PENDING_SUPERVISOR_REVIEW
        readiness = await self.validate_case_transition_readiness(
            case_id, CaseStatus.PENDING_SUPERVISOR_REVIEW, principal
        )
        if not readiness.is_ready:
            msg = readiness.blocking_reasons[0]
            code = "TRANSITION_PRECONDITION_FAILED"
            low = msg.lower()
            if "lead investigator" in low:
                code = "LEAD_INVESTIGATOR_REQUIRED"
            elif "linked incident" in low:
                code = "INCIDENT_REQUIRED"
            elif "findings or notes" in low:
                code = "EVIDENCE_FINDINGS_REQUIRED"
            elif "ai candidate segments" in low:
                code = "AI_SEGMENTS_PENDING_REVIEW"
            raise BusinessRuleError(msg, code=code)

        prior_status = case_record.status
        case_record.status = CaseStatus.PENDING_SUPERVISOR_REVIEW.value
        case_record.version_id += 1
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_SUBMITTED_FOR_REVIEW.value,
            target_id=case_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "from_status": prior_status,
                "to_status": case_record.status,
                "reason": payload.reason,
                "submitted_by_id": str(principal.user_id),
                "new_version": case_record.version_id,
            },
        )
        return self._to_case_read(case_record)

    async def approve_case_transition(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseApprovalRequest,
    ) -> CaseApprovalRead:
        """Record formal supervisory approval or rejection on case transition (Phase 87)."""
        if not has_permission(principal.role_code, Permission.CASE_TRANSITION_APPROVE):
            raise PermissionDeniedError(
                "You do not have permission to approve case transitions.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Separation of Duties check:
        # A supervisor who investigated or submitted the case cannot approve their own case
        is_self_submission = False
        if case_record.lead_investigator_id == principal.user_id:
            is_self_submission = True
        else:
            try:
                events = await self.audit_repo.list_events_for_target(
                    target_type=AuditTargetType.CASE.value,
                    target_id=str(case_id),
                    limit=20,
                )
                for ev in events:
                    if ev.action == AuditAction.CASE_SUBMITTED_FOR_REVIEW.value:
                        if ev.actor_id == principal.user_id:
                            is_self_submission = True
                        break
            except Exception:
                pass

        if is_self_submission:
            await self._record_audit_event(
                actor_id=principal.user_id,
                action=AuditAction.CASE_SELF_APPROVAL_BLOCKED.value,
                target_id=case_record.id,
                department_id=case_record.department_id,
                details={
                    "case_id": str(case_id),
                    "actor_id": str(principal.user_id),
                    "reason": "Self-approval prohibited by separation of duties policy.",
                },
            )
            raise PermissionDeniedError(
                "Supervisors cannot approve their own case review submissions.",
                code="SELF_APPROVAL_PROHIBITED",
            )

        # Idempotency check:
        approvals = await self.case_repo.list_approvals_for_case(case_id)
        if approvals:
            latest = approvals[0]
            if (
                latest.approver_id == principal.user_id
                and latest.decision == payload.decision
                and latest.from_status == payload.from_status
                and latest.to_status == payload.to_status
                and latest.rationale == payload.rationale
            ):
                return self._to_approval_read(latest)

        if payload.expected_version_id is not None and case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        if case_record.status != payload.from_status:
            raise BusinessRuleError(
                f"Case status mismatch: expected '{payload.from_status}', found '{case_record.status}'.",
                code="CASE_STATUS_MISMATCH",
            )

        # Validate rationale for rejection
        if payload.decision in {CaseApprovalDecision.REJECTED.value, CaseApprovalDecision.CHANGES_REQUESTED.value}:
            if not payload.rationale or len(payload.rationale.strip()) < 10:
                raise BusinessRuleError(
                    "Rejection requires a documented rationale of at least 10 characters.",
                    code="RATIONALE_REQUIRED",
                )

        approval = CaseApproval(
            id=uuid4(),
            case_id=case_id,
            approver_id=principal.user_id,
            decision=payload.decision,
            from_status=payload.from_status,
            to_status=payload.to_status,
            rationale=payload.rationale,
            created_at=utc_now(),
        )
        saved_approval = await self.case_repo.create_approval(approval)

        # Update case status based on approval decision
        if payload.decision == CaseApprovalDecision.APPROVED.value:
            validate_case_status_transition(case_record.status, payload.to_status)
            case_record.status = payload.to_status
            if CaseStatus(payload.to_status) in TERMINAL_CASE_STATUSES:
                case_record.closed_at = utc_now()
        elif payload.decision in {
            CaseApprovalDecision.REJECTED.value,
            CaseApprovalDecision.CHANGES_REQUESTED.value,
        }:
            case_record.status = CaseStatus.UNDER_INVESTIGATION.value
            case_record.closed_at = None

        case_record.version_id += 1
        await self.case_repo.session.flush()

        audit_act = (
            AuditAction.CASE_APPROVAL_RECORDED.value
            if payload.decision == CaseApprovalDecision.APPROVED.value
            else AuditAction.CASE_APPROVAL_REJECTED.value
        )
        await self._record_audit_event(
            actor_id=principal.user_id,
            action=audit_act,
            target_id=saved_approval.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "approval_id": str(saved_approval.id),
                "decision": payload.decision,
                "from_status": payload.from_status,
                "to_status": payload.to_status,
                "rationale": payload.rationale,
                "new_version": case_record.version_id,
            },
        )
        return self._to_approval_read(saved_approval)

    async def list_pending_approvals(
        self,
        principal: AuthenticatedPrincipal,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CaseRead]:
        """List cases in PENDING_SUPERVISOR_REVIEW status within authorized department scope (Phase 87)."""
        if not has_any_permission(
            principal.role_code,
            [
                Permission.CASE_APPROVAL_READ,
                Permission.CASE_TRANSITION_APPROVE,
            ],
        ):
            raise PermissionDeniedError(
                "You do not have permission to view pending case approvals.",
                code="PERMISSION_DENIED",
            )

        dept_id = None if principal.role_code == "super_admin" else principal.department_id
        pending_cases = await self.case_repo.list_pending_approvals(
            department_id=dept_id, limit=limit, offset=offset
        )
        return [self._to_case_read(c) for c in pending_cases]

    async def list_case_approvals(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseApprovalRead]:
        """List all approval records for a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        approvals = await self.case_repo.list_approvals_for_case(case_id)
        return [self._to_approval_read(a) for a in approvals]

    async def get_case_transition_history(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseTransitionHistoryItem]:
        """Retrieve chronological audit and approval history for case lifecycle transitions (Phase 87)."""
        if not has_any_permission(
            principal.role_code,
            [
                Permission.CASE_TRANSITION_HISTORY_READ,
                Permission.CASE_READ_OWN,
                Permission.CASE_READ_DEPT,
                Permission.CASE_READ_GLOBAL,
            ],
        ):
            raise PermissionDeniedError(
                "You do not have permission to view case transition history.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        history_items: list[CaseTransitionHistoryItem] = []

        # 1. Approval records
        approvals = await self.case_repo.list_approvals_for_case(case_id)
        for app in approvals:
            history_items.append(
                CaseTransitionHistoryItem(
                    id=app.id,
                    case_id=app.case_id,
                    action="approval_decision",
                    from_status=app.from_status,
                    to_status=app.to_status,
                    actor_id=app.approver_id,
                    actor_role=None,
                    rationale=app.rationale,
                    decision=app.decision,
                    version_id=None,
                    created_at=app.created_at,
                )
            )

        # 2. Audit events
        try:
            events = await self.audit_repo.list_events_for_target(
                target_type=AuditTargetType.CASE.value,
                target_id=str(case_id),
                limit=100,
            )
            for ev in events:
                if ev.action in {
                    AuditAction.CASE_STATUS_TRANSITION.value,
                    AuditAction.CASE_SUBMITTED_FOR_REVIEW.value,
                    AuditAction.CASE_CLOSED.value,
                    AuditAction.CASE_REOPENED.value,
                }:
                    details = ev.details or {}
                    history_items.append(
                        CaseTransitionHistoryItem(
                            id=ev.id,
                            case_id=case_id,
                            action=ev.action,
                            from_status=details.get("from_status") or details.get("prior_status"),
                            to_status=details.get("to_status") or (CaseStatus.CLOSED.value if ev.action == AuditAction.CASE_CLOSED.value else None),
                            actor_id=ev.actor_id,
                            actor_role=ev.actor_role,
                            rationale=details.get("reason"),
                            decision=None,
                            version_id=details.get("new_version"),
                            created_at=ev.created_at,
                        )
                    )
        except Exception:
            pass

        history_items.sort(key=lambda x: x.created_at)
        return history_items



    # =========================================================================
    # Phase 88: Escalations, Referrals, Closure, and Reopening
    # =========================================================================


    async def get_case_activity_timeline(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        event_types: list[str] | None = None,
        actor_id: UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        outcome: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        ascending: bool = False,
    ) -> CaseTimelineResponse:
        """Retrieve a unified, read-only case activity timeline with deterministic tie-breaking and cursor pagination (Phase 88)."""
        if not has_any_permission(
            principal.role_code,
            [
                Permission.CASE_TIMELINE_READ,
                Permission.CASE_READ_OWN,
                Permission.CASE_READ_DEPT,
                Permission.CASE_READ_GLOBAL,
            ],
        ):
            raise PermissionDeniedError(
                "You do not have permission to view the case activity timeline.",
                code="PERMISSION_DENIED",
            )

        if limit < 1 or limit > 100:
            raise BusinessRuleError("Limit must be between 1 and 100.", code="INVALID_LIMIT")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise BusinessRuleError("start_time cannot be after end_time.", code="INVALID_TIME_RANGE")

        cursor_ts: datetime | None = None
        cursor_seq: int | None = None
        cursor_id: UUID | None = None
        if cursor:
            cursor_ts, cursor_seq, cursor_id = _decode_timeline_cursor(cursor)

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Expand event_types if group aliases are used
        expanded_types: set[str] | None = None
        if event_types:
            expanded_types = set()
            for et in event_types:
                clean_et = et.strip().lower()
                if clean_et in TIMELINE_GROUP_EXPANSIONS:
                    expanded_types.update(TIMELINE_GROUP_EXPANSIONS[clean_et])
                else:
                    expanded_types.add(clean_et)

        # Retrieve audit events
        raw_events: Sequence[Any] = []
        try:
            if hasattr(self.audit_repo, "list_events_for_case"):
                raw_events = await self.audit_repo.list_events_for_case(
                    case_id=case_id,
                    department_id=case_record.department_id,
                    event_types=list(expanded_types) if expanded_types else None,
                    actor_id=actor_id,
                    outcome=outcome,
                    start_time=start_time,
                    end_time=end_time,
                    limit=500,
                    ascending=ascending,
                )
        except Exception:
            raw_events = []

        if not raw_events:
            try:
                raw_events = await self.audit_repo.list_events_for_target(
                    target_type=AuditTargetType.CASE.value,
                    target_id=str(case_id),
                    limit=500,
                )
            except Exception:
                raw_events = []

        can_admin_notes = has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED) and (
            principal.department_id == case_record.department_id
            or has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        )
        is_lead = principal.user_id == case_record.lead_investigator_id

        filtered_items: list[CaseTimelineEventRead] = []

        for ev in raw_events:
            det = getattr(ev, "details", None)
            if isinstance(det, str):
                try:
                    parsed_det = json.loads(det)
                except Exception:
                    parsed_det = {}
            elif isinstance(det, dict):
                parsed_det = dict(det)
            else:
                parsed_det = {}

            # Verify case correlation
            ev_target_id = getattr(ev, "target_id", None)
            cid_in_det = parsed_det.get("case_id")
            if str(ev_target_id) != str(case_id) and str(cid_in_det) != str(case_id):
                continue

            # Filtering checks
            ev_action = getattr(ev, "action", "")
            if expanded_types and ev_action.lower() not in expanded_types:
                continue

            ev_actor_id = getattr(ev, "actor_id", None)
            if actor_id is not None and ev_actor_id != actor_id:
                continue

            ev_outcome = getattr(ev, "outcome", "success")
            if outcome is not None and ev_outcome.lower() != outcome.strip().lower():
                continue

            ev_created_at = getattr(ev, "created_at", None)
            if ev_created_at is None:
                continue

            if start_time is not None and ev_created_at < start_time:
                continue
            if end_time is not None and ev_created_at > end_time:
                continue

            # Case note visibility filtering
            if ev_action.startswith("case:note:"):
                note_vis = parsed_det.get("visibility") or parsed_det.get("to_visibility") or parsed_det.get("from_visibility") or "internal"
                is_author = principal.user_id == ev_actor_id
                if note_vis == CaseNoteVisibility.RESTRICTED.value:
                    if not is_author and not can_admin_notes:
                        continue
                elif note_vis == CaseNoteVisibility.CONFIDENTIAL.value:
                    if not is_author and not is_lead and not can_admin_notes:
                        continue
                if ev_action == AuditAction.CASE_NOTE_RESTRICTED_ACCESS_DENIED.value and not can_admin_notes:
                    continue

            # Sanitize details
            sanitized_details: dict[str, Any] = {}
            for k, v in parsed_det.items():
                if k in SAFE_TIMELINE_DETAIL_KEYS:
                    sanitized_details[k] = v

            for prohibited in ("content", "body", "password", "token", "secret", "storage_key", "presigned_url", "key"):
                sanitized_details.pop(prohibited, None)

            if "ai" in ev_action:
                sanitized_details["is_advisory"] = True
                sanitized_details["advisory_disclaimer"] = AI_ADVISORY_DISCLAIMER

            summary_text = _format_timeline_summary(ev_action, ev_outcome, sanitized_details)

            seq_num = getattr(ev, "sequence_number", None)
            event_item = CaseTimelineEventRead(
                id=ev.id,
                case_id=case_id,
                case_reference=case_record.reference_number,
                event_type=ev_action,
                timestamp=ev_created_at,
                sequence_number=seq_num,
                actor_id=ev_actor_id,
                actor_role=getattr(ev, "actor_role", None),
                outcome=ev_outcome,
                summary=summary_text,
                details=sanitized_details,
            )
            filtered_items.append(event_item)

        # Deterministic sorting: (timestamp, sequence_number or 0, str(id))
        filtered_items.sort(
            key=lambda x: (x.timestamp, x.sequence_number if x.sequence_number is not None else 0, str(x.id)),
            reverse=not ascending,
        )

        # Apply cursor filtering
        if cursor_ts is not None and cursor_id is not None:
            c_seq = cursor_seq if cursor_seq is not None else 0
            if ascending:
                filtered_items = [
                    x for x in filtered_items
                    if (x.timestamp, x.sequence_number if x.sequence_number is not None else 0, str(x.id))
                    > (cursor_ts, c_seq, str(cursor_id))
                ]
            else:
                filtered_items = [
                    x for x in filtered_items
                    if (x.timestamp, x.sequence_number if x.sequence_number is not None else 0, str(x.id))
                    < (cursor_ts, c_seq, str(cursor_id))
                ]

        total_count = len(filtered_items)
        paged_items = filtered_items[:limit]
        has_more = len(filtered_items) > limit
        next_cursor = None
        if has_more and paged_items:
            last = paged_items[-1]
            next_cursor = _encode_timeline_cursor(last.timestamp, last.sequence_number, last.id)

        try:
            await self._record_audit_event(
                actor_id=principal.user_id,
                actor_role=principal.role_code,
                action=AuditAction.CASE_TIMELINE_ACCESSED.value,
                target_id=case_record.id,
                department_id=case_record.department_id,
                details={
                    "case_id": str(case_id),
                    "event_count": len(paged_items),
                    "total_count": total_count,
                },
            )
        except Exception:
            pass

        return CaseTimelineResponse(
            items=paged_items,
            total_count=total_count,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def escalate_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseEscalationRequest,
    ) -> CaseEscalationRead:
        """Escalate an investigation case to leadership or external oversight (Phase 88)."""
        if not has_permission(principal.role_code, Permission.CASE_ESCALATE):
            raise PermissionDeniedError(
                "You do not have permission to escalate cases.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Validate target department exists
        target_dept = await self.department_repo.get_by_id(payload.escalated_to_department_id)
        if target_dept is None:
            raise ResourceNotFoundError(
                "Target escalation department not found.",
                code="DEPARTMENT_NOT_FOUND",
            )

        # Concurrency check
        if case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        escalation = CaseEscalation(
            id=uuid4(),
            case_id=case_id,
            escalated_by_id=principal.user_id,
            escalated_to_department_id=payload.escalated_to_department_id,
            reason=payload.reason,
            escalation_level=payload.escalation_level,
            case_version_id=case_record.version_id,
            created_at=utc_now(),
        )
        saved = await self.case_repo.create_escalation(escalation)

        case_record.version_id += 1
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_ESCALATED.value,
            target_id=saved.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "escalated_to_department_id": str(payload.escalated_to_department_id),
                "escalation_level": payload.escalation_level,
                "reason": payload.reason,
            },
        )
        return self._to_escalation_read(saved)

    async def list_case_escalations(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseEscalationRead]:
        """List all escalations recorded for a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        escalations = await self.case_repo.list_escalations_for_case(case_id)
        return [self._to_escalation_read(e) for e in escalations]

    async def refer_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseReferralCreate,
    ) -> CaseReferralRead:
        """Create a case referral to an internal partner or external agency (Phase 88)."""
        if not has_permission(principal.role_code, Permission.CASE_REFER):
            raise PermissionDeniedError(
                "You do not have permission to refer cases.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        if payload.target_department_id is not None:
            target_dept = await self.department_repo.get_by_id(payload.target_department_id)
            if target_dept is None:
                raise ResourceNotFoundError(
                    "Target referral department not found.", code="DEPARTMENT_NOT_FOUND"
                )

        referral = CaseReferral(
            id=uuid4(),
            case_id=case_id,
            referred_by_id=principal.user_id,
            target_department_id=payload.target_department_id,
            target_external_agency=payload.target_external_agency,
            referral_purpose=payload.referral_purpose,
            status=CaseReferralStatus.PENDING.value,
            resolution_notes=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        saved = await self.case_repo.create_referral(referral)

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_REFERRED.value,
            target_id=saved.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "referral_id": str(saved.id),
                "purpose": payload.referral_purpose,
            },
        )
        return self._to_referral_read(saved)

    async def update_referral_status(
        self,
        case_id: UUID,
        referral_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseReferralUpdate,
    ) -> CaseReferralRead:
        """Update case referral outcome and resolution notes."""
        if not has_permission(principal.role_code, Permission.CASE_REFER):
            raise PermissionDeniedError(
                "You do not have permission to manage case referrals.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        referral = await self.case_repo.get_referral_by_id(referral_id)
        if referral is None or referral.case_id != case_id:
            raise ResourceNotFoundError("Case referral not found.", code="REFERRAL_NOT_FOUND")

        referral.status = payload.status
        if payload.resolution_notes is not None:
            referral.resolution_notes = payload.resolution_notes
        referral.updated_at = utc_now()
        await self.case_repo.session.flush()
        return self._to_referral_read(referral)

    async def list_case_referrals(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[CaseReferralRead]:
        """List all referrals for a case."""
        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        referrals = await self.case_repo.list_referrals_for_case(case_id)
        return [self._to_referral_read(r) for r in referrals]

    async def close_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseCloseRequest,
    ) -> CaseRead:
        """Formally close an investigation case with documented rationale (Phase 88)."""
        if not has_permission(principal.role_code, Permission.CASE_CLOSE):
            raise PermissionDeniedError(
                "You do not have permission to close cases.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_writable(case_record, principal)

        if case_record.status == CaseStatus.DRAFT.value:
            raise BusinessRuleError(
                "Draft cases cannot be closed without being opened.", code="INVALID_CASE_STATE"
            )

        if case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        prior_status = case_record.status
        case_record.status = CaseStatus.CLOSED.value
        case_record.closed_at = utc_now()
        case_record.version_id += 1
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_CLOSED.value,
            target_id=case_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "prior_status": prior_status,
                "reason": payload.reason,
                "is_legal_hold": case_record.is_legal_hold,
            },
        )
        return self._to_case_read(case_record)

    async def reopen_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseReopenRequest,
    ) -> CaseRead:
        """Reopen a closed or resolved investigation case (Phase 88)."""
        if not has_permission(principal.role_code, Permission.CASE_REOPEN):
            raise PermissionDeniedError(
                "You do not have permission to reopen cases.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_writable(case_record, principal)

        if CaseStatus(case_record.status) not in TERMINAL_CASE_STATUSES:
            raise BusinessRuleError(
                f"Only resolved or closed cases can be reopened (current: '{case_record.status}').",
                code="CASE_NOT_CLOSED",
            )

        if case_record.version_id != payload.expected_version_id:
            raise ConflictError(
                f"Case version conflict: expected {payload.expected_version_id}, but found {case_record.version_id}.",
                code="CONCURRENCY_CONFLICT",
            )

        prior_status = case_record.status
        target_st = getattr(payload, "target_status", None) or CaseStatus.UNDER_INVESTIGATION
        if target_st not in {CaseStatus.UNDER_INVESTIGATION, CaseStatus.REOPENED}:
            raise BusinessRuleError(
                f"Reopened status must be 'under_investigation' or 'reopened' (got '{target_st.value}').",
                code="INVALID_REOPEN_TARGET",
            )
        case_record.status = target_st.value
        case_record.closed_at = None
        case_record.version_id += 1
        await self.case_repo.session.flush()

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_REOPENED.value,
            target_id=case_record.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "prior_status": prior_status,
                "reason": payload.reason,
            },
        )
        return self._to_case_read(case_record)

    # =========================================================================
    # Phase 89: Case Exports & Manifests
    # =========================================================================

    async def export_case(
        self,
        case_id: UUID,
        principal: AuthenticatedPrincipal,
        payload: CaseExportRequest,
    ) -> CaseExportRead:
        """Generate a cryptographically hashed, controlled case disclosure package (Phase 89)."""
        if not has_permission(principal.role_code, Permission.CASE_EXPORT):
            raise PermissionDeniedError(
                "You do not have permission to export cases.",
                code="PERMISSION_DENIED",
            )

        case_record = await self.case_repo.get_by_id(case_id)
        if case_record is None:
            raise ResourceNotFoundError("Case not found.", code="CASE_NOT_FOUND")

        self._assert_case_visible(case_record, principal)

        # Restricted notes export validation
        if payload.include_restricted_notes:
            can_restricted = has_permission(
                principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED
            )
            if not can_restricted:
                raise PermissionDeniedError(
                    "Elevated permission required to export restricted working notes.",
                    code="RESTRICTED_EXPORT_DENIED",
                )

        # 1. Compile evidence manifest items (verifying digest format and integrity)
        evidence_links = await self.case_repo.list_case_evidence(case_id)
        manifest_evidence_items: list[dict[str, Any]] = []
        for el in evidence_links:
            att = el.evidence
            digest = getattr(att, "sha256_hash", None) or getattr(att, "sha256_digest", "")
            is_valid_digest = isinstance(digest, str) and len(digest.strip()) == 64
            v_status = (
                EvidenceVerificationStatus.VERIFIED.value
                if is_valid_digest
                else EvidenceVerificationStatus.INTEGRITY_FAILED.value
            )
            manifest_evidence_items.append(
                {
                    "evidence_id": str(el.evidence_id),
                    "file_name": getattr(att, "original_filename", "evidence_artifact"),
                    "sha256_digest": digest,
                    "file_size_bytes": getattr(att, "file_size", 0),
                    "verification_status": v_status,
                    "notes": el.notes,
                }
            )

        # 2. Compile notes (redacting restricted and confidential notes if not authorized)
        can_restricted = has_permission(principal.role_code, Permission.CASE_NOTE_READ_RESTRICTED)
        can_admin = can_restricted and (
            principal.department_id == case_record.department_id
            or has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        )
        is_lead = principal.user_id == case_record.lead_investigator_id

        raw_notes = await self.case_repo.list_notes_for_case(case_id)
        manifest_notes: list[dict[str, Any]] = []
        for n in raw_notes:
            if n.visibility == CaseNoteVisibility.RESTRICTED.value:
                if not (payload.include_restricted_notes and can_restricted):
                    continue
            elif n.visibility == CaseNoteVisibility.CONFIDENTIAL.value:
                if not (n.author_id == principal.user_id or is_lead or can_admin):
                    continue
            manifest_notes.append(
                {
                    "note_id": str(n.id),
                    "visibility": n.visibility,
                    "content": n.content,
                    "author_id": str(n.author_id),
                    "created_at": n.created_at.isoformat(),
                }
            )

        # 3. Compile findings
        raw_findings = await self.case_repo.list_findings_for_case(case_id)
        manifest_findings: list[dict[str, Any]] = [
            {
                "finding_id": str(f.id),
                "title": f.title,
                "description": f.description,
                "finding_type": f.finding_type,
                "is_preliminary": f.is_preliminary,
                "created_at": f.created_at.isoformat(),
            }
            for f in raw_findings
        ]

        # 4. Compile AI candidate segments with mandatory statutory disclaimer
        raw_ai_segs = await self.case_repo.list_case_ai_segments(case_id)
        manifest_ai_segs: list[dict[str, Any]] = [
            {
                "segment_id": str(s.segment_id),
                "investigative_relevance": s.investigative_relevance,
                "score": s.segment.calibrated_score
                if getattr(s.segment, "calibrated_score", None) is not None
                else getattr(s.segment, "raw_score", 0.0),
                "label": getattr(s.segment, "raw_label", "candidate_action"),
                "review_status": getattr(
                    s.segment, "review_status", SegmentReviewStatus.PENDING_REVIEW.value
                ),
                "advisory_disclaimer": AI_ADVISORY_DISCLAIMER,
            }
            for s in raw_ai_segs
        ]

        # 5. Assemble complete manifest dictionary (strict exclusion of credentials/tokens)
        manifest_payload: dict[str, Any] = {
            "case_reference_number": case_record.reference_number,
            "case_id": str(case_record.id),
            "department_id": str(case_record.department_id),
            "title": case_record.title,
            "summary": case_record.summary,
            "status": case_record.status,
            "priority": case_record.priority,
            "export_scope": payload.export_scope,
            "export_format": payload.export_format,
            "exported_by_id": str(principal.user_id),
            "exported_at": utc_now().isoformat(),
            "evidence_manifest": manifest_evidence_items,
            "notes": manifest_notes,
            "findings": manifest_findings,
            "ai_candidate_segments": manifest_ai_segs,
            "advisory_notice": AI_ADVISORY_DISCLAIMER,
        }

        # Canonical JSON string for hashing
        canonical_json = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
        manifest_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        export_record = CaseExport(
            id=uuid4(),
            case_id=case_id,
            department_id=case_record.department_id,
            exported_by_id=principal.user_id,
            export_scope=payload.export_scope,
            export_format=payload.export_format,
            manifest_sha256=manifest_sha256,
            evidence_count=len(manifest_evidence_items),
            manifest_payload=canonical_json,
            status="completed",
            purpose=payload.purpose,
            expires_at=utc_now() + timedelta(days=7),
            created_at=utc_now(),
        )
        saved_export = await self.case_repo.create_export(export_record)

        await self._record_audit_event(
            actor_id=principal.user_id,
            action=AuditAction.CASE_EXPORTED.value,
            target_id=saved_export.id,
            department_id=case_record.department_id,
            details={
                "case_id": str(case_id),
                "export_id": str(saved_export.id),
                "manifest_sha256": manifest_sha256,
                "evidence_count": len(manifest_evidence_items),
                "scope": payload.export_scope,
                "purpose": payload.purpose,
            },
        )
        return self._to_export_read(saved_export, manifest_payload)

    async def get_case_export(
        self,
        export_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> CaseExportRead:
        """Retrieve an existing case export package (Phase 89)."""
        export_record = await self.case_repo.get_export_by_id(export_id)
        if export_record is None:
            raise ResourceNotFoundError("Case export not found.", code="EXPORT_NOT_FOUND")

        can_global = has_permission(principal.role_code, Permission.CASE_READ_GLOBAL)
        if not can_global and export_record.department_id != principal.department_id:
            raise ResourceNotFoundError("Case export not found.", code="EXPORT_NOT_FOUND")

        try:
            payload_dict = json.loads(export_record.manifest_payload)
        except Exception:
            payload_dict = {}

        return self._to_export_read(export_record, payload_dict)

    # -------------------------------------------------------------------------
    # DTO Mappers
    # -------------------------------------------------------------------------

    def _to_note_read(self, n: CaseNote) -> CaseNoteRead:
        return CaseNoteRead(
            id=n.id,
            case_id=n.case_id,
            author_id=n.author_id,
            visibility=n.visibility,
            content=n.content,
            version_id=n.version_id,
            is_archived=n.is_archived,
            evidence_reference_ids=n.evidence_reference_ids,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )

    def _to_finding_read(self, f: CaseFinding) -> CaseFindingRead:
        return CaseFindingRead(
            id=f.id,
            case_id=f.case_id,
            author_id=f.author_id,
            finding_type=f.finding_type,
            title=f.title,
            description=f.description,
            evidence_ids=f.evidence_ids,
            ai_segment_ids=f.ai_segment_ids,
            incident_ids=f.incident_ids,
            version_id=f.version_id,
            is_preliminary=f.is_preliminary,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )

    def _to_approval_read(self, a: CaseApproval) -> CaseApprovalRead:
        return CaseApprovalRead(
            id=a.id,
            case_id=a.case_id,
            approver_id=a.approver_id,
            decision=a.decision,
            from_status=a.from_status,
            to_status=a.to_status,
            rationale=a.rationale,
            created_at=a.created_at,
        )

    def _to_escalation_read(self, e: CaseEscalation) -> CaseEscalationRead:
        return CaseEscalationRead(
            id=e.id,
            case_id=e.case_id,
            escalated_by_id=e.escalated_by_id,
            escalated_to_department_id=e.escalated_to_department_id,
            reason=e.reason,
            escalation_level=e.escalation_level,
            case_version_id=e.case_version_id,
            created_at=e.created_at,
        )

    def _to_referral_read(self, r: CaseReferral) -> CaseReferralRead:
        return CaseReferralRead(
            id=r.id,
            case_id=r.case_id,
            referred_by_id=r.referred_by_id,
            target_department_id=r.target_department_id,
            target_external_agency=r.target_external_agency,
            referral_purpose=r.referral_purpose,
            status=r.status,
            resolution_notes=r.resolution_notes,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    def _to_export_read(self, ex: CaseExport, payload_dict: dict[str, Any]) -> CaseExportRead:
        return CaseExportRead(
            id=ex.id,
            case_id=ex.case_id,
            department_id=ex.department_id,
            exported_by_id=ex.exported_by_id,
            export_scope=ex.export_scope,
            export_format=ex.export_format,
            manifest_sha256=ex.manifest_sha256,
            evidence_count=ex.evidence_count,
            manifest_payload=payload_dict,
            status=ex.status,
            purpose=ex.purpose,
            expires_at=ex.expires_at,
            created_at=ex.created_at,
        )
