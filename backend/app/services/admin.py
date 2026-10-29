"""Administration and System Settings domain service (Phase 118).

Enforces:
- Separation of platform-wide system settings (Super Admin exclusive) and department settings.
- Scoping rules: Department Admins are strictly isolated to their own department.
- Zero secret, token, or connection string disclosure.
- Tamper-evident audit logging for all configuration mutations.
- Immunity to privilege escalation: settings endpoints cannot alter user roles or account status.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config.settings import Settings
from backend.app.core.authorization import Permission, has_permission
from backend.app.core.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.logging import get_logger
from backend.app.repositories.identity import DepartmentRepository
from backend.app.schemas.admin import (
    DepartmentListItem,
    DepartmentSettingsRead,
    DepartmentSettingsUpdate,
    SystemSettingsRead,
    SystemSettingsUpdate,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.services.audit import AuditService

logger = get_logger("services.admin")

# Thread-safe in-memory operational state for system and department settings
_SYSTEM_OPERATIONAL_STATE: dict[str, Any] = {
    "maintenance_mode": False,
    "system_announcement": None,
}

_DEPARTMENT_OPERATIONAL_STATE: dict[UUID, dict[str, Any]] = {}


class AdminService:
    """Service governing administrative operations and system configuration."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        dept_repo: DepartmentRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.dept_repo = dept_repo
        self.audit_service = audit_service
        self.settings = settings

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        settings: Settings,
    ) -> AdminService:
        """Construct an AdminService wired with dependencies bound to ``session``."""
        dept_repo = DepartmentRepository(session)
        audit_service = AuditService.from_session(session, settings)
        return cls(
            session=session,
            dept_repo=dept_repo,
            audit_service=audit_service,
            settings=settings,
        )

    async def get_system_settings(
        self,
        principal: AuthenticatedPrincipal,
    ) -> SystemSettingsRead:
        """Retrieve sanitized system-level settings (Super Admin only)."""
        if not has_permission(principal.role_code, Permission.SYSTEM_CONFIG_MANAGE):
            raise PermissionDeniedError(
                "Super Admin privileges required to inspect system configuration.",
                code="PERMISSION_DENIED",
            )

        return SystemSettingsRead(
            environment=self.settings.ENVIRONMENT.value,
            app_version=self.settings.APP_VERSION,
            log_level=self.settings.LOG_LEVEL.value,
            cors_allowed_origins=list(self.settings.CORS_ALLOWED_ORIGINS),
            auth_access_token_expire_minutes=self.settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES,
            auth_refresh_token_expire_days=self.settings.AUTH_REFRESH_TOKEN_EXPIRE_DAYS,
            biometric_matching_enabled=self.settings.BIOMETRIC_MATCHING_ENABLED,
            maintenance_mode=_SYSTEM_OPERATIONAL_STATE["maintenance_mode"],
            system_announcement=_SYSTEM_OPERATIONAL_STATE["system_announcement"],
            database_status="configured_redacted",
            redis_status="configured_redacted",
            storage_endpoint_url_redacted=self.settings.STORAGE_ENDPOINT_URL,
            storage_bucket_name=self.settings.STORAGE_BUCKET_NAME,
            storage_region=self.settings.STORAGE_REGION,
            ai_provider=self.settings.AI_PROVIDER.value,
            max_upload_size_bytes=self.settings.MAX_EVIDENCE_FILE_BYTES,
            allowed_evidence_mime_types=list(self.settings.ALLOWED_EVIDENCE_MIME_TYPES),
        )

    async def update_system_settings(
        self,
        body: SystemSettingsUpdate,
        principal: AuthenticatedPrincipal,
    ) -> SystemSettingsRead:
        """Update operational system settings (Super Admin only)."""
        if not has_permission(principal.role_code, Permission.SYSTEM_CONFIG_MANAGE):
            raise PermissionDeniedError(
                "Super Admin privileges required to update system configuration.",
                code="PERMISSION_DENIED",
            )

        updated_fields: dict[str, Any] = {}
        if body.maintenance_mode is not None:
            _SYSTEM_OPERATIONAL_STATE["maintenance_mode"] = body.maintenance_mode
            updated_fields["maintenance_mode"] = body.maintenance_mode
        if body.system_announcement is not None:
            _SYSTEM_OPERATIONAL_STATE["system_announcement"] = body.system_announcement
            updated_fields["system_announcement"] = body.system_announcement

        await self.audit_service.record_security_event(
            action="system:config:manage",
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            department_id=principal.department_id,
            target_type="system",
            target_id="settings",
            outcome="success",
            details={"updated_fields": updated_fields},
            fail_closed=True,
        )

        return await self.get_system_settings(principal)

    async def get_department_settings(
        self,
        department_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> DepartmentSettingsRead:
        """Retrieve department settings with tenant boundary verification."""
        is_global = has_permission(principal.role_code, Permission.DEPARTMENT_READ_GLOBAL)
        if not is_global and principal.department_id != department_id:
            raise PermissionDeniedError(
                "Cannot access department settings outside your assigned department.",
                code="DEPARTMENT_MISMATCH",
            )

        dept = await self.dept_repo.get_by_id(department_id)
        if dept is None:
            raise ResourceNotFoundError(
                f"Department '{department_id}' not found.",
                code="DEPARTMENT_NOT_FOUND",
            )

        dept_state = _DEPARTMENT_OPERATIONAL_STATE.get(department_id, {})

        return DepartmentSettingsRead(
            department_id=dept.id,
            code=dept.code,
            name=dept.name,
            description=dept.description,
            is_active=dept.is_active,
            contact_email=dept_state.get("contact_email"),
            retention_period_days=dept_state.get("retention_period_days", 365),
            max_active_cases_per_investigator=dept_state.get(
                "max_active_cases_per_investigator", 10
            ),
            require_two_party_case_closure=dept_state.get(
                "require_two_party_case_closure", True
            ),
        )

    async def update_department_settings(
        self,
        department_id: UUID,
        body: DepartmentSettingsUpdate,
        principal: AuthenticatedPrincipal,
    ) -> DepartmentSettingsRead:
        """Update department operational settings within authorized boundary."""
        is_global = has_permission(principal.role_code, Permission.DEPARTMENT_UPDATE_GLOBAL)
        can_dept = has_permission(principal.role_code, Permission.DEPARTMENT_READ_OWN)

        if not is_global and not can_dept:
            raise PermissionDeniedError(
                "Insufficient privileges to update department settings.",
                code="PERMISSION_DENIED",
            )

        if not is_global and principal.department_id != department_id:
            raise PermissionDeniedError(
                "Cannot modify department settings outside your assigned department.",
                code="DEPARTMENT_MISMATCH",
            )

        dept = await self.dept_repo.get_by_id(department_id)
        if dept is None:
            raise ResourceNotFoundError(
                f"Department '{department_id}' not found.",
                code="DEPARTMENT_NOT_FOUND",
            )

        dept_state = _DEPARTMENT_OPERATIONAL_STATE.setdefault(department_id, {})
        updated_fields: dict[str, Any] = {}

        if body.description is not None:
            dept.description = body.description
            updated_fields["description"] = body.description

        if body.contact_email is not None:
            dept_state["contact_email"] = body.contact_email
            updated_fields["contact_email"] = body.contact_email

        if body.retention_period_days is not None:
            dept_state["retention_period_days"] = body.retention_period_days
            updated_fields["retention_period_days"] = body.retention_period_days

        if body.max_active_cases_per_investigator is not None:
            dept_state["max_active_cases_per_investigator"] = (
                body.max_active_cases_per_investigator
            )
            updated_fields["max_active_cases_per_investigator"] = (
                body.max_active_cases_per_investigator
            )

        if body.require_two_party_case_closure is not None:
            dept_state["require_two_party_case_closure"] = body.require_two_party_case_closure
            updated_fields["require_two_party_case_closure"] = (
                body.require_two_party_case_closure
            )

        await self.session.flush()

        await self.audit_service.record_security_event(
            action="department:update",
            actor_id=principal.user_id,
            actor_role=principal.role_code,
            department_id=department_id,
            target_type="department",
            target_id=str(department_id),
            outcome="success",
            details={"updated_fields": updated_fields},
            fail_closed=True,
        )

        return await self.get_department_settings(department_id, principal)

    async def list_admin_departments(
        self,
        principal: AuthenticatedPrincipal,
    ) -> list[DepartmentListItem]:
        """List departments with metadata for administrative overview (Super Admin only)."""
        if not has_permission(principal.role_code, Permission.DEPARTMENT_READ_GLOBAL):
            raise PermissionDeniedError(
                "Super Admin privileges required to inspect global departments list.",
                code="PERMISSION_DENIED",
            )

        items, _ = await self.dept_repo.list_paginated(limit=100, offset=0)
        return [
            DepartmentListItem(
                id=d.id,
                code=d.code,
                name=d.name,
                description=d.description,
                is_active=d.is_active,
                created_at=d.created_at,
            )
            for d in items
        ]
