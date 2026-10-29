"""Security audit and evidence export domain service (Phases 58-59).

Enforces:
- Append-only tamper-evident security audit logging with SHA-256 hash chains.
- Strict multi-tenant and department-scoped query enforcement.
- Cryptographic ledger verification with explicit statutory disclaimers.
- Evidence export manifest hashing and authorized packaging.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config.settings import Settings
from backend.app.core.audit import (
    AuditAction,
    AuditOutcome,
    AuditTargetType,
)
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    SecurityError,
)
from backend.app.core.logging import get_logger
from backend.app.core.secrets import redact_mapping
from backend.app.models.audit import EvidenceExport, SecurityAuditEvent
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.evidence import EvidenceRepository
from backend.app.repositories.incident import IncidentRepository
from backend.app.schemas.audit import (
    AuditEventExportRequest,
    AuditEventExportResponse,
    AuditSearchFilterParams,
    AuditVerificationReport,
    EvidenceExportRequest,
    EvidenceExportResponse,
    SecurityAuditEventRead,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.pagination import PaginatedResponse, PaginationMetadata

logger = get_logger("services.audit")


class AuditService:
    """Domain service managing tamper-evident security audit events and evidence exports."""

    def __init__(
        self,
        audit_repo: AuditRepository,
        incident_repo: IncidentRepository,
        evidence_repo: EvidenceRepository,
        settings: Settings,
    ) -> None:
        self.audit_repo = audit_repo
        self.incident_repo = incident_repo
        self.evidence_repo = evidence_repo
        self.settings = settings

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings,
    ) -> AuditService:
        """Construct an AuditService wired with repositories bound to ``session``."""
        return cls(
            audit_repo=AuditRepository(session),
            incident_repo=IncidentRepository(session),
            evidence_repo=EvidenceRepository(session),
            settings=settings,
        )

    async def record_security_event(
        self,
        *,
        action: str,
        actor_id: UUID | None,
        actor_role: str | None,
        actor_ip: str | None = None,
        actor_user_agent: str | None = None,
        department_id: UUID | None = None,
        target_type: str,
        target_id: str,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
        fail_closed: bool = True,
    ) -> SecurityAuditEvent | None:
        """Record a tamper-evident audit event adhering to fail-closed policy."""
        try:
            event = await self.audit_repo.append_event(
                action=action,
                actor_id=actor_id,
                actor_role=actor_role,
                actor_ip=actor_ip,
                actor_user_agent=actor_user_agent,
                department_id=department_id,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                details=details,
            )
            return event
        except Exception as exc:
            logger.error(
                "Failed to append security audit event",
                extra={
                    "action": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "error": str(exc),
                },
            )
            if fail_closed:
                raise SecurityError(
                    f"Audit event recording failed under fail-closed security policy: {exc}",
                    code="AUDIT_PERSISTENCE_FAILED",
                ) from exc
            return None

    async def search_audit_events(
        self,
        params: AuditSearchFilterParams,
        principal: AuthenticatedPrincipal,
    ) -> PaginatedResponse[SecurityAuditEventRead]:
        """Search security audit events with strict department/tenant authorization."""
        can_read_global = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_GLOBAL)
        can_read_dept = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_DEPT)

        if not can_read_global and not can_read_dept:
            raise PermissionDeniedError(
                "You do not have permission to view security audit events.",
                code="PERMISSION_DENIED",
            )

        department_scope: UUID | None = params.department_id
        if not can_read_global:
            # Department-scoped users can only see events in their own department
            department_scope = principal.department_id

        # Normalize enum/str parameters
        action_val: str | None = None
        if params.action is not None:
            action_val = (
                str(params.action.value) if hasattr(params.action, "value") else str(params.action)
            )

        target_val: str | None = None
        if params.target_type is not None:
            target_val = (
                str(params.target_type.value)
                if hasattr(params.target_type, "value")
                else str(params.target_type)
            )

        outcome_val: str | None = None
        if params.outcome is not None:
            outcome_val = (
                str(params.outcome.value)
                if hasattr(params.outcome, "value")
                else str(params.outcome)
            )

        offset = (params.page - 1) * params.page_size

        events, total_count = await self.audit_repo.list_events_paginated(
            actor_id=params.actor_id,
            action=action_val,
            target_type=target_val,
            target_id=params.target_id,
            department_id=department_scope,
            outcome=outcome_val,
            start_time=params.start_time,
            end_time=params.end_time,
            limit=params.page_size,
            offset=offset,
        )

        read_items = [SecurityAuditEventRead.model_validate(e) for e in events]
        metadata = PaginationMetadata.from_counts(
            page=params.page,
            page_size=params.page_size,
            total_items=total_count,
        )

        return PaginatedResponse(items=read_items, pagination=metadata)

    async def verify_audit_chain(
        self,
        principal: AuthenticatedPrincipal,
        *,
        start_sequence: int = 1,
        limit: int = 1000,
    ) -> AuditVerificationReport:
        """Verify tamper-evident hash chain integrity for authorized reviewers."""
        can_read_global = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_GLOBAL)
        can_read_dept = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_DEPT)

        if not can_read_global and not can_read_dept:
            raise PermissionDeniedError(
                "You do not have permission to verify audit chain integrity.",
                code="PERMISSION_DENIED",
            )

        result_dict = await self.audit_repo.verify_chain(
            limit=limit,
            start_sequence=start_sequence,
        )

        return AuditVerificationReport.model_validate(result_dict)

    async def export_incident_evidence(
        self,
        incident_id: UUID,
        payload: EvidenceExportRequest,
        principal: AuthenticatedPrincipal,
    ) -> EvidenceExportResponse:
        """Generate an authorized evidence export package and cryptographic manifest (Phase 59)."""
        can_export_global = has_permission(principal.role_code, Permission.EVIDENCE_EXPORT_GLOBAL)
        can_export_dept = has_permission(principal.role_code, Permission.EVIDENCE_EXPORT_DEPT)

        if not can_export_global and not can_export_dept:
            raise PermissionDeniedError(
                "You do not have permission to export incident evidence packages.",
                code="PERMISSION_DENIED",
            )

        incident = await self.incident_repo.get_by_id(incident_id)
        if incident is None:
            raise ResourceNotFoundError("Incident not found.", code="INCIDENT_NOT_FOUND")

        # Scope enforcement
        if not can_export_global and incident.department_id != principal.department_id:
            raise ResourceNotFoundError("Incident not found.", code="INCIDENT_NOT_FOUND")

        # Collect evidence records
        attachments = await self.evidence_repo.list_attachments_by_incident(incident.id)
        valid_attachments = [
            a
            for a in attachments
            if a.evidence_status != "quarantined" and a.scan_status == "clean"
        ]

        # Generate cryptographic export manifest
        manifest_items = [
            {
                "evidence_id": str(a.id),
                "original_filename": a.original_filename,
                "sha256": a.sha256_hash,
                "file_size_bytes": a.file_size_bytes,
                "mime_type": a.declared_mime_type,
                "created_at": a.created_at.isoformat()
                if a.created_at is not None
                else datetime.now(UTC).isoformat(),
            }
            for a in valid_attachments
        ]
        manifest_payload = {
            "incident_id": str(incident.id),
            "reference_number": incident.reference_number,
            "department_id": str(incident.department_id),
            "export_scope": payload.export_scope,
            "export_format": payload.export_format,
            "exported_by_id": str(principal.user_id),
            "evidence_count": len(valid_attachments),
            "evidence_items": manifest_items,
            "exported_at": datetime.now(UTC).isoformat(),
        }

        manifest_raw = json.dumps(manifest_payload, sort_keys=True).encode("utf-8")
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()

        export_record = EvidenceExport(
            id=uuid4(),
            incident_id=incident.id,
            department_id=incident.department_id,
            exported_by_id=principal.user_id,
            export_scope=payload.export_scope,
            export_format=payload.export_format,
            evidence_count=len(valid_attachments),
            manifest_sha256=manifest_sha256,
            status="completed",
            reason=payload.reason,
            created_at=datetime.now(UTC),
        )

        created_export = await self.audit_repo.create_evidence_export(export_record)

        # Record tamper-evident security audit event
        await self.record_security_event(
            action=AuditAction.EVIDENCE_EXPORTED.value,
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            department_id=incident.department_id,
            target_type=AuditTargetType.INCIDENT.value,
            target_id=str(incident.id),
            outcome=AuditOutcome.SUCCESS.value,
            details={
                "export_id": str(created_export.id),
                "manifest_sha256": manifest_sha256,
                "evidence_count": len(valid_attachments),
                "export_scope": payload.export_scope,
                "reason": payload.reason,
            },
        )

        logger.info(
            "Evidence export package created",
            extra={
                "export_id": str(created_export.id),
                "incident_id": str(incident.id),
                "exporter_id": str(principal.user_id),
                "manifest_sha256": manifest_sha256,
            },
        )

        return EvidenceExportResponse.model_validate(created_export)

    async def list_evidence_exports(
        self,
        principal: AuthenticatedPrincipal,
        *,
        incident_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[EvidenceExportResponse]:
        """List historical evidence exports for authorized department or platform administrators."""
        can_export_global = has_permission(principal.role_code, Permission.EVIDENCE_EXPORT_GLOBAL)
        can_export_dept = has_permission(principal.role_code, Permission.EVIDENCE_EXPORT_DEPT)

        if not can_export_global and not can_export_dept:
            raise PermissionDeniedError(
                "You do not have permission to view evidence export logs.",
                code="PERMISSION_DENIED",
            )

        department_scope: UUID | None = None
        if not can_export_global:
            department_scope = principal.department_id

        if page_size > 100:
            page_size = 100
        offset = (page - 1) * page_size

        exports, total_count = await self.audit_repo.list_evidence_exports_paginated(
            department_id=department_scope,
            incident_id=incident_id,
            limit=page_size,
            offset=offset,
        )

        items = [EvidenceExportResponse.model_validate(e) for e in exports]
        metadata = PaginationMetadata.from_counts(
            page=page,
            page_size=page_size,
            total_items=total_count,
        )

        return PaginatedResponse(items=items, pagination=metadata)


    async def get_audit_event_detail(
        self,
        event_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> SecurityAuditEventRead:
        """Retrieve a single security audit event with redacted details and tenant scoping."""
        can_read_global = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_GLOBAL)
        can_read_dept = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_DEPT)

        if not can_read_global and not can_read_dept:
            raise PermissionDeniedError(
                "You do not have permission to view security audit events.",
                code="PERMISSION_DENIED",
            )

        event = await self.audit_repo.get_by_id(event_id)
        if event is None:
            raise ResourceNotFoundError("Security audit event not found.", code="AUDIT_EVENT_NOT_FOUND")

        if not can_read_global and event.department_id != principal.department_id:
            raise ResourceNotFoundError("Security audit event not found.", code="AUDIT_EVENT_NOT_FOUND")

        details_dict: dict[str, Any] | None = None
        if event.details:
            try:
                raw_details = json.loads(event.details) if isinstance(event.details, str) else event.details
                if isinstance(raw_details, dict):
                    details_dict = redact_mapping(raw_details)
                else:
                    details_dict = {"raw": raw_details}
            except Exception:
                details_dict = {"raw": event.details}

        event_read = SecurityAuditEventRead.model_validate(event)
        if details_dict is not None:
            event_read.details = details_dict
        return event_read

    async def export_audit_events(
        self,
        request: AuditEventExportRequest,
        principal: AuthenticatedPrincipal,
    ) -> AuditEventExportResponse:
        """Export security audit events in CSV or JSON format with formula injection protection."""
        can_read_global = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_GLOBAL)
        can_read_dept = has_permission(principal.role_code, Permission.AUDIT_EVENT_READ_DEPT)

        if not can_read_global and not can_read_dept:
            raise PermissionDeniedError(
                "You do not have permission to export security audit events.",
                code="PERMISSION_DENIED",
            )

        department_scope: UUID | None = request.department_id
        if not can_read_global:
            department_scope = principal.department_id

        limit = min(request.limit, 1000)
        events, _total_count = await self.audit_repo.list_events_paginated(
            actor_id=request.actor_id,
            action=request.action,
            target_type=request.target_type,
            target_id=request.target_id,
            department_id=department_scope,
            outcome=request.outcome,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=limit,
            offset=0,
        )

        export_id = uuid4()
        now = datetime.now(UTC)

        def _sanitize_cell(val: Any) -> str:
            s = "" if val is None else str(val)
            if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
                return f"'{s}"
            return s

        if request.export_format == "csv":
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "id", "sequence_number", "action", "actor_id", "actor_role",
                "department_id", "target_type", "target_id", "outcome",
                "created_at", "previous_event_hash", "event_hash"
            ])
            for ev in events:
                writer.writerow([
                    _sanitize_cell(ev.id),
                    _sanitize_cell(ev.sequence_number),
                    _sanitize_cell(ev.action),
                    _sanitize_cell(ev.actor_id),
                    _sanitize_cell(ev.actor_role),
                    _sanitize_cell(ev.department_id),
                    _sanitize_cell(ev.target_type),
                    _sanitize_cell(ev.target_id),
                    _sanitize_cell(ev.outcome),
                    _sanitize_cell(ev.created_at.isoformat() if hasattr(ev.created_at, "isoformat") else ev.created_at),
                    _sanitize_cell(ev.previous_event_hash),
                    _sanitize_cell(ev.event_hash),
                ])
            content_str = output.getvalue()
        else:
            records = []
            for ev in events:
                ev_read = SecurityAuditEventRead.model_validate(ev)
                if ev_read.details:
                    ev_read.details = redact_mapping(ev_read.details)
                records.append(ev_read.model_dump(mode="json"))
            content_str = json.dumps(records, indent=2, sort_keys=True)

        hash_digest = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

        await self.record_security_event(
            action="audit:events:exported",
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            department_id=principal.department_id,
            target_type="audit",
            target_id=str(export_id),
            outcome="success",
            details={
                "export_format": request.export_format,
                "total_records": len(events),
                "hash_digest": hash_digest,
            },
            fail_closed=True,
        )

        return AuditEventExportResponse(
            export_id=export_id,
            exported_at=now,
            export_format=request.export_format,
            total_records=len(events),
            content=content_str,
            hash_digest=hash_digest,
        )
