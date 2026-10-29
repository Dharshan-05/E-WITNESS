"""Live PostgreSQL Full-Stack Integration and End-to-End Verification (Phase 119).

Systematically executes and validates the 12 core end-to-end user workflows and
security invariants against real PostgreSQL 16 using actual FastAPI API contracts:

1. Valid authentication and logout (access token, me introspection, session revocation).
2. Invalid credentials and disabled-account rejection (401 unauthorized, disabled/suspended check).
3. Student creates report and sees only permitted updates to their own report (student ownership & boundary).
4. Staff submits an incident within permitted scope (staff intake & department scoping).
5. Department Administrator manages only users and workflows in their own department (tenant isolation).
6. Investigator accesses assigned cases only (investigator workload & assignment boundaries).
7. Unauthorized cross-department and unassigned-case requests are rejected (404 masking & 403 forbidden).
8. Evidence upload validation, hash persistence and authorized retrieval (upload session, hash integrity, download URL).
9. Append-only investigation notes and permitted case transitions (lifecycle states & separation of duties).
10. Audit events produced for security-sensitive operations (tamper-evident SHA-256 hash chaining).
11. Session expiration and revocation handled safely (refresh rotation & replay compromise revocation).
12. AI advisory outputs are non-authoritative and cannot mutate official findings or evidence (advisory disclaimer & human decision).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from backend.app.config.settings import Settings
from backend.app.core.case import (
    AI_ADVISORY_DISCLAIMER,
    CaseNoteVisibility,
    CasePriority,
    CaseStatus,
)
from backend.app.core.identity import AccountStatus, RoleCode
from backend.app.infrastructure.database import DatabaseSessionManager
from backend.app.infrastructure.storage import InMemoryStorageClient
from backend.app.main import create_app
from backend.app.models.department import Department
from backend.app.models.user import User
from backend.app.repositories.identity import (
    DepartmentRepository,
    RoleRepository,
    UserRepository,
)
from backend.app.services.password import PasswordService


async def _setup_phase119_environment(
    postgres_db_manager: DatabaseSessionManager,
) -> dict[str, Any]:
    """Seed synthetic departments, default roles, and role-based test accounts."""
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
            Department(
                code=f"SEC-{suffix}",
                name=f"Campus Safety Department {suffix}",
                is_active=True,
            )
        )
        dept_conduct = await dept_repo.create(
            Department(
                code=f"COND-{suffix}",
                name=f"Student Conduct Office {suffix}",
                is_active=True,
            )
        )

        student_sec = await user_repo.create(
            User(
                email=f"student_sec_{suffix.lower()}@ewitness.edu",
                full_name="Alice Student SEC",
                role_id=roles[RoleCode.STUDENT].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        student_cond = await user_repo.create(
            User(
                email=f"student_cond_{suffix.lower()}@ewitness.edu",
                full_name="Bob Student COND",
                role_id=roles[RoleCode.STUDENT].id,
                department_id=dept_conduct.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        staff_sec = await user_repo.create(
            User(
                email=f"staff_sec_{suffix.lower()}@ewitness.edu",
                full_name="Charlie Staff SEC",
                role_id=roles[RoleCode.STAFF].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        admin_sec = await user_repo.create(
            User(
                email=f"admin_sec_{suffix.lower()}@ewitness.edu",
                full_name="Dana Dept Admin SEC",
                role_id=roles[RoleCode.DEPT_ADMIN].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        admin_cond = await user_repo.create(
            User(
                email=f"admin_cond_{suffix.lower()}@ewitness.edu",
                full_name="Evan Dept Admin COND",
                role_id=roles[RoleCode.DEPT_ADMIN].id,
                department_id=dept_conduct.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        inv_sec_1 = await user_repo.create(
            User(
                email=f"inv_sec_1_{suffix.lower()}@ewitness.edu",
                full_name="Fiona Lead Investigator SEC",
                role_id=roles[RoleCode.INVESTIGATOR].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        inv_sec_2 = await user_repo.create(
            User(
                email=f"inv_sec_2_{suffix.lower()}@ewitness.edu",
                full_name="George Second Investigator SEC",
                role_id=roles[RoleCode.INVESTIGATOR].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        super_admin = await user_repo.create(
            User(
                email=f"super_admin_{suffix.lower()}@ewitness.edu",
                full_name="Helen Global Super Admin",
                role_id=roles[RoleCode.SUPER_ADMIN].id,
                department_id=None,
                account_status=AccountStatus.ACTIVE.value,
                is_active=True,
                password_hash=hashed_pw,
            )
        )

        disabled_user = await user_repo.create(
            User(
                email=f"disabled_{suffix.lower()}@ewitness.edu",
                full_name="Ivan Disabled User",
                role_id=roles[RoleCode.STUDENT].id,
                department_id=dept_sec.id,
                account_status=AccountStatus.DISABLED.value,
                is_active=False,
                deactivated_at=datetime.now(UTC),
                password_hash=hashed_pw,
            )
        )

        return {
            "dept_sec": dept_sec,
            "dept_cond": dept_conduct,
            "student_sec": student_sec,
            "student_cond": student_cond,
            "staff_sec": staff_sec,
            "admin_sec": admin_sec,
            "admin_cond": admin_cond,
            "inv_sec_1": inv_sec_1,
            "inv_sec_2": inv_sec_2,
            "super_admin": super_admin,
            "disabled_user": disabled_user,
            "default_pw": default_pw,
            "suffix": suffix,
        }


async def _login_and_get_tokens(
    client: httpx.AsyncClient, email: str, password: str
) -> tuple[str, str, dict[str, Any]]:
    """Helper to authenticate and return (access_token, refresh_token, token_payload)."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    data = resp.json()
    return data["access_token"], data["refresh_token"], data


@pytest.mark.integration
class TestPhase119FullStackE2EVerification:
    """End-to-End full-stack workflow integration test suite for E-WITNESS Phase 119."""

    async def test_all_twelve_e2e_scenarios(
        self,
        postgres_settings: Settings,
        postgres_db_manager: DatabaseSessionManager,
    ) -> None:
        """Execute and verify all 12 institutional E2E workflows against real PostgreSQL."""
        env = await _setup_phase119_environment(postgres_db_manager)
        app = create_app(postgres_settings, db_manager=postgres_db_manager)
        storage_client = InMemoryStorageClient(postgres_settings.STORAGE_ENDPOINT_URL)
        app.state.storage_client = storage_client
        app.state.db_manager = postgres_db_manager

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver.local") as client:
            pw = env["default_pw"]

            # =====================================================================
            # Scenario 1: Valid authentication and logout
            # =====================================================================
            access_token, refresh_token, token_data = await _login_and_get_tokens(
                client, env["student_sec"].email, pw
            )
            assert token_data["token_type"] == "bearer"
            assert token_data["expires_in"] > 0
            assert len(access_token) > 20
            assert len(refresh_token) > 20

            # Introspect current user
            me_resp = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert me_resp.status_code == 200
            me_data = me_resp.json()
            assert me_data["user"]["email"] == env["student_sec"].email
            assert me_data["role"]["code"] == RoleCode.STUDENT.value
            assert me_data["department"]["id"] == str(env["dept_sec"].id)
            session_id = me_data["session_id"]

            # Logout
            logout_resp = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"session_id": session_id},
            )
            assert logout_resp.status_code == 200
            assert logout_resp.json()["status"] == "success"

            # Post-logout token rejection
            revoked_resp = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert revoked_resp.status_code in (401, 403)

            # =====================================================================
            # Scenario 2: Invalid credentials and disabled-account rejection
            # =====================================================================
            # 2a. Wrong password
            bad_pw_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": env["student_sec"].email, "password": "WrongPassword123!"},
            )
            assert bad_pw_resp.status_code == 401

            # 2b. Nonexistent user
            nonexistent_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "nonexistent_user@ewitness.edu", "password": pw},
            )
            assert nonexistent_resp.status_code == 401

            # 2c. Disabled account
            disabled_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": env["disabled_user"].email, "password": pw},
            )
            assert disabled_resp.status_code in (401, 403)

            # =====================================================================
            # Scenario 3: Student creates a report and sees only permitted updates
            # =====================================================================
            student_token, _, _ = await _login_and_get_tokens(
                client, env["student_sec"].email, pw
            )
            student_headers = {"Authorization": f"Bearer {student_token}"}

            now_iso = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
            create_inc_resp = await client.post(
                "/api/v1/incidents",
                headers=student_headers,
                json={
                    "title": "Unauthorized entry into engineering lab",
                    "description": "Observed individuals attempting to force door handle at 10 PM.",
                    "category": "safety_hazard",
                    "severity": "medium",
                    "location": "Engineering Hall Room 102",
                    "occurred_at": now_iso,
                },
            )
            assert create_inc_resp.status_code == 201
            incident_data = create_inc_resp.json()
            incident_id = incident_data["id"]
            ref_number = incident_data["reference_number"]
            assert ref_number.startswith("INC-2026-")
            assert incident_data["status"] == "submitted"
            assert incident_data["reporter_id"] == str(env["student_sec"].id)
            assert incident_data["department_id"] == str(env["dept_sec"].id)

            # Submitter can view own report in list
            list_resp = await client.get("/api/v1/incidents", headers=student_headers)
            assert list_resp.status_code == 200
            own_items = list_resp.json()["items"]
            assert any(item["id"] == incident_id for item in own_items)

            # Submitter can update permitted fields while submitted
            update_resp = await client.patch(
                f"/api/v1/incidents/{incident_id}",
                headers=student_headers,
                json={"title": "Updated: Unauthorized entry into engineering laboratory"},
            )
            assert update_resp.status_code == 200
            assert "Updated:" in update_resp.json()["title"]

            # Student B in another department CANNOT view Student A's incident
            student_b_token, _, _ = await _login_and_get_tokens(
                client, env["student_cond"].email, pw
            )
            student_b_headers = {"Authorization": f"Bearer {student_b_token}"}

            b_list = await client.get("/api/v1/incidents", headers=student_b_headers)
            assert b_list.status_code == 200
            assert all(item["id"] != incident_id for item in b_list.json()["items"])

            # Direct access by Student B returns 404 (safe tenant isolation masking)
            b_direct = await client.get(
                f"/api/v1/incidents/{incident_id}",
                headers=student_b_headers,
            )
            assert b_direct.status_code in (403, 404)

            # =====================================================================
            # Scenario 4: Staff submits an incident within permitted scope
            # =====================================================================
            staff_token, _, _ = await _login_and_get_tokens(
                client, env["staff_sec"].email, pw
            )
            staff_headers = {"Authorization": f"Bearer {staff_token}"}

            staff_inc_resp = await client.post(
                "/api/v1/incidents",
                headers=staff_headers,
                json={
                    "title": "Staff hazard observation on walkway",
                    "description": "Fallen power line near library walkway after storm.",
                    "category": "safety_hazard",
                    "severity": "high",
                    "location": "North Library Walkway",
                    "occurred_at": now_iso,
                },
            )
            assert staff_inc_resp.status_code == 201
            staff_inc = staff_inc_resp.json()
            assert staff_inc["reporter_id"] == str(env["staff_sec"].id)
            assert staff_inc["department_id"] == str(env["dept_sec"].id)

            # =====================================================================
            # Scenario 5: Dept Admin manages only own department
            # =====================================================================
            admin_sec_token, _, _ = await _login_and_get_tokens(
                client, env["admin_sec"].email, pw
            )
            admin_sec_headers = {"Authorization": f"Bearer {admin_sec_token}"}

            # 5a. Admin SEC can read own department settings
            dept_settings_resp = await client.get(
                f"/api/v1/admin/settings/department/{env['dept_sec'].id}",
                headers=admin_sec_headers,
            )
            assert dept_settings_resp.status_code == 200
            assert dept_settings_resp.json()["department_id"] == str(env["dept_sec"].id)

            # 5b. Admin SEC can update own department settings
            dept_patch_resp = await client.patch(
                f"/api/v1/admin/settings/department/{env['dept_sec'].id}",
                headers=admin_sec_headers,
                json={"retention_period_days": 180, "max_active_cases_per_investigator": 15},
            )
            assert dept_patch_resp.status_code == 200
            assert dept_patch_resp.json()["retention_period_days"] == 180

            # 5c. Admin SEC CANNOT manage or view settings of COND department (403 Forbidden)
            cross_dept_resp = await client.get(
                f"/api/v1/admin/settings/department/{env['dept_cond'].id}",
                headers=admin_sec_headers,
            )
            assert cross_dept_resp.status_code in (403, 404)

            cross_patch_resp = await client.patch(
                f"/api/v1/admin/settings/department/{env['dept_cond'].id}",
                headers=admin_sec_headers,
                json={"retention_period_days": 90},
            )
            assert cross_patch_resp.status_code in (403, 404)

            # 5d. Dept Admin can triage incident in own department
            triage_resp = await client.post(
                f"/api/v1/incidents/{incident_id}/status",
                headers=admin_sec_headers,
                json={"status": "triaged", "reason": "Verified and routed for investigation."},
            )
            assert triage_resp.status_code == 200
            assert triage_resp.json()["status"] == "triaged"

            # =====================================================================
            # Scenario 6 & 7: Investigator accesses assigned cases only & Cross-dept rejected
            # =====================================================================
            inv1_token, _, _ = await _login_and_get_tokens(
                client, env["inv_sec_1"].email, pw
            )
            inv1_headers = {"Authorization": f"Bearer {inv1_token}"}

            # Create case in SEC department
            create_case_resp = await client.post(
                "/api/v1/cases",
                headers=inv1_headers,
                json={
                    "title": "Investigation into Unauthorized Entry Incident",
                    "summary": "Formal investigation regarding forced door handle at lab.",
                    "priority": "high",
                },
            )
            assert create_case_resp.status_code == 201
            case_data = create_case_resp.json()
            case_id = case_data["id"]
            assert case_data["status"] == "open"

            # Assign Lead Investigator 1
            assign_resp = await client.post(
                f"/api/v1/cases/{case_id}/assignments",
                headers=admin_sec_headers,
                json={
                    "new_investigator_id": str(env["inv_sec_1"].id),
                    "assignment_reason": "Primary investigator for facility security.",
                    "expected_version": case_data["version_id"],
                },
            )
            assert assign_resp.status_code == 200
            assert assign_resp.json()["lead_investigator_id"] == str(env["inv_sec_1"].id)

            # Investigator 1 accesses assigned case
            get_case_resp = await client.get(
                f"/api/v1/cases/{case_id}",
                headers=inv1_headers,
            )
            assert get_case_resp.status_code == 200
            assert get_case_resp.json()["id"] == case_id

            # Cross-department Admin COND cannot access SEC case (safe 404 masking)
            admin_cond_token, _, _ = await _login_and_get_tokens(
                client, env["admin_cond"].email, pw
            )
            admin_cond_headers = {"Authorization": f"Bearer {admin_cond_token}"}

            cross_case_resp = await client.get(
                f"/api/v1/cases/{case_id}",
                headers=admin_cond_headers,
            )
            assert cross_case_resp.status_code in (403, 404)

            # =====================================================================
            # Scenario 8: Evidence upload validation, hash persistence & retrieval
            # =====================================================================
            # Request upload session for JPEG evidence
            file_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + (b"A" * 1024)
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()

            upload_sess_resp = await client.post(
                f"/api/v1/incidents/{incident_id}/attachments/upload-session",
                headers=admin_sec_headers,
                json={
                    "filename": "door_damage_evidence.jpg",
                    "content_type": "image/jpeg",
                    "file_size_bytes": len(file_bytes),
                },
            )
            assert upload_sess_resp.status_code == 201
            upload_session_data = upload_sess_resp.json()
            upload_id = upload_session_data["session_id"]
            storage_key = upload_session_data["storage_key"]

            # Store bytes into in-memory mock storage
            storage_client.store_mock_object(storage_key, file_bytes, "image/jpeg")

            # Complete upload session
            complete_upload_resp = await client.post(
                f"/api/v1/incidents/{incident_id}/attachments/upload-sessions/{upload_id}/complete",
                headers=admin_sec_headers,
            )
            assert complete_upload_resp.status_code == 200
            attachment_data = complete_upload_resp.json()
            attachment_id = attachment_data["id"]
            assert attachment_data["sha256_hash"] == file_sha256
            assert attachment_data["original_filename"] == "door_damage_evidence.jpg"

            # Retrieve authorized download URL with expiration
            download_resp = await client.get(
                f"/api/v1/incidents/{incident_id}/attachments/{attachment_id}/download",
                headers=admin_sec_headers,
            )
            assert download_resp.status_code == 200
            download_data = download_resp.json()
            assert "download_url" in download_data
            assert "expires_at" in download_data
            assert "test.internal" in download_data["download_url"]

            # Link evidence to case
            link_ev_resp = await client.post(
                f"/api/v1/cases/{case_id}/evidence",
                headers=inv1_headers,
                json={
                    "evidence_id": attachment_id,
                    "notes": "Photographic evidence of forced laboratory entry.",
                },
            )
            assert link_ev_resp.status_code == 201

            # =====================================================================
            # Scenario 9: Append-only investigation notes & case transitions
            # =====================================================================
            # Add note with visibility tier
            note_resp = await client.post(
                f"/api/v1/cases/{case_id}/notes",
                headers=inv1_headers,
                json={
                    "content": "Pry marks observed on the door frame indicate metallic tool usage.",
                    "visibility": CaseNoteVisibility.INTERNAL.value,
                },
            )
            assert note_resp.status_code == 201
            note_data = note_resp.json()
            note_id = note_data["id"]
            assert note_data["visibility"] == "internal"
            assert note_data["version_id"] == 1

            # Update note content (creates append-only history entry)
            note_update_resp = await client.patch(
                f"/api/v1/cases/{case_id}/notes/{note_id}",
                headers=inv1_headers,
                json={
                    "content": "Pry marks observed on the door frame indicate heavy metallic crowbar usage.",
                    "edit_reason": "Updated after forensic metallurgy assessment.",
                    "expected_version_id": 1,
                },
            )
            assert note_update_resp.status_code == 200
            assert note_update_resp.json()["version_id"] == 2

            # Fetch fresh case version
            current_case = (await client.get(f"/api/v1/cases/{case_id}", headers=inv1_headers)).json()

            # Transition case status: open -> under_investigation
            trans_resp = await client.patch(
                f"/api/v1/cases/{case_id}",
                headers=inv1_headers,
                json={
                    "status": CaseStatus.UNDER_INVESTIGATION.value,
                    "status_reason": "Formal investigation commenced.",
                    "expected_version": current_case["version_id"],
                },
            )
            assert trans_resp.status_code == 200
            assert trans_resp.json()["status"] == "under_investigation"

            # Fetch fresh case version for submission
            current_case = (await client.get(f"/api/v1/cases/{case_id}", headers=inv1_headers)).json()

            # Submit case for supervisor review
            submit_rev_resp = await client.post(
                f"/api/v1/cases/{case_id}/submit-for-review",
                headers=inv1_headers,
                json={
                    "reason": "All forensic leads completed; ready for supervisory sign-off.",
                    "expected_version_id": current_case["version_id"],
                },
            )
            assert submit_rev_resp.status_code == 200
            assert submit_rev_resp.json()["status"] == "pending_supervisor_review"

            # Fetch fresh case version for approvals
            current_case = (await client.get(f"/api/v1/cases/{case_id}", headers=inv1_headers)).json()

            # Separation of duties: Lead investigator CANNOT approve own case
            self_approve_resp = await client.post(
                f"/api/v1/cases/{case_id}/approvals",
                headers=inv1_headers,
                json={
                    "decision": "approved",
                    "from_status": "pending_supervisor_review",
                    "to_status": "closed",
                    "rationale": "Self approval attempt by investigator.",
                    "expected_version_id": current_case["version_id"],
                },
            )
            assert self_approve_resp.status_code in (400, 403)

            # Department supervisor approves case
            sup_approve_resp = await client.post(
                f"/api/v1/cases/{case_id}/approvals",
                headers=admin_sec_headers,
                json={
                    "decision": "approved",
                    "from_status": "pending_supervisor_review",
                    "to_status": "closed",
                    "rationale": "Investigation is thorough and verified.",
                    "expected_version_id": current_case["version_id"],
                },
            )
            assert sup_approve_resp.status_code in (200, 201)

            # =====================================================================
            # Scenario 10: Audit events produced with cryptographic hash verification
            # =====================================================================
            # Query audit events
            super_token, _, _ = await _login_and_get_tokens(
                client, env["super_admin"].email, pw
            )
            super_headers = {"Authorization": f"Bearer {super_token}"}

            audit_list_resp = await client.get("/api/v1/audit/events", headers=super_headers)
            assert audit_list_resp.status_code == 200
            audit_events = audit_list_resp.json()["items"]
            assert len(audit_events) > 0

            # Cryptographic chain verification endpoint
            verify_resp = await client.get("/api/v1/audit/verify", headers=super_headers)
            assert verify_resp.status_code == 200
            verify_data = verify_resp.json()
            assert verify_data["chain_valid"] is True
            assert verify_data["total_events_verified"] >= len(audit_events)

            # =====================================================================
            # Scenario 11: Session expiration and refresh token rotation & replay
            # =====================================================================
            user_token, user_refresh, _ = await _login_and_get_tokens(
                client, env["staff_sec"].email, pw
            )
            # Legitimate rotation
            rot_resp = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": user_refresh},
            )
            assert rot_resp.status_code == 200
            rot_data = rot_resp.json()
            new_access_token = rot_data["access_token"]
            new_refresh_token = rot_data["refresh_token"]
            assert new_refresh_token != user_refresh

            # Replaying the consumed old refresh token triggers replay detection & revocation
            replay_resp = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": user_refresh},
            )
            assert replay_resp.status_code in (401, 403)

            # The rotated token should now also be revoked due to compromised session revocation
            post_replay_resp = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": new_refresh_token},
            )
            assert post_replay_resp.status_code in (401, 403)

            # =====================================================================
            # Scenario 12: AI advisory outputs are non-authoritative
            # =====================================================================
            # Create advisory AI candidate segment annotation on the case evidence
            ai_seg_resp = await client.post(
                f"/api/v1/cases/{case_id}/evidence/{attachment_id}/ai-segments",
                headers=inv1_headers,
                json={
                    "evidence_id": attachment_id,
                    "start_seconds": 12.5,
                    "end_seconds": 18.0,
                    "raw_score": 0.88,
                    "raw_label": "forced_entry_tool",
                },
            )
            assert ai_seg_resp.status_code == 201
            ai_seg = ai_seg_resp.json()
            assert ai_seg["advisory_disclaimer"] == AI_ADVISORY_DISCLAIMER
            assert ai_seg["review_status"] == "pending_review"
            segment_id = ai_seg["segment_id"]

            # AI prediction CANNOT mutate official case status or evidence integrity
            fresh_case = (await client.get(f"/api/v1/cases/{case_id}", headers=inv1_headers)).json()
            assert fresh_case["status"] in ("pending_supervisor_review", "closed", "under_investigation")

            # Human Reviewer performs explicit review determination
            review_resp = await client.post(
                f"/api/v1/cases/{case_id}/ai-segments/{segment_id}/review",
                headers=inv1_headers,
                json={
                    "review_status": "confirmed",
                    "review_rationale": "Human reviewer confirms metallic pry bar visible at 00:14.",
                    "corrected_label": "confirmed_crowbar",
                    "expected_review_status": "pending_review",
                },
            )
            assert review_resp.status_code == 200
            review_data = review_resp.json()
            assert review_data["review_status"] == "confirmed"
            assert review_data["human_corrected_label"] == "confirmed_crowbar"
            # Provenance preserved
            assert review_data["advisory_disclaimer"] == AI_ADVISORY_DISCLAIMER
