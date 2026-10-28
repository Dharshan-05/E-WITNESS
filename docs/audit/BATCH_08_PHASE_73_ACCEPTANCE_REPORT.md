# E-WITNESS — Batch 08, Phase 73 Acceptance Report
## Biometric Data Governance, Consent, Retention & Revocation Audit

**Project:** E-WITNESS (High-Assurance Evidence Management Platform)  
**Batch:** 08 — Biometric Privacy, Governance & Face Verification  
**Phase:** 73 of 120  
**Audit Date:** 2026-10-27  
**Auditor:** ML Test Engineer & Dataset-Governance Auditor  
**Gate Status:** `ACCEPTED WITH LIMITATIONS`  
**Production Readiness:** `NO-GO` (Automated matching prohibited; system not approved for live deployment)  
**Mandatory Safety Invariant:** `BIOMETRIC_MATCHING_ENABLED = False` permanently enforced across all runtime configurations

---

## 1. Executive Summary & Audit Decision

Phase 73 of the E-WITNESS roadmap implements and verifies the **Biometric Data Governance, Consent, Retention & Revocation** subsystem. The objective of Phase 73 is to ensure that biometric references and governance assessments cannot be registered, retained, accessed, or evaluated without affirmative legal authorization, valid active consent (where consent is the governing legal basis), and strict retention expiry boundaries.

### Summary of Accomplishments:
1. **Consent Lifecycle & Affirmative Confirmation:** Verified that consent registration requires affirmative confirmation (`consent_confirmed=True`), a valid subject identifier, versioned notice references, and an explicit lawful basis. Enforced that **governance approval alone does NOT substitute for individual consent**; where explicit consent is the designated legal basis, processing fails closed unless consent status is explicitly `ACTIVE`.
2. **Server-Side Retention Expiry Enforcement:** Hardened the service layer across [`BiometricReferenceService`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/biometrics.py#L400-L600), [`BiometricGovernanceService`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/biometrics.py#L82-L350), [`FaceDetectionService`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/biometrics.py#L610-L750), and [`FaceMatchingService`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/biometrics.py#L785-L950) so that expired references and governance authorizations fail closed dynamically, even if a background cleanup job has not run.
3. **Idempotent Retention Cleanup Engine:** Implemented `cleanup_expired_references()` and `cleanup_expired_governance()` to scan for records past their `retention_expires_at` UTC timestamp, transition them to `EXPIRED` status, purge encrypted templates (cryptographic erasure), and record privacy-preserving audit events. Repeated executions are verified idempotent (no-ops that never reactivate records).
4. **Cascading Revocation & Cryptographic Erasure:** Confirmed that withdrawing consent immediately transitions governance authorization to `REVOKED`, nulls `encrypted_template` ciphertext across all associated enrolled references, and logs structured audit events without exposing sensitive payloads or keys.
5. **Route & Migration Safety:** Exposed an administrative retention cleanup endpoint (`POST /biometrics/retention/cleanup`) restricted to `Permission.BIOMETRIC_CONFIG_MANAGE`. Confirmed that no database migration was necessary because the required schema and constraints were previously established in `20261014_0010_add_biometric_governance_and_reference_registry.py`.
6. **Empirical Test Verification:** Created and executed a dedicated suite of 20 unit tests in [`tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py`](file:///D:/PROJECT/E-WITTNESS/tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py) (20/20 passed in 0.32s). Executed the complete biometrics unit suite (145/145 passed in 0.65s).

### Audit Determination
**Decision: `ACCEPTED WITH LIMITATIONS`**  
Phase 73 satisfies all architectural, cryptographic, and procedural requirements for biometric data governance, consent management, retention expiry, and revocation. Production deployment remains strictly blocked (`NO-GO`), and automated biometric matching remains disabled.

---

## 2. Actual Files Inspected & Modified

### Inspected Files:
- `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`
- `docs/audit/BATCH_08_PHASE_72_ACCEPTANCE_REPORT.md`
- `docs/architecture/biometric-privacy-and-legal-feasibility.md`
- `backend/app/core/biometrics.py`
- `backend/app/core/authorization.py`
- `backend/app/core/identity.py`
- `backend/app/config/settings.py`
- `backend/app/models/biometrics.py`
- `backend/app/core/biometric_crypto.py`
- `backend/migrations/versions/20261014_0010_add_biometric_governance_and_reference_registry.py`

### Modified Files:
- [`backend/app/repositories/biometrics.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/repositories/biometrics.py): Added `list_expired_active()` query methods on `BiometricGovernanceRepository` and `BiometricReferenceRepository`.
- [`backend/app/schemas/biometrics.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/schemas/biometrics.py): Added `BiometricRetentionCleanupResponse` read DTO.
- [`backend/app/services/biometrics.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/services/biometrics.py):
  - Added `cleanup_expired_governance()` to `BiometricGovernanceService`.
  - Added dynamic expiry transition in `get_governance_record()`.
  - Added `cleanup_expired_references()` to `BiometricReferenceService`.
  - Added dynamic expiry transition and template purging in `get_reference()`.
  - Added affirmative consent status checks and retention expiry guards in `enroll_reference()`, `detect_faces()`, and `match_faces()`.
- [`backend/app/api/v1/biometrics.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/api/v1/biometrics.py): Added `POST /biometrics/retention/cleanup` endpoint.
- [`docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`](file:///D:/PROJECT/E-WITTNESS/docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md): Updated Phase 73 entry.

### Created Test Suite:
- [`tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py`](file:///D:/PROJECT/E-WITTNESS/tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py): 20 comprehensive automated unit tests.

---

## 3. Consent Lifecycle Design & Enforcement

The consent architecture in E-WITNESS distinguishes between **administrative governance authorization** (legal review of a processing program) and **individual subject consent** (affirmative permission granted by an individual data subject):

```
                                  [ Subject Action ]
                                           │
                                  POST /governance
                                  (consent_confirmed=True)
                                           │
                                           ▼
                                 ┌───────────────────┐
                                 │   CONSENT: ACTIVE │
                                 │ GOV: PENDING_REV  │
                                 └─────────┬─────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
      [ Legal Review: Approved ]                        [ Subject Revocation ]
                    │                                             │
                    ▼                                             ▼
        ┌───────────────────────┐                     ┌───────────────────────┐
        │    CONSENT: ACTIVE    │                     │   CONSENT: WITHDRAWN  │
        │     GOV: APPROVED     │                     │     GOV: REVOKED      │
        └───────────┬───────────┘                     └───────────┬───────────┘
                    │                                             │
        [ Retention Expiry ]                          [ Immediate Cascade ]
                    │                                             │
                    ▼                                             ▼
        ┌───────────────────────┐                     ┌───────────────────────┐
        │    CONSENT: EXPIRED   │                     │  All Active References│
        │     GOV: REVOKED      │                     │     Marked REVOKED    │
        └───────────────────────┘                     │    Templates PURGED   │
                                                      └───────────────────────┘
```

### Key Lifecycle Rules:
1. **Affirmative Consent:** In `create_governance_record()`, when `lawful_basis == "explicit_consent"`, `consent_confirmed` must be explicitly `True` and `subject_user_id` must be present. Silence, pre-ticked checkboxes, or implied agreement are rejected with `BiometricGovernanceError`.
2. **Separation of Governance from Consent:** In `enroll_reference()`, the service validates that legal approval (`status == "approved"`) and individual consent (`consent_status == "active"`) are both satisfied. Legal approval of a research program cannot enroll a subject whose consent is missing, withdrawn, or expired.
3. **Purpose Limitation:** Permissible biometric purposes are restricted to the 4 enumerated values in `BiometricPurpose`. Prohibited purposes (`ProhibitedBiometricPurpose`) raise an immediate `ValueError` at the schema validator level.
4. **Ownership and Tenant Scoping:** Data subjects (`ROLE_STUDENT`, `ROLE_STAFF`) can enroll and withdraw their own consent records, but are blocked with `PermissionDeniedError` if attempting to view, create, or withdraw consent for another subject.

---

## 4. Retention & Expiry Enforcement

Retention in E-WITNESS is strictly governed by UTC timestamps and explicit policy limits:

| Parameter | Value | Enforcement Layer |
| :--- | :---: | :--- |
| Default Retention Period | 90 days | Schema default; configurable up to 365 days |
| Maximum Retention Period | 365 days | Database check constraint `ck_biometric_governance_retention_days` |
| Expiry Calculation | `created_at + timedelta(days=retention_days)` | Set on record creation using `datetime.now(UTC)` |
| Timezone Discipline | Strictly UTC (`UTCDateTime`) | ORM type mapping; no naive datetime persistence |

### Server-Side Expiry Guard:
- **Dynamic Check on Access:** In `BiometricReferenceService.get_reference()`, if `now >= reference.retention_expires_at` and `reference.status == ACTIVE`, the service dynamically transitions the reference to `EXPIRED`, zeroes out `encrypted_template = None`, and records the expiry reason.
- **Fail-Closed Downstream Blocking:** In `FaceDetectionService.detect_faces()` and `FaceMatchingService.match_faces()`, any reference or governance record whose `retention_expires_at` is in the past raises `BiometricGovernanceError(code="RETENTION_EXPIRED")`.
- **Cleanup Idempotency:** The background cleanup job (`cleanup_expired_references()`) transitions records from `ACTIVE` to `EXPIRED`. Subsequent runs query only active expired records (`WHERE status = 'active' AND retention_expires_at <= cutoff`), ensuring repeated execution is a safe, zero-mutation no-op.

---

## 5. Withdrawal, Revocation & Deletion State Transitions

When consent is withdrawn or a reference is revoked, the system transitions state through an explicit deletion state machine:

```
Reference Status Transitions:
  [ PENDING_APPROVAL ] ──(Enrollment)──> [ ACTIVE ]
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │                                             │
             (Revocation / Expiry)                         (Consent Withdrawal)
                     │                                             │
                     ▼                                             ▼
               [ EXPIRED ]                                   [ REVOKED ]
        (encrypted_template = None)                   (encrypted_template = None)
```

### Deletion Actions Executed:
1. **Authorization Invalidation:** The governance record is set to `status = REVOKED` and `consent_status = WITHDRAWN`, halting all future API authorizations immediately.
2. **Cascading Reference Invalidation:** All active references linked to the governance record are queried via `list_active_by_governance_record()` and transitioned to `status = REVOKED`.
3. **Cryptographic Erasure:** For every affected reference, `ref.encrypted_template = None` is executed, wiping the AES-256-GCM ciphertext payload from the database row.
4. **Audit Trail Logging:** Privacy-preserving audit events (`BIOMETRIC_CONSENT_REVOKED`, `BIOMETRIC_REFERENCE_REVOKED`) are appended to the security audit ledger. These events record the reference identifier, actor identifier, and timestamp, but **never** record raw images, feature vectors, or encryption keys.

---

## 6. Logical Deletion vs. Cryptographic Erasure vs. Physical Deletion

Phase 73 enforces strict truth-in-auditing regarding data erasure boundaries:

| Deletion Layer | Implementation Mechanism | Guaranteed Boundary | Limitations & Residual State |
| :--- | :--- | :--- | :--- |
| **Logical Deletion** | `status = 'revoked'`, `revoked_at = now()`, `revocation_reason = ...` | Application layer blocks any query, detection, or matching using this record. | Database row remains present; metadata (identifier, dates, audit logs) is preserved for chain of custody. |
| **Cryptographic Erasure** | `encrypted_template = None` + Key revocation in `BiometricKeyManager` | Ciphertext is expunged from the database record; even with raw database access, no template ciphertext exists. | SHA-256 digest (`template_digest`) is retained in metadata for cryptographic non-repudiation of past actions. |
| **Physical Deletion** | Database block zeroing / storage media sanitization | Storage blocks are physically overwritten. | **NOT claimed.** PostgreSQL Write-Ahead Logs (WAL), database replication streams, OS filesystem buffers, and database backup snapshots retain raw blocks until cycled, vacuumed, or expired. |

> [!IMPORTANT]
> The E-WITNESS platform explicitly distinguishes between logical deletion, cryptographic erasure, and physical storage sanitization. Setting `encrypted_template = None` provides effective cryptographic erasure at the application and schema layers, but does not guarantee instantaneous physical block overwrite on underlying disk hardware.

---

## 7. Encryption & Key-Management Review

Audited [`backend/app/core/biometric_crypto.py`](file:///D:/PROJECT/E-WITTNESS/backend/app/core/biometric_crypto.py):
- **Algorithm:** AES-256-GCM authenticated encryption using 256-bit keys and 96-bit random nonces.
- **Envelope Format:** `v1:<key_id>:<base64(nonce + ciphertext + 16_byte_tag)>`.
- **Key Lifecycle:** Keys support `ACTIVE`, `ROTATED`, and `REVOKED` states.
- **Fail-Closed on Revocation:** Attempting to decrypt or encrypt using a key marked `REVOKED` raises `BiometricKeyRevokedError` immediately.
- **Limitation Disclosed:** In the current prototype configuration, `BiometricKeyManager` stores keys in memory. In a multi-instance or persistent cloud deployment, a hardware security module (HSM) or dedicated KMS (e.g., AWS KMS, HashiCorp Vault) is required. Keys are not durable across process restarts without external KMS backing.

---

## 8. Database Migrations & Rollback Behavior

- **Migration Status:** Verified that migration `backend/migrations/versions/20261014_0010_add_biometric_governance_and_reference_registry.py` already includes all required tables, constraints, indexes, and UTC timestamp columns.
- **No Schema Changes Required:** No new database migration was needed for Phase 73.
- **Rollback Safety:** The existing migration provides an exact `downgrade()` function that drops `biometric_references` followed by `biometric_governance_records` in correct dependency order.

---

## 9. Empirical Test Verification

A dedicated unit test suite was implemented in [`tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py`](file:///D:/PROJECT/E-WITTNESS/tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py).

### Test Results: 20/20 Passed (0.32s)

```
tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py
  Group A: Formal Consent Records & Consent Lifecycle
    test_valid_explicit_consent_registration                    PASSED [ 5%]
    test_unconfirmed_consent_fails_closed                       PASSED [10%]
    test_explicit_consent_missing_subject_fails_closed          PASSED [15%]
    test_governance_approval_not_treated_as_consent             PASSED [20%]
    test_unauthorized_user_cannot_register_governance_for_other PASSED [25%]
    test_student_can_register_own_consent                       PASSED [30%]
  Group B: Retention Enforcement & Expiry Workflows
    test_expired_governance_record_rejected_for_enrollment      PASSED [35%]
    test_expired_governance_record_rejected_for_face_detection  PASSED [40%]
    test_dynamic_expiry_on_get_reference                       PASSED [45%]
    test_cleanup_expired_references_idempotency                 PASSED [50%]
  Group C: Consent Withdrawal, Cascading Revocation & Cryptographic Erasure
    test_consent_withdrawal_cascades_to_all_active_references   PASSED [55%]
    test_consent_withdrawal_idempotency                         PASSED [60%]
    test_unauthorized_user_cannot_withdraw_another_subjects_consent PASSED [65%]
    test_single_reference_revocation_purges_ciphertext          PASSED [70%]
  Group D: Security Regressions & Matching Prohibition Invariant
    test_matching_disabled_invariant_is_unconditional           PASSED [75%]
    test_consent_cannot_enable_biometric_matching               PASSED [80%]
    test_retention_cleanup_route_exists_and_is_protected        PASSED [85%]
    test_zero_1_to_n_search_routes_in_biometrics_router         PASSED [90%]
    test_reference_read_dto_zero_template_or_ciphertext_leakage PASSED [95%]
    test_violence_detection_remains_independent_of_biometric_consent PASSED [100%]
```

### Complete Biometrics Unit Suite: 145/145 Passed (0.65s)
- `tests/unit/biometrics/test_biometrics_governance_and_detection.py`: 51 passed
- `tests/unit/biometrics/test_biometrics_matching_and_security.py`: 28 passed
- `tests/unit/biometrics/test_biometrics_services_coverage.py`: 22 passed
- `tests/unit/biometrics/test_phase72_role_permissions_and_prohibition.py`: 24 passed
- `tests/unit/biometrics/test_phase73_consent_retention_and_revocation.py`: 20 passed
- **Total: 145 passed, 0 failed.**

---

## 10. Unresolved Legal, Operational & Technical Risks

1. **Unresolved Statutory Regimes:** As documented in Phase 71, statutory applicability (BIPA, CCPA, EU AI Act, FERPA) remains unconfirmed by legal counsel. The 5 formal inquiry questions submitted to qualified counsel remain open.
2. **KMS Durability:** Key material in `BiometricKeyManager` is currently in-memory. A production deployment requires an external KMS with envelope encryption to guarantee key durability and automated key rotation across distributed nodes.
3. **Database Backup Sanitization:** Cryptographic erasure wipes `encrypted_template` from active rows, but historical database backups and WAL logs prior to revocation may contain ciphertext until retention cycles expire.
4. **Academic Dataset Rights:** The violence-detection dataset training rights remain `UNRESOLVED`. Commercial deployment remains blocked.
5. **Historical Violence Test Partition:** The test partition ($N=354$) remains sealed and was not accessed or evaluated.

---

## 11. Production Readiness Decision

**Status: `NO-GO`**

Automated biometric matching remains permanently disabled (`BIOMETRIC_MATCHING_ENABLED = False`). The system is an evidence management and advisory forensic tool, not an automated identification or surveillance platform. Production deployment is strictly prohibited until formal legal counsel opinion is executed, KMS integration is operationalized, and the remaining Batch 08 phases (Phases 74–80) are completed and audited.

---

## 12. Recommendation for Phase 74

Phase 73 has verified consent capture, retention enforcement, cascading revocation, and cryptographic erasure. The subsystem is ready for **Phase 74: Biometric Reference Registry & Envelope Encryption Integration**.

- **Execution Boundary:** The agent will pause and wait for explicit user authorization before proceeding to Phase 74.
- **Phase 74 Focus:** Restricted reference enrollment, opaque reference ID generation (`REF-BIO-...`), provenance linkage to `evidence_attachments`, and automated template digest verification.
