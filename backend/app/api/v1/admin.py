"""Administration and System Settings API endpoints (Phase 118).

Provides:
- GET /admin/settings/system: Retrieve system settings with secrets redacted (Super Admin only).
- PATCH /admin/settings/system: Update operational system settings (Super Admin only).
- GET /admin/settings/department: Retrieve caller's assigned department settings.
- GET /admin/settings/department/{department_id}: Retrieve department settings by ID.
- PATCH /admin/settings/department/{department_id}: Update department settings.
- GET /admin/departments: List departments for administrative oversight (Super Admin only).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import (
    AdminServiceDep,
    CurrentUserDep,
    require_any_permission,
    require_permission,
)
from backend.app.core.authorization import Permission
from backend.app.core.exceptions import PermissionDeniedError
from backend.app.schemas.admin import (
    DepartmentListItem,
    DepartmentSettingsRead,
    DepartmentSettingsUpdate,
    SystemSettingsRead,
    SystemSettingsUpdate,
)
from backend.app.schemas.auth import AuthenticatedPrincipal

router = APIRouter(prefix="/admin", tags=["Administration & Settings"])
v1_admin_router = router


@router.get(
    "/settings/system",
    response_model=SystemSettingsRead,
    summary="Get system operational settings",
    description="Retrieve sanitized system configuration and operational state (Super Admin only) (Phase 118).",
)
async def get_system_settings(
    admin_service: AdminServiceDep,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.SYSTEM_CONFIG_MANAGE)),
    ],
) -> SystemSettingsRead:
    return await admin_service.get_system_settings(principal)


@router.patch(
    "/settings/system",
    response_model=SystemSettingsRead,
    summary="Update system operational settings",
    description="Update operational system settings (maintenance mode, announcement) with audit logging (Super Admin only) (Phase 118).",
)
async def update_system_settings(
    body: SystemSettingsUpdate,
    admin_service: AdminServiceDep,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.SYSTEM_CONFIG_MANAGE)),
    ],
) -> SystemSettingsRead:
    return await admin_service.update_system_settings(body, principal)


@router.get(
    "/settings/department",
    response_model=DepartmentSettingsRead,
    summary="Get current user department settings",
    description="Retrieve department settings for the caller's assigned department (Phase 118).",
)
async def get_current_user_department_settings(
    admin_service: AdminServiceDep,
    principal: CurrentUserDep,
) -> DepartmentSettingsRead:
    if principal.department_id is None:
        raise PermissionDeniedError(
            "User is not assigned to an institutional department.",
            code="NO_DEPARTMENT_ASSIGNED",
        )
    return await admin_service.get_department_settings(principal.department_id, principal)


@router.get(
    "/settings/department/{department_id}",
    response_model=DepartmentSettingsRead,
    summary="Get department settings by ID",
    description="Retrieve department settings for authorized department administrator or Super Admin (Phase 118).",
)
async def get_department_settings_by_id(
    department_id: UUID,
    admin_service: AdminServiceDep,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_any_permission(
                Permission.DEPARTMENT_READ_OWN,
                Permission.DEPARTMENT_READ_GLOBAL,
            )
        ),
    ],
) -> DepartmentSettingsRead:
    return await admin_service.get_department_settings(department_id, principal)


@router.patch(
    "/settings/department/{department_id}",
    response_model=DepartmentSettingsRead,
    summary="Update department settings",
    description="Update department settings with audit trail (Dept Admin for own dept, Super Admin for any) (Phase 118).",
)
async def update_department_settings(
    department_id: UUID,
    body: DepartmentSettingsUpdate,
    admin_service: AdminServiceDep,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_any_permission(
                Permission.DEPARTMENT_READ_OWN,
                Permission.DEPARTMENT_UPDATE_GLOBAL,
            )
        ),
    ],
) -> DepartmentSettingsRead:
    return await admin_service.update_department_settings(department_id, body, principal)


@router.get(
    "/departments",
    response_model=list[DepartmentListItem],
    summary="List departments for admin console",
    description="List all departments with operational metadata (Super Admin only) (Phase 118).",
)
async def list_admin_departments(
    admin_service: AdminServiceDep,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DEPARTMENT_READ_GLOBAL)),
    ],
) -> list[DepartmentListItem]:
    return await admin_service.list_admin_departments(principal)
