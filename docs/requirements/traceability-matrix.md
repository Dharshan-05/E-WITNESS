# E-WITNESS — Requirements Traceability Matrix (RTM)

**Document ID:** `EW-DOC-REQ-003`  
**Phase:** Phase 120 — Final Security Audit, Acceptance and Handover  
**Version:** 2.0.0 (Final Release Baseline)  
**Status:** FULLY VERIFIED & ACCEPTED (🟢 GREEN)  

---

## 1. Overview and 120-Phase Verification Summary

This traceability matrix links every uniquely identified E-WITNESS requirement (`FR`, `NFR`, `SEC`, `EVI`, `AUD`) to its implementing modules, automated test suites, security implications, and final verification status across all 120 roadmap phases:
- **Batch 01 (Phases 01–10)**: Scaffolding, Requirements, Architecture, Environment, Config/Secrets, FastAPI Bootstrap, Layered Standards, Logging/Tracing, Testing Foundation, Foundation Audit.
- **Batch 02 (Phases 11–20)**: PostgreSQL Connectivity, SQLAlchemy Async Engine, Alembic Migrations, Core Identity Models, Normalization, Authentication, Token Lifecycle, Session Management, Account Security.
- **Batch 03 (Phases 21–30)**: Multi-Tenant RBAC/ABAC Guards, Department & Role Administration, API Conventions, Error Translation, Security Headers, CORS, Rate Limiting.
- **Batch 04 (Phases 31–40)**: Incident Intake, Anonymous/Witness Reporting, Department Triage Queues, Status Updates, Supplemental Submissions, Workflow State Machine.
- **Batch 05 (Phases 41–50)**: Digital Evidence Ingestion, Streaming Validation, SHA-256 Hashing, Multipart Chunking, S3 Storage Adapters, Quarantine Scanner, Storage Isolation.
- **Batch 06 (Phases 51–60)**: Case Dossiers, Case Linkage, Investigator Workspaces, Custody Event Ledger, Tamper-Evident History, Audit Export Logging.
- **Batch 07 (Phases 61–70)**: Append-Only Notes, Formal Findings, Case Dispositions, AI Job Queue, R3D-18 Violence Detection, Advisory Annotations.
- **Batch 08 (Phases 71–80)**: Biometric Privacy & Disabling Enforcements (`BIOMETRIC_MATCHING_ENABLED=False`), Legal Hold, Evidence Export Packages, Retention Lifecycle.
- **Batch 09 (Phases 81–90)**: Investigation Workspace, Break-Glass Controls, Human-in-the-Loop AI Review, Supervisory Overrides, Statutory AI Disclaimers.
- **Batch 10 (Phases 91–100)**: Cryptographic Audit Hash Chaining (Merkle SHA-256), Monotonic Sequence Numbers, Department Analytics, Operational Health Probes, Regression Gates.
- **Batch 11 (Phases 101–110)**: Backend Threat Model, Replay Defense, API Audit Matrix, Key Lifecycle, Upload Quarantine, Model Provenance Allowlist, Disaster Recovery, Container Hardening.
- **Batch 12 (Phases 111–120)**: React SPA UI (Auth, Triage, Uploads, Dossiers, AI Review, Dashboards, Audit/Admin), Deployment Hardening, Full-Stack E2E Integration, Final Security Acceptance.

---

## 2. Functional Requirements Traceability (`FR-001` – `FR-020`)

| Req ID | Title | Stakeholder(s) | Implementing Source Files | Automated Test Suite(s) | Verification Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `FR-001` | Role-Scoped User Authentication | All 5 Roles | `backend/app/api/v1/auth.py`, `backend/app/services/auth.py`, `backend/app/core/tokens.py`, `frontend/src/auth/AuthProvider.tsx` | `tests/unit/auth/`, `tests/integration/api/test_phase119_fullstack_e2e_verification.py`, `frontend/src/test/authApi.test.ts` | **VERIFIED (🟢 GREEN)** |
| `FR-002` | Tenant & Department Provisioning | Super Admin, Dept Admin | `backend/app/api/v1/departments.py`, `backend/app/services/department.py`, `backend/app/models/department.py` | `tests/unit/department/`, `tests/integration/api/test_departments.py`, `tests/unit/admin/test_admin_api_phase118.py` | **VERIFIED (🟢 GREEN)** |
| `FR-003` | Departmental User Management | Dept Admin, Staff, Investigator | `backend/app/api/v1/users.py`, `backend/app/services/user.py`, `backend/app/repositories/identity.py` | `tests/unit/identity/`, `tests/unit/security/test_batch11_group01_security_hardening.py` | **VERIFIED (🟢 GREEN)** |
| `FR-004` | Student Incident & Witness Reporting | Student | `backend/app/api/v1/incidents.py`, `backend/app/services/incident.py`, `frontend/src/components/incident/IncidentCreateForm.tsx` | `tests/unit/incident/`, `frontend/src/test/incidentsPage.test.tsx`, `tests/e2e/test_browser_e2e_playwright.py` | **VERIFIED (🟢 GREEN)** |
| `FR-005` | Staff Incident Recording & Reporting | Staff, Dept Admin | `backend/app/api/v1/incidents.py`, `backend/app/services/incident.py` | `tests/unit/incident/`, `tests/integration/api/test_phase119_fullstack_e2e_verification.py` | **VERIFIED (🟢 GREEN)** |
| `FR-006` | Permitted Case Status Tracking | Student, Staff | `backend/app/api/v1/incidents.py`, `backend/app/schemas/incident.py` (redacted response views) | `tests/unit/incident/test_incident_redaction.py`, `frontend/src/test/incidentList.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-007` | Supplemental Information Submission | Student, Staff, Investigator | `backend/app/api/v1/incidents.py` (`POST /{id}/supplemental`), `backend/app/models/incident.py` | `tests/unit/incident/test_supplemental.py`, `frontend/src/test/incidentDetail.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-008` | Department Workflow Configuration | Dept Admin | `backend/app/api/v1/admin.py`, `backend/app/models/department.py`, `frontend/src/pages/AdminPage.tsx` | `tests/unit/admin/test_admin_api_phase118.py`, `frontend/src/test/adminPage.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-009` | Case Triage & Investigator Assignment | Dept Admin, Investigator | `backend/app/api/v1/cases.py` (`POST /triage`), `backend/app/services/case.py` | `tests/unit/case/test_case_triage.py`, `tests/integration/api/test_phase119_fullstack_e2e_verification.py` | **VERIFIED (🟢 GREEN)** |
| `FR-010` | Assigned Case Workspace | Investigator | `backend/app/api/v1/cases.py`, `frontend/src/pages/CasesPage.tsx`, `frontend/src/components/case/` | `tests/unit/case/test_case_authorization.py`, `frontend/src/test/caseDossier.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-011` | Append-Only Investigation Notes | Investigator | `backend/app/api/v1/cases.py` (`POST /{id}/notes`), `backend/app/models/case.py` (`CaseNote`) | `tests/unit/case/test_case_notes_append_only.py`, `frontend/src/test/caseNotes.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-012` | Formal Case Findings & Disposition | Investigator, Dept Admin | `backend/app/api/v1/cases.py` (`POST /{id}/findings`, `POST /{id}/disposition`) | `tests/unit/case/test_case_disposition.py`, `frontend/src/test/caseFindings.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-013` | Controlled Digital Evidence Upload | Student, Staff, Investigator | `backend/app/api/v1/evidence.py`, `backend/app/infrastructure/storage.py`, `frontend/src/components/evidence/` | `tests/unit/evidence/test_upload_lifecycle.py`, `frontend/src/test/chunkedUpload.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-014` | Authorized Evidence Retrieval | Investigator, Student, Staff | `backend/app/api/v1/evidence.py` (`GET /{id}/download`), `backend/app/services/evidence.py` | `tests/unit/evidence/test_evidence_access.py`, `tests/integration/api/test_phase119_fullstack_e2e_verification.py` | **VERIFIED (🟢 GREEN)** |
| `FR-015` | Asynchronous AI Analysis Trigger | Investigator | `backend/app/api/v1/ai.py` (`POST /jobs`), `backend/app/services/ai_job.py`, `scripts/train_violence_model.py` | `tests/unit/ai/test_ai_job_service.py`, `tests/unit/ai/test_ml_pipeline_scripts.py` | **VERIFIED (🟢 GREEN)** |
| `FR-016` | Non-Authoritative AI Presentation | Investigator | `backend/app/models/ai.py`, `frontend/src/components/video/AIAnnotationOverlay.tsx` | `tests/unit/ai/test_ai_requirements.py`, `frontend/src/test/videoEvidenceReview.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-017` | Departmental Oversight Reporting | Dept Admin | `backend/app/api/v1/analytics.py`, `backend/app/services/analytics.py`, `frontend/src/pages/AnalyticsPage.tsx` | `tests/unit/analytics/test_analytics.py`, `frontend/src/test/analyticsDashboard.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `FR-018` | Platform Operational Administration | Super Admin | `backend/app/api/v1/admin.py`, `backend/app/services/admin.py`, `frontend/src/pages/AdminPage.tsx` | `tests/unit/admin/test_admin_api_phase118.py`, `frontend/src/test/adminApi.test.ts` | **VERIFIED (🟢 GREEN)** |
| `FR-019` | Centralized Validated Configuration | Super Admin (DevOps) | `backend/app/config/settings.py`, `backend/app/core/secrets.py` | `tests/unit/config/test_settings.py`, `tests/unit/config/test_redaction.py` | **VERIFIED (🟢 GREEN)** |
| `FR-020` | Scoped Search and Filtering | All 5 Roles | `backend/app/repositories/case.py`, `backend/app/repositories/incident.py`, `backend/app/repositories/audit.py` | `tests/unit/audit/test_audit_api_phase118.py`, `tests/integration/api/test_phase119_fullstack_e2e_verification.py` | **VERIFIED (🟢 GREEN)** |

---

## 3. Nonfunctional Requirements Traceability (`NFR-001` – `NFR-012`)

| Req ID | Category | Implementing Files | Verification Evidence & Test Suite(s) | Status |
| :--- | :--- | :--- | :--- | :---: |
| `NFR-001` | Availability & No Startup AI Calls | `backend/app/config/settings.py` (`AI_CONNECT_ON_STARTUP=False`), `backend/app/main.py` | `tests/unit/config/test_settings.py`, `tests/integration/api/test_bootstrap_and_health.py` | **VERIFIED (🟢 GREEN)** |
| `NFR-002` | Worker & AI Fault Isolation | `backend/app/services/ai_job.py`, `backend/app/core/ai.py` | `tests/unit/ai/test_ai_job_service.py` (simulated failures fail safely to `failed` state) | **VERIFIED (🟢 GREEN)** |
| `NFR-003` | API Latency & Async Pooling | `backend/app/infrastructure/database.py`, `asyncpg` async connection pooling | Integration test suites verify asynchronous execution with pre-ping validation | **VERIFIED (🟢 GREEN)** |
| `NFR-004` | Streaming Upload Efficiency | `backend/app/infrastructure/storage.py`, `frontend/src/api/evidence.ts` | `tests/unit/evidence/test_upload_lifecycle.py`, chunked streaming at 5MB boundaries | **VERIFIED (🟢 GREEN)** |
| `NFR-005` | Async DB Pooling & Timeouts | `backend/app/infrastructure/database.py`, `backend/app/config/settings.py` | `tests/unit/db/test_identity_and_database_unit.py`, connection recycling and timeouts | **VERIFIED (🟢 GREEN)** |
| `NFR-006` | Multi-Department Scalability | `backend/app/models/`, composite indices on `(department_id, created_at)` | Database query plan and foreign-key cascade constraint verifications | **VERIFIED (🟢 GREEN)** |
| `NFR-007` | Structured Error Envelope & Safety | `backend/app/api/errors.py`, `backend/app/schemas/common.py` | `tests/unit/architecture/test_layer_boundaries.py`, structured JSON error payloads | **VERIFIED (🟢 GREEN)** |
| `NFR-008` | Accessibility Readiness (WCAG 2.1 AA) | `frontend/src/components/`, semantic HTML, ARIA attributes, contrast ratios | `frontend/src/test/` accessibility assertions across 30 Vitest suites | **VERIFIED (🟢 GREEN)** |
| `NFR-009` | Layered Architecture Separation | `backend/app/core/architecture.py` (AST boundary enforcer) | `tests/unit/architecture/test_layer_boundaries.py` (0 violations across entire backend) | **VERIFIED (🟢 GREEN)** |
| `NFR-010` | Static Type Safety & Linting | `pyproject.toml`, `frontend/tsconfig.json`, `eslint.config.js` | `ruff check .`, `mypy`, `npm run lint`, `npm run build` (0 errors, 0 warnings) | **VERIFIED (🟢 GREEN)** |
| `NFR-011` | Offline Test Reproducibility | `tests/conftest.py`, pytest test doubles and SQLite/PostgreSQL fixtures | 1,548 unit tests + 185 frontend tests execute deterministically | **VERIFIED (🟢 GREEN)** |
| `NFR-012` | Request Correlation & Observability | `backend/app/middleware/request_context.py`, `backend/app/core/logging.py` | `tests/unit/logging/test_logging_and_context.py`, `X-Request-ID` propagation | **VERIFIED (🟢 GREEN)** |

---

## 4. Security and Privacy Requirements Traceability (`SEC-001` – `SEC-015`)

| Req ID | Title | Implementing Files | Automated Test Suite(s) | Status |
| :--- | :--- | :--- | :--- | :---: |
| `SEC-001` | Default-Deny Authorization | `backend/app/api/dependencies.py` (`require_role`, `require_authenticated_user`) | `tests/unit/security/test_batch11_group01_security_hardening.py`, `artifacts/BATCH_11_API_AUTHORIZATION_AUDIT.md` | **VERIFIED (🟢 GREEN)** |
| `SEC-002` | Mandatory Department Isolation | `backend/app/services/`, anti-enumeration 404 masking | `tests/integration/api/test_phase119_fullstack_e2e_verification.py` (Scenarios 1-3) | **VERIFIED (🟢 GREEN)** |
| `SEC-003` | Assigned-Case Isolation | `backend/app/services/case.py` (investigator need-to-know check) | `tests/unit/case/test_case_authorization.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-004` | Submitter Privacy & UUIDs | `backend/app/models/base.py`, RFC 4122 v4 UUIDs across all entities | `tests/unit/incident/test_incident_redaction.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-005` | Production Secret Entropy & Validation | `backend/app/config/settings.py`, `backend/app/core/secrets.py` | `tests/unit/config/test_settings.py`, Shannon entropy $\ge 3.5$ checks | **VERIFIED (🟢 GREEN)** |
| `SEC-006` | Token Signing Algorithm Pinning | `backend/app/core/tokens.py`, explicit HS256/RS256 validation | `tests/unit/auth/test_token_lifecycle.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-007` | Mandatory TLS Verification | `backend/app/config/settings.py` (`STORAGE_VERIFY_TLS=True`) | `tests/unit/config/test_settings.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-008` | Comprehensive Secret Redaction | `backend/app/core/secrets.py` (`redact_secrets`, `***REDACTED***`) | `tests/unit/config/test_redaction.py`, `tests/unit/admin/test_admin_api_phase118.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-009` | Strict CORS Policy Enforcement | `backend/app/main.py`, production wildcard rejection | `tests/unit/config/test_settings.py`, `deployment/nginx.conf` | **VERIFIED (🟢 GREEN)** |
| `SEC-010` | Safe File Upload Validation | `backend/app/infrastructure/scanner.py`, `storage.py` | `tests/unit/security/test_input_hardening_and_uploads.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-011` | Isolated Object Storage Access | `backend/app/infrastructure/storage.py`, presigned URL expiry $\le 300\text{s}$ | `tests/unit/evidence/test_upload_lifecycle.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-012` | AI Data Boundary & Prompt Safety | `backend/app/core/ai.py`, `backend/app/services/ai_job.py` | `tests/unit/ai/test_batch11_ai_security_and_provenance.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-013` | Adaptive Password Hashing | `backend/app/core/security.py`, `Argon2id` password hasher | `tests/unit/auth/test_password_hashing.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-014` | Rate Limiting & Payload Ceilings | `backend/app/middleware/body_size_limit.py`, `backend/app/core/rate_limit.py` | `tests/unit/middleware/test_rate_limiting.py` | **VERIFIED (🟢 GREEN)** |
| `SEC-015` | Production Debug Prohibition | `backend/app/config/settings.py`, fail-fast on `DEBUG=True` | `tests/unit/config/test_settings.py` | **VERIFIED (🟢 GREEN)** |

---

## 5. Evidence Integrity and Traceability (`EVI-001` – `EVI-010`)

| Req ID | Title | Implementing Files | Automated Test Suite(s) | Status |
| :--- | :--- | :--- | :--- | :---: |
| `EVI-001` | Immediate Cryptographic Hashing (`SHA-256`) | `backend/app/services/evidence.py`, `backend/app/infrastructure/storage.py` | `tests/unit/evidence/test_upload_lifecycle.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-002` | Authoritative Evidence Immutability | `backend/app/models/evidence.py`, write-once sealed state checks | `tests/unit/evidence/test_evidence_immutability.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-003` | Integrity Verification on Retrieval | `backend/app/services/evidence.py` (`verify_evidence_integrity`) | `tests/unit/evidence/test_evidence_retrieval.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-004` | Chain-of-Custody Event Ledger | `backend/app/models/custody.py`, `backend/app/services/custody.py` | `tests/unit/custody/test_custody_timeline.py`, `frontend/src/test/custodyTimeline.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `EVI-005` | Evidence Ownership & Case Binding | `backend/app/models/evidence.py` (`incident_id`, `case_id`, `uploader_id`) | `tests/unit/evidence/test_evidence_relationships.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-006` | Derivative & AI Artifact Separation | `backend/app/models/ai.py` (`AICandidateSegment`, `AIAnalysisJob`) | `tests/unit/ai/test_ai_requirements.py`, `frontend/src/test/videoEvidenceReview.test.tsx` | **VERIFIED (🟢 GREEN)** |
| `EVI-007` | Safe Quarantine & Malware Hook | `backend/app/infrastructure/scanner.py`, `QuarantineStatus` lifecycle | `tests/unit/security/test_input_hardening_and_uploads.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-008` | Controlled Retention & Legal Hold | `backend/app/models/case.py` (`is_legal_hold`, `retention_schedule`) | `tests/unit/case/test_retention_and_legal_hold.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-009` | Deterministic Evidence Export Manifest | `backend/app/services/evidence_export.py`, SHA-256 package manifest | `tests/unit/evidence/test_export_manifest.py` | **VERIFIED (🟢 GREEN)** |
| `EVI-010` | Storage Key Randomization | `backend/app/infrastructure/storage.py` (`uuid4/sha256` storage keys) | `tests/unit/evidence/test_storage_keys.py` | **VERIFIED (🟢 GREEN)** |

---

## 6. Auditability and Accountability Traceability (`AUD-001` – `AUD-008`)

| Req ID | Title | Implementing Files | Automated Test Suite(s) | Status |
| :--- | :--- | :--- | :--- | :---: |
| `AUD-001` | Append-Only Audit Trail | `backend/app/models/audit.py`, `backend/app/services/audit.py` | `tests/unit/audit/test_audit_api_phase118.py`, `frontend/src/test/auditApi.test.ts` | **VERIFIED (🟢 GREEN)** |
| `AUD-002` | Comprehensive Security Event Coverage | `backend/app/core/audit.py`, auth/RBAC/case/evidence event hooks | `tests/integration/api/test_phase119_fullstack_e2e_verification.py` (Scenarios 1-12) | **VERIFIED (🟢 GREEN)** |
| `AUD-003` | Cryptographic Hash Chaining | `backend/app/models/audit.py` (`previous_event_hash`, `event_hash`) | `backend/app/api/v1/audit.py` (`GET /verify`), `tests/unit/audit/test_audit_api_phase118.py` | **VERIFIED (🟢 GREEN)** |
| `AUD-004` | Non-Repudiation Context Capture | `backend/app/core/context.py`, actor ID, role, department, IP, request ID | `tests/unit/logging/test_logging_and_context.py` | **VERIFIED (🟢 GREEN)** |
| `AUD-005` | Zero Secret Leakage in Audit Logs | `backend/app/services/audit.py`, formula injection escaping (`=,+,-,@`) | `tests/unit/audit/test_audit_api_phase118.py` | **VERIFIED (🟢 GREEN)** |
| `AUD-006` | Break-Glass Emergency Access Auditing | `backend/app/services/break_glass.py`, mandatory justification requirement | `tests/unit/security/test_break_glass.py` | **VERIFIED (🟢 GREEN)** |
| `AUD-007` | AI Invocation Auditing | `backend/app/services/ai_job.py`, model name, version, hash logged | `tests/unit/ai/test_batch11_ai_security_and_provenance.py` | **VERIFIED (🟢 GREEN)** |
| `AUD-008` | Scoped Audit Inspection | `backend/app/api/v1/audit.py`, department scoping & super-admin rights | `tests/unit/audit/test_audit_api_phase118.py`, `frontend/src/test/auditPage.test.tsx` | **VERIFIED (🟢 GREEN)** |

---

## 7. Sign-Off and Release Certification

Every requirement in this matrix has been mapped to concrete implementation source files and verified through automated test suites (Python unit and integration tests, frontend Vitest suites, and Playwright browser tests). Zero requirements remain unimplemented or unverified.

**Final Status:** **VERIFIED (🟢 GREEN)** across all 65 requirements.
