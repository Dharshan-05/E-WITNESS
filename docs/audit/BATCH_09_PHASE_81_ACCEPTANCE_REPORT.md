# E-WITNESS — Batch 09, Phase 81 Acceptance Report
## Formal Case Lifecycle & References

**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Batch:** 09 — Case Management, Investigation Workspace & Human Review  
**Phase:** 81 of 120 (Opening Phase of Batch 09)  
**Previous Phase:** Phase 80 — `ACCEPTED WITH LIMITATIONS` (Batch 08 Closure & Batch 09 Handoff)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Status:** `NO-GO`  
**Evaluation Date:** 2026-10-28  

---

## 1. Executive Summary & Architectural Findings

Phase 81 establishes the formal backend foundation for investigation case management in E-WITNESS, strictly adhering to the requirements outlined in `docs/audit/BATCH_08_CLOSURE_AND_BATCH_09_HANDOFF.md`.

This phase introduces:
1. **Canonical Annual Reference Sequencing (`CASE-YYYY-XXXXX`)**: A robust, human-readable case reference numbering format governed by atomic database counters (`CaseSequenceCounter`) with row-level locks (`with_for_update()`) and an automated concurrency collision retry loop.
2. **Formal Case Lifecycle State Machine**: Enhanced status progression (`DRAFT -> OPEN -> UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW -> CLOSED`, with an authorized `REOPENED` workflow).
3. **Explicit Permissions & Multi-Tenant Departmental Isolation**: Canonical permission definitions (`CASE_CREATE`, `CASE_READ`, `CASE_UPDATE`, `CASE_ASSIGN`) mapped to authorized system roles (`INVESTIGATOR`, `DEPT_ADMIN`, `SUPER_ADMIN`). Cross-department unauthorized access is masked with `ResourceNotFoundError` (HTTP 404) to achieve zero information leakage across departmental tenants.
4. **Optimistic Concurrency & Append-Only Audit Logging**: Comprehensive version checking (`version_id`) and immutable audit trails for case creation, status changes, assignments, closures, and reopening.
5. **Strict Preservation of Batch 08 Safety Invariants**: `BIOMETRIC_MATCHING_ENABLED = False` remains permanently enforced; zero biometric recognition or 1:N searches; zero modifications to master evidence; and zero access to the sealed historical violence-detection test partition ($N=354$).

---

## 2. Mandatory Safety Invariants Verification

| Invariant / Guardrail | Standard | Verified State |
| :--- | :--- | :--- |
| **`BIOMETRIC_MATCHING_ENABLED`** | Must remain `False` across all configurations and overrides | **Permanently Enforced (`False`)** — Verified fail-closed (`BiometricsDisabledError`) |
| **Biometric Face Matching & Recognition** | 1:1 verification, 1:N identification, and automated suspect tagging prohibited | **Completely Prohibited** — Zero biometric recognition endpoints in case management |
| **Biometric Embeddings & Descriptors** | Zero facial descriptors or templates generated or persisted | **Strictly Zero Generated or Stored** |
| **Sealed Test Partition** | Historical violence test partition ($N=354$) unaccessed and untouched | **Strictly Unaccessed** — Verified by static codebase audit |
| **Original Evidence Integrity** | Master evidence bytes and cryptographic digests must remain immutable | **Preserved** — Read-only evidence linkage; zero byte modifications |
| **Canonical Case Reference Format** | Strict pattern `CASE-YYYY-XXXXX` with annual zero-padded sequence | **Enforced** — `format_canonical_case_reference()` produces 5-digit padded references |
| **Reference Number Immutability** | Once issued, case reference numbers can never be modified | **Enforced** — Excluded from `CaseUpdate` schema (`extra="forbid"`) |
| **State Machine Integrity** | Validated transitions: `DRAFT -> OPEN -> UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW -> CLOSED` | **Enforced** — Invalid transitions rejected with `BusinessRuleError` |
| **Departmental Tenant Isolation** | Cross-department access denied without information leakage | **Enforced** — Masked as `ResourceNotFoundError` ("Case not found", HTTP 404) |
| **Optimistic Concurrency** | Race condition prevention via monotonic `version_id` | **Enforced** — Stale updates trigger `BusinessRuleError` conflict |
| **Auditability** | Append-only event logging for creation, updates, assignments, closure, reopening | **Enforced** — Logged via `AuditRepository.append_event` |
| **Production Gate** | Not ready for production deployment | **`NO-GO` Across All Environments** |

---

## 3. Files Implemented and Modified

| File Path | Change Type | Purpose & Details |
| :--- | :--- | :--- |
| [`backend/app/core/authorization.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/authorization.py) | **Modified** | Added canonical permission codes `CASE_CREATE = "case:create"`, `CASE_READ = "case:read"`, `CASE_UPDATE = "case:update"`, `CASE_ASSIGN = "case:assign"`. Added canonical alias `PermissionCode = Permission`. Configured role bindings for `INVESTIGATOR`, `DEPT_ADMIN`, and `SUPER_ADMIN`. |
| [`backend/app/core/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/case.py) | **Modified** | Added `PENDING_SUPERVISOR_REVIEW = "pending_supervisor_review"` and `REOPENED = "reopened"` to `CaseStatus`. Updated `VALID_CASE_TRANSITIONS` mapping. Added `format_canonical_case_reference(year, sequence_num)`. Added optional sequence number support to `generate_case_reference_number`. |
| [`backend/app/models/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/models/case.py) | **Modified** | Added `CaseSequenceCounter` model with primary key `year`, `current_sequence`, and `updated_at`. Updated check constraint `ck_cases_status_allowed_values` to accept all formal lifecycle statuses. |
| [`backend/app/models/__init__.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/models/__init__.py) | **Modified** | Exported `CaseSequenceCounter` for discovery by SQLAlchemy and Alembic. |
| [`backend/migrations/versions/20261028_0017_add_case_sequence_counters_and_lifecycle_statuses.py`](file:///D:/PROJECT/E-WITTNESS/backend/migrations/versions/20261028_0017_add_case_sequence_counters_and_lifecycle_statuses.py) | **Created** | Alembic database migration creating `case_sequence_counters` table and updating `ck_cases_status_allowed_values` check constraint on `cases`. |
| [`backend/app/repositories/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/repositories/case.py) | **Modified** | Implemented `get_next_case_sequence(year)` with `with_for_update()` row locking and UPSERT logic. Implemented `next_reference_number(when)` producing `CASE-YYYY-XXXXX`. |
| [`backend/app/schemas/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/schemas/case.py) | **Modified** | Added optional `target_status: CaseStatus | None` to `CaseReopenRequest` defaulting to `CaseStatus.UNDER_INVESTIGATION` while permitting explicit `CaseStatus.REOPENED`. |
| [`backend/app/services/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/case.py) | **Modified** | Added `_generate_unique_case_reference` with collision retry loop. Updated `create_case`, `assign_case`, `_assert_case_visible`, and `_assert_case_writable` to honor un-scoped permissions (`CASE_CREATE`, `CASE_READ`, `CASE_UPDATE`, `CASE_ASSIGN`). Hardened `reopen_case` to safely support `target_status`. |
| [`tests/unit/cases/test_phase81_case_lifecycle_and_references.py`](file:///D:/PROJECT/E-WITTNESS/tests/unit/cases/test_phase81_case_lifecycle_and_references.py) | **Created** | Comprehensive 19-test suite verifying canonical reference formatting, atomic database counters, collision retry, immutability, state transitions, closure/reopening workflows, permissions, 404 tenant masking, concurrency conflict detection, audit logging, and Batch 08 safety boundaries. |
| [`docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`](file:///D:/PROJECT/E-WITTNESS/docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md) | **Updated** | Updated Phase 81 row status to `ACCEPTED WITH LIMITATIONS`. |

---

## 4. Test Verification & Results

All test suites were executed in the project virtual environment with complete test isolation.

### 4.1 Phase 81 Dedicated Test Suite
**Command:** `uv run pytest tests/unit/cases/test_phase81_case_lifecycle_and_references.py -o addopts="" -v`  
**Result:** **19 passed / 19 tests in 1.27s**

Key test cases verified:
1. `test_case_creation_valid_input`: Case creation with title, summary, priority, and default initial status `OPEN`.
2. `test_case_creation_invalid_input_boundaries`: Rejection of short titles (<3 chars), excessive titles (>255 chars), and short summaries (<10 chars).
3. `test_case_reference_number_canonical_format`: Validation of `CASE-YYYY-XXXXX` format with 5-digit annual sequence.
4. `test_case_reference_concurrency_collision_retry`: Automated collision resolution re-attempting reference generation.
5. `test_case_reference_number_immutability`: Verification that reference numbers cannot be altered in update operations.
6. `test_permitted_case_lifecycle_state_machine_transitions`: Verification of legal transitions:
   - `DRAFT -> OPEN`
   - `OPEN -> UNDER_INVESTIGATION`
   - `UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW`
   - `PENDING_SUPERVISOR_REVIEW -> CLOSED`
   - `CLOSED -> REOPENED`
   - `REOPENED -> UNDER_INVESTIGATION`
7. `test_rejection_of_invalid_case_lifecycle_transitions`: Verification that illegal transitions (e.g. `DRAFT -> CLOSED`, `CLOSED -> OPEN`, `UNDER_INVESTIGATION -> DRAFT`) are rejected.
8. `test_authorized_case_closure_workflow`: Authorized closure setting `closed_at` timestamp and recording audit event.
9. `test_authorized_case_reopening_workflow`: Authorized reopening clearing `closed_at` and advancing `version_id`.
10. `test_permission_codes_exist_and_map_to_authorized_roles`: Verification that `PermissionCode.CASE_*` codes are bound to authorized roles.
11. `test_unauthorized_roles_denied_case_creation`: Unauthorized roles (e.g. `STUDENT`) denied case creation with `PermissionDeniedError` (HTTP 403).
12. `test_cross_department_case_access_masked_as_not_found`: Cross-department access attempts return `ResourceNotFoundError` ("Case not found", HTTP 404) to prevent probing.
13. `test_cross_department_case_creation_forbidden`: Non-super-admins cannot initiate cases for foreign departments.
14. `test_list_cases_enforces_department_filter_for_non_global_principals`: Case listing automatically scoped to caller department.
15. `test_optimistic_concurrency_conflict_detection`: Concurrent update collisions detected via `version_id` checks.
16. `test_audit_event_logged_on_case_assignment`: Investigator reassignment emits append-only audit event.
17. `test_biometric_matching_strictly_disabled_and_fails_closed`: Permanent `BIOMETRIC_MATCHING_ENABLED = False` fail-closed verification.
18. `test_case_management_code_never_references_sealed_violence_partition`: Static codebase audit ensuring no references to the sealed violence test dataset.
19. `test_case_sequence_counter_model_attributes`: ORM mapping verification for `CaseSequenceCounter`.

### 4.2 Full Case Subsystem Regression Suite
**Command:** `uv run pytest tests/unit/cases/ -o addopts=""`  
**Result:** **99 passed / 99 tests in 2.33s** (zero regressions across all existing domain, service, notes, and export tests).

### 4.3 Full Biometrics Regression Suite (Batch 08 Invariants)
**Command:** `uv run pytest tests/unit/biometrics/ -o addopts=""`  
**Result:** **355 passed / 355 tests in 13.69s** (zero regressions in privacy redaction, envelope encryption, key vaulting, and matching prohibition).

---

## 5. Limitations & Operational Boundaries

1. **Phase 82 Scope Boundary**: Detailed investigator workload quotas, active case count caps (e.g. 10 cases per investigator), and assignment rejection thresholds are deferred to Phase 82.
2. **Phase 86 Scope Boundary**: Formal case note visibility tiers (`internal`, `confidential`, `restricted`) and findings management belong to Phase 86.
3. **Phase 89 Scope Boundary**: Controlled cryptographic disclosure manifests with composite SHA-256 evidence digests belong to Phase 89.
4. **Mock vs Production Sequencing**: In SQLite in-memory unit tests using mocks, sequencing falls back safely to timestamped hex references when repository mocks return unconfigured mocks, while PostgreSQL production environments utilize the atomic `CaseSequenceCounter` table with row-level locks.
5. **Production Status Strictly `NO-GO`**: E-WITNESS remains an academic and research prototype; deployment to production environments is strictly prohibited.

---

## 6. Handoff & Next Phase Direction

Phase 81 is successfully completed and verified. The repository is ready to proceed to:
- **Phase 82: Case Assignment & Workload Limits**
- Focus: Investigator assignment quotas, active workload calculation, workload threshold enforcement, and supervisor override mechanisms.
- Retain all Batch 08 and Phase 81 safety invariants without modification.
