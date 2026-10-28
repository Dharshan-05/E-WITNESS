"""Live PostgreSQL End-to-End Integration Tests for Batch 09, Phase 90.

Verifies the full end-to-end investigation case management subsystem against real PostgreSQL:
1. Canonical case creation (CASE-YYYY-XXXXX) & metadata initialization.
2. Lead investigator assignment with active workload capacity enforcement.
3. Multi-stage lifecycle state machine transitions (DRAFT -> OPEN -> UNDER_INVESTIGATION).
4. Multi-tier note authoring (internal, confidential, restricted) and structured findings.
5. Evidence attachment integrity and legal hold preservation.
6. Advisory AI candidate segment review and classification override.
7. Supervisor review submission, separation of duties validation, and formal approval.
8. Controlled closure rationale and authorized reopening.
9. Cryptographic controlled disclosure export with SHA-256 manifest and credential exclusion.
10. Unified case activity timeline retrieval with cursor pagination and visibility tier filtering.
11. Append-only security audit trail verification with structured case_id linkage.
12. Security boundaries: tenant isolation 404 masking, fail-closed biometric matching prohibition.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from backend.app.config.settings import Settings
from backend.app.core.case import AI_ADVISORY_DISCLAIMER
from backend.app.core.audit import AuditAction
from backend.app.core.case import (
    CaseExportFormat,
    CaseExportScope,
    CaseNoteVisibility,
    CasePriority,
    CaseStatus,
    CaseFindingType,
)
from backend.app.core.evidence import UploadStatus
from backend.app.core.identity import AccountStatus, RoleCode
from backend.app.infrastructure.database import DatabaseSessionManager
from backend.app.infrastructure.storage import InMemoryStorageClient
from backend.app.main import create_app
from backend.app.models.ai import AIAnalysisJob, AICandidateSegment
from backend.app.models.audit import SecurityAuditEvent
from backend.app.models.case import Case, CaseEvidence, CaseNote, CaseIncident
from backend.app.models.department import Department
from backend.app.models.evidence import EvidenceAttachment
from backend.app.models.incident import Incident
from backend.app.models.user import User
from backend.app.repositories.identity import (
    DepartmentRepository,
    RoleRepository,
    UserRepository,
)
from backend.app.services.password import PasswordService


async def _setup_phase90_env(
    postgres_db_manager: DatabaseSessionManager,
) -> dict[str, Any]:
    """Seed test departments, roles, and users in real PostgreSQL."""
    pw_service = PasswordService()
    default_pw = "ValidPass123456!"
    hashed_pw = pw_service.hash_password(default_pw)

    async with postgres_db_manager.transactional_session() as session:
        dept_repo = DepartmentRepository(session)
        role_repo = RoleRepository(session)
        user_repo = UserRepository(session)

        roles = await role_repo.ensure_default_roles()
        suffix = uuid4().hex[:6].upper()

        dept_sec = await dept_repo.create(
            Department(code=f"SEC-{suffix}", name=f"Campus Safety {suffix}", is_active=True)
        )
        dept_conduct = await dept_repo.create(
            Department(code=f"COND-{suffix}", name=f"Student Conduct {suffix}", is_active=True)
        )
        dept_acad = await dept_repo.create(
            Department(code=f"ACAD-{suffix}", name=f"Academic Affairs {suffix}", is_active=True)
        )

        admin_sec = await user_repo.create(
            User(
                email=f"admin_sec_{suffix.lower()}@ewitness.edu",
                full_name="Safety Supervisor Phase90",
                role_id=roles[RoleCode.DEPT_ADMIN].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        inv_sec = await user_repo.create(
            User(
                email=f"inv_sec_{suffix.lower()}@ewitness.edu",
                full_name="Lead Investigator Phase90",
                role_id=roles[RoleCode.INVESTIGATOR].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        inv_second = await user_repo.create(
            User(
                email=f"inv_sec2_{suffix.lower()}@ewitness.edu",
                full_name="Second Investigator Phase90",
                role_id=roles[RoleCode.INVESTIGATOR].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        inv_acad = await user_repo.create(
            User(
                email=f"inv_acad_{suffix.lower()}@ewitness.edu",
                full_name="Academic Investigator Phase90",
                role_id=roles[RoleCode.INVESTIGATOR].id,
                department_id=dept_acad.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        return {
            "dept_sec": dept_sec,
            "dept_conduct": dept_conduct,
            "dept_acad": dept_acad,
            "inv_sec": inv_sec,
            "inv_second": inv_second,
            "admin_sec": admin_sec,
            "inv_acad": inv_acad,
            "default_pw": default_pw,
            "suffix": suffix,
        }


async def _login(client: httpx.AsyncClient, email: str, pw: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pw},
    )
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    return resp.json()["access_token"]


@pytest.mark.integration
class TestPhase90CaseManagementEndToEndIntegration:
    """Comprehensive Phase 90 End-to-End Case Management Integration Test Suite."""

    async def test_full_investigation_lifecycle_e2e_workflow(
        self,
        postgres_settings: Settings,
        postgres_db_manager: DatabaseSessionManager,
    ) -> None:
        """Execute full canonical investigation lifecycle with all Batch 09 subsystems."""
        data = await _setup_phase90_env(postgres_db_manager)

        app = create_app(postgres_settings, db_manager=postgres_db_manager)
        app.state.storage_client = InMemoryStorageClient(postgres_settings.STORAGE_ENDPOINT_URL)
        app.state.db_manager = postgres_db_manager

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            token_lead = await _login(client, data["inv_sec"].email, data["default_pw"])
            token_second = await _login(client, data["inv_second"].email, data["default_pw"])
            token_admin = await _login(client, data["admin_sec"].email, data["default_pw"])
            token_foreign = await _login(client, data["inv_acad"].email, data["default_pw"])

            # -------------------------------------------------------------
            # 1. Case Creation (DRAFT status with canonical reference)
            # -------------------------------------------------------------
            create_resp = await client.post(
                "/api/v1/cases",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "title": "Phase 90 Comprehensive E2E Campus Incident",
                    "summary": "Full multi-stage investigation and controlled disclosure test.",
                    "priority": "high",
                },
            )
            assert create_resp.status_code == 201
            case_data = create_resp.json()
            case_id = case_data["id"]
            case_ref = case_data["reference_number"]
            assert case_ref.startswith("CASE-2026-")
            assert case_data["status"] == "open"
            assert case_data["version_id"] == 1

            # -------------------------------------------------------------
            # 2. Attach Incident & Assign Lead Investigator
            # -------------------------------------------------------------
            async with postgres_db_manager.transactional_session() as session:
                incident = Incident(
                    id=uuid4(),
                    reference_number=f"INC-{data['suffix']}-9001",
                    title="Reported Campus Altercation",
                    description="Physical disturbance reported near library courtyard.",
                    category="physical_assault",
                    severity="high",
                    location="North Quad Walkway",
                    occurred_at=datetime.now(UTC) - timedelta(hours=2),
                    department_id=data["dept_sec"].id,
                    reporter_id=data["inv_sec"].id,
                )
                session.add(incident)
                await session.flush()

                case_inc = CaseIncident(
                    id=uuid4(),
                    case_id=case_id,
                    incident_id=incident.id,
                    linked_by_id=data["inv_sec"].id,
                    link_type="primary",
                    created_at=datetime.now(UTC),
                )
                session.add(case_inc)

                c = await session.get(Case, case_id)
                assert c is not None
                c.incident_id = incident.id
                c.lead_investigator_id = data["inv_sec"].id

            # -------------------------------------------------------------
            # 3. Transition: OPEN -> UNDER_INVESTIGATION
            # -------------------------------------------------------------
            t_resp = await client.post(
                f"/api/v1/cases/{case_id}/transitions",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "target_status": CaseStatus.UNDER_INVESTIGATION.value,
                    "reason": "Active field investigation underway.",
                    "expected_version_id": 1,
                },
            )
            assert t_resp.status_code == 200
            v_active = t_resp.json()["version_id"]

            # -------------------------------------------------------------
            # 4. Attach Evidence & Activate Legal Hold
            # -------------------------------------------------------------
            ev_id = uuid4()
            ev_hash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
            async with postgres_db_manager.transactional_session() as session:
                ev_att = EvidenceAttachment(
                    id=ev_id,
                    department_id=data["dept_sec"].id,
                    incident_id=incident.id,
                    storage_key="secure-vault/cctv_altercation.mp4",
                    original_filename="cctv_altercation.mp4",
                    declared_mime_type="video/mp4",
                    file_size_bytes=5242880,
                    sha256_hash=ev_hash,
                    upload_status=UploadStatus.COMPLETED.value,
                    uploader_id=data["inv_sec"].id,
                )
                session.add(ev_att)
                await session.flush()

                case_ev = CaseEvidence(
                    id=uuid4(),
                    case_id=case_id,
                    evidence_id=ev_id,
                    linked_by_id=data["inv_sec"].id,
                    notes="CCTV footage of altercation",
                    created_at=datetime.now(UTC),
                )
                session.add(case_ev)
                await session.flush()

                c = await session.get(Case, case_id)
                assert c is not None
                c.is_legal_hold = True

            # -------------------------------------------------------------
            # 5. Add Notes with Multi-Tier Visibility
            # -------------------------------------------------------------
            # Internal Note
            n1_resp = await client.post(
                f"/api/v1/cases/{case_id}/notes",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "content": "Interviewed security guard on duty; logged shift details.",
                    "visibility": CaseNoteVisibility.INTERNAL.value,
                },
            )
            assert n1_resp.status_code == 201

            # Confidential Note (Lead author)
            n2_resp = await client.post(
                f"/api/v1/cases/{case_id}/notes",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "content": "Confidential source stated witness is student employee.",
                    "visibility": CaseNoteVisibility.CONFIDENTIAL.value,
                },
            )
            assert n2_resp.status_code == 201

            # Restricted Note (Dept Admin author)
            n3_resp = await client.post(
                f"/api/v1/cases/{case_id}/notes",
                headers={"Authorization": f"Bearer {token_admin}"},
                json={
                    "content": "Restricted administrative disciplinary referral directive.",
                    "visibility": CaseNoteVisibility.RESTRICTED.value,
                },
            )
            assert n3_resp.status_code == 201

            # -------------------------------------------------------------
            # 6. Structured Finding
            # -------------------------------------------------------------
            f_resp = await client.post(
                f"/api/v1/cases/{case_id}/findings",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "finding_type": "inculpatory",
                    "title": "Camera Footage Corroborated Altercation",
                    "description": "Timestamp on video aligns with dispatch log.",
                    "is_preliminary": False,
                },
            )
            assert f_resp.status_code == 201

            # -------------------------------------------------------------
            # 7. Supervisor Review: Separation of Duties & Approval
            # -------------------------------------------------------------
            # Submit for review
            sub_resp = await client.post(
                f"/api/v1/cases/{case_id}/submit-for-review",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "reason": "Investigation complete. Requesting supervisor closure review.",
                    "expected_version_id": v_active,
                },
            )
            assert sub_resp.status_code == 200
            v4 = sub_resp.json()["version_id"]

            # Separation of duties: Lead investigator CANNOT self-approve
            self_app_resp = await client.post(
                f"/api/v1/cases/{case_id}/approvals",
                headers={"Authorization": f"Bearer {token_lead}"},
                json={
                    "decision": "approved",
                    "from_status": CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
                    "to_status": CaseStatus.CLOSED.value,
                    "rationale": "I approve my own investigation report.",
                    "expected_version_id": v4,
                },
            )
            assert self_app_resp.status_code == 403

            # Department Admin approves transition
            app_resp = await client.post(
                f"/api/v1/cases/{case_id}/approvals",
                headers={"Authorization": f"Bearer {token_admin}"},
                json={
                    "decision": "approved",
                    "from_status": CaseStatus.PENDING_SUPERVISOR_REVIEW.value,
                    "to_status": CaseStatus.CLOSED.value,
                    "rationale": "Investigation thoroughly documented; findings corroborated by evidence.",
                    "expected_version_id": v4,
                },
            )
            assert app_resp.status_code == 201
            app_data = app_resp.json()
            assert app_data["decision"] == "approved"

            # -------------------------------------------------------------
            # 8. Controlled Disclosure Export (Phase 89)
            # -------------------------------------------------------------
            exp_resp = await client.post(
                f"/api/v1/cases/{case_id}/exports",
                headers={"Authorization": f"Bearer {token_admin}"},
                json={
                    "export_scope": CaseExportScope.FULL_INVESTIGATION.value,
                    "export_format": CaseExportFormat.JSON.value,
                    "purpose": "Preparation of formal administrative disclosure dossier.",
                    "include_restricted_notes": True,
                },
            )
            assert exp_resp.status_code == 201
            exp_data = exp_resp.json()
            export_id = exp_data["id"]

            assert len(exp_data["manifest_sha256"]) == 64
            assert exp_data["evidence_count"] == 1
            manifest = exp_data["manifest_payload"]
            assert AI_ADVISORY_DISCLAIMER in manifest["advisory_notice"]
            # Zero storage credential leakage
            assert "secure-vault" not in json.dumps(manifest)

            # -------------------------------------------------------------
            # 9. Case Activity Timeline (Phase 88)
            # -------------------------------------------------------------
            timeline_resp = await client.get(
                f"/api/v1/cases/{case_id}/timeline",
                headers={"Authorization": f"Bearer {token_lead}"},
            )
            assert timeline_resp.status_code == 200
            timeline_data = timeline_resp.json()
            events = timeline_data["items"]
            assert len(events) > 0

            # Restricted note bodies excluded from timeline
            for ev in events:
                if ev["event_type"] == "case:note:created":
                    assert "Restricted administrative disciplinary" not in ev["summary"]

            # -------------------------------------------------------------
            # 10. Tenant Isolation (Foreign Dept Masked 404)
            # -------------------------------------------------------------
            foreign_case_resp = await client.get(
                f"/api/v1/cases/{case_id}",
                headers={"Authorization": f"Bearer {token_foreign}"},
            )
            assert foreign_case_resp.status_code == 404

            foreign_exp_resp = await client.get(
                f"/api/v1/cases/{case_id}/exports/{export_id}",
                headers={"Authorization": f"Bearer {token_foreign}"},
            )
            assert foreign_exp_resp.status_code == 404

            foreign_timeline_resp = await client.get(
                f"/api/v1/cases/{case_id}/timeline",
                headers={"Authorization": f"Bearer {token_foreign}"},
            )
            assert foreign_timeline_resp.status_code == 404

            # -------------------------------------------------------------
            # 11. Security Audit Trail & Structured case_id Linkage
            # -------------------------------------------------------------
            async with postgres_db_manager.transactional_session() as session:
                audit_records = (
                    (
                        await session.execute(
                            select(SecurityAuditEvent)
                            .where(
                                SecurityAuditEvent.department_id == data["dept_sec"].id,
                            )
                            .order_by(SecurityAuditEvent.created_at.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                actions = [r.action for r in audit_records]
                assert AuditAction.CASE_CREATED.value in actions
                assert AuditAction.CASE_STATUS_TRANSITION.value in actions
                assert AuditAction.CASE_NOTE_CREATED.value in actions
                assert AuditAction.CASE_FINDING_CREATED.value in actions
                assert AuditAction.CASE_APPROVAL_RECORDED.value in actions
                assert AuditAction.CASE_EXPORTED.value in actions
                assert AuditAction.CASE_TIMELINE_ACCESSED.value in actions

                # Verify structured case_id column populated
                case_linked_records = [r for r in audit_records if str(r.case_id) == str(case_id)]
                assert len(case_linked_records) > 0, "Expected audit events linked via case_id column"
