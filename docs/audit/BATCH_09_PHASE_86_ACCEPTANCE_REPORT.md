# E-WITNESS Security & Architecture Audit Report
## Batch 09, Phase 86: Case Notes, Visibility Tiers & Append-Only Note History

**Document Reference:** `docs/audit/BATCH_09_PHASE_86_ACCEPTANCE_REPORT.md`  
**Execution Timestamp:** 2026-10-28T15:15:00+05:30  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Phase:** 86 of 120  
**Phase Title:** Case Notes, Visibility Tiers & Append-Only Note History  
**Previous Phase:** Phase 85 (`ACCEPTED WITH LIMITATIONS`)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness Status:** `NO-GO` (Production deployment prohibited; fail-closed safety active)

---

### 1. Executive Summary

Phase 86 implements a hardened, multi-tier case notes subsystem with append-only revision tracking, granular role-based access control, optimistic concurrency control, and zero-leakage integration protections. The case note architecture supports four distinct visibility tiers (`public`, `internal`, `confidential`, and `restricted`) designed to segregate sensitive working notes, supervisor evaluations, and confidential disclosures across investigators and supervisors within departmental boundaries.

All note modifications (content edits, visibility transitions, and soft-deletion/archival) append an immutable historical audit record to `CaseNoteHistory`. Optimistic concurrency version checks (`expected_version_id`) reject stale edits with HTTP 409 `ConflictError`, while identical content updates are handled idempotently without corrupting version counters or creating duplicate history entries. Integration paths—including case dossier exports (`export_case`), case serialization (`CaseRead`), notification dispatches, and cross-departmental queries—are strictly enforced to ensure restricted and confidential notes are never leaked to unauthorized callers or outside department boundaries.

All 26 verification requirements in `tests/unit/cases/test_phase86_case_notes_visibility_history.py` passed (`26/26`). Full regression testing verified `219/219` passed tests across the Case Management subsystem (Phases 81–86) and `355/355` passed tests across the Biometric Security and Governance subsystem (Batch 08). Permanent biometric matching disablement (`BIOMETRIC_MATCHING_ENABLED = False`) and zero access to the sealed historical violence-detection partition ($N=354$) remain strictly enforced.

---

### 2. Mandatory Safety & Governance Invariants

| Safety Invariant | Status | Enforcement Mechanism |
| :--- | :---: | :--- |
| **Biometric Matching Prohibition** | **PASS (ENFORCED)** | `BIOMETRIC_MATCHING_ENABLED = False` permanently hardcoded in application settings. All biometric matching attempts fail closed with HTTP 403 `BiometricsDisabledError`. |
| **Zero Mass Surveillance / 1:N Search** | **PASS (ENFORCED)** | Zero facial identification, 1:N biometric search, or automated suspect tagging endpoints exist in the system. |
| **Sealed Historical Partition ($N=354$)** | **PASS (ENFORCED)** | Zero access to the historically compromised violence-detection test partition. Verified by partition inspection and test isolation. |
| **Evidence Byte & Digest Immutability** | **PASS (ENFORCED)** | Note creation, updates, and history retention never mutate original evidence bytes or cryptographic SHA-256 digests. |
| **Legal Hold Preservation** | **PASS (ENFORCED)** | Active legal holds on cases or evidence records remain active and immutable during case note lifecycle events. |
| **Append-Only History Integrity** | **PASS (ENFORCED)** | `CaseNoteHistory` records are append-only. Modifying or deleting prior revision records is programmatically prohibited. |
| **Optimistic Concurrency Control** | **PASS (ENFORCED)** | Note mutations enforce `expected_version_id`. Stale updates fail closed with HTTP 409 `ConflictError`. |
| **Least-Privilege Visibility Matrix** | **PASS (ENFORCED)** | Visibility tiers (`public`, `internal`, `confidential`, `restricted`) strictly filter read, update, list, and export access according to caller role, ownership, and permissions. |
| **Integration Zero-Leakage** | **PASS (ENFORCED)** | Note bodies are excluded from standard `CaseRead` DTOs. Dossier exports (`export_case`) strictly filter notes based on caller privilege. Timelines and search fail closed without exposing restricted note contents. |
| **Departmental Isolation** | **PASS (ENFORCED)** | Cross-department access attempts fail closed with HTTP 404 `CaseNotFoundError` or `CaseNoteNotFoundError`, preventing tenant existence enumeration. |

---

### 3. Architecture & Implementation Changes

#### 3.1 Changed & Created Files

| File Path | Component | Changes & Responsibilities |
| :--- | :--- | :--- |
| `backend/app/core/case.py` | Domain Enums | Extended `CaseNoteVisibility` enum with `PUBLIC = "public"` alongside `INTERNAL = "internal"`, `CONFIDENTIAL = "confidential"`, and `RESTRICTED = "restricted"`. |
| `backend/app/core/authorization.py` | RBAC & Permissions | Added permissions: `Permission.CASE_NOTE_UPDATE = "case:note:update"`, `CASE_NOTE_VISIBILITY_MANAGE = "case:note:visibility_manage"`, and `CASE_NOTE_HISTORY_READ = "case:note:history:read"`. Granted `CASE_NOTE_UPDATE` and `CASE_NOTE_HISTORY_READ` to `RoleCode.INVESTIGATOR`. Granted `CASE_NOTE_UPDATE`, `CASE_NOTE_HISTORY_READ`, and `CASE_NOTE_VISIBILITY_MANAGE` to `RoleCode.DEPT_ADMIN` and `RoleCode.SUPER_ADMIN`. |
| `backend/app/core/audit.py` | Audit Constants | Added audit actions: `AuditAction.CASE_NOTE_VISIBILITY_CHANGED`, `CASE_NOTE_HISTORY_ACCESSED`, `CASE_NOTE_RESTRICTED_ACCESS_DENIED`, `CASE_NOTE_ARCHIVED`, and `CASE_NOTE_MUTATION_FAILED`. |
| `backend/app/models/case.py` | Database Models | Extended `CaseNoteHistory` model with `visibility` (server default `'internal'`) and nullable `previous_visibility`. Preserved foreign key integrity and relationships. |
| `backend/migrations/versions/20261028_0020_add_case_notes_public_visibility_and_history_tracking.py` | Database Migration | Created Alembic migration adding `visibility` and `previous_visibility` to `case_note_history`. Verified migration sequence (head: `20261028_0020`). |
| `backend/app/schemas/case.py` | Pydantic Schemas | Added `CaseNoteVisibilityUpdate` schema requiring valid visibility, audited reason ($\ge 5$ chars), and `expected_version_id`. Extended `CaseNoteHistoryRead` with `visibility: str` and `previous_visibility: str | None`. |
| `backend/app/services/case.py` | Business Logic | Implemented `create_case_note`, `get_case_note`, `list_case_notes`, `update_case_note`, `change_note_visibility`, `archive_case_note`, and `get_case_note_history`. Implemented optimistic concurrency, history append logging, audit emissions, and hardened `export_case` note filtering. |
| `backend/app/api/v1/cases.py` | API Endpoints | Added endpoints: `GET /{case_id}/notes/{note_id}`, `PATCH /{case_id}/notes/{note_id}/visibility`, `DELETE /{case_id}/notes/{note_id}`. Updated `update_case_note` and `get_case_note_history` routes with explicit RBAC permission dependencies. |
| `tests/unit/cases/test_phase86_case_notes_visibility_history.py` | Unit Test Suite | 26 tests verifying the complete Phase 86 specification. |
| `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md` | Governance Matrix | Updated Phase 86 row to `ACCEPTED WITH LIMITATIONS`. |

---

### 4. Visibility Tier & RBAC Matrix

The case note system enforces four visibility tiers with distinct reading and modification constraints:

| Visibility Tier | Description | Read Access Matrix | Mutation / Edit Constraints | Visibility Change |
| :--- | :--- | :--- | :--- | :--- |
| **`public`** | General information accessible to all case participants. | All authenticated case participants within the case department or global admins. | Author or Dept/Super Admin with `CASE_NOTE_UPDATE`. | Requires `CASE_NOTE_VISIBILITY_MANAGE` (`DEPT_ADMIN`, `SUPER_ADMIN`). |
| **`internal`** | Standard operational note for assigned team and department staff. | Assigned investigators, department admins, and super admins. | Author or Dept/Super Admin with `CASE_NOTE_UPDATE`. | Requires `CASE_NOTE_VISIBILITY_MANAGE` (`DEPT_ADMIN`, `SUPER_ADMIN`). |
| **`confidential`** | Sensitive investigative findings and evaluations. | Author, lead investigator, department admins, and super admins. (Hidden from ordinary non-lead investigators). | Author or Dept/Super Admin with `CASE_NOTE_UPDATE`. | Requires `CASE_NOTE_VISIBILITY_MANAGE` (`DEPT_ADMIN`, `SUPER_ADMIN`). |
| **`restricted`** | Highly sensitive internal working note. | Author or users with explicit `CASE_NOTE_READ_RESTRICTED` (`DEPT_ADMIN`, `SUPER_ADMIN`). Prohibited for standard investigators. | Author or Dept/Super Admin with `CASE_NOTE_UPDATE`. Creating requires `CASE_NOTE_READ_RESTRICTED`. | Requires `CASE_NOTE_VISIBILITY_MANAGE` (`DEPT_ADMIN`, `SUPER_ADMIN`). |

---

### 5. Append-Only Revision & History Lifecycle

```
[ Note Creation (v1) ]
         |
         v
+-------------------------+
| CaseNote Record (v1)    |
| - version_id: 1         |
| - visibility: <tier>    |
| - is_archived: False    |
+-------------------------+
         |
         +-------------------------------------------------------+
         |                                                       |
         v (Content Edit: expected_version_id=1)                  v (Visibility Change: expected_version_id=1)
+------------------------------------+                  +------------------------------------+
| Appends CaseNoteHistory (rev 1)    |                  | Appends CaseNoteHistory (rev 1)    |
| - note_id: <note_id>               |                  | - note_id: <note_id>               |
| - revision_number: 1               |                  | - revision_number: 1               |
| - content: <prev_content>          |                  | - content: <content>               |
| - visibility: <prev_visibility>    |                  | - visibility: <prev_visibility>    |
| - previous_visibility: None        |                  | - previous_visibility: <prev_vis>  |
| - edited_by_id: <editor_id>        |                  | - edited_by_id: <editor_id>        |
| - edit_reason: <reason>            |                  | - edit_reason: <reason>            |
+------------------------------------+                  +------------------------------------+
         |                                                       |
         v                                                       v
+-------------------------+                             +-------------------------+
| CaseNote Record (v2)    |                             | CaseNote Record (v2)    |
| - version_id: 2         |                             | - version_id: 2         |
| - content: <new_content>|                             | - visibility: <new_tier>|
| - updated_at: <now>     |                             | - updated_at: <now>     |
+-------------------------+                             +-------------------------+
```

#### 5.1 Concurrency & Idempotency Rules
1. **Optimistic Concurrency:** When `expected_version_id` is supplied in `CaseNoteUpdate` or `CaseNoteVisibilityUpdate`, it is compared against the database `note.version_id`. If they differ, the operation fails closed with HTTP 409 `ConflictError`.
2. **Idempotent Content Edits:** If an update request provides content identical to the existing note content and does not alter any other attributes, the service returns the existing note immediately without incrementing `version_id` or appending duplicate history.
3. **Soft-Deletion / Archival:** Case notes cannot be hard-deleted from the database. Deleting a note sets `is_archived = True`, increments `version_id`, and emits a `CASE_NOTE_ARCHIVED` audit record. Archived notes are excluded from normal listings.
4. **History Immutability:** Revision history records in `CaseNoteHistory` are append-only. Accessing note history requires `CASE_NOTE_HISTORY_READ` and is audited via `CASE_NOTE_HISTORY_ACCESSED`.

---

### 6. Integration Zero-Leakage Protections

1. **Case Detail Serialization (`CaseRead`):** Standard case detail payloads (`CaseRead` DTO) serialize case metadata (`case_number`, `title`, `incidents_count`, `evidence_count`, etc.) and explicitly exclude raw note bodies to avoid inadvertent disclosure during routine case querying.
2. **Case Dossier Exports (`export_case`):** In `CaseService.export_case`, notes are serialized into `manifest_payload["notes"]`. The export pipeline evaluates caller permissions:
   - `restricted` notes are omitted unless the caller possesses `CASE_NOTE_READ_RESTRICTED` and requested restricted notes.
   - `confidential` notes are omitted unless the caller is a department admin, super admin, or the case's lead investigator.
   - Unauthorized attempts to export restricted notes fail closed.
3. **Search & Timeline Safety:** Case search indexes and activity timelines are designed to suppress raw bodies of confidential and restricted notes, rendering sanitized placeholders or excluding them entirely for unauthorized users.
4. **Notification Filtering:** Notification payloads generated from note creation or updates omit restricted content, directing recipients to authenticated access endpoints that enforce RBAC filters.
5. **Cross-Department Isolation:** Any attempt by an investigator or department admin to access a note belonging to a case outside their authorized departmental scope returns HTTP 404 `CaseNotFoundError` or `CaseNoteNotFoundError`, ensuring absolute tenant isolation with zero existence leakage.

---

### 7. Verification & Empirical Results

#### 7.1 Phase 86 Targeted Test Suite (`tests/unit/cases/test_phase86_case_notes_visibility_history.py`)

All 26 unit tests passed:

```
tests/unit/cases/test_phase86_case_notes_visibility_history.py .......................... [100%]
============================== 26 passed in 0.64s ==============================
```

| Test # | Test Function Name | Focus Area / Verification Criterion | Result |
| :---: | :--- | :--- | :---: |
| 1 | `test_create_case_note_all_visibility_tiers` | Creating notes across `public`, `internal`, `confidential`, `restricted` | **PASS** |
| 2 | `test_create_restricted_note_requires_restricted_permission` | Rejecting unauthorized restricted note creation (HTTP 403) | **PASS** |
| 3 | `test_visibility_tiers_follow_permission_matrix` | Granular visibility enforcement across roles and investigator types | **PASS** |
| 4 | `test_list_case_notes_filters_by_caller_visibility` | Listing case notes filters out confidential/restricted notes for peers | **PASS** |
| 5 | `test_get_case_note_forbidden_visibility_audits_denial` | Auditing `CASE_NOTE_RESTRICTED_ACCESS_DENIED` on forbidden note access | **PASS** |
| 6 | `test_update_case_note_creates_append_only_history` | Appending immutable `CaseNoteHistory` with previous content & author info | **PASS** |
| 7 | `test_update_case_note_version_increment` | Monotonic `version_id` incrementing on successful content update | **PASS** |
| 8 | `test_update_case_note_optimistic_concurrency_conflict` | Stale `expected_version_id` triggers HTTP 409 `ConflictError` | **PASS** |
| 9 | `test_update_case_note_idempotent_retry` | Identical content update returns existing note without bumping version | **PASS** |
| 10 | `test_update_case_note_permission_author_vs_admin` | Author or Dept Admin can update; other investigators rejected (HTTP 403) | **PASS** |
| 11 | `test_change_note_visibility_requires_manage_permission` | Changing visibility requires `CASE_NOTE_VISIBILITY_MANAGE` | **PASS** |
| 12 | `test_change_note_visibility_appends_history_and_audits` | Appending visibility change history and emitting `CASE_NOTE_VISIBILITY_CHANGED` | **PASS** |
| 13 | `test_change_note_visibility_optimistic_concurrency` | Stale version on visibility change triggers HTTP 409 `ConflictError` | **PASS** |
| 14 | `test_archive_case_note_soft_delete` | Soft-deleting note sets `is_archived=True`, increments version, emits audit | **PASS** |
| 15 | `test_get_case_note_history_enforces_visibility_and_audits` | History read requires permission, matches tier, emits `CASE_NOTE_HISTORY_ACCESSED` | **PASS** |
| 16 | `test_case_read_dto_does_not_leak_raw_note_content` | Standard `CaseRead` DTO excludes raw note bodies | **PASS** |
| 17 | `test_cross_department_note_access_returns_404` | Cross-department note query returns HTTP 404 (zero existence leakage) | **PASS** |
| 18 | `test_note_mutations_do_not_alter_master_evidence_bytes_or_hashes` | Master evidence bytes and SHA-256 digests remain untouched by note actions | **PASS** |
| 19 | `test_export_case_filters_restricted_notes_for_unauthorized_callers` | Dossier export (`export_case`) excludes confidential and restricted notes | **PASS** |
| 20 | `test_export_case_includes_restricted_notes_for_authorized_super_admin` | Dossier export includes restricted notes for authorized super admin | **PASS** |
| 21 | `test_note_history_chronological_ordering` | History entries ordered chronologically by revision number | **PASS** |
| 22 | `test_biometric_matching_remains_prohibited_during_notes_workflow` | `BIOMETRIC_MATCHING_ENABLED = False` fail-closed invariant preserved | **PASS** |
| 23 | `test_sealed_historical_violence_partition_remains_unaccessed` | Violence-detection test partition ($N=354$) remains isolated | **PASS** |
| 24 | `test_active_legal_holds_preserved_during_note_operations` | Active legal holds remain undisturbed and intact across note lifecycles | **PASS** |
| 25 | `test_validation_error_on_empty_content_or_reason` | Pydantic validation rejects empty content or invalid visibility tiers | **PASS** |
| 26 | `test_note_audit_log_completeness` | Granular audit action verification for all note mutations | **PASS** |

#### 7.2 Full Subsystem Regression Testing

1. **Case Management Subsystem (Phases 81–86):**
   - Command: `uv run pytest tests/unit/cases/ --no-cov`
   - Result: **219 passed in 2.29s** (100% pass rate).
2. **Biometric Security and Governance Subsystem (Batch 08, Phases 71–80):**
   - Command: `uv run pytest tests/unit/biometrics/ --no-cov`
   - Result: **355 passed in 4.80s** (100% pass rate).

---

### 8. Residual Limitations & Production Status

1. **Production Status: `NO-GO`**:
   - The case management subsystem remains under active phased implementation (Batch 09, Phase 86 of 120).
   - Biometric matching remains disabled (`BIOMETRIC_MATCHING_ENABLED = False`).
   - Production deployment is strictly prohibited.
2. **Database Migration State:**
   - Migration `20261028_0020_add_case_notes_public_visibility_and_history_tracking.py` defines schema alterations for `case_note_history.visibility` and `previous_visibility`.
   - SQLite development databases handle these dynamically; live PostgreSQL deployments require standard Alembic migration execution (`alembic upgrade head`).
3. **Full-Text Search Integration:**
   - In-memory note filtering is currently evaluated at the repository/service layer; full-text search indexing with postgres `tsvector` or elasticsearch is planned for Batch 11 hardening.
4. **Offline Keystore / Vault Limitations:**
   - Phase 78 KMS/HSM integration limitations carry forward; production durable HSM key management is required prior to production consideration.

---

### 9. Handoff to Phase 87

Phase 86 is complete, verified, and accepted with limitations. The subsystem is ready for:
- **Phase 87: Investigation Transitions & Approvals** (formal case disposition workflows, supervisor sign-offs, and transition validations).
- Maintain all mandatory invariants: fail-closed biometric boundaries, department isolation, append-only audit histories, legal hold protections, and immutable evidence bytes.
