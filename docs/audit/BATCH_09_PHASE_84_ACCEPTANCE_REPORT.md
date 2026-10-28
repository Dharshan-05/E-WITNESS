# E-WITNESS Security & Architecture Audit Report
## Batch 09, Phase 84: AI Segments in Case Files — Advisory Annotations Only

**Document Reference:** `docs/audit/BATCH_09_PHASE_84_ACCEPTANCE_REPORT.md`  
**Execution Timestamp:** 2026-10-28T13:03:00+05:30  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Phase:** 84 of 120  
**Phase Title:** AI Segments in Case Files — Advisory Annotations Only  
**Previous Phase:** Phase 83 (`ACCEPTED WITH LIMITATIONS`)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness Status:** `NO-GO` (Production deployment prohibited; fail-closed safety active)

---

### 1. Executive Summary

Phase 84 implements the secure, auditable integration of AI-generated video candidate segments into formal case dossiers as non-binding, probabilistic advisory annotations. The architecture strictly enforces human review precedence, model provenance validation, non-spoofable reviewer identity, temporal sanity constraints, legal hold immutability, optimistic concurrency control, and cross-department zero-leakage isolation.

All 22 rigorous verification requirements were evaluated and passed (`22/22`). Full regression testing verified `171/171` passed unit tests across the Case Management subsystem (Phases 81–84) and `355/355` passed unit tests across the Biometric Security and Governance subsystem (Batch 08). Permanent biometric matching disablement (`BIOMETRIC_MATCHING_ENABLED = False`) and zero access to the sealed historical violence-detection partition ($N=354$) remain strictly enforced.

---

### 2. Mandatory Safety & Governance Invariants

| Safety Invariant | Status | Enforcement Mechanism |
| :--- | :---: | :--- |
| **Biometric Matching Prohibition** | **PASS (ENFORCED)** | `BIOMETRIC_MATCHING_ENABLED = False` permanently hardcoded in application settings. All matching attempts fail closed with HTTP 403 `BiometricsDisabledError`. |
| **Zero Mass Surveillance / 1:N Search** | **PASS (ENFORCED)** | No 1:N facial search, automated suspect tagging, or facial identification endpoints exist in the system. |
| **Sealed Historical Partition ($N=354$)** | **PASS (ENFORCED)** | No access to the compromised historical violence-detection test partition. Verified by partition inspection and test isolation. |
| **Mandatory Advisory Disclaimer** | **PASS (ENFORCED)** | Statutory non-authoritative warning `AI_ADVISORY_DISCLAIMER` is injected into every AI segment read payload and case export. |
| **Human Review Precedence** | **PASS (ENFORCED)** | AI candidate segments default to `pending_review`. Model predictions cannot alter evidence status or case disposition without audited human review. |
| **Evidence Byte & Digest Immutability** | **PASS (ENFORCED)** | Attaching advisory segments never mutates master evidence bytes or SHA-256 digests. Digest traceability is preserved. |
| **Legal Hold Preservation** | **PASS (ENFORCED)** | Under active legal hold on either case or parent evidence, unlinking segments is rejected with HTTP 409 `LEGAL_HOLD_ACTIVE`. |
| **Departmental Zero-Leakage** | **PASS (ENFORCED)** | Cross-department access attempts return HTTP 404 `CASE_NOT_FOUND` or HTTP 404 `LINK_NOT_FOUND`, preventing resource existence disclosure. |

---

### 3. Implementation Details

#### 3.1 Data Model Validations & Constraints
- **Temporal Validity:** Validated $start \ge 0$, $end > start$, and duration calculations.
- **Duration Boundary Enforcement:** Segment boundary checked against known parent video duration ($end \le duration$). Out-of-bounds segments are rejected with `SEGMENT_EXCEEDS_DURATION`.
- **Score Range Verification:** Raw and calibrated confidence scores strictly bounded in $[0.0, 1.0]$. Non-finite values (`NaN`, `+Inf`, `-Inf`) are rejected with `INVALID_CONFIDENCE_SCORE`.
- **Model Provenance Verification:** Segment model names and versions validated against `APPROVED_AI_MODELS` via `validate_model_provenance`. Unrecognized models are rejected with `UNAPPROVED_MODEL_PROVENANCE`.

#### 3.2 Human Review Workflow & Optimistic Concurrency
- **Permission Scoping:** Creation and linking require `CASE_AI_SEGMENT_MANAGE`. Review determination requires `CASE_AI_SEGMENT_REVIEW`.
- **Conflict of Interest Guard:** Initial incident reporters are prohibited from acting as human reviewers for AI segments, raising `CONFLICT_OF_INTEREST`.
- **Review State Machine:** Permissible review transitions governed by `VALID_AI_SEGMENT_REVIEW_TRANSITIONS`:
  - `pending_review` $\to$ `under_review`, `confirmed`, `rejected`, `inconclusive`, `escalated`
  - `confirmed` $\to$ `rejected`, `escalated` (reverting to unreviewed or inconclusive is blocked)
  - `rejected` $\to$ `escalated` (direct confirmation without escalation is blocked)
  - `escalated` $\to$ `confirmed`, `rejected`, `inconclusive`
- **Non-Spoofable Reviewer Identity:** `reviewed_by_id` is derived strictly from the authenticated JWT session principal (`principal.user_id`), ignoring any client payload body spoofing.
- **Optimistic Concurrency Control:** `CaseAISegmentReviewRequest` supports `expected_review_status`. Mismatched concurrent updates are aborted with HTTP 409 `ConflictError`.

#### 3.3 Audit Trail & Provenance Traceability
- **Audit Actions:**
  - `CASE_AI_SEGMENT_LINKED`: Emitted upon advisory segment association, recording model provenance and parent evidence SHA-256 digest.
  - `CASE_AI_SEGMENT_REVIEWED`: Emitted upon human determination, recording previous state, new state, reviewer ID, rationale, and corrected label.
  - `CASE_AI_SEGMENT_UNLINKED`: Emitted upon advisory segment removal (gated by legal hold checks).
- **Audit History API:** `GET /cases/{case_id}/ai-segments/{segment_id}/history` provides an auditable chronological review log.
- **Atomic Rollback:** Failed creation/linking transactions emit failure audit records (`AuditOutcome.FAILURE`) and never fabricate misleading success events.

---

### 4. Verification Evidence & Test Execution

#### 4.1 Phase 84 Unit Test Suite
**Command:** `uv run pytest tests/unit/cases/test_phase84_ai_segments_in_case_files.py --no-cov -v`  
**Result:** **22 passed / 22 tests in 0.56s**

```
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_valid_advisory_segment_linked_to_authorized_case_evidence PASSED [  4%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_invalid_or_negative_segment_timestamps_rejected PASSED [  9%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_end_timestamp_preceding_or_equal_to_start_rejected PASSED [ 13%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_segment_exceeding_known_video_duration_rejected PASSED [ 18%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_invalid_confidence_values_rejected PASSED [ 22%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_missing_or_unverified_model_provenance_handled_explicitly PASSED [ 27%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_new_annotations_default_to_pending_review PASSED [ 31%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_unauthorized_review_decision_rejected PASSED [ 36%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_authorized_confirmation_rejection_and_inconclusive_decisions PASSED [ 40%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_invalid_review_state_transitions_rejected PASSED [ 45%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_reviewer_identity_cannot_be_spoofed PASSED [ 50%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_cross_department_access_denied PASSED [ 54%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_original_evidence_bytes_and_digest_remain_unchanged PASSED [ 59%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_legal_holds_remain_active_after_annotation_and_review PASSED [ 63%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_annotation_creation_failure_does_not_produce_misleading_success_audit PASSED [ 68%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_review_decisions_preserve_historical_audit_records PASSED [ 72%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_concurrent_review_updates_handled_safely PASSED [ 77%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_model_prediction_is_never_represented_as_legal_finding PASSED [ 81%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_biometric_matching_remains_disabled PASSED [ 86%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_no_access_to_sealed_historical_violence_partition PASSED [ 90%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_existing_phase81_phase82_phase83_regressions PASSED [ 95%]
tests/unit/cases/test_phase84_ai_segments_in_case_files.py::test_applicable_batch08_biometric_regression_tests PASSED [100%]
```

#### 4.2 Subsystem Regression Suites
- **Case Management Subsystem (Phases 81–84):** `uv run pytest tests/unit/cases/ --no-cov`  
  **Result:** **171 passed / 171 tests in 1.57s**
- **Biometric Governance Subsystem (Batch 08):** `uv run pytest tests/unit/biometrics/ --no-cov`  
  **Result:** **355 passed / 355 tests in 3.71s**

---

### 5. Verified Limitations & Residual Risks

1. **Non-Authoritative Advisory Scope:** Model inference is purely investigative assistance; automated classifications have no binding legal authority and must never be treated as evidence of guilt.
2. **Video Duration Metadata Reliance:** Duration validation relies on parsed container metadata in evidence records. In corrupted or unindexed video containers, duration validation falls back to segment-level boundaries.
3. **Application-Layer Tenant Isolation:** Departmental isolation is enforced at the repository and service layers with 404 masking; database engine row-level security (RLS) is scheduled for future infrastructure hardening.
4. **Permanent Biometric Disabled State:** Biometric matching remains disabled (`BIOMETRIC_MATCHING_ENABLED = False`). Production deployment remains strictly `NO-GO`.

---

### 6. Subsystem Sign-Off

- **Phase Status:** `ACCEPTED WITH LIMITATIONS`
- **Production Status:** `NO-GO`
- **Handoff Target:** Phase 85 (Human Review & AI Classification Correction / Override Workflows)
