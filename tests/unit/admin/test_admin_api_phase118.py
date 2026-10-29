"""Unit tests for Phase 118: Administration and System Settings API, scoping, and security boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.dependencies import get_admin_service, get_current_principal
from backend.app.config.settings import Settings
from backend.app.core.authorization import RoleCode
from backend.app.main import create_app
from backend.app.models.department import Department
from backend.app.repositories.audit import AuditRepository
from backend.app.repositories.identity import DepartmentRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.services.admin import AdminService
from backend.app.services.audit import AuditService


def _get_test_settings() -> Settings:
    return Settings(
        ENVIRONMENT="testing",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
        STORAGE_BUCKET_NAME="test-bucket",
        STORAGE_ACCESS_KEY="test_access_key_valid",
        STORAGE_SECRET_KEY="test_secret_key_valid",
        AUTH_SECRET_KEY="test_key_with_length_greater_than_32_characters",
        AI_API_KEY="test",
        BIOMETRIC_ANALYSIS_ENABLED=True,
        BIOMETRIC_DETECTION_ENABLED=True,
        BIOMETRIC_MATCHING_ENABLED=False,
    )


def _make_principal(
    role_code: str,
    department_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid4(),
        role_code=role_code,
        department_id=department_id,
        email=f"{role_code.lower()}@institution.edu",
        full_name="Test Operator",
        account_status="active",
        is_active=True,
        session_id=uuid4(),
    )


def _make_sample_dept(dept_id: UUID, code: str, name: str) -> Department:
    return Department(
        id=dept_id,
        code=code,
        name=name,
        description="Department for test",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_system_settings_super_admin_only_and_secrets_redaction() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    mock_audit_repo = AsyncMock(spec=AuditRepository)
    mock_audit_service = AuditService(
        audit_repo=mock_audit_repo,
        incident_repo=AsyncMock(),
        evidence_repo=AsyncMock(),
        settings=settings,
    )
    mock_dept_repo = AsyncMock(spec=DepartmentRepository)

    admin_service = AdminService(
        session=AsyncMock(),
        dept_repo=mock_dept_repo,
        audit_service=mock_audit_service,
        settings=settings,
    )

    app.dependency_overrides[get_admin_service] = lambda: admin_service

    transport = ASGITransport(app=app)

    # 1. Dept Admin attempts to access system settings -> 403 Forbidden
    dept_admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=uuid4())
    app.dependency_overrides[get_current_principal] = lambda: dept_admin

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/admin/settings/system")
        assert resp.status_code == 403

        # 2. Super Admin accesses system settings -> 200 OK with sanitized settings
        super_admin = _make_principal(RoleCode.SUPER_ADMIN.value)
        app.dependency_overrides[get_current_principal] = lambda: super_admin

        resp_super = await client.get("/api/v1/admin/settings/system")
        assert resp_super.status_code == 200
        data = resp_super.json()
        assert data["environment"] == "testing"
        assert data["biometric_matching_enabled"] is False
        assert "AUTH_SECRET_KEY" not in data
        assert "STORAGE_SECRET_KEY" not in data
        assert "DATABASE_URL" not in data
        assert data["database_status"] == "configured_redacted"

        # 3. Super Admin updates maintenance mode & announcement
        patch_resp = await client.patch(
            "/api/v1/admin/settings/system",
            json={"maintenance_mode": True, "system_announcement": "Scheduled maintenance tonight"},
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["maintenance_mode"] is True
        assert patched["system_announcement"] == "Scheduled maintenance tonight"

        # Verify audit record was created for system config manage
        mock_audit_repo.append_event.assert_awaited()
        _, audit_kwargs = mock_audit_repo.append_event.call_args
        assert audit_kwargs["action"] == "system:config:manage"


@pytest.mark.asyncio
async def test_department_settings_tenant_isolation_and_validation() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    dept_a_id = uuid4()
    dept_b_id = uuid4()
    dept_a = _make_sample_dept(dept_a_id, "CAMPUS_POLICE", "Campus Police Dept")
    dept_b = _make_sample_dept(dept_b_id, "STUDENT_AFFAIRS", "Student Affairs")

    mock_audit_repo = AsyncMock(spec=AuditRepository)
    mock_audit_service = AuditService(
        audit_repo=mock_audit_repo,
        incident_repo=AsyncMock(),
        evidence_repo=AsyncMock(),
        settings=settings,
    )
    mock_dept_repo = AsyncMock(spec=DepartmentRepository)

    async def mock_get_by_id(did: UUID) -> Department | None:
        if did == dept_a_id:
            return dept_a
        if did == dept_b_id:
            return dept_b
        return None

    mock_dept_repo.get_by_id.side_effect = mock_get_by_id

    admin_service = AdminService(
        session=AsyncMock(),
        dept_repo=mock_dept_repo,
        audit_service=mock_audit_service,
        settings=settings,
    )
    app.dependency_overrides[get_admin_service] = lambda: admin_service

    transport = ASGITransport(app=app)

    # 1. Dept Admin for Dept A inspects their own department settings
    dept_a_admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_a_id)
    app.dependency_overrides[get_current_principal] = lambda: dept_a_admin

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/admin/settings/department")
        assert resp.status_code == 200
        assert resp.json()["department_id"] == str(dept_a_id)
        assert resp.json()["code"] == "CAMPUS_POLICE"

        # 2. Dept Admin for Dept A attempts to update Dept B settings -> 403 Forbidden
        patch_b_resp = await client.patch(
            f"/api/v1/admin/settings/department/{dept_b_id}",
            json={"contact_email": "attacker@dept-b.edu"},
        )
        assert patch_b_resp.status_code == 403

        # 3. Dept Admin for Dept A updates own department settings
        patch_a_resp = await client.patch(
            f"/api/v1/admin/settings/department/{dept_a_id}",
            json={
                "contact_email": "chief@campus-police.edu",
                "retention_period_days": 180,
                "max_active_cases_per_investigator": 15,
                "require_two_party_case_closure": True,
            },
        )
        assert patch_a_resp.status_code == 200
        patched_data = patch_a_resp.json()
        assert patched_data["contact_email"] == "chief@campus-police.edu"
        assert patched_data["retention_period_days"] == 180
        assert patched_data["max_active_cases_per_investigator"] == 15

        # 4. Input bounds validation: invalid retention period (< 30 days) yields 422
        invalid_resp = await client.patch(
            f"/api/v1/admin/settings/department/{dept_a_id}",
            json={"retention_period_days": 5},
        )
        assert invalid_resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_departments_list_super_admin_only() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    mock_dept_repo = AsyncMock(spec=DepartmentRepository)
    dept1 = _make_sample_dept(uuid4(), "DEPT1", "Department One")
    dept2 = _make_sample_dept(uuid4(), "DEPT2", "Department Two")
    mock_dept_repo.list_paginated.return_value = ([dept1, dept2], 2)

    admin_service = AdminService(
        session=AsyncMock(),
        dept_repo=mock_dept_repo,
        audit_service=AsyncMock(),
        settings=settings,
    )
    app.dependency_overrides[get_admin_service] = lambda: admin_service

    transport = ASGITransport(app=app)

    # 1. Dept Admin cannot access global list of departments -> 403
    dept_admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept1.id)
    app.dependency_overrides[get_current_principal] = lambda: dept_admin

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/admin/departments")
        assert resp.status_code == 403

        # 2. Super Admin can access -> 200 with list
        super_admin = _make_principal(RoleCode.SUPER_ADMIN.value)
        app.dependency_overrides[get_current_principal] = lambda: super_admin

        resp_super = await client.get("/api/v1/admin/departments")
        assert resp_super.status_code == 200
        items = resp_super.json()
        assert len(items) == 2
        assert items[0]["code"] == "DEPT1"
