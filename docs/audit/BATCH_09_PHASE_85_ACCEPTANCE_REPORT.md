# E-WITNESS Security & Architecture Audit Report
## Batch 09, Phase 85: Human Review & AI Classification Correction / Override Workflows

**Document Reference:** `docs/audit/BATCH_09_PHASE_85_ACCEPTANCE_REPORT.md`  
**Execution Timestamp:** 2026-10-28T14:40:00+05:30  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Phase:** 85 of 120  
**Phase Title:** Human Review & AI Classification Correction / Override Workflows  
**Previous Phase:** Phase 84 (`ACCEPTED WITH LIMITATIONS`)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness Status:** `NO-GO` (Production deployment prohibited; fail-closed safety active)

---

### 1. Executive Summary

Phase 85 establishes an auditable, controlled human-review, classification correction, and supervisor override framework for AI-generated candidate segments linked to investigative case files. The subsystem guarantees that machine-generated violence detections remain strictly probabilistic advisory cues. Authorized investigators and supervisors can record human review determinations (`confirmed`, `rejected`, `inconclusive`, `escalated`), correct misclassifications, and execute audited supervisor overrides while preserving original model outputs, confidence metrics, and timestamps in perpetuity.

All 22 verification requirements specified in the execution charter were validated and passed (`22/22`). Full regression testing verified `193/193` passed unit tests across the Case Management subsystem (Phases 81–85) and `355/355` passed unit tests across the Biometric Security and Governance subsystem (Batch 08). Permanent biometric matching disablement (`BIOMETRIC_MATCHING_ENABLED = False`) and zero access to the sealed historical violence-detection partition ($N=354$) remain strictly enforced.

---

### 2. Mandatory Safety & Governance Invariants

| Safety Invariant | Status | Enforcement Mechanism |
| :--- | :---: | :--- |
| **Biometric Matching Prohibition** | **PASS (ENFORCED)** | `BIOMETRIC_MATCHING_ENABLED = False` permanently hardcoded in application settings. All matching attempts fail closed with HTTP 403 `BiometricsDisabledError`. |
| **Zero Mass Surveillance / 1:N Search** | **PASS (ENFORCED)** | No 1:N facial search, automated suspect tagging, or facial identification endpoints exist in the system. |
| **Sealed Historical Partition ($N=354$)** | **PASS (ENFORCED)** | No access to the compromised historical violence-detection test partition. Verified by partition inspection and test isolation. |
| **Mandatory Advisory Disclaimer** | **PASS (ENFORCED)** | Statutory non-authoritative warning `AI_ADVISORY_DISCLAIMER` is injected into every AI segment read payload, review response, and case export. |
| **Probabilistic Non-Dispositive Inference** | **PASS (ENFORCED)** | AI candidate segment determinations cannot automatically close cases, adjudicate guilt, or create binding case dispositions without human workflow. |
| **Model Output Immutability** | **PASS (ENFORCED)** | Original model name, version, raw confidence, calibrated score, and initial label are captured in `original_ai_prediction` upon first review and remain immutable across all subsequent revisions. |
| **Supervisor-Only Overrides** | **PASS (ENFORCED)** | Standard investigators (`ROLE_INVESTIGATOR`) are prohibited from overriding determinations or passing `is_override=True`. Overrides strictly require `CASE_AI_SEGMENT_OVERRIDE`, restricted to `ROLE_DEPT_ADMIN` and `ROLE_SUPER_ADMIN`. |
| **Reviewer Independence & Conflict of Interest** | **PASS (ENFORCED)** | Incident reporters are prohibited from acting as human reviewers for segments associated with their reported incident, returning HTTP 403 `CONFLICT_OF_INTEREST`. |
| **Non-Spoofable Reviewer Identity** | **PASS (ENFORCED)** | `reviewed_by_id` is derived strictly from the authenticated JWT session principal (`principal.user_id`). Client attempts to inject spoofed reviewer identities are rejected. |
| **Evidence Byte & Digest Immutability** | **PASS (ENFORCED)** | Human reviews, classification corrections, and overrides never alter master evidence bytes or SHA-256 digests. |
| **Legal Hold Preservation** | **PASS (ENFORCED)** | Active legal holds on case files or underlying evidence strictly block segment unlinking with HTTP 409 `LEGAL_HOLD_ACTIVE`. |
| **Departmental Zero-Leakage** | **PASS (ENFORCED)** | Cross-department access attempts return HTTP 404 `CASE_NOT_FOUND` or HTTP 404 `LINK_NOT_FOUND`, preventing resource existence disclosure. |

---

### 3. Architecture & Implementation Changes

#### 3.1 Changed & Created Files

| File Path | Component | Changes & Responsibilities |
| :--- | :--- | :--- |
| `backend/app/core/authorization.py` | Authorization Core | Added `Permission.CASE_AI_SEGMENT_OVERRIDE = "case:ai_segment:override"`. Assigned strictly to `RoleCode.DEPT_ADMIN` and `RoleCode.SUPER_ADMIN`; withheld from `RoleCode.INVESTIGATOR`. |
| `backend/app/core/audit.py` | Audit Constants | Added `AuditAction.CASE_AI_SEGMENT_OVERRIDDEN`, `CASE_AI_SEGMENT_CLASSIFICATION_CORRECTED`, `CASE_AI_SEGMENT_ESCALATED`, and `CASE_AI_SEGMENT_OVERRIDE_REJECTED`. |
| `backend/app/schemas/case.py` | API Schemas | Extended `CaseAISegmentReviewRequest` with `expected_revision` and `is_override: bool = False`. Extended `CaseAISegmentRead` with `original_ai_prediction`, `current_human_decision`, `human_corrected_label`, `decision_revision`, `is_override`. Extended `CaseAISegmentHistoryItemRead` with `is_override` and `decision_revision`. |
| `backend/app/services/case.py` | Business Logic | Updated `review_ai_segment` with: optimistic concurrency checks, state transition validation, conflict-of-interest checks, supervisor override enforcement, original prediction freezing, append-only metadata revision history, evidence digest lookup, and granular audit event emissions. Implemented `get_case_ai_segment_review_history` with chronological sorting. |
| `backend/app/api/v1/cases.py` | API Endpoints | Updated `review_ai_segment` route to require either `CASE_AI_SEGMENT_REVIEW` or `CASE_AI_SEGMENT_OVERRIDE`. Added explicit supervisor endpoint `POST /{case_id}/ai-segments/{segment_id}/override` guarded by `CASE_AI_SEGMENT_OVERRIDE`. |
| `tests/unit/cases/test_phase85_ai_review_correction_overrides.py` | Test Suite | 22 comprehensive unit tests covering all required areas. |
| `docs/audit/BATCH_09_PHASE_85_ACCEPTANCE_REPORT.md` | Audit Record | Formal audit report for Phase 85. |
| `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md` | Governance Matrix | Updated Phase 85 to `ACCEPTED WITH LIMITATIONS`. |

#### 3.2 Review and Override State-Transition Rules

Permissible transitions are strictly enforced via `VALID_AI_SEGMENT_REVIEW_TRANSITIONS` in `backend/app/core/case.py`:

```
                 +-------------------+
                 |  pending_review   |
                 +---------+---------+
                           |
        +------------------+------------------+
        |                  |                  |
        v                  v                  v
  +-----------+      +-----------+      +------------+
  | confirmed |      | rejected  |      | inconclusive|
  +-----+-----+      +-----+-----+      +------------+
        |                  |
        | (override only)  | (escalation only)
        v                  v
  +-----------+      +-----------+
  | rejected  |      | escalated |
  +-----------+      +-----+-----+
                           |
              +------------+------------+
              |                         |
              v                         v
        +-----------+             +-----------+
        | confirmed |             | rejected  |
        +-----------+             +-----------+
```

- `pending_review` $\to$ `under_review`, `confirmed`, `rejected`, `inconclusive`, `escalated`
- `under_review` $\to$ `confirmed`, `rejected`, `inconclusive`, `escalated`
- `confirmed` $\to$ `rejected` (requires supervisor override or new revision), `escalated`
- `rejected` $\to$ `escalated` (direct jump from `rejected` to `confirmed` is rejected without escalation/override)
- `inconclusive` $\to$ `under_review`, `confirmed`, `rejected`, `escalated`
- `escalated` $\to$ `confirmed`, `rejected`, `inconclusive`

#### 3.3 Permission and Reviewer-Independence Matrix

| Action / Operation | Required Permission | Allowed Roles | Prohibited Roles | Independence Guards |
| :--- | :--- | :--- | :--- | :--- |
| **Initial Review** | `CASE_AI_SEGMENT_REVIEW` | `INVESTIGATOR`, `DEPT_ADMIN`, `SUPER_ADMIN` | `OFFICER`, `COMMUNITY_LEADER`, `AUDITOR` | Derived strictly from JWT principal; incident reporters blocked from reviewing incident segments (`CONFLICT_OF_INTEREST`, 403). |
| **Classification Correction** | `CASE_AI_SEGMENT_REVIEW` | `INVESTIGATOR`, `DEPT_ADMIN`, `SUPER_ADMIN` | `OFFICER`, `COMMUNITY_LEADER`, `AUDITOR` | Frozen in metadata; model outputs remain immutable in `original_ai_prediction`. |
| **Supervisor Override** | `CASE_AI_SEGMENT_OVERRIDE` | `DEPT_ADMIN`, `SUPER_ADMIN` | `INVESTIGATOR` (prohibited from overrides or `is_override=True`) | Attempting override without permission returns HTTP 403 `PermissionDeniedError` and emits `CASE_AI_SEGMENT_OVERRIDE_REJECTED`. |
| **History Inspection** | `CASE_AI_SEGMENT_REVIEW` | `INVESTIGATOR`, `DEPT_ADMIN`, `SUPER_ADMIN` | `OFFICER`, `COMMUNITY_LEADER`, `AUDITOR` | Department isolation enforced; cross-department access returns HTTP 404 (zero leakage). |

#### 3.4 Original-Prediction Preservation Design

When an AI candidate segment is first reviewed:
1. `original_ai_prediction` is initialized from the candidate segment:
   ```json
   {
     "label": segment.raw_label,
     "raw_score": segment.raw_score,
     "calibrated_score": segment.calibrated_score,
     "model_name": segment.model_name,
     "model_version": segment.model_version
   }
   ```
2. Subsequent classification corrections modify `human_corrected_label` and `label` in the active representation, but `original_ai_prediction` is immutable.
3. Every human action appends an immutable revision dictionary into `metadata["revisions"]`:
   ```json
   {
     "revision": new_revision,
     "decision": payload.review_status,
     "previous_status": old_status,
     "reviewer_id": str(principal.user_id),
     "rationale": payload.review_rationale,
     "timestamp": datetime.now(UTC).isoformat(),
     "is_override": is_override,
     "corrected_label": payload.corrected_label
   }
   ```
4. `decision_revision` increments monotonically.
5. `current_human_decision` and `human_corrected_label` are explicitly segregated from `original_ai_prediction` in API responses.

#### 3.5 Concurrency Controls & Transaction Handling

- **Optimistic Concurrency:** Clients pass `expected_review_status` and/or `expected_revision`. If the database state diverges, the operation rejects immediately with HTTP 409 `ConflictError`.
- **Idempotency:** When a client retries the identical request (identical status, corrected label, and rationale), the service returns the existing state without incrementing `decision_revision` and without appending duplicate audit records.
- **Transaction Rollback:** In the event of an unhandled exception or transaction failure during segment mutation, the database transaction rolls back completely. No misleading success audit records are written.

---

### 4. Verification Evidence & Test Execution

#### 4.1 Phase 85 Unit Test Suite
**Command:** `uv run pytest tests/unit/cases/test_phase85_ai_review_correction_overrides.py -v --no-cov`  
**Result:** **22 passed / 22 tests** (100% pass rate in 0.60s)

| Test Name | Verification Focus | Result |
| :--- | :--- | :---: |
| `test_authorized_review_decision` | Authorized investigator can confirm, reject, escalate, or set inconclusive | **PASS** |
| `test_classification_correction_preserves_original_ai_prediction` | Classification correction records human label while preserving model scores | **PASS** |
| `test_override_creates_new_revision_and_retains_old_decision` | Supervisor override creates new revision, retains history, updates relevance | **PASS** |
| `test_unauthorized_override_is_rejected` | Unauthorized investigator override rejected with 403 & audited failure | **PASS** |
| `test_client_cannot_spoof_reviewer_identity` | Reviewer identity derived strictly from authenticated token | **PASS** |
| `test_client_supplied_role_or_override_flag_cannot_grant_privileges` | Client payload cannot elevate role or override flag | **PASS** |
| `test_missing_or_inadequate_rationale_rejected` | Empty, missing, or whitespace rationale rejected with 422 | **PASS** |
| `test_stale_expected_version_returns_conflict` | Stale expected status or revision returns HTTP 409 Conflict | **PASS** |
| `test_concurrent_review_updates_cannot_silently_overwrite` | Concurrent race conditions detected via optimistic versioning | **PASS** |
| `test_invalid_review_state_transitions_rejected` | Direct invalid state transitions (rejected $\to$ confirmed) rejected | **PASS** |
| `test_conflict_of_interest_restrictions_enforced` | Incident reporter prohibited from reviewing incident segments (403) | **PASS** |
| `test_cross_department_correction_and_history_denied` | Cross-department access attempts return HTTP 404 (zero leakage) | **PASS** |
| `test_legal_holds_remain_effective` | Active legal hold blocks unlinking/deletion of reviewed segment (HTTP 409) | **PASS** |
| `test_original_evidence_bytes_and_digest_remain_unchanged` | Review determinations never mutate master evidence bytes or SHA-256 digest | **PASS** |
| `test_audit_history_remains_ordered_and_append_only` | Review history is strictly append-only and chronologically ordered | **PASS** |
| `test_failed_transactions_do_not_leave_misleading_success_audit` | Rolled back review transactions do not generate success audit events | **PASS** |
| `test_repeated_requests_and_retries_idempotent` | Identical retries return existing state without revision increment | **PASS** |
| `test_superseded_decisions_cannot_be_edited_through_stale_requests` | Historical revisions cannot be modified through stale references | **PASS** |
| `test_advisory_disclaimer_present_in_all_responses` | Statutory advisory disclaimer injected into review responses | **PASS** |
| `test_ai_decisions_cannot_automatically_close_cases_or_create_findings` | AI review decisions cannot mutate case lifecycle status | **PASS** |
| `test_biometric_matching_remains_disabled` | `BIOMETRIC_MATCHING_ENABLED = False` permanently locked; fail-closed | **PASS** |
| `test_sealed_historical_violence_partition_is_not_accessed` | Historically exposed test partition ($N=354$) remains inaccessible | **PASS** |

#### 4.2 Full Subsystem Regression Testing
- **Case Management Subsystem (Phases 81–85):**  
  **Command:** `uv run pytest tests/unit/cases/ --no-cov`  
  **Result:** **193 passed / 193 tests** (100% pass rate in 2.24s)
- **Biometric Governance Subsystem (Batch 08):**  
  **Command:** `uv run pytest tests/unit/biometrics/ --no-cov`  
  **Result:** **355 passed / 355 tests** (100% pass rate in 4.45s)

---

### 5. Remaining Limitations & Handoff to Phase 86

1. **Production Status Remains `NO-GO`:** Production deployment is strictly prohibited pending full Batch 09 completion and end-to-end integration hardening.
2. **Biometrics Fail-Closed:** `BIOMETRIC_MATCHING_ENABLED = False` remains permanently in effect.
3. **Partition Sealing:** Sealed violence-detection test partition ($N=354$) remains isolated.
4. **Handoff to Phase 86:**
   - Foundation established: Immutable AI advisory segments, review determinations, classification corrections, and supervisor overrides.
   - Phase 86 Mission: Implement Case Notes, Visibility Tiers (`public`, `internal`, `confidential`, `restricted`), and Append-Only Note History.
