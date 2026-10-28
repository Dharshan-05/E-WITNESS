# E-WITNESS Security & Architecture Audit Report
## Batch 09, Phase 88: Case Activity Timeline, Audit History & Operational Traceability

**Document Reference:** `docs/audit/BATCH_09_PHASE_88_ACCEPTANCE_REPORT.md`  
**Execution Timestamp:** 2026-10-28T19:12:00+05:30  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Phase:** 88 of 120  
**Phase Title:** Case Activity Timeline, Audit History & Operational Traceability  
**Previous Phase:** Phase 87 (`ACCEPTED WITH LIMITATIONS`)  
**Phase Outcome:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness Status:** `NO-GO` (Production deployment prohibited; fail-closed safety active)

---

### 1. Executive Summary

Phase 88 implements a unified, read-only case activity timeline, audit history, and operational traceability engine within the E-WITNESS Case Management Subsystem. The implementation unifies all case-related events into a chronological stream, capturing lifecycle transitions, supervisor reviews and approval decisions, assignment updates, evidence linkages, legal hold additions/removals, human reviews of AI candidate segments, and case note modifications.

The timeline engine enforces deterministic ordering with multi-field tie-breaking across `(timestamp, sequence_number, event_id)` and provides opaque base64 cursor pagination that cleanly handles high-frequency events sharing identical timestamps without skipping or duplicating records. Strict note visibility tier filtering prevents unauthorized exposure of confidential or restricted note events, and all note bodies, credentials, tokens, presigned URLs, and raw storage keys are systematically sanitized from timeline summaries and detail payloads.

All 29 verification tests in `tests/unit/cases/test_phase88_case_activity_timeline.py` passed (`29/29`). Subsystem regression testing verified `276/276` passed tests across the Case Management subsystem (Phases 81–88) and `355/355` passed tests across the Biometrics Governance subsystem (Batch 08). Biometric matching remains permanently disabled (`BIOMETRIC_MATCHING_ENABLED = False`), and zero access to the sealed historical violence-detection partition ($N=354$) is strictly verified.

---

### 2. Mandatory Safety & Governance Invariants

| Safety Invariant | Status | Enforcement Mechanism |
| :--- | :---: | :--- |
| **Biometric Matching Prohibition** | **PASS (ENFORCED)** | `BIOMETRIC_MATCHING_ENABLED = False` permanently locked. Biometric matching attempts raise `BiometricsDisabledError` (HTTP 403). |
| **Zero Mass Surveillance / 1:N Search** | **PASS (ENFORCED)** | No 1:N facial search, matching, identification, or automated suspect tagging endpoints exist in codebase. |
| **Sealed Historical Partition ($N=354$)** | **PASS (ENFORCED)** | Zero access to the historically compromised partition; verified by negative repository glob scans and strict test isolation. |
| **Evidence Byte & Digest Immutability** | **PASS (ENFORCED)** | Timeline event projection never alters evidence files, storage payloads, or cryptographic SHA-256 digests. |
| **Active Legal Hold Preservation** | **PASS (ENFORCED)** | Legal hold activations and releases are recorded as immutable timeline events; active holds continue protecting evidence from unlinking or deletion. |
| **Deterministic Tie-Breaking & Pagination** | **PASS (ENFORCED)** | Events sharing identical timestamps are deterministically tie-broken on `(timestamp, sequence_number or 0, str(id))`, preventing skips or duplicate delivery across cursor pages. |
| **Opaque Base64 Cursor Security** | **PASS (ENFORCED)** | Cursors are validated, tamper-resistant, base64-encoded composite state tuples. Tampered or malformed cursors fail safely with HTTP 422 `BusinessRuleError`. |
| **Note Visibility Tier Protection** | **PASS (ENFORCED)** | Confidential notes are restricted to author, lead investigator, and department admin. Restricted notes are restricted to author and admins with `CASE_NOTE_READ_RESTRICTED`. Note bodies/content are entirely stripped from event summaries and details. |
| **Sensitive Payload Exclusion** | **PASS (ENFORCED)** | Credentials, tokens, passwords, presigned URLs, and internal object storage keys are strictly stripped; only pre-approved safe keys (`SAFE_TIMELINE_DETAIL_KEYS`) are projected. |
| **Advisory AI Markers** | **PASS (ENFORCED)** | AI candidate segment review events carry `"is_advisory": True` and include `AI_ADVISORY_DISCLAIMER`; AI models cannot autonomously mutate case state. |
| **Departmental Zero-Leakage Isolation** | **PASS (ENFORCED)** | Cross-department timeline queries fail closed with HTTP 404 `CaseNotFoundError`, preventing unauthorized cross-tenant state or existence enumeration. |
| **Operational Traceability Audit** | **PASS (ENFORCED)** | Every timeline query generates an immutable audit record: `AuditAction.CASE_TIMELINE_ACCESSED` with target case ID, actor ID, and query parameters. |

---

### 3. Architecture & Implementation Changes

#### 3.1 Changed & Created Files

| File Path | Component | Changes & Responsibilities |
| :--- | :--- | :--- |
| `backend/app/core/authorization.py` | RBAC & Permissions | Added `Permission.CASE_TIMELINE_READ = "case:timeline:read"`. Assigned permission to `RoleCode.INVESTIGATOR`, `RoleCode.DEPT_ADMIN`, and `RoleCode.SUPER_ADMIN`. |
| `backend/app/core/audit.py` | Audit Constants | Added `AuditAction.CASE_TIMELINE_ACCESSED = "case:timeline:accessed"`. |
| `backend/app/schemas/case.py` | Schemas & DTOs | Added `CaseTimelineEventRead` and `CaseTimelineResponse`. Re-exported in `backend/app/schemas/__init__.py`. |
| `backend/app/repositories/audit.py` | Repository Layer | Implemented `list_events_for_case` supporting direct `target_id == case_id` and JSON payload `details.like(%"case_id": "...")%`, with filtering by action, actor, timestamp ranges, and deterministic sorting. |
| `backend/app/services/case.py` | Business Logic | Implemented cursor encoding/decoding (`_encode_timeline_cursor`, `_decode_timeline_cursor`), payload sanitization (`SAFE_TIMELINE_DETAIL_KEYS`), event group expansion (`TIMELINE_GROUP_EXPANSIONS`), human-readable summary synthesis (`_format_timeline_summary`), and `get_case_activity_timeline` with full RBAC, visibility tier enforcement, limit bounds validation, and audit emission. |
| `backend/app/api/v1/cases.py` | API Endpoints | Registered `GET /{case_id}/timeline` returning `CaseTimelineResponse` with query parameters (`cursor`, `limit`, `event_types`, `actor_id`, `start_time`, `end_time`, `outcome`, `reverse`). |
| `tests/unit/cases/test_phase88_case_activity_timeline.py` | Unit Test Suite | 29 automated tests verifying all Phase 88 functional and security requirements. |
| `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md` | Governance Matrix | Updated Phase 88 status to `ACCEPTED WITH LIMITATIONS`. |

---

### 4. Event Synthesis, Sanitization & Cursor Pagination Architecture

```
                       [ Incoming Timeline Query ]
                                    │
                                    ▼
                     [ 1. Authorization & RBAC ]
             (Permission.CASE_TIMELINE_READ & Dept Isolation)
             (Cross-department queries masked with HTTP 404)
                                    │
                                    ▼
                  [ 2. Parameter & Cursor Validation ]
             (Limit: 1..200; Time-range checks; Opaque Base64 Cursor)
                                    │
                                    ▼
                  [ 3. Audit Repository Event Query ]
             (target_id == case_id OR details["case_id"] == case_id)
             (Filters: Event Types, Actor ID, Time Range, Outcome)
                                    │
                                    ▼
                [ 4. Note Visibility Tier Evaluation ]
         ┌──────────────────────────┴──────────────────────────┐
         │ Confidential Note Event?                            │ Restricted Note Event?
         ▼                                                     ▼
   Author / Lead / DeptAdmin?                            Author / RestrictedAdmin?
   NO: Drop Event from Stream                            NO: Drop Event from Stream
   YES: Strip Note Content Body                          YES: Strip Note Content Body
         │                                                     │
         └──────────────────────────┬──────────────────────────┘
                                    │
                                    ▼
                 [ 5. Sensitive Payload Sanitization ]
            (Strip passwords, tokens, presigned URLs, storage keys)
            (Retain SAFE_TIMELINE_DETAIL_KEYS; enforce is_advisory=True)
                                    │
                                    ▼
              [ 6. Deterministic Sort & Cursor Page Slicing ]
           Order: (timestamp ASC/DESC, sequence_number, str(id))
           Slice: requested limit; generate next/prev base64 cursors
                                    │
                                    ▼
              [ 7. Audit Emission & Response Delivery ]
           (Emit AuditAction.CASE_TIMELINE_ACCESSED; return 200 OK)
```

---

### 5. Verification Test Suite (29/29 Passed)

All 29 tests in `tests/unit/cases/test_phase88_case_activity_timeline.py` passed:

| # | Test Case Identifier | Verification Scope | Status |
| :-: | :--- | :--- | :-: |
| 1 | `test_timeline_chronological_and_reverse_ordering` | Supports chronological (ASC) and reverse-chronological (DESC) ordering | **PASS** |
| 2 | `test_timeline_deterministic_tie_breaking_for_identical_timestamps` | Deterministic tie-breaking on `(timestamp, sequence_number, event_id)` | **PASS** |
| 3 | `test_timeline_cursor_pagination_forward_and_backward` | Cursor pagination forward and backward traversals | **PASS** |
| 4 | `test_timeline_cursor_pagination_with_shared_timestamps` | Pagination across events with identical timestamps without drops or duplicates | **PASS** |
| 5 | `test_timeline_malformed_cursor_rejected_with_bad_request` | Tampered/malformed base64 cursor rejected with HTTP 422 `BusinessRuleError` | **PASS** |
| 6 | `test_timeline_limit_bounds_validation` | Page limit bounds ($1 \le limit \le 200$) enforced | **PASS** |
| 7 | `test_timeline_invalid_time_range_rejected` | Invalid time range (`start_time > end_time`) rejected with HTTP 422 | **PASS** |
| 8 | `test_timeline_filtering_by_event_type_and_group_aliases` | Filtering by explicit action and category group aliases (`transition`, `review`, etc.) | **PASS** |
| 9 | `test_timeline_filtering_by_actor_id` | Filtering by specific actor UUID | **PASS** |
| 10 | `test_timeline_filtering_by_time_range` | Filtering within start and end datetime bounds | **PASS** |
| 11 | `test_timeline_filtering_by_outcome` | Filtering by `success` or `failure` outcome status | **PASS** |
| 12 | `test_timeline_department_isolation_and_404_masking` | Cross-department access attempts masked with HTTP 404 `CaseNotFoundError` | **PASS** |
| 13 | `test_timeline_unauthorized_caller_rejected_403` | Caller without `CASE_TIMELINE_READ` rejected with HTTP 403 `ForbiddenError` | **PASS** |
| 14 | `test_timeline_missing_case_returns_404` | Non-existent case ID returns HTTP 404 `CaseNotFoundError` | **PASS** |
| 15 | `test_timeline_note_visibility_tiers_confidential_filtering` | Confidential notes hidden from non-lead investigators; note body stripped | **PASS** |
| 16 | `test_timeline_note_visibility_tiers_restricted_filtering` | Restricted notes hidden from callers without `CASE_NOTE_READ_RESTRICTED` | **PASS** |
| 17 | `test_timeline_note_access_denied_events_isolated` | Note access denied events isolated to authorized administrative roles | **PASS** |
| 18 | `test_timeline_sensitive_payloads_excluded_no_note_bodies_or_storage_keys` | Passwords, tokens, presigned URLs, and raw storage keys strictly stripped | **PASS** |
| 19 | `test_timeline_evidence_events_preserve_hashes_and_exclude_credentials` | Evidence events retain SHA-256 digests while omitting storage credentials | **PASS** |
| 20 | `test_timeline_legal_hold_events_preserve_active_holds` | Legal hold activation/release events present with hold rationale | **PASS** |
| 21 | `test_timeline_ai_review_events_remain_strictly_advisory` | AI candidate segment events carry `is_advisory=True` and advisory disclaimer | **PASS** |
| 22 | `test_timeline_approvals_and_rejections_accurately_represented` | Approval and rejection decisions accurately represented with rationales | **PASS** |
| 23 | `test_timeline_failed_attempts_distinguished_from_success` | Failed attempts marked with outcome `failure` and distinguished from success | **PASS** |
| 24 | `test_timeline_idempotent_duplicate_requests_do_not_create_duplicate_success_events` | Idempotent duplicate requests do not create duplicate success events | **PASS** |
| 25 | `test_timeline_inconsistent_or_corrupt_details_fail_safely` | Corrupted JSON details fail safely with unparsed summary and empty details | **PASS** |
| 26 | `test_timeline_audit_event_recorded_on_access` | `AuditAction.CASE_TIMELINE_ACCESSED` recorded upon timeline access | **PASS** |
| 27 | `test_biometric_matching_remains_disabled_in_phase88` | `BIOMETRIC_MATCHING_ENABLED = False` permanently locked fail-closed | **PASS** |
| 28 | `test_sealed_historical_violence_partition_is_not_accessed` | Historically exposed partition ($N=354$) remains isolated | **PASS** |
| 29 | `test_relevant_phase81_to_87_regression_behavior_intact` | References, assignments, legal holds, reviews, and approval regressions intact | **PASS** |

---

### 6. Full Subsystem Regression Results

1. **Case Management Subsystem (Phases 81–88):**
   - Command: `uv run pytest tests/unit/cases/ -v --no-cov`
   - Result: **`276 passed in 10.21s`** (0 failures, 0 errors).
2. **Biometrics Governance Subsystem (Batch 08):**
   - Command: `uv run pytest tests/unit/biometrics/ --no-cov`
   - Result: **`355 passed in 12.73s`** (0 failures, 0 errors).

---

### 7. Limitations & Residual Risks

1. **Audit Table Case-ID Indexing:** Events linked via JSON string pattern matching (`details.like(%"case_id": "...")%`) should be accelerated with a dedicated `case_id` foreign key index on the `audit_events` table in production PostgreSQL migrations.
2. **Read Replica Routing:** High-volume timeline reads should be directed to a database read replica in production environments to avoid contention with primary transaction writes.
3. **External KMS Vault Non-Durable in Dev:** The cryptographic vault fallback remains `is_durable=False` in development/test environments.
4. **Production Readiness:** The subsystem remains explicitly designated as **`NO-GO`** for production deployment until end-to-end integration (Phase 90) and deployment hardening are completed.

---

### 8. Phase Acceptance Decision

**Verdict:** `ACCEPTED WITH LIMITATIONS`  
Phase 88 satisfies all requirements for unified case activity timeline projection, deterministic cursor pagination, note visibility protection, sensitive credential sanitization, departmental isolation, and operational audit traceability.
