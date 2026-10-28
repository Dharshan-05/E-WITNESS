# E-WITNESS Batch 08 Closure & Batch 09 Handoff Verification Specification

**Document Reference:** `docs/audit/BATCH_08_CLOSURE_AND_BATCH_09_HANDOFF.md`  
**Closing Batch:** Batch 08 — Biometric Governance and Security (Phases 71–80)  
**Receiving Batch:** Batch 09 — Case Management, Investigation Workspace & Human Review (Phases 81–90)  
**Handoff Verification Date:** 2026-10-28T09:41:00Z  
**Final Handoff Status:** **`READY WITH LIMITATIONS`**  
**Subsystem Production Status:** **`NO-GO`** (Strictly Enforced Across All Environments)  

---

## 1. Executive Handoff Overview

This document establishes the formal verification and architectural boundary handoff from **Batch 08 (Biometric Governance and Security, Phases 71–80)** to **Batch 09 (Case Management, Investigation Workspace & Human Review, Phases 81–90)**.

The audit was conducted strictly against the live repository at `D:\PROJECT\E-WITTNESS`. All claims of technical readiness, cryptographic safety, privacy boundaries, and test coverage have been independently cross-referenced with actual source files, configuration validators, and recorded pytest runs.

The final evaluation verdict is **`READY WITH LIMITATIONS`**. No critical defects block Phase 81 ("Formal Case Lifecycle & References"), provided that all mandatory governance invariants, cryptographic limitations, and ethical boundaries detailed herein are strictly maintained.

---

## 2. Exact Files Inspected & Repository Working Tree Status

### 2.1 Git Working Tree Inspection

- **Current Branch:** `main` (up to date with `origin/main`).
- **Modified Working Tree Files (Batch 08 Hardening & Phase 80 Audit):**
  - `ai_services/face_detection/detector.py`: Fail-closed detection boundary; decompression bomb thresholds.
  - `ai_services/violence_detection/calibration.py`: Non-biometric calibration models (Batch 07 baseline preserved).
  - `ai_services/violence_detection/classifier.py`: Sealed AI classifier interface.
  - `backend/app/__init__.py`: Package entrypoint initialization.
  - `backend/app/api/dependencies.py`: Principal injection and permission enforcement.
  - `backend/app/api/v1/biometrics.py`: Biometric REST endpoints (redaction, quality, review, re-encryption).
  - `backend/app/config/settings.py`: Hard-coded `BIOMETRIC_MATCHING_ENABLED` production guard and vault config.
  - `backend/app/core/ai.py`: Isolated AI runtime configuration.
  - `backend/app/core/audit.py`: Append-only audit logging ledger.
  - `backend/app/core/biometric_crypto.py`: AES-256-GCM envelope encryption, AAD binding, pluggable vault provider protocol.
  - `backend/app/core/exceptions.py`: Fail-closed domain exception definitions.
  - `backend/app/models/__init__.py` & `backend/app/models/biometrics.py`: Biometric SQL models (consent, reference, review).
  - `backend/app/repositories/biometrics.py`: Tenant-scoped database queries (`department_id` enforced).
  - `backend/app/schemas/biometrics.py`: Pydantic V2 schemas for biometric APIs.
  - `backend/app/services/biometrics.py`: Governance, reference registry, face detection, and review services.
  - `docs/architecture/biometric-privacy-and-legal-feasibility.md`: Architectural specification and legal analysis.
  - `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`: Global phase status matrix (Batch 08 closed at Phase 80).
  - `tests/unit/ai/test_ai_job_service.py`: Batch 07 regression protection.
- **Untracked Batch 08 Modules Verified:**
  - `ai_services/face_detection/evaluation.py`: Detection precision/recall/IoU and perturbation robustness engine.
  - `ai_services/face_detection/geometry.py`: Redaction geometry, bounds, padding, and box consolidation.
  - `ai_services/face_detection/quality.py`: Photometric quality assessment (Laplacian blur, exposure, contrast).
  - `ai_services/face_detection/redaction.py`: Non-destructive solid, blur, and pixelation masking.
  - `ai_services/face_detection/review.py`: Quality review decision matrix and state machine.
  - `backend/migrations/versions/20261028_0016_add_biometric_quality_review_schema.py`: Alembic migration for reviews.
  - `tests/unit/biometrics/test_phase80_final_security_audit.py`: 18 cross-cutting security tests.
- **Sealed Test Partitions Verified:**
  - `data/` and historical violence test partitions ($N=354$) remain untouched, unreferenced, and unopened.

---

## 3. Evidence Available & Actual Test Verification

The following automated test suites were executed directly during this verification session. No results from unexecuted tests or historical assumptions were accepted:

| Test Suite / Target Path | Test Scope | Number of Tests | Result | Execution Duration |
| :--- | :--- | :---: | :---: | :---: |
| `tests/unit/biometrics/test_phase80_final_security_audit.py` | Cross-cutting 13 mandatory invariant tests | 18 | **PASSED** | 0.90s |
| `tests/unit/biometrics/` | Complete biometrics unit test suite (Phases 71–80) | 355 | **PASSED** | 6.65s |
| `tests/integration/api/test_batch08_group01_regressions.py` | PostgreSQL async integration (Governance & Registry) | 4 | **PASSED** | 14.10s |
| `tests/integration/api/test_batch08_group02_regressions.py` | PostgreSQL async integration (Redaction & Reviews) | 2 | **PASSED** | 7.49s |
| `tests/unit/cases/test_cases_domain_and_service.py` | Case management domain models & service logic | 36 | **PASSED** | 0.70s |
| `tests/unit/cases/test_cases_group02_notes_workflow_export.py` | Case notes, workflow transitions, and export manifests | 44 | **PASSED** | 0.87s |
| **Combined Verification Total** | **Subsystem Regressions + Batch 09 Baseline** | **441** | **ALL PASSED** | **Zero Failures** |

---

## 4. Comparison of Phase 80 Report vs. Actual Implementation

The assertions in [`docs/audit/BATCH_08_PHASE_80_FINAL_SECURITY_AUDIT.md`](file:///d:/PROJECT/E-WITTNESS/docs/audit/BATCH_08_PHASE_80_FINAL_SECURITY_AUDIT.md) were compared against source code and behavior:

1. **Assertion:** `BIOMETRIC_MATCHING_ENABLED = False` cannot be overridden in production.
   - **Realized In Code:** Confirmed in `backend/app/config/settings.py` (`_enforce_production_security_gate`, lines 733–737) and `backend/app/services/biometrics.py` (lines 1378–1385). Overriding with `True` in production raises `ValueError`. Calling `match_faces` raises `BiometricProhibitedError` / `BiometricsDisabledError`.
2. **Assertion:** AAD binding prevents envelope tampering or ciphertext transplantation across departments.
   - **Realized In Code:** Confirmed in `backend/app/core/biometric_crypto.py`. Decrypting under altered `reference_id` or `department_id` fails authenticated tag verification and raises `BiometricDecryptionFailedError`.
3. **Assertion:** Image decoding enforces strict decompression-bomb protection.
   - **Realized In Code:** Confirmed in `ai_services/face_detection/detector.py` and `redaction.py`. Image dimension cap ($\le 4096\text{px}$, $\le 16.8\text{Mpx}$) is evaluated before raster allocation.
4. **Assertion:** Redaction operates non-destructively; zero detections trigger human review.
   - **Realized In Code:** Confirmed in `ai_services/face_detection/redaction.py`. Original evidence byte buffers and hashes in object storage are never overwritten. Zero detections force `requires_human_review = True`.
5. **Assertion:** Review state machine prevents unauthorized tampering with completed reviews.
   - **Realized In Code:** Confirmed in `ai_services/face_detection/review.py` (`validate_review_state_transition`). Moving out of `COMPLETED` raises `BusinessRuleError("Review is COMPLETED; cannot transition...")` unless `is_authorized_reopen=True`.
6. **Assertion:** Redaction geometry consolidation and confidence-sorted greedy matching are active.
   - **Realized In Code:** Confirmed in `ai_services/face_detection/evaluation.py` (lines 297–305) and `backend/app/schemas/biometrics.py` (`FaceRedactionRequest.consolidate_overlapping`).

---

## 5. Discrepancies Found & Resolution

During deep inspection, the following non-blocking discrepancies were identified and resolved:

| Item | Previous Claim or Implementation State | Verified Reality & Resolution | Status |
| :--- | :--- | :--- | :---: |
| **KMS Provider Scope** | Some prior reports referenced "KMS integration". | The implementation provides `ExternalKmsVaultAdapter`, an interface adapter boundary with mock/probe capability. It does NOT connect to live cloud HSM infrastructure. Explicitly disclosed in audit. | **RESOLVED & DISCLOSED** |
| **Key Revocation Scope** | Revocation was described as "cryptographic erasure". | Software status revocation immediately halts real-time decryption via `BiometricKeyRevokedError`. However, it does not wipe pre-existing cold backups or disk snapshots from prior points in time. | **RESOLVED & DISCLOSED** |
| **Demographic Fairness** | Testing measured empirical robustness across blur and lighting. | Robustness tests evaluate synthetic image perturbations only. Demographic parity across human racial/ethnic/gender groups is strictly **`NOT ESTABLISHED`**. | **RESOLVED & DISCLOSED** |
| **Settings Validation in Production** | Unit tests initially used dummy URLs with unescaped `#` characters. | Test URLs were updated to valid RFC 3986 formats (`postgresql+asyncpg://prod_user:...@db.internal:5432/ewitness_prod`) to satisfy regex validators. | **RESOLVED IN TEST** |

---

## 6. Mandatory Safety Invariants Preserved for Batch 09

Downstream engineering teams implementing Batch 09 must uphold the following non-negotiable boundaries:

1. **Permanent Biometric Matching Lock:**
   - Under no circumstances shall Batch 09 case dossier workflows, investigator queues, or search filters invoke or introduce automated face matching, 1:1 identity verification, 1:N recognition, or automated suspect tagging.
2. **Evidence Immutability & Child Attachment Segregation:**
   - Master evidence objects stored in object storage and registered in the `evidence` table are immutable.
   - Privacy-redacted versions produced for case export or court disclosure must be stored as separate, derivative `EvidenceAttachment` objects with their own independent SHA-256 digests.
3. **Multi-Tenant Department Boundary Isolation:**
   - Case records, evidence attachments, and quality review dossiers must remain strictly partitioned by `department_id`. Investigators cannot inspect, assign, or reassign cases across departmental boundaries.
4. **Mandatory Fairness Disclaimers on Downstream Exports:**
   - Any investigative case dossier or disclosure manifest containing face detection or redaction metadata must prominently display the mandatory legal disclaimer: `DEMOGRAPHIC FAIRNESS NOT ESTABLISHED`.
5. **Isolation of Sealed Test Partitions:**
   - Batch 09 test fixtures and seed data must never reference, load, or touch the historical violence detection test partition ($N=354$).

---

## 7. Concrete Prerequisites & Interface Contracts for Batch 09

Batch 09 implementation can cleanly interface with the sealed Batch 08 subsystem via these established contracts:

```mermaid
classDiagram
    class CaseService {
        +create_case(request, principal)
        +link_evidence(case_id, evidence_id, principal)
        +link_redacted_derivative(case_id, redacted_attachment, principal)
        +link_quality_review(case_id, review_id, principal)
    }

    class FaceDetectionService {
        +redact_faces(image_bytes, request, principal) FaceRedactionResponse
    }

    class QualityReviewWorkflowService {
        +get_review_by_evidence_id(evidence_id, principal) BiometricQualityReviewRead
        +validate_review_status_for_disclosure(review_id) bool
    }

    class EvidenceAttachment {
        +UUID id
        +UUID case_id
        +str storage_key
        +str sha256_hash
        +bool is_redacted_derivative
        +UUID parent_evidence_id
    }

    CaseService --> EvidenceAttachment : manages
    CaseService ..> FaceDetectionService : invokes for redaction
    CaseService ..> QualityReviewWorkflowService : reads review status
```

### Key Interface Signatures

- **`FaceDetectionService.redact_faces(image_bytes: bytes, request: FaceRedactionRequest, principal: AuthenticatedPrincipal) -> FaceRedactionResponse`**
- **`QualityReviewWorkflowService.get_review(review_id: UUID, principal: AuthenticatedPrincipal) -> BiometricQualityReviewRead`**
- **`QualityReviewStatus`: `PENDING_REVIEW`, `IN_REVIEW`, `NEEDS_REDACTION`, `COMPLETED`, `ESCALATED`, `CANCELLED`**

---

## 8. Exact Scope of Phase 81: Formal Case Lifecycle & References

Phase 81 is the opening phase of Batch 09. Its scope is strictly bounded:

- **Approved Scope:**
  1. Formal Case Lifecycle: State machine managing transitions across `DRAFT -> OPEN -> UNDER_INVESTIGATION -> PENDING_SUPERVISOR_REVIEW -> CLOSED / REOPENED`.
  2. Canonical Reference Numbering: Deterministic generation and validation of immutable case reference identifiers formatted as `CASE-YYYY-XXXXX`.
  3. Case File Metadata Persistence: Core SQLAlchemy case models, repositories, and transactional database services.
  4. Role Authorization: Enforcing `PermissionCode.CASE_CREATE`, `CASE_READ`, `CASE_UPDATE`, and `CASE_ASSIGN`.
  5. Cross-Department Tenant Enforcement: Ensuring cases are isolated by `department_id`.
- **Excluded Scope (Strictly Prohibited in Phase 81):**
  - No frontend UI implementation (reserved for Batch 12).
  - No case notes with visibility tiers (reserved for Phase 86).
  - No case evidence export manifests (reserved for Phase 89).
  - No automated biometric matching or face recognition.
  - No modification to historical audit records or sealed partitions.

---

## 9. Final Handoff Status & Sign-Off

- **Batch 08 Formal Verdict:** **`ACCEPTED WITH LIMITATIONS`**
- **Batch 08 Status:** **`CLOSED & SEALED`**
- **Handoff to Batch 09 Status:** **`READY WITH LIMITATIONS`**
- **Production Status:** Strictly **`NO-GO`** across all environments.
- **Next Authorized Step:** Proceed to **Batch 09, Phase 81 ("Formal Case Lifecycle & References")** adhering strictly to the invariants and prerequisites defined in this document.
