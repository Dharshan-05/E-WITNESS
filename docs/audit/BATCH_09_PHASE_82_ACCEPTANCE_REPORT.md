# E-WITNESS — Batch 09, Phase 82 Acceptance Report
## Case Assignment, Investigator Workload Limits & Supervisor Overrides

**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Batch:** 09 — Case Management, Investigation Workspace & Human Review  
**Phase:** 82 of 120  
**Previous Phase:** Phase 81 — `ACCEPTED WITH LIMITATIONS` (Formal Case Lifecycle & References)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Status:** `NO-GO`  
**Evaluation Date:** 2026-10-28  

---

## 1. Executive Summary & Architectural Findings

Phase 82 implements and validates the investigator assignment workflow, active-case workload calculations, configurable assignment capacity bounds, and audited supervisor override mechanisms for the E-WITNESS Case Management Subsystem.

This phase introduces:
1. **Departmental Containment & Investigator Eligibility Validation**: Case assignment strictly enforces that the designated lead investigator belongs to the same department as the case (`investigator.department_id == case.department_id`). Furthermore, accounts with inactive status, disabled/suspended flags, or ineligible non-investigator roles (`STUDENT`, `STAFF`, `GUEST`) are strictly rejected with deterministic domain errors (`INELIGIBLE_INVESTIGATOR_ROLE`).
2. **Active Workload Definition & Calculation**: Implemented formal categorization of case lifecycle states into `ACTIVE_CASE_STATUSES` (`DRAFT`, `OPEN`, `UNDER_INVESTIGATION`, `PENDING_REVIEW`, `PENDING_SUPERVISOR_REVIEW`, `SUSPENDED`, `REOPENED`) versus `TERMINAL_CASE_STATUSES` (`CLOSED`, `RESOLVED`). Closed and resolved cases are strictly excluded from active workload totals.
3. **Configurable Workload Limits**: Integrated `INVESTIGATOR_MAX_ACTIVE_CASES` (default: **10**, validated bounds: $1 \le N \le 1000$) within system settings. Assignment requests attempting to allocate a case to an investigator currently at or above capacity are blocked with `INVESTIGATOR_CAPACITY_EXCEEDED` (HTTP 422).
4. **Audited Supervisor Overrides**: Added dedicated permission `CASE_ASSIGN_OVERRIDE` (`case:assign:override`), restricted strictly to `DEPT_ADMIN` and `SUPER_ADMIN` roles (investigators cannot override their own capacity limits). Overrides require an explicit, non-empty justification ($\ge 10$ non-whitespace characters) and emit a specialized append-only audit event `CASE_ASSIGNMENT_OVERRIDDEN` (`case:assignment:overridden`) recording the prior workload, configured limit, resulting workload, justification, case reference, and supervisor ID.
5. **Concurrency Control & Row-Level Locking**: Integrated pessimistic row-level locking (`with_for_update=True`) on investigator user queries during assignment to serialize concurrent assignment evaluations. Combined with optimistic concurrency checking on the target case (`expected_version` matched against `case.version_id`), this dual-layer concurrency design prevents race conditions, oversaturation past capacity, and conflicting concurrent assignments.
6. **Zero-Leakage Multi-Tenant Isolation**: Maintained strict departmental isolation on assignment mutations and investigator workload queries. Cross-department probing attempts are masked with `ResourceNotFoundError` (HTTP 404), ensuring zero metadata disclosure across institutional tenants.
7. **Strict Preservation of Batch 08 Safety Invariants**: `BIOMETRIC_MATCHING_ENABLED = False` remains permanently enforced; zero biometric recognition or 1:N searches; zero modifications to master evidence; and zero access to the sealed historical violence-detection test partition ($N=354$).

---

## 2. Mandatory Safety Invariants Verification

| Invariant / Guardrail | Standard | Verified State |
| :--- | :--- | :--- |
| **`BIOMETRIC_MATCHING_ENABLED`** | Must remain `False` across all configurations and overrides | **Permanently Enforced (`False`)** — Verified fail-closed (`BiometricsDisabledError`) |
| **Biometric Face Matching & Recognition** | 1:1 verification, 1:N identification, and automated suspect tagging prohibited | **Completely Prohibited** — Zero biometric recognition endpoints in case assignment |
| **Biometric Embeddings & Descriptors** | Zero facial descriptors or templates generated or persisted | **Strictly Zero Generated or Stored** |
| **Sealed Test Partition** | Historical violence test partition ($N=354$) unaccessed and untouched | **Strictly Unaccessed** — Verified by static codebase audit |
| **Original Evidence Integrity** | Master evidence bytes and cryptographic digests must remain immutable | **Preserved** — Assignment links reference identifiers only; zero evidence byte modifications |
| **Canonical Case Reference Format** | Strict pattern `CASE-YYYY-XXXXX` preserved across assignments | **Preserved** — References retained unchanged through all assignments and reassignments |
| **Departmental Tenant Isolation** | Cross-department access denied without information leakage | **Enforced** — Masked as `ResourceNotFoundError` ("Case not found", HTTP 404) |
| **Workload Quota Enforcement** | Max 10 active cases per investigator enforced in database layer | **Enforced** — Database-queried active case count checked against configured limit |
| **Supervisor Override Safeguards** | Privileged override requires `CASE_ASSIGN_OVERRIDE` and non-empty rationale | **Enforced** — 403 `OVERRIDE_PERMISSION_DENIED` on lack of permission; 422 on justification $< 10$ chars |
| **Pessimistic & Optimistic Concurrency**| Prevent concurrent over-assignment and stale updates | **Enforced** — `with_for_update()` row locking on user + `version_id` verification on case |
| **Audit Trail Completeness** | Append-only logging of standard and overridden assignments | **Enforced** — `CASE_ASSIGNED`, `CASE_REASSIGNED`, and `CASE_ASSIGNMENT_OVERRIDDEN` |
| **Production Gate** | Not ready for production deployment | **`NO-GO` Across All Environments** |

---

## 3. Files Implemented and Modified

| File Path | Change Type | Purpose & Details |
| :--- | :--- | :--- |
| [`backend/app/core/authorization.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/authorization.py) | **Modified** | Added permission `CASE_ASSIGN_OVERRIDE = "case:assign:override"`. Bound permission strictly to `RoleCode.DEPT_ADMIN` and `RoleCode.SUPER_ADMIN` (explicitly excluded from `RoleCode.INVESTIGATOR`). |
| [`backend/app/core/audit.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/audit.py) | **Modified** | Added canonical audit action `CASE_ASSIGNMENT_OVERRIDDEN = "case:assignment:overridden"`. |
| [`backend/app/core/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/case.py) | **Modified** | Added `ACTIVE_CASE_STATUSES` set (`DRAFT`, `OPEN`, `UNDER_INVESTIGATION`, `PENDING_REVIEW`, `PENDING_SUPERVISOR_REVIEW`, `SUSPENDED`, `REOPENED`) and confirmed `TERMINAL_CASE_STATUSES` (`CLOSED`, `RESOLVED`). Reconfirmed default limit `INVESTIGATOR_DEFAULT_MAX_ACTIVE_CASES = 10`. |
| [`backend/app/config/settings.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/config/settings.py) | **Modified** | Added `INVESTIGATOR_MAX_ACTIVE_CASES: int = Field(default=10, ge=1, le=1000)` in Section 8.2 with environment variable binding. |
| [`backend/app/models/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/models/case.py) | **Modified** | Added `is_supervisor_override: Mapped[bool]` and `override_justification: Mapped[str | None]` fields to `CaseAssignment` model. |
| [`backend/migrations/versions/20261028_0018_add_supervisor_override_to_case_assignments.py`](file:///D:/PROJECT/E-WITTNESS/backend/migrations/versions/20261028_0018_add_supervisor_override_to_case_assignments.py) | **Created** | Alembic migration script adding `is_supervisor_override` and `override_justification` columns to `case_assignments` table. |
| [`backend/app/repositories/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/repositories/case.py) | **Modified** | Updated `count_active_cases_for_investigator` query to filter strictly by `Case.status.in_([s.value for s in ACTIVE_CASE_STATUSES])`. |
| [`backend/app/repositories/identity.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/repositories/identity.py) | **Modified** | Added optional `with_for_update: bool = False` argument to `UserRepository.get_by_id` and `get_by_id_unscoped` to support database-level pessimistic row locking. |
| [`backend/app/schemas/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/schemas/case.py) | **Modified** | Added `is_supervisor_override` and `override_justification` to `CaseAssignRequest` and `CaseAssignmentRead` (with Pydantic null-coercion validator). Added `department_id` to `InvestigatorWorkloadRead`. |
| [`backend/app/services/case.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/case.py) | **Modified** | Integrated `INVESTIGATOR_MAX_ACTIVE_CASES` from settings. Hardened `assign_case` with 404 tenant masking, override permission verification, $\ge 10$-char justification validation, account/role eligibility checks, database workload query, pessimistic locking, and enriched audit logging. Hardened `get_investigator_workload` with department masking. |
| [`backend/app/api/v1/cases.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/api/v1/cases.py) | **Modified** | Added `Permission.CASE_ASSIGN` dependency requirement to `POST /{case_id}/assignments`. |
| [`tests/unit/cases/test_phase82_assignment_workload_limits.py`](file:///D:/PROJECT/E-WITTNESS/tests/unit/cases/test_phase82_assignment_workload_limits.py) | **Created** | Comprehensive 26-test suite covering departmental containment, eligibility, capacity limits, active status sets, supervisor overrides, concurrency locking, and safety invariants. |
| [`docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`](file:///D:/PROJECT/E-WITTNESS/docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md) | **Updated** | Updated Phase 82 status to `ACCEPTED WITH LIMITATIONS`. |

---

## 4. Test Verification & Results

All test executions completed successfully within the project environment (`Python 3.15.2`).

### 4.1 Phase 82 Dedicated Test Suite
**Command:** `uv run pytest tests/unit/cases/test_phase82_assignment_workload_limits.py --no-cov`  
**Result:** **26 passed / 26 tests in 1.27s**

Key test cases verified:
1. `test_valid_same_department_assignment`: Successful case assignment to eligible investigator in matching department.
2. `test_assignment_to_inactive_investigator_rejected`: Assignment rejected if investigator account is suspended or disabled.
3. `test_assignment_to_ineligible_role_rejected`: Assignment rejected if target user possesses a non-investigator role (`ROLE_STUDENT`, `ROLE_STAFF`).
4. `test_cross_department_assignment_rejected`: Rejection with `CROSS_DEPARTMENT_ASSIGNMENT_FORBIDDEN` when case and investigator belong to different departments.
5. `test_cross_department_case_access_returns_not_found_on_assignment`: Probing a foreign case returns 404 `ResourceNotFoundError` for zero leakage.
6. `test_workload_counts_across_every_case_status`: Verified that all 7 statuses in `ACTIVE_CASE_STATUSES` contribute to workload while terminal statuses are excluded.
7. `test_assignment_rejected_at_configured_maximum`: Assignment rejected with `INVESTIGATOR_CAPACITY_EXCEEDED` when active workload is $\ge 10$.
8. `test_assignment_allowed_below_maximum`: Assignment succeeds without override when active workload is $< 10$.
9. `test_closed_cases_excluded_from_active_workload`: `CLOSED` and `RESOLVED` cases do not count against capacity limits.
10. `test_reassignment_updates_workload_and_records_history`: Reassignment creates new assignment record and retains prior assignment history.
11. `test_missing_or_blank_override_justification_rejected`: Parameterized test ensuring justifications $< 10$ characters (None, empty, whitespace, short strings) are rejected.
12. `test_unauthorized_override_rejected`: Rejection with 403 `OVERRIDE_PERMISSION_DENIED` when an investigator attempts a supervisor override.
13. `test_authorized_override_audited_correctly`: Successful override by department admin emits `CASE_ASSIGNMENT_OVERRIDDEN` with `prior_workload`, `configured_limit`, and `resulting_workload`.
14. `test_client_supplied_workload_values_forbidden_in_schema`: Verifies client cannot spoof workload counters; authoritative values must come from database queries.
15. `test_concurrent_assignment_uses_with_for_update_row_locking`: Verifies `with_for_update=True` is passed to the repository to serialize concurrent assignments.
16. `test_database_rollback_on_failed_assignment`: Transaction rolls back cleanly upon assignment failure.
17. `test_audit_preserves_initial_and_reassignment_history`: Append-only audit events capture complete reassignment trajectory.
18. `test_optimistic_concurrency_conflict_handled_safely`: Mismatched `expected_version` triggers 409 conflict and aborts assignment.
19. `test_departmental_isolation_on_workload_endpoint`: Foreign investigator workload query returns 404 `INVESTIGATOR_NOT_FOUND`.
20. `test_canonical_case_reference_format_preserved`: `CASE-YYYY-XXXXX` format verified across assignment lifecycle.
21. `test_biometric_matching_strictly_disabled_cannot_be_overridden`: Permanent enforcement of `BIOMETRIC_MATCHING_ENABLED = False`.
22. `test_case_management_never_references_sealed_violence_partition`: Static audit ensures no references to the sealed violence test dataset ($N=354$).

### 4.2 Full Case Subsystem Regression Suite
**Command:** `uv run pytest tests/unit/cases/ --no-cov`  
**Result:** **125 passed / 125 tests in 2.75s**
- `test_cases_domain_and_service.py`: 36 passed
- `test_cases_group02_notes_workflow_export.py`: 44 passed
- `test_phase81_case_lifecycle_and_references.py`: 19 passed
- `test_phase82_assignment_workload_limits.py`: 26 passed

### 4.3 Biometric Subsystem Regression Suite (Batch 08 Invariants)
**Command:** `uv run pytest tests/unit/biometrics/ --no-cov`  
**Result:** **355 passed / 355 tests in 7.44s** (zero regressions across all 10 Batch 08 test suites).

---

## 5. Residual Limitations & Production Status

1. **Local Workload Caching**: Workload calculations execute an authoritative SQL count query against the `cases` table for every assignment operation. While pessimistic row locks on `users` prevent race conditions, high-throughput multi-tenant workloads in future batches may benefit from Redis-backed caching with transaction invalidation.
2. **Bulk Assignment Workflows**: Assignments are currently processed one case at a time. Bulk reassignment (e.g., reassigning all active cases when an investigator takes leave) is not yet implemented and remains deferred to administrative workflow expansions.
3. **Frontend UI Deferred**: Assignment forms, workload visual badges, and supervisor override dialogs remain unimplemented until Batch 12 (Phase 115).
4. **Production Gate**: The system remains under active architectural expansion; production deployment status is strictly **`NO-GO`**.

---

## 6. Handoff to Phase 83

- **Phase 82 Outcome:** `ACCEPTED WITH LIMITATIONS`
- **Next Phase:** Phase 83 — *Enriched Evidence Inventory & Legal Hold*
- **Handoff Directives:**
  - Build upon the established case lifecycle and assignment models.
  - Implement legal hold flags on evidence items linked to open or investigated cases, preventing evidence deletion or tampering while holds are active.
  - Maintain `BIOMETRIC_MATCHING_ENABLED = False` fail-closed guards.
  - Preserve multi-tenant departmental isolation and immutable append-only audit trails.
