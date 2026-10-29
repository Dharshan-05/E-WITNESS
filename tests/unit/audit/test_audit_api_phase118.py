"""Unit tests for Phase 118: Audit log search, event details with redaction, export, and verification."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.dependencies import get_audit_service, get_current_principal
from backend.app.config.settings import Settings
from backend.app.core.authorization import RoleCode
from backend.app.main import create_app
from backend.app.models.audit import SecurityAuditEvent
from backend.app.repositories.audit import AuditRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
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
        full_name="Test Admin",
        account_status="active",
        is_active=True,
        session_id=uuid4(),
    )


def _make_sample_event(
    *,
    event_id: UUID,
    seq: int,
    action: str,
    dept_id: UUID | None,
    actor_id: UUID | None,
    details: dict | None = None,
) -> SecurityAuditEvent:
    now = datetime.now(UTC)
    details_str = json.dumps(details or {"info": "test"})
    return SecurityAuditEvent(
        id=event_id,
        sequence_number=seq,
        action=action,
        actor_id=actor_id,
        actor_role="ROLE_INVESTIGATOR",
        actor_ip="127.0.0.1",
        actor_user_agent="pytest-client",
        department_id=dept_id,
        target_type="incident",
        target_id=str(uuid4()),
        outcome="success",
        details=details_str,
        previous_event_hash="prev_hash_123",
        event_hash=hashlib.sha256(b"event_hash").hexdigest(),
        created_at=now,
    )


@pytest.mark.asyncio
async def test_get_audit_event_detail_redaction_and_scoping() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    dept_a = uuid4()
    dept_b = uuid4()
    event_a_id = uuid4()
    event_b_id = uuid4()

    event_a = _make_sample_event(
        event_id=event_a_id,
        seq=1,
        action="auth:login:success",
        dept_id=dept_a,
        actor_id=uuid4(),
        details={"user_email": "alice@dept-a.edu", "secret_token": "super_secret_jwt_token_12345"},
    )
    event_b = _make_sample_event(
        event_id=event_b_id,
        seq=2,
        action="incident:submitted",
        dept_id=dept_b,
        actor_id=uuid4(),
        details={"case_title": "Dept B incident"},
    )

    mock_audit_repo = AsyncMock(spec=AuditRepository)

    async def mock_get_by_id(eid: UUID) -> SecurityAuditEvent | None:
        if eid == event_a_id:
            return event_a
        if eid == event_b_id:
            return event_b
        return None

    mock_audit_repo.get_by_id.side_effect = mock_get_by_id

    mock_service = AuditService(
        audit_repo=mock_audit_repo,
        incident_repo=AsyncMock(),
        evidence_repo=AsyncMock(),
        settings=settings,
    )

    # 1. Dept Admin for Dept A inspecting Event A (allowed, secrets redacted)
    current_user = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=dept_a)
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    app.dependency_overrides[get_current_principal] = lambda: current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/api/v1/audit/events/{event_a_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(event_a_id)
        assert data["details"]["user_email"] == "alice@dept-a.edu"
        # Secret token must be redacted
        assert data["details"]["secret_token"] == "***REDACTED***"

        # 2. Dept Admin for Dept A inspecting Event B from Dept B (must return 404 to prevent info leak)
        resp_b = await client.get(f"/api/v1/audit/events/{event_b_id}")
        assert resp_b.status_code == 404

        # 3. Super Admin inspecting Event B from Dept B (allowed)
        super_admin = _make_principal(RoleCode.SUPER_ADMIN.value, department_id=None)
        app.dependency_overrides[get_current_principal] = lambda: super_admin
        resp_super = await client.get(f"/api/v1/audit/events/{event_b_id}")
        assert resp_super.status_code == 200
        assert resp_super.json()["id"] == str(event_b_id)


@pytest.mark.asyncio
async def test_export_audit_events_json_and_csv_formula_injection() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    dept_id = uuid4()
    event_id = uuid4()
    # Event with potential CSV formula injection in action / target_id
    malicious_event = _make_sample_event(
        event_id=event_id,
        seq=1,
        action="=cmd|' /C calc'!A0",
        dept_id=dept_id,
        actor_id=uuid4(),
        details={"token": "raw_secret_value", "normal_key": "normal_val"},
    )

    mock_audit_repo = AsyncMock(spec=AuditRepository)
    mock_audit_repo.list_events_paginated.return_value = ([malicious_event], 1)
    mock_audit_repo.append_event.return_value = malicious_event

    mock_service = AuditService(
        audit_repo=mock_audit_repo,
        incident_repo=AsyncMock(),
        evidence_repo=AsyncMock(),
        settings=settings,
    )

    super_admin = _make_principal(RoleCode.SUPER_ADMIN.value)
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    app.dependency_overrides[get_current_principal] = lambda: super_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Test JSON Export
        resp_json = await client.post(
            "/api/v1/audit/events/export",
            json={"export_format": "json", "limit": 100},
        )
        assert resp_json.status_code == 200
        body_json = resp_json.json()
        assert body_json["export_format"] == "json"
        assert body_json["total_records"] == 1
        parsed_records = json.loads(body_json["content"])
        assert len(parsed_records) == 1
        # Secret in JSON must be redacted
        assert parsed_records[0]["details"]["token"] == "***REDACTED***"
        # SHA-256 digest verified
        expected_hash = hashlib.sha256(body_json["content"].encode("utf-8")).hexdigest()
        assert body_json["hash_digest"] == expected_hash

        # Test CSV Export with formula injection check
        resp_csv = await client.post(
            "/api/v1/audit/events/export",
            json={"export_format": "csv", "limit": 100},
        )
        assert resp_csv.status_code == 200
        body_csv = resp_csv.json()
        assert body_csv["export_format"] == "csv"
        # Check formula injection was sanitized with leading quote
        assert "'=cmd|' /C calc'!A0" in body_csv["content"]


@pytest.mark.asyncio
async def test_audit_verification_endpoint() -> None:
    settings = _get_test_settings()
    app = create_app(settings)

    mock_audit_repo = AsyncMock(spec=AuditRepository)
    mock_audit_repo.verify_chain.return_value = {
        "status": "verified",
        "chain_valid": True,
        "total_events_verified": 42,
        "first_sequence_number": 1,
        "last_sequence_number": 42,
        "tampered_event_ids": [],
        "tampered_sequence_numbers": [],
        "errors": [],
        "disclaimer": "Cryptographic hash chaining detects historical alteration...",
        "verified_at": datetime.now(UTC),
    }

    mock_service = AuditService(
        audit_repo=mock_audit_repo,
        incident_repo=AsyncMock(),
        evidence_repo=AsyncMock(),
        settings=settings,
    )

    dept_admin = _make_principal(RoleCode.DEPT_ADMIN.value, department_id=uuid4())
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    app.dependency_overrides[get_current_principal] = lambda: dept_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/audit/verify?limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "verified"
        assert data["chain_valid"] is True
        assert data["total_events_verified"] == 42
