# E-WITNESS — Batch 08, Phase 75 Final Remediation & Phase 76 Readiness Report

**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Batch:** 08 — Biometric Governance and Security  
**Phase:** 75 — Approved Face Detection Component  
**Report Date:** 2026-10-27  
**Gate Outcome:** `PASS WITH LIMITATIONS`  
**Production Status:** `NO-GO`  
**Phase 76 Readiness Decision:** `READY WITH LIMITATIONS`

---

## 1. Executive Summary

This audit report documents the formal verification, remediation, and readiness review following the findings in `BATCH_08_PHASE_75_FOLLOWUP_SECURITY_REVIEW.md`.

All identified concerns regarding image decoding resource safeguards, decompression bomb escalation, memory bounds, error message pointer leaks, and redaction outcome semantics have been remediated, verified in code, and comprehensively tested across unit and integration test suites.

### Governance and Invariant Compliance Summary

| Invariant / Control | Policy Standard | Verified Status |
| :--- | :--- | :--- |
| **`BIOMETRIC_MATCHING_ENABLED`** | Must remain `False` across all configurations | **Enforced (`False`)** |
| **Biometric Template Generation** | No facial embeddings (128-d / 512-d) or descriptors | **Zero Templates Generated** |
| **Decompression Bomb Protection** | Single-axis $\le 4096\text{px}$, pixels $\le 16,777,216$ | **Enforced Pre-Allocation** |
| **Pillow Warning Escalation** | `DecompressionBombWarning` escalated to fatal error | **Enforced (`filterwarnings("error")`)** |
| **Error Message Sanitization** | No memory addresses (`0x...`) or file paths leaked | **Enforced (`_sanitize_error_message`)** |
| **Redaction Outcome Semantics** | Unredacted images never marked as redacted | **Enforced (`is_redacted`, `requires_human_review`)** |
| **Non-Anonymization Disclaimer** | Statutory advisory disclaimer on all responses | **Enforced (`PRIVACY_REDACTION_ADVISORY_DISCLAIMER`)** |
| **Test Partition Sealed** | Historical test partition ($N=354$) unaccessed | **Strictly Unaccessed** |

---

## 2. Detailed Technical Remediation Verification

### 2.1 Task A — Image-Decoding Limits & Resource Safeguards

1. **Pre-Allocation Dimension Limits:**
   - Single-axis dimension limit tightened from $8192\text{px}$ to **$4096\text{px}$** (DCI 4K compliant).
   - Maximum decoded pixel budget lowered from $67,108,864\text{px}$ to **$16,777,216\text{px}$** ($\approx 16.8\text{ MP}$), reducing the uncompressed 24-bit RGB memory allocation ceiling by 75% (from $\approx 201\text{ MB}$ down to $\approx 50.3\text{ MB}$).
   - Both `inspect_image_dimensions_and_format` (via zero-allocation magic header inspection) and `apply_face_redaction` (via Pillow `_validate_dimensions`) strictly check `width * height > MAX_IMAGE_PIXELS` before raster buffers are allocated or copied.

2. **Payload Size Pre-Check:**
   - Enforced at service layer (`FaceDetectionService.detect_faces`) before any decoding or header parsing: `len(image_bytes) > BIOMETRIC_MAX_IMAGE_SIZE_BYTES` raises `PayloadTooLargeError`.
   - Re-enforced at detector layer (`inspect_image_dimensions_and_format`): `len(image_bytes) > MAX_IMAGE_BYTES` raises `ValueError`.

3. **Format Validation (Signatures & Decoder Checks):**
   - Header magic inspection validates PNG (`\x89PNG\r\n\x1a\n`), JPEG (`\xff\xd8`), and WebP (`RIFF...WEBP`). Any unrecognized signature raises `UnsupportedMediaTypeError`.
   - Pillow decoder secondary check validates stream integrity, chunk structure, and corruption.

4. **Pillow Warning Escalation (`DecompressionBombWarning` vs `DecompressionBombError`):**
   - In Pillow source (`_decompression_bomb_check`), payloads exceeding $2 \times \text{MAX\_IMAGE\_PIXELS}$ raise `DecompressionBombError`, but payloads in the interval $(\text{MAX\_IMAGE\_PIXELS}, 2 \times \text{MAX\_IMAGE\_PIXELS}]$ only emit `DecompressionBombWarning`.
   - In `ai_services/face_detection/redaction.py`, `apply_face_redaction` now executes within a `warnings.catch_warnings()` context with `warnings.filterwarnings("error", category=Image.DecompressionBombWarning)`. This converts mid-range decompression bomb warnings into immediate fatal exceptions, preventing unbounded raster allocation.

5. **Explicit Decompression Bomb Guarantee Disclosure:**
   - Header parsing alone cannot prevent decompression bombs, because crafted files (such as decompression bombs with misleading IHDR chunks, gzip stream loops, or truncated defective Huffman trees) can claim modest dimensions in the header while consuming unbounded decompression state.
   - Therefore, a two-phase defense is enforced:
     1. Phase 1 (Header Pre-Check): Fast fail for headers claiming $> 4096\text{px}$ or $> 16.8\text{Mpx}$.
     2. Phase 2 (Pillow Decoder Bounds): `Image.MAX_IMAGE_PIXELS = 16_777_216` coupled with scoped `DecompressionBombWarning` escalation to catch mid-range decompression bombs during streaming decompression.

6. **Exception Sanitization & Pointer Scrubbing:**
   - Introduced `_sanitize_error_message(exc: Exception) -> str` in `ai_services/face_detection/redaction.py`.
   - The sanitizer strips hexadecimal memory addresses (`0x[0-9a-fA-F]+`), local filesystem paths (both Windows `C:\...` / `D:\...` and POSIX paths), and internal Pillow object representations (`<... at ...>`).
   - Clean, typed error descriptions (`UnsupportedMediaTypeError`) are surfaced to callers without leaking infrastructure internals.

7. **Concurrency & Intermediate Memory Buffers:**
   - Single-image peak uncompressed raster footprint is capped at $4096 \times 4096 \times 3 \approx 50.3\text{ MB}$.
   - Together with the intermediate copy buffer (`work_img = pil_img.copy()`) and encoded output buffer (`out_buf`), peak memory per request is bounded to $\approx 100\text{ MB}-150\text{ MB}$.
   - Concurrency bounds in Uvicorn / worker processes prevent thread exhaustion under simultaneous requests.

---

### 2.2 Task B — Redaction Outcome Semantics & Human Oversight

1. **Explicit Outcome Semantics in Schemas and Dataclasses:**
   - `RedactedImageResult` (`ai_services/face_detection/redaction.py`) and `FaceRedactionResponse` (`backend/app/schemas/biometrics.py`) now include:
     - `is_redacted: bool`: Strictly `True` only when at least one face region was visually obscured (solid box, blur, or pixelate).
     - `requires_human_review: bool`: Flagged `True` whenever automated redaction is incomplete, zero faces were detected, candidate faces were excluded, or bounding boxes clipped.
     - `review_reason: str | None`: Explicit structured reason explaining the human review trigger.

2. **Detection Failure Fails Closed:**
   - In `FaceDetectionService.redact_faces`, `await self.detect_faces(...)` executes first.
   - Any failure (biometrics disabled, missing governance, lack of permission, payload too large, corrupted image) raises immediately and halts processing. A detection exception never produces a redaction response.

3. **Handled Operational Scenarios:**
   - **Zero Detected Faces ($N=0$):** Image copy returned with `is_redacted = False`, `requires_human_review = True`, and `review_reason = "No faces detected in input image; human review required to confirm no unredacted individuals or bystanders are present."`. An unmodified image is never represented as redacted or anonymized.
   - **All Candidate Faces Below Confidence Threshold:** When candidates exist but none meet `min_confidence` (e.g. confidence 0.35 with threshold 0.50), returns `is_redacted = False`, `requires_human_review = True`, and `review_reason` detailing the candidate count below threshold.
   - **Partial Redactions:** When some faces meet threshold but others fall below, returns `is_redacted = True`, `requires_human_review = True`, and `review_reason = "Partial redaction: X face(s) redacted, but Y candidate detection(s) fell below confidence threshold..."`.
   - **Clean Redactions:** When all candidate detections meet threshold and are validly obscured, returns `is_redacted = True`, `requires_human_review = False`, and `review_reason = None`.
   - **Edge Clipping Safety:** If a bounding box clips outside the image bounds to non-positive dimensions, `clipping_failure` is detected, triggering `requires_human_review = True`.
   - **Overlapping Detections:** Redaction applies `padding_ratio` (default 10%) on all sides to cover hairlines, ears, and chin. Overlapping boxes are independently drawn/filtered, compositing together cleanly without clipping each other.

4. **Style Selection & Non-Anonymization Disclaimer:**
   - Solid masking (opaque rectangle with charcoal black `(18, 18, 18)`) is preferred for dependable visual concealment.
   - Blur (Gaussian blur radius 20) and Pixelation (block size 16) are available for non-sensitive presentation, but must not be represented as mathematically irreversible or anonymized.
   - The mandatory `PRIVACY_REDACTION_ADVISORY_DISCLAIMER` is embedded in every redaction result and response:
     > *"PRIVACY REDACTION ADVISORY: Face redaction (blur/pixelate/mask) reduces visual identifiability of detected facial regions for privacy protection. It does not provide absolute anonymization or mathematical differential privacy guarantees. Contextual clues, clothing, gait, or background details may remain identifiable. Original unredacted evidence is preserved intact under strict chain-of-custody controls."*

---

## 3. Phase 76 Scope & Boundary Definition

Before proceeding to Phase 76, strict technical boundaries are defined to prevent scope creep into unauthorized biometric recognition:

### 3.1 Prohibited Scope (Zero Tolerance)
- **NO Biometric Matching:** `BIOMETRIC_MATCHING_ENABLED` remains locked to `False`.
- **NO Facial Embeddings / Descriptors:** No generation of 128-d, 512-d, or any high-dimensional vector representations.
- **NO Biometric Templates:** No creation or persistent storage of biometric templates.
- **NO 1:1 Identity Verification or 1:N Identification:** Strictly forbidden under institutional policy.

### 3.2 Approved Scope for Phase 76
Phase 76 is strictly redefined as **Photometric Evidence Quality Assessment & Redaction Geometry Verification**:
1. **Photometric Quality Metrics (Non-Identifying):**
   - Sharpness / Blur metric (Laplacian variance).
   - Exposure balance (histogram entropy and under/over-exposure saturation checks).
   - Dynamic range and contrast metrics.
2. **Redaction Geometry Verification:**
   - Aspect ratio checks on detected face bounding boxes ($0.5 \le \text{aspect\_ratio} \le 2.0$).
   - Overlap resolution / bounding box IoU consolidation for clustered bystander faces.
   - Verification that redaction masks completely encompass detected landmarks (eyes, nose, mouth).
3. **Mandatory Human Review Behavior:**
   - Frames failing quality thresholds (e.g. Laplacian variance $< 100.0$, overexposure $> 15\%$, or aspect ratio anomaly) must be flagged with `requires_human_review = True` and documented failure codes.

---

## 4. Test Execution & Evidence

### 4.1 Focused Phase 75 Unit Test Suite
- **Test File:** `tests/unit/biometrics/test_phase75_approved_face_detection.py`
- **Command:** `uv run pytest tests/unit/biometrics/test_phase75_approved_face_detection.py --no-cov -v`
- **Exit Code:** `0`
- **Result:** **45 passed in 0.48s**
- **Categories Covered:**
  - Category A: Detection Behavior & Input Validation (15 tests)
  - Category B: Security, Authorization & Tenant Scoping (9 tests)
  - Category C: Matching Prohibition & Isolation (2 tests)
  - Category D: Privacy-Preserving Redaction Boundary & Outcome Semantics (18 tests)
  - Category E: Zero Leakage & Auditability (1 test)

### 4.2 Comprehensive Biometrics Unit Suite
- **Directory:** `tests/unit/biometrics/`
- **Command:** `uv run pytest tests/unit/biometrics/ --no-cov`
- **Exit Code:** `0`
- **Result:** **216 passed in 0.96s**
- **Suite Breakdown:**
  - `test_biometrics_governance_and_detection.py`: 50 passed
  - `test_biometrics_matching_and_security.py`: 28 passed
  - `test_biometrics_services_coverage.py`: 22 passed
  - `test_phase72_role_permissions_and_prohibition.py`: 24 passed
  - `test_phase73_consent_retention_and_revocation.py`: 20 passed
  - `test_phase74_reference_registry_and_encryption.py`: 27 passed
  - `test_phase75_approved_face_detection.py`: 45 passed

### 4.3 Integration Regression Test Suite
- **Test Files:**
  - `tests/integration/api/test_batch08_group01_regressions.py`
  - `tests/integration/api/test_batch08_group02_regressions.py`
- **Command:** `uv run pytest tests/integration/api/test_batch08_group01_regressions.py tests/integration/api/test_batch08_group02_regressions.py --no-cov`
- **Exit Code:** `0`
- **Result:** **6 passed in 18.26s**

### 4.4 Files Modified in this Remediation
- `ai_services/face_detection/detector.py`: Tightened dimension bounds to 4096px and 16.8 MP.
- `ai_services/face_detection/redaction.py`: Pre-allocation validation, Pillow warning escalation, error message sanitization, explicit outcome semantics (`is_redacted`, `requires_human_review`, `review_reason`).
- `backend/app/schemas/biometrics.py`: Added `is_redacted`, `requires_human_review`, `review_reason` to `FaceRedactionResponse`.
- `backend/app/services/biometrics.py`: Added `detector` injection to `FaceDetectionService`, forwarded outcome semantic fields in `redact_faces`.
- `docs/audit/E_WITNESS_PHASE_STATUS_MATRIX.md`: Updated Phase 75 status to `PASS WITH LIMITATIONS` (45 tests) and Phase 76 to `READY WITH LIMITATIONS`.
- `tests/unit/biometrics/test_phase75_approved_face_detection.py`: Added tests for zero faces, candidate faces below threshold, partial redactions, clean redactions, pointer sanitization, detection failure prevention, clipping failures, and Pillow warning escalation.

---

## 5. Gate Recommendation & Phase 76 Readiness

1. **Phase 75 Final Status:** `PASS WITH LIMITATIONS`
   - Limitations: Component is approved strictly for offline, non-destructive privacy redaction and authorized bounding box detection under approved governance records. Model weights must be locally installed (zero automatic network downloads).
2. **Production Status:** `NO-GO`
   - Biometric matching remains prohibited (`BIOMETRIC_MATCHING_ENABLED = False`). Production deployment of biometric systems is not authorized.
3. **Phase 76 Readiness Decision:** `READY WITH LIMITATIONS`
   - Phase 76 implementation may proceed only after user authorization, and must adhere strictly to the non-identifying photometric quality and redaction geometry scope defined in Section 3.2.

---
*Report certified by Antigravity Quality & Security Auditor.*
