# E-WITNESS Security & Architecture Audit Report
## Batch 09, Phase 87: Investigation Transitions & Approvals

**Document Reference:** `docs/audit/BATCH_09_PHASE_87_ACCEPTANCE_REPORT.md`  
**Execution Timestamp:** 2026-10-28T16:05:00+05:30  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Phase:** 87 of 120  
**Phase Title:** Investigation Transitions & Approvals  
**Previous Phase:** Phase 86 (`ACCEPTED WITH LIMITATIONS`)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness Status:** `NO-GO` (Production deployment prohibited; fail-closed safety active)

---

### 1. Executive Summary

Phase 87 implements a formal, server-side investigation transition and approval workflow within the E-WITNESS Case Management Subsystem. The implementation establishes an audited, deterministic lifecycle state machine that governs case progression through formal statuses (`DRAFT`, `OPEN`, `UNDER_INVESTIGATION`, `PENDING_REVIEW`, `PENDING_SUPERVISOR_REVIEW`, `SUSPENDED`, `RESOLVED`, `CLOSED`, and `REOPENED`).

Direct status bypass via generic update endpoints (`update_case`) is strictly prohibited; all status mutations must satisfy workflow permissions and centralized readiness gates (`validate_case_transition_readiness`). A hardened supervisor approval pipeline (`submit_case_for_review`, `list_pending_approvals`, `approve_case_transition`) enforces strict separation of duties, preventing lead investigators and review submitters from approving their own cases (`SELF_APPROVAL_PROHIBITED`, HTTP 403). Concurrency control is enforced via optimistic version checks (`expected_version_id`), immediately rejecting conflicting concurrent decisions with HTTP 409 `ConflictError`, while identical approval requests are processed idempotently.

All 28 verification requirements in `tests/unit/cases/test_phase87_investigation_transitions_approvals.py` passed (`28/28`). Regression testing verified `247/247` passed tests across the Case Management subsystem (Phases 81–87) and `355/355` passed tests across the Biometric Governance subsystem (Batch 08). Biometric matching remains permanently disabled (`BIOMETRIC_MATCHING_ENABLED = False`), and zero access to the sealed historical violence-detection partition ($N=354$) is strictly preserved.

---

### 2. Mandatory Safety & Governance Invariants

| Safety Invariant | Status | Enforcement Mechanism |
| :--- | :---: | :--- |
| **Biometric Matching Prohibition** | **PASS (ENFORCED)** | `BIOMETRIC_MATCHING_ENABLED = False` permanently hardcoded. All face matching calls fail closed with HTTP 403 `BiometricsDisabledError`. |
| **Zero Mass Surveillance / 1:N Search** | **PASS (ENFORCED)** | Zero 1:N facial search, matching, identification, or automated suspect tagging endpoints exist in codebase. |
| **Sealed Historical Partition ($N=354$)** | **PASS (ENFORCED)** | Zero access to the historically compromised partition; verified by negative repository glob scans and strict test isolation. |
| **Evidence Byte & Digest Immutability** | **PASS (ENFORCED)** | Case transitions and supervisory approvals never modify original evidence files, attachment records, or cryptographic SHA-256 hashes. |
| **Active Legal Hold Preservation** | **PASS (ENFORCED)** | Active legal holds (`is_legal_hold = True` and linked `LegalHold` records) remain active and intact across transitions, suspensions, and closures. |
| **Separation of Duties** | **PASS (ENFORCED)** | Supervisors who are assigned as lead investigator or who submitted the case for review are blocked from approving or rejecting the case (`SELF_APPROVAL_PROHIBITED`, HTTP 403). |
| **Optimistic Concurrency Control** | **PASS (ENFORCED)** | Transitions and approvals enforce `expected_version_id`. Stale requests return HTTP 409 `ConflictError` before executing conflicting state updates. |
| **Centralized Readiness Validation** | **PASS (ENFORCED)** | Centralized `validate_case_transition_readiness` validates lead investigator assignment, linked incidents, findings/notes, unreviewed AI candidate segments, and legal holds without inventing data. |
| **Mandatory Rejection Rationale** | **PASS (ENFORCED)** | Rejection or changes-requested decisions require a documented rationale of at least 10 non-whitespace characters (`RATIONALE_REQUIRED`). |
| **Departmental Zero-Leakage Isolation** | **PASS (ENFORCED)** | Cross-department access attempts fail closed with HTTP 404 `CaseNotFoundError`, preventing unauthorized cross-tenant state or existence enumeration. |
| **Non-Spoofable Actor Identity** | **PASS (ENFORCED)** | Actor identity and authority are derived exclusively from verified JWT authentication tokens, never client-supplied JSON payloads. |
| **Advisory AI Annotations** | **PASS (ENFORCED)** | Violence-detection predictions remain advisory annotations (`AI_ADVISORY_DISCLAIMER`); AI predictions cannot autonomously trigger transitions or closures. |

---

### 3. Architecture & Implementation Changes

#### 3.1 Changed & Created Files

| File Path | Component | Changes & Responsibilities |
| :--- | :--- | :--- |
| `backend/app/core/case.py` | State Machine | Updated `VALID_CASE_TRANSITIONS` to disallow direct closure jumps from `DRAFT` (must transition `DRAFT -> OPEN`). |
| `backend/app/core/authorization.py` | RBAC & Permissions | Added permissions: `Permission.CASE_TRANSITION_SUBMIT`, `CASE_TRANSITION_PERFORM`, `CASE_APPROVAL_READ`, and `CASE_TRANSITION_HISTORY_READ`. Assigned permissions to `RoleCode.INVESTIGATOR`, `RoleCode.DEPT_ADMIN`, and `RoleCode.SUPER_ADMIN`. |
| `backend/app/core/audit.py` | Audit Constants | Added audit actions: `AuditAction.CASE_SUBMITTED_FOR_REVIEW`, `CASE_APPROVAL_REJECTED`, `CASE_SELF_APPROVAL_BLOCKED`, and `CASE_TRANSITION_FAILED`. |
| `backend/app/schemas/case.py` | Schemas & DTOs | Added `CaseSubmitReviewRequest`, `CaseReadinessCheck`, `CaseReadinessResult`, and `CaseTransitionHistoryItem`. Re-exported in `backend/app/schemas/__init__.py`. |
| `backend/app/repositories/case.py` | Repository Layer | Added `get_by_id_for_update(case_id)` and `list_pending_approvals(department_id, limit, offset)`. |
| `backend/app/services/case.py` | Business Logic | Implemented `validate_case_transition_readiness`, `get_case_readiness`, `transition_case_status`, `submit_case_for_review`, `approve_case_transition`, `list_pending_approvals`, and `get_case_transition_history`. Enforced separation of duties, optimistic version locking, rationale length checks, and direct status update guards. |
| `backend/app/api/v1/cases.py` | API Endpoints | Added endpoints: `GET /pending-approvals`, `POST /{case_id}/submit-for-review`, `GET /{case_id}/readiness`, and `GET /{case_id}/transitions/history`. |
| `tests/unit/cases/test_phase87_investigation_transitions_approvals.py` | Unit Test Suite | 28 automated tests covering all Phase 87 requirements. |
| `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md` | Governance Matrix | Updated Phase 87 status to `ACCEPTED WITH LIMITATIONS`. |

---

### 4. Transition State Machine & Approval Workflow

```
       +---------+
       |  DRAFT  |
       +----+----+
            |
            v
       +----+----+       (Investigator Assigned, Incident Linked)
       |  OPEN   | ------------------------------------+
       +----+----+                                     |
            |                                          |
            v                                          v
   +--------+-------------+                  +---------+-----------+
   | UNDER_INVESTIGATION  | <--------------+ |      SUSPENDED      |
   +----+-----------------+  (Rejection)     +---------+-----------+
        |                                              ^
        | submit_for_review                            |
        v                                              |
   +----+--------------------+                         |
   | PENDING_SUPERVISOR_     |                         |
   | REVIEW                  |                         |
   +----+--------------------+                         |
        |                                              |
        | approve_case_transition                      |
        | (Separation of duties enforced)              |
        v                                              |
   +----+--------------------+                         |
   |   RESOLVED / CLOSED     | ------------------------+
   +----+--------------------+
        |
        | (Approved Reopen Policy)
        v
   +----+--------------------+
   |       REOPENED          |
   +-------------------------+
```

---

### 5. Verification Test Suite (28/28 Passed)

All 28 tests in `tests/unit/cases/test_phase87_investigation_transitions_approvals.py` passed:

| # | Test Case Identifier | Verification Scope | Status |
| :-: | :--- | :--- | :-: |
| 1 | `test_valid_lifecycle_transitions` | Permitted lifecycle transitions succeed | **PASS** |
| 2 | `test_invalid_transitions_rejected` | Disallowed lifecycle jumps fail closed | **PASS** |
| 3 | `test_direct_status_mutation_cannot_bypass_workflow_validation` | `update_case` enforces workflow authorization & readiness | **PASS** |
| 4 | `test_authorized_submission_for_supervisor_review` | Authorized submission advances status and emits audit event | **PASS** |
| 5 | `test_unauthorized_submission_rejected` | Unauthorized role/state submissions fail closed | **PASS** |
| 6 | `test_authorized_supervisor_approval` | Supervisor approval transitions status and records approval | **PASS** |
| 7 | `test_unauthorized_approval_rejected` | Non-supervisory callers cannot record approval decisions | **PASS** |
| 8 | `test_rejection_requires_defined_rationale` | Rejection requires $\ge 10$-character documented rationale | **PASS** |
| 9 | `test_self_approval_blocked_by_separation_of_duties` | Lead investigator / submitter self-approval blocked (403) | **PASS** |
| 10 | `test_case_reopening_follows_approved_policy` | Case reopening transitions to `REOPENED` with audit event | **PASS** |
| 11 | `test_client_supplied_reviewer_identity_cannot_be_spoofed` | Actor identity derived strictly from verified principal | **PASS** |
| 12 | `test_client_supplied_roles_or_permissions_cannot_grant_authority` | Client role claims in payload cannot bypass RBAC | **PASS** |
| 13 | `test_cross_department_approvals_and_transitions_denied` | Cross-department operations masked with HTTP 404 | **PASS** |
| 14 | `test_stale_case_versions_return_conflict` | Stale `expected_version_id` raises HTTP 409 Conflict | **PASS** |
| 15 | `test_concurrent_approvals_cannot_finalize_incompatible_outcomes` | Competing decisions fail closed on version conflict | **PASS** |
| 16 | `test_duplicate_requests_follow_idempotency_policy` | Duplicate identical approval submissions return existing record | **PASS** |
| 17 | `test_case_readiness_checks_reject_missing_mandatory_information` | Readiness checks flag missing investigator, incidents, AI reviews | **PASS** |
| 18 | `test_readiness_checks_do_not_invent_or_assume_unavailable_data` | Missing prerequisites produce explicit blocking reasons | **PASS** |
| 19 | `test_legal_holds_remain_intact_during_transitions` | Active legal holds preserved across all transitions and closures | **PASS** |
| 20 | `test_evidence_bytes_and_sha256_digests_remain_unchanged` | Master evidence bytes and digests remain unaltered | **PASS** |
| 21 | `test_case_note_visibility_rules_respected_in_approval_payloads` | Restricted/confidential notes are not leaked in approvals | **PASS** |
| 22 | `test_ai_annotations_remain_advisory_cannot_automatically_close_cases` | AI model scores cannot autonomously close cases | **PASS** |
| 23 | `test_transition_and_approval_history_is_preserved` | Chronological transition and approval history retrieved | **PASS** |
| 24 | `test_audit_events_match_committed_state_changes` | Security audit events emitted for lifecycle transitions | **PASS** |
| 25 | `test_failed_transactions_do_not_leave_misleading_success_events` | Failed transitions emit failure events, not success | **PASS** |
| 26 | `test_biometric_matching_remains_disabled` | `BIOMETRIC_MATCHING_ENABLED = False` permanently locked | **PASS** |
| 27 | `test_sealed_historical_violence_partition_is_not_accessed` | Compromised partition ($N=354$) remains isolated | **PASS** |
| 28 | `test_relevant_phase81_to_86_regression_behavior_intact` | References, workloads, and queue filtering intact | **PASS** |

---

### 6. Full Subsystem Regression Results

1. **Case Management Subsystem (Phases 81–87):**
   - Command: `uv run pytest tests/unit/cases/ -v --no-cov`
   - Result: **`247 passed in 3.31s`** (0 failures, 0 errors).
2. **Biometrics Governance Subsystem (Batch 08):**
   - Command: `uv run pytest tests/unit/biometrics/ --no-cov`
   - Result: **`355 passed in 4.70s`** (0 failures, 0 errors).

---

### 7. Limitations & Residual Risks

1. **In-Memory Approvals Query Join:** In `get_case_transition_history`, approval records and audit events are merged and sorted in memory rather than via a single consolidated SQL view. While performant for typical case volumes ($\le 500$ transition events), a database-level view or materialized history table should be considered for large-scale enterprise deployments.
2. **Single Lead Reviewer Assumption:** The current workflow models a single `lead_investigator_id` per case. Joint investigation multi-lead assignments are deferred to future enterprise extensions.
3. **External KMS Vault Non-Durable in Dev:** The cryptographic vault fallback remains `is_durable=False` in development/test environments.
4. **Production Readiness:** The subsystem remains explicitly designated as **`NO-GO`** for production deployment until end-to-end integration (Phase 90) and deployment hardening are completed.

---

### 8. Phase Acceptance Decision

**Verdict:** `ACCEPTED WITH LIMITATIONS`  
Phase 87 satisfies all requirements for formal investigation transitions, separation of duties, supervisor approval pipelines, readiness validation, and audit tracking.
