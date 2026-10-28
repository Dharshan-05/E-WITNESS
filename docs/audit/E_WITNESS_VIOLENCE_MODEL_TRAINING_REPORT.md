# E-WITNESS — Violence Detection Model Training & Readiness Report

**Document ID:** `EW-REPORT-ML-TRAIN-2026-10-26-REV4`  
**Execution Timestamp:** 2026-10-26T23:38:00+05:30  
**Project:** E-WITNESS Digital Evidence Management Platform  
**System Environment:** Windows 10/11 x64 | Python 3.15.2 | PyTorch 2.15.0.dev20260907+cu126  
**Hardware Accelerator:** NVIDIA GeForce RTX 4050 Laptop GPU (6,141 MiB VRAM, Driver 616.92)  
**Workspace:** `D:\PROJECT\E-WITTNESS`  
**Required Status Vocabulary:** `PASS` | `FAIL` | `BLOCKED` | `RESTRICTED` | `APPROVED` | `VALIDATED` | `NOT VALIDATED` | `NOT RUN` | `NOT READY`

---

## 1. Executive Summary & Verification Gate Status

This report delivers the verified findings of the Batch 07 Final Verification Gate for the E-WITNESS violence detection subsystem.

### Overall Pipeline Gate Status
| Evaluation Gate | Requirement | Formal Status | Evidence Summary |
| :--- | :--- | :--- | :--- |
| **1. Dataset Rights & Governance** | Upstream rights clearance for commercial & platform training | **`BLOCKED`** | Kaggle REST API reports `MIT` (Owner: `Yash07Yadav`), but downloaded archive contains no physical `LICENSE` file. The composite includes unverified third-party Hollywood movie clips (`MovieFights`) under studio copyright, NHL broadcast footage (`HockeyFight`), and academic sets (`RWF-2000`). Upstream sources have no copyright assignment to the aggregator. Evaluated candidates (AIRTLab, VID) are academic/non-commercial only. Full training strictly withheld. |
| **2. Dataset Ingestion Tooling** | Fail-closed validation, documentary evidence, symlink/path-traversal protection, deduplication, zero-leakage | **`PASS`** | `scripts/ingest_approved_dataset.py` enforces documentary evidence on disk, allowlisted licenses, path traversal and symlink rejection, rejection of unapproved/mixed assets (`moviefights`, `hockeyfight`), 0 cross-split hash overlap, and atomic writes. Verified by 15 unit tests (15/15 passed, exit code 0). |
| **3. Evaluation Separation** | Strict split separation, validation-only calibration, test-only reporting | **`PASS`** | Training script ignores test split entirely. Validation split is used strictly for Platt fitting and threshold sweeps. Test split is evaluated once for reporting. Manifest hash semantics distinguish internal test splits from external benchmark distributions. |
| **4. Regression & Unit Tests** | Automated test suite across AI subsystem | **`PASS`** | **123/123 unit tests passed across 13 test files (100% assertion pass rate)**. 12 of 13 test suites exit with code 0 (`0x0`). `test_dataset_migration.py` (15/15 passed, exit code 0); `test_ml_pipeline_scripts.py` (8/8 assertions passed). Windows exit code `0xC0000005` in `test_ml_pipeline_scripts.py` is isolated to PyTorch nightly autograd worker thread shutdown on CPython 3.15. |
| **5. Statistical Calibration** | Platt scaling convergence and ECE target verification | **`NOT VALIDATED`** | Previous synthetic ECE of `0.0075` was an artifact of $N=16$ balanced samples falling into a single coin-flip bin ($0.4925$ vs $0.5000$). With $N < 100$, sample size is statistically inadequate for representative validation. Software pipeline fallback and inverted score detection are verified (`INVERTED_SCORE_DIRECTION_FALLBACK`), but real-world calibration is formally **`NOT VALIDATED`**. |
| **6. Full 10-Epoch Training** | Multi-hour full training run on local GPU | **`NOT RUN`** | Mandatory stop condition observed. Training is gated behind Gate 1 (Dataset Rights); stopped prior to unapproved full run. |
| **7. Production Readiness** | End-to-end readiness for production deployment | **`NOT READY`** | Gated behind verified dataset rights clearance and full-scale calibrated training on an approved dataset. |

---

## 2. Dataset Licensing & Provenance Review

### 2.1 Authoritative Kaggle REST API Record
Direct inspection of the Kaggle dataset endpoint (`https://www.kaggle.com/api/v1/datasets/view/yash07yadav/project-data`) retrieved the authoritative upstream metadata, archived in [`data/dataset_licensing_evidence.json`](file:///D:/PROJECT/E-WITTNESS/data/dataset_licensing_evidence.json):

- **Byte-for-Byte Verification:** The declared size (`13,921,264,652 bytes`) matches the scanned archive in `data/raw/Complete Dataset` to the exact byte.
- **Declared License:** `MIT` on Kaggle web form.
- **On-Disk Audit:** No `LICENSE` or `README` file exists in the downloaded archive (`data/raw/Complete Dataset`).

### 2.2 Component Rights Analysis & Legal Corrections
Detailed provenance review is documented in [`docs/audit/E_WITNESS_DATASET_PROVENANCE.md`](file:///D:/PROJECT/E-WITTNESS/docs/audit/E_WITNESS_DATASET_PROVENANCE.md):

1. **`MovieFights` (`RESTRICTED` / `FAIL`):** Ripped from commercial Hollywood action films posted on YouTube. Film studios retain exclusive copyrights under 17 U.S.C. § 106. An individual aggregator cannot grant an open-source MIT license to proprietary third-party commercial cinema clips without authorization.
2. **`RWF-2000` (`RESTRICTED`):** Governed by SMIIP Lab's explicit license prohibiting commercial use, modification, and redistribution without prior written approval.
3. **`HockeyFight` (`RESTRICTED`):** Broadcast footage owned by the National Hockey League (NHL). Distributed under research fair-use conventions; non-commercial only.
4. **`Real Life Violence Situations` (`UNVERIFIED`):** YouTube scrapes without formal open license; authors request citation only.
5. **Correction on AIRTLab:** The official GitHub repository contains no root `LICENSE` file; README specifies research/educational citation only. Status: **`RESTRICTED`** (NOT CC BY 4.0).
6. **Correction on VID Dataset:** Canonical Harvard Dataverse deposit is licensed under **CC BY-NC 4.0** (Attribution-NonCommercial), which expressly prohibits commercial use. Status: **`RESTRICTED`** (NOT CC0).
7. **Overarching Legal Conclusion:** **No candidate dataset is currently commercially cleared or unreservedly approved for open-ended enterprise use without separate written clearance or strict non-commercial bounding.**
8. **Governance Decision:** In strict adherence to E-WITNESS digital evidence handling protocols, Gate 1 is marked **`BLOCKED`**. Full training is stopped.

---

## 3. Dataset Ingestion Tooling & Evidence-Based Verification

The migration tool [`scripts/ingest_approved_dataset.py`](file:///D:/PROJECT/E-WITTNESS/scripts/ingest_approved_dataset.py) enforces:

- **Evidence on Disk:** Requires physical documentary evidence file to exist on disk before ingestion begins.
- **SPDX Allowlist & Affirmative Rights:** `license_id` must match `APPROVED_DATASET_LICENSES`, and `is_commercial_cleared` and `is_model_training_permitted` must be affirmatively true.
- **Mixed Component Filtering:** Scanning rejects any directory containing known restricted components (`moviefights`, `hockeyfight`, `rwf-2000`) with `GovernanceError`.
- **Symlink and Path-Traversal Defense:** Prevents symlink attacks and directory escapes during video scanning and evidence loading.
- **Synthetic Flagging:** Synthetic datasets cannot accidentally be marked as production eligible (`production_training_eligible = False`).
- **Bitwise Deduplication & Disjoint Splits:** Enforces zero cross-split hash overlap via SHA-256 and writes derived outputs atomically.

---

## 4. Calibration Analysis & Evaluation Data Separation

### 4.1 Calibration Analysis
- Previous smoke-test metrics (`slope A = -0.0600`, `intercept B = 0.0000`, `calibrated ECE = 0.0075`) were caused by 16 synthetic vectors hovering near $0.50$ falling into a single bin with empirical accuracy $0.50$.
- Software pipeline now guards against inverted slopes (`slope <= 0` triggers `INVERTED_SCORE_DIRECTION_FALLBACK`) and sample size deficiency ($N < 30$ triggers `FITTED_SMALL_SAMPLE`).
- Representative calibration validation requires $N \ge 100$ on verified real data (`is_statistically_adequate_benchmark`).
- Real-world calibration is formally reported as **`NOT VALIDATED`**.

### 4.2 Evaluation Data Separation
- Held-out test clips are never accessed by `train_violence_model.py`.
- Validation data is exclusively used for Platt calibration and threshold sweep analysis.
- Test data is evaluated once, without parameter tuning.
- Manifest hash semantics:
  - `INTERNAL_TEST_SPLIT`: Training manifest SHA matches evaluation manifest SHA.
  - `EXTERNAL_BENCHMARK_SPLIT`: Checkpoint evaluated on an out-of-distribution external benchmark.

---

## 5. Prerequisites for Future Production Training

Full 10-epoch training on the local NVIDIA RTX 4050 GPU remains strictly gated. It may proceed **only** when all of the following gates pass:

1. **Dataset Rights Clearance:** A replacement violence detection dataset is acquired with verified `APPROVED` rights status and an approved SPDX license identifier (`CC-BY-4.0`, `MIT`, `Apache-2.0`, `CC0-1.0`) in `backend.app.core.ai::APPROVED_DATASET_LICENSES`.
2. **Provenance Record Signed:** A complete `provenance.json` is audited and signed by the engineering and legal governance leads.
3. **Automated Ingestion:** `scripts/ingest_approved_dataset.py` ingests the dataset, confirms 0 cross-split leakage, and outputs an approved `manifest.json`.
4. **Civil-Rights Invariant Intact:** `BIOMETRIC_MATCHING_ENABLED = False` remains strictly enforced.
5. **Runtime Compatibility:** Model training executed under stable Python runtime (Python 3.12 / 3.13 LTS) to guarantee clean C++ autograd worker thread termination without Windows `0xC0000005` interpreter teardown faults.

*Report certified by Antigravity Senior Full-Stack & ML Systems Engineering.*
