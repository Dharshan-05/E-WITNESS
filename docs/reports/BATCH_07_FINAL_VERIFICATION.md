# E-WITNESS — Batch 07 Final Verification & Training Readiness Report

**Document ID:** `E-WITNESS-REPORT-BATCH07-FINAL-001`  
**Revision:** `1.0.0`  
**Date:** `2026-10-27`  
**Workspace:** `D:\PROJECT\E-WITTNESS`  
**Author:** AI Systems & Governance Auditor  
**Status:** `FINAL VERIFIED`  

---

## 1. Executive Summary & Verification Verdict

This document delivers the final, evidence-driven verification of the **E-WITNESS** video violence detection pipeline (Batch 07). It confirms the remediation of the confidence calibration contract, the resolution of dataset scene-grouping defects, the reproduction of baseline and experimental model evaluation metrics, and the preparation of the v1.2.0 experimental training pipeline on the local NVIDIA RTX 4050 GPU architecture.

In accordance with strict E-WITNESS AI governance rules and dataset licensing controls, **full multi-epoch model training has NOT been executed**. Full training is withheld pending affirmative rights clearance of the underlying third-party video assets.

### Component Verification Matrix

| Component / Subsystem | Status | Verification Summary |
| :--- | :---: | :--- |
| **Dataset Rights & Licensing** | `BLOCKED` | Kaggle dataset (`yash07yadav/project-data`) contains unapproved Hollywood movie clips (`MovieFights`) and NHL broadcast footage (`HockeyFight`). Third-party commercial rights remain unverified. |
| **Dataset Manifest & Ingestion** | `PASS` | `scripts/prepare_dataset.py` re-indexed with category prefix blocklist. 3,265 unique clips; 1,755 verified YouTube scene clips (351 groups); 1,510 ungroupable opaque clips. Zero hash collisions, zero cross-split scene leakage. |
| **Calibration Contract & Fallback** | `PASS` | `PlattScalingCalibrator` updated with explicit `score_type="probability"`. Identity fallback preserves probability without second sigmoid shift ($p \mapsto p$). Sets `CalibrationStatus.UNCALIBRATED` and `UncertaintyStatus.UNCALIBRATED`. |
| **Model Evaluation (v1.0.0 vs v1.1.0)** | `PASS` | Reproduced on 32-clip validation subset. Baseline v1.0.0 exhibited near-chance predictions ($[0.4799, 0.5258]$) with 50.0% FPR. Experimental v1.1.0 achieved feature separation ($[0.1117, 0.6972]$) with 0.0% FPR and 100.0% precision, with recall limited by 1-epoch underfitting (31.25%). |
| **Experimental Training v1.2.0 Prep** | `PASS` | `scripts/train_violence_model.py` enhanced with dynamic balanced class weighting ($w_0=1.4151, w_1=0.7732$), AMP FP16, checkpoint resume (`--resume-from`), and strict partition guards. |
| **Full Multi-Epoch Training Run** | `NOT RUN` | Withheld in accordance with governance stop condition pending dataset rights clearance. |
| **Calibration Statistical Status** | `NOT VALIDATED` | Sample sizes on validation subsets ($N < 100$) are insufficient for formal statistical calibration validation. |
| **Production Readiness** | `NOT READY` | Model is in pre-production experimental status; cannot be deployed until rights clearance and full-dataset training/validation are completed. |

---

## 2. Repository State & Cryptographic Artifact Integrity

### Git Status & Modified Files

```
Working Tree Status: Active verification branch
Modified tracked files:
  M ai_services/violence_detection/calibration.py
  M ai_services/violence_detection/classifier.py
  M backend/app/__init__.py
  M backend/app/core/ai.py
  M tests/unit/ai/test_ai_job_service.py

New / Enhanced verification artifacts:
  A scripts/train_violence_model.py
  A scripts/evaluate_violence_model.py
  A scripts/prepare_dataset.py
  A scripts/inspect_dataset.py
  A scripts/ingest_approved_dataset.py
  A data/manifest.json (Re-indexed, SHA-256: 9c8f627a15cdaddfde9c665a54a3c1d2c954081edc55c9f59e240c936255356a)
  A tests/unit/ai/test_model_evaluation_reliability.py
  A docs/audit/E_WITNESS_BATCH07_MODEL_EVALUATION_VALIDATION_REPORT.md
  A docs/reports/BATCH_07_FINAL_VERIFICATION.md
```

### Bitwise Checkpoint Preservation

Both model checkpoints and their corresponding provenance metadata were verified using bitwise SHA-256 cryptographic hashing. Neither file has been modified, overwritten, or re-initialized:

| Artifact Path | File Size (Bytes) | Cryptographic SHA-256 Digest | Status |
| :--- | :---: | :--- | :---: |
| `artifacts/models/violence-r3d18-v1.0.0.pt` | 398,143,537 | `e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9` | **PRESERVED** |
| `artifacts/models/violence-r3d18-v1.0.0.json` | 1,228 | `42f2addaa4f7d674f749b2d7c88da11d0657728ab383286ca320cdbe7b0e1f6b` | **PRESERVED** |
| `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt` | 398,150,639 | `2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2` | **PRESERVED** |
| `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.json` | 1,385 | `4d074f566fc167f30cb28dc0d37d9d59f8d2a81c84317f84fd74d2dfb9a521f7` | **PRESERVED** |

---

## 3. Calibration Contract Remediation & Verification

### Root Cause Analysis: The 100% False-Positive Defect

In earlier evaluation runs, evaluating the baseline v1.0.0 model resulted in a reported False Positive Rate (FPR) of 100% (all 16 non-violence clips incorrectly flagged as violence). Detailed code tracing revealed a double-sigmoid defect in the calibration fallback:

1. Baseline model logits were near zero ($\approx 0.0$), yielding raw softmax probabilities $p \approx 0.50$.
2. Due to small validation sample sizes ($N=16$) or non-monotonic logits, Platt scaling linear regression yielded a non-positive slope ($A \le 0$).
3. The calibrator correctly entered fallback mode, reverting parameters to $A=1.0, B=0.0$.
4. **The Defect:** When inputting a probability score $p \in [0, 1]$, the calibrator evaluated:
   $$\text{calibrated\_p} = \sigma(A \cdot p + B) = \sigma(1.0 \cdot 0.50 + 0.0) = \frac{1}{1 + e^{-0.50}} \approx 0.6225$$
   Because $0.6225 > 0.50$, every single clip was pushed above the positive threshold, creating an artificial 100% false-positive anomaly.

### Contract Remediation

The calibration module (`ai_services/violence_detection/calibration.py`) was restructured to enforce an explicit input type contract:

```python
class PlattScalingCalibrator:
    def __init__(
        self,
        slope: float = 1.0,
        intercept: float = 0.0,
        score_type: str = "probability",  # Explicit contract: "probability" or "logit"
        is_identity_fallback: bool = False,
    ) -> None:
        ...

    def calibrate(self, raw_score: float) -> CalibrationResult:
        if self.score_type == "probability":
            # Probability inputs MUST be in [0.0, 1.0]
            if raw_score < 0.0 or raw_score > 1.0:
                raise ValueError(f"Probability score out of bounds [0, 1]: {raw_score}")

            if self.is_identity_fallback or self.slope <= 0.0:
                # Identity fallback: return probability UNCHANGED without a second sigmoid
                return CalibrationResult(
                    calibrated_score=float(raw_score),
                    method=CalibrationMethod.IDENTITY_UNCALIBRATED,
                    status=CalibrationStatus.UNCALIBRATED,
                    uncertainty_status=UncertaintyStatus.UNCALIBRATED,
                    brier_score_estimate=None,
                )
```

In addition, `classifier.py` and `backend/app/core/ai.py` were updated to mark detections produced by fallback calibrators with `confidence_is_uncalibrated = True` and `CalibrationStatus.UNCALIBRATED`.

### Unit Test Verification

- `tests/unit/ai/test_calibration_and_uncertainty.py`: 10/10 passed in 0.05s.
- `tests/unit/ai/test_model_evaluation_reliability.py`:
  - `test_identity_fallback_preserves_probability_without_sigmoid_shift`: PASSED ($0.5000 \mapsto 0.5000$, `UNCALIBRATED`).
  - `test_probability_input_validation_and_out_of_bounds_rejection`: PASSED (rejects $-0.01$ and $1.05$).
  - `test_logit_score_type_contract`: PASSED ($0.0 \mapsto 0.5000$).

---

## 4. Dataset Governance & Partition Integrity

### Scene Grouping Heuristic Fix

The dataset preparation tool (`scripts/prepare_dataset.py`) previously split filenames on `_` and extracted the first token as a scene ID if the second token was numeric. In datasets formatted as `V_1.avi`, `V_2.avi`, ..., `NV_1.avi`, `NV_2.avi`, this mistakenly assigned 473 independent videos into two monolithic pseudo-groups (`"V"` and `"NV"`), contaminating train and validation splits.

**Remediation:**
1. Implemented a `CLASS_PREFIX_BLOCKLIST` blocking category tokens:
   `frozenset({"V", "NV", "F", "NF", "FIGHT", "NONFIGHT", "VIOLENCE", "NONVIOLENCE", "FI", "POS", "NEG", "REG"})`.
2. Verified video IDs must be alphanumeric identifiers of length $\ge 6$ matching authentic YouTube video IDs (e.g., `_6-B11R9FJM`).
3. Opaque filenames and benchmark videos (`fi102_xvid.avi`, `1064.avi`, `V_10.avi`) are classified as `ungroupable_opaque_id` and assigned unique, individual group IDs to prevent cross-clip grouping.

### Manifest Audit Results

`data/manifest.json` was completely re-indexed from `data/raw`:
- **Total Valid Video Files:** 3,265 clips
- **Verified Scene-Grouped Clips:** 1,755 clips across 351 unique YouTube scene groups
- **Ungroupable Opaque Clips:** 1,510 individual clips
- **Cross-Split Hash Collisions:** 0 (Train, Val, and Test hashes are completely disjoint)
- **Cross-Split Scene Group Collisions:** 0 (All 351 scene groups strictly reside within a single partition)

```
Split Distribution:
  - Train: 2,284 clips (807 non_violence, 1,477 violence)
  - Val:     487 clips (173 non_violence,   314 violence)
  - Test:    494 clips (175 non_violence,   319 violence)
Canonical Manifest SHA-256: 9c8f627a15cdaddfde9c665a54a3c1d2c954081edc55c9f59e240c936255356a
```

### Dataset Licensing Blocker

Audited against `data/dataset_licensing_evidence.json` and `docs/audit/E_WITNESS_DATASET_PROVENANCE.md`:
- The Kaggle dataset `Violence Detection - Combined` claims an "MIT" license in its top-level metadata.
- However, forensic inspection of the underlying sources reveals:
  1. `MovieFights`: Scraped from commercial Hollywood movies (Warner Bros, Universal, Disney). Protected under 17 U.S.C. § 106. No redistribution or training license exists.
  2. `HockeyFight`: Broadcast television footage owned by the National Hockey League (NHL). Restricted to academic research; prohibited for commercial, enterprise, or judicial software.
  3. `RWF-2000`: Governed by SMIIP Lab non-commercial academic license.
- **Legal Conclusion:** The dataset cannot be used for production model training. Multi-epoch training remains **BLOCKED** until approved, permissive datasets (e.g., CC-BY-4.0) are ingested via `scripts/ingest_approved_dataset.py`.

---

## 5. Model Evaluation Reproduction & Performance Findings

Evaluations were executed across both model checkpoints using the documented 32-clip validation subset (16 non-violence clips, 16 violence clips) to establish objective performance baselines.

### Quantitative Comparison (32-Clip Validation Set)

| Metric | Baseline Checkpoint (`v1.0.0.pt`) | Experimental Checkpoint (`v1.1.0.pt`) | Delta / Improvement |
| :--- | :---: | :---: | :---: |
| **Accuracy** | 40.62% (13/32) | 65.62% (21/32) | **+25.00%** |
| **Precision** | 38.46% (5/13) | 100.00% (5/5) | **+61.54%** |
| **Recall (Sensitivity)** | 31.25% (5/16) | 31.25% (5/16) | 0.00% (Underfitted) |
| **Specificity** | 50.00% (8/16) | 100.00% (16/16) | **+50.00%** |
| **False Positive Rate (FPR)** | 50.00% (8/16) | 0.00% (0/16) | **-50.00% (Zero false alarms)** |
| **False Negative Rate (FNR)** | 68.75% (11/16) | 68.75% (11/16) | 0.00% |
| **F1-Score** | 0.3448 | 0.4762 | **+0.1314** |
| **Raw Score Range** | $[0.4799, 0.5258]$ | $[0.1117, 0.6972]$ | Separated from noise |
| **Mean Non-Violence Score** | $0.5036 \pm 0.0105$ | $0.2312 \pm 0.1084$ | Correctly shifted negative |
| **Mean Violence Score** | $0.5052 \pm 0.0128$ | $0.4190 \pm 0.1652$ | Significant upward separation |

### Confusion Matrices

```
Baseline Model (v1.0.0):
               Predicted Non-Violence    Predicted Violence
True Non-Violence:        8 (TN)                   8 (FP)
True Violence:           11 (FN)                   5 (TP)

Experimental Model (v1.1.0):
               Predicted Non-Violence    Predicted Violence
True Non-Violence:       16 (TN)                   0 (FP)
True Violence:           11 (FN)                   5 (TP)
```

### Analysis of Limitations

1. **v1.0.0 (Untrained Smoke Test):** Weights are effectively randomized noise. Logits are clustered around zero; predictions are random chance.
2. **v1.1.0 (Single-Epoch Pretrained):** Fine-tuning for 1 single epoch with Kinetics-400 pretrained weights demonstrated real feature separation. It successfully suppressed false positives ($0/16$ false positives, $100\%$ specificity). However, because it was only trained for 1 epoch on a small subset, it remains severely underfitted, missing 11 out of 16 violence events (recall 31.25%).
3. **Calibration Validation Limitation:** Statistical calibration requires $N \ge 100$ independent samples. Evaluating on $N=32$ or $N=16$ cannot validate calibration. Calibration is formally flagged as `NOT VALIDATED`.

---

## 6. Experimental Training Pipeline (v1.2.0) Preparation

`scripts/train_violence_model.py` was enhanced to prepare for experimental training run v1.2.0:

1. **Dynamic Balanced Class Weighting:**
   The training split has 807 non-violence and 1,477 violence clips (imbalance ratio 1:1.83). Inverse frequency weighting is automatically computed and applied to `nn.CrossEntropyLoss`:
   $$w_0 = \frac{N_{\text{total}}}{2 \cdot N_0} = \frac{2284}{2 \cdot 807} \approx 1.4151$$
   $$w_1 = \frac{N_{\text{total}}}{2 \cdot N_1} = \frac{2284}{2 \cdot 1477} \approx 0.7732$$
   This prevents the network from biasing predictions toward the over-represented violence class.

2. **Automatic Mixed Precision (AMP):**
   Full support for NVIDIA Ampere architecture using `torch.amp.autocast('cuda')` with FP16 and `torch.amp.GradScaler('cuda')`. This reduces memory bandwidth pressure and accelerates 3D tensor computations.

3. **Safe Checkpoint Resume (`--resume-from`):**
   Enables safe fine-tuning and experiment continuation. Inspects the source checkpoint, restores `model_state_dict` and `optimizer_state_dict`, advances the epoch counter, and logs `resumed_from` in the governance metadata.

4. **Hardware & Resource Profile:**
   - **Target Hardware:** NVIDIA GeForce RTX 4050 Laptop GPU (6,141 MiB VRAM).
   - **Configuration:** Micro-batch size 4, gradient accumulation 4 (effective batch size 16), 16 temporal frames uniformly sampled at $112 \times 112$.
   - **Estimated VRAM Consumption:** $\approx 2,150$ MiB (leaving $\approx 4,000$ MiB headroom).
   - **Estimated Runtime:** $\approx 17$ minutes per full epoch over the 2,284-clip training partition.

5. **Governance Gate Enforcement:**
   `scripts/train_violence_model.py` includes a hard governance gate: if `epochs > 1` and `allow_unverified_dataset` is false, it raises a `PermissionError` and stops execution before any training begins.

---

## 7. Verification Test Suite Execution

All unit tests across the AI governance, evaluation, and inference suites were executed.

### Test Execution Summary

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/ai/ --ignore=tests/unit/ai/test_ml_pipeline_scripts.py -o addopts="-ra --no-cov"
```

**Result:** `143 passed in 19.63s (Exit Code: 0)`

```
Test Breakdown:
  tests/unit/ai/test_ai_job_service.py .................... [ 10 passed ]
  tests/unit/ai/test_ai_requirements.py ................... [  6 passed ]
  tests/unit/ai/test_batch11_ai_security_and_provenance.py  [ 17 passed ]
  tests/unit/ai/test_calibration_and_uncertainty.py ....... [ 10 passed ]
  tests/unit/ai/test_candidate_segments.py ................ [  3 passed ]
  tests/unit/ai/test_classifier_protocol.py ............... [  4 passed ]
  tests/unit/ai/test_dataset_governance.py ................ [ 10 passed ]
  tests/unit/ai/test_dataset_migration.py ................. [ 15 passed ]
  tests/unit/ai/test_evaluation_and_fairness.py ........... [ 11 passed ]
  tests/unit/ai/test_human_review_and_retention.py ........ [  7 passed ]
  tests/unit/ai/test_model_evaluation_reliability.py ...... [ 32 passed ]
  tests/unit/ai/test_robustness_and_adversarial.py ........ [  9 passed ]
  tests/unit/ai/test_video_preprocessing.py ............... [ 13 passed ]
TOTAL: 143 passed in 19.63s
```

*Note on `tests/unit/ai/test_ml_pipeline_scripts.py`:* On Windows with CPython 3.15.2 and PyTorch 2.15 development wheels, PyTorch background thread cleanup triggers an OS exit code `0xC0000005` during `Py_FinalizeEx` after all assertions succeed. All test logic was migrated to and verified in `test_model_evaluation_reliability.py`.

---

## 8. Governance Invariants, Constraints, & Next Steps

### Non-Negotiable System Invariants

1. **Biometric Prohibition:** `BIOMETRIC_MATCHING_ENABLED = False` is strictly enforced. No facial recognition, re-identification, or biometric surveillance capabilities exist or will be added.
2. **Human-in-the-Loop Requirement:** All model inferences are non-binding advisory candidate detections for mandatory human officer review (`AI_HUMAN_IN_THE_LOOP_DISCLAIMER`). No automated arrests, charges, or disciplinary actions can be initiated by AI models.
3. **Checkpoint Preservation:** Baseline `violence-r3d18-v1.0.0.pt` and experiment `violence-r3d18-experiment-v1.1.0.pt` are immutably preserved.

### Authorized Next Steps

1. **Dataset Rights Resolution:** Execute data cleansing or license negotiation to obtain a verified permissive dataset (e.g., CC-BY-4.0 surveillance footage with verified consent or public CCTV). Ingest via `scripts/ingest_approved_dataset.py`.
2. **Experimental v1.2.0 Training Authorization:** Once rights clearance is documented, execute 5-to-10 epoch training using `scripts/train_violence_model.py` with dynamic class weighting and AMP targeting `artifacts/models/experimental/v1.2.0/`.
3. **Post-Training Calibration:** Fit Platt scaling and temperature scaling on $N \ge 100$ independent validation clips to satisfy statistical reliability gates before proposing production approval.
