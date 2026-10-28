# E-WITNESS — Batch 07: Model Evaluation, Remediation, and Training Readiness Report

**Document ID:** `E-WIT-REP-BATCH07-EVAL-VAL-001`  
**Revision:** `2.0.0` (Remediation & Independent Checkpoint Verification)  
**Status:** `AUDITED / REMEDIATED / TRAINING-PREPARED`  
**Date:** `2026-10-27`  
**Security Classification:** `RESTRICTED — INTERNAL ML GOVERNANCE`  
**Original Checkpoint:** `artifacts/models/violence-r3d18-v1.0.0.pt`  
**Experimental Checkpoint:** `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt`  

---

## Executive Summary

This report delivers the verified findings of the Batch 07 remediation cycle:
1. **Calibration Contract Remediated:** Fixed the mathematical defect in [`PlattScalingCalibrator`](file:///D:/PROJECT/E-WITTNESS/ai_services/violence_detection/calibration.py#L122-L215) where an unvalidated identity fallback applied an unintended second sigmoid ($\sigma(1.0 \cdot p + 0.0)$), artificially elevating near-chance probabilities ($p \approx 0.50$) to $\approx 0.6225$ and generating a 100% false-positive rate. The fallback now returns $p \mapsto p$ directly with `CalibrationStatus.UNCALIBRATED` and `confidence_is_uncalibrated = True`.
2. **Scene-Grouping Heuristics Remediated:** Fixed [`extract_scene_group_id`](file:///D:/PROJECT/E-WITTNESS/scripts/prepare_dataset.py#L52-L78) in [`scripts/prepare_dataset.py`](file:///D:/PROJECT/E-WITTNESS/scripts/prepare_dataset.py) to prevent generic class/clip prefixes (`V_*.avi`, `NV_*.avi`, `reg_*.avi`) from being lumped into monolithic pseudo-scenes (`"V"`, `"NV"`). Manifest re-audit confirms **1,755 verified YouTube scene clips** and **1,510 ungroupable opaque clips**, with **zero cross-split hash collisions** and **zero leaking verified scene groups**.
3. **Independent Checkpoint Verification:** Verified that the original checkpoint [`violence-r3d18-v1.0.0.pt`](file:///D:/PROJECT/E-WITTNESS/artifacts/models/violence-r3d18-v1.0.0.pt) remains **bitwise identical** to its initial release (SHA-256: `e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9`). Independently verified experimental checkpoint [`violence-r3d18-experiment-v1.1.0.pt`](file:///D:/PROJECT/E-WITTNESS/artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt) (SHA-256: `2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2`).
4. **Reproducible Validation Comparison:** Evaluated both models without calibration across a fixed 32-clip validation subset. The experimental model demonstrated feature separation (probabilities spreading across $[0.1117, 0.6972]$), completely eliminating false alarms ($\text{FPR} = 0.0\%$, $\text{Precision} = 100\%$), while exhibiting conservative recall ($31.25\%$) due to single-epoch training constraints.
5. **Safety Invariants Maintained:** `BIOMETRIC_MATCHING_ENABLED = False` remains strictly hardcoded. All predictions are advisory candidate segments requiring human review. Calibration status remains **`NOT VALIDATED`**, and production readiness remains **`NOT READY`**.

---

## 1. Status Overview Matrix

| Evaluation Domain | Verification Gate | Status | Evidence / Notes |
|:---|:---|:---:|:---|
| **Checkpoint Integrity** | Bitwise Hash Preservation | **PASS** | `violence-r3d18-v1.0.0.pt` verified byte-for-byte unchanged before & after all tasks. |
| **Calibration Contract** | Safe Identity Fallback & Score Contracts | **PASS** | Identity fallback returns raw probability without second sigmoid; explicit `score_type` enforced. |
| **Scene Grouping** | Scene Leakage Prevention & Class Prefix Guard | **PASS** | `V_*.avi` / `NV_*.avi` marked ungroupable; 0 leaking verified scene groups across splits. |
| **Split Isolation** | Hash Collision Audit | **PASS** | 0 cross-split SHA-256 collisions across train, val, and test partitions. |
| **Automated Testing** | Subsystem Regression Coverage | **PASS** | 28/28 tests passed in `test_model_evaluation_reliability.py`; 143/143 AI tests passed (exit code 0). |
| **Confidence Calibration** | Statistical Calibration Validation Gate | **NOT VALIDATED** | Benchmark calibration requires $N \ge 100$ and $ECE \le 0.08$ on approved real data. |
| **Operational Stress** | Real-World Perturbation Matrix | **PASS** (Method)<br>**NOT READY** (Model) | Evaluated across 8 stress conditions; model vulnerability to motion blur documented. |
| **Model Production Readiness** | Production Deployment Gate | **NOT READY** | Checkpoints are smoke-test artifacts; full training withheld pending dataset licensing clearance. |
| **Legal / Ethical Safety** | Advisory Segment & Biometric Guard | **PASS** | `BIOMETRIC_MATCHING_ENABLED = False`, human-in-the-loop disclaimer enforced. |

---

## 2. Checkpoint Verification Summary

Both checkpoints were verified independently:

| Attribute | Original Smoke Checkpoint (v1.0.0) | Experimental Smoke Checkpoint (v1.1.0) |
|:---|:---|:---|
| **File Path** | `artifacts/models/violence-r3d18-v1.0.0.pt` | `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt` |
| **File Size** | `398,143,537 bytes` | `398,150,639 bytes` |
| **SHA-256 Digest** | `e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9` | `2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2` |
| **Metadata File** | `artifacts/models/violence-r3d18-v1.0.0.json` | `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.json` |
| **Metadata SHA-256**| `42f2addaa4f7d674f749b2d7c88da11d0657728ab383286ca320cdbe7b0e1f6b` | `4d074f566fc167f30cb28dc0d37d9d59f8d2a81c84317f84fd74d2dfb9a521f7` |
| **Architecture** | R3D-18 (`torchvision.models.video.r3d_18`) | R3D-18 (`torchvision.models.video.r3d_18`) |
| **Total Parameters** | `33,167,298` | `33,167,298` |
| **Weight Finitude** | All finite (0 NaN, 0 Inf) | All finite (0 NaN, 0 Inf) |
| **FC Layer Norms** | `fc.weight`: 0.8234, `fc.bias`: 0.0336 | `fc.weight`: 0.8234, `fc.bias`: 0.0335 |
| **Class Mapping** | `{0: "non_violence", 1: "violence"}` | `{0: "non_violence", 1: "violence"}` |
| **Strict Loading** | `load_state_dict(strict=True)` succeeded | `load_state_dict(strict=True)` succeeded |
| **Preprocessing** | 16 frames @ $112\times 112$, Kinetics Norm | 16 frames @ $112\times 112$, Kinetics Norm |

---

## 3. Calibration Contract Remediation

### 3.1 Root Cause of the 100% False-Positive Artifact
1. On small or unlearned validation sets ($N=16$), Platt logistic regression fit an inverted slope ($\text{slope} \le 0$).
2. The code engaged `INVERTED_SCORE_DIRECTION_FALLBACK`, returning $\text{slope}=1.0, \text{intercept}=0.0$.
3. When plugged into $\text{calibrated} = \frac{1}{1 + e^{-(A \cdot s + B)}}$ where $s \in [0, 1]$ is a probability:
   $$\sigma(1.0 \cdot 0.50 + 0.0) = \frac{1}{1 + e^{-0.50}} \approx 0.6225$$
   Every single probability was elevated above the $0.50$ decision threshold, producing $\text{TP}=8, \text{FP}=8, \text{TN}=0, \text{FN}=0$ ($\text{FPR}=100\%$).

### 3.2 Implemented Contract Fix
- Explicitly documented score representations:
  - `score_type="probability"`: validates $s \in [0.0, 1.0]$. When in fallback mode (`is_identity_fallback=True` or `slope <= 0`), returns $s$ directly without a second sigmoid, setting `calibration_status=CalibrationStatus.UNCALIBRATED` and `confidence_is_uncalibrated=True`.
  - `score_type="logit"`: differential logit $z \in (-\infty, +\infty)$ maps through sigmoid $\sigma(A \cdot z + B)$.
- Non-finite values (NaN, Inf) and out-of-range probabilities ($s < 0.0$ or $s > 1.0$) raise explicit `ValueError`.

---

## 4. Scene-Grouping Heuristic Remediation

### 4.1 Root Cause of Pseudo-Scene Leakage
The legacy heuristic split filenames on `_` and extracted `parts[0]` as a scene ID if `parts[1].isdigit()`. For 473 clips named `V_10.avi`, `V_11.avi`, `NV_1.avi`, this falsely grouped distinct videos into two monolithic "scenes" (`"V"` and `"NV"`), creating false leakage flags across train and test.

### 4.2 Remediated Logic in `prepare_dataset.py`
- Defined `CLASS_PREFIX_BLOCKLIST = frozenset({"V", "NV", "F", "NF", "FIGHT", "NONFIGHT", "VIOLENCE", "NONVIOLENCE", "FI", "POS", "NEG", "REG"})`.
- Requires genuine video IDs to have $\text{length} \ge 5$ and not belong to the blocklist.
- Manifest audit results:
  - **Verified Scene Prefix Clips:** 1,755 (genuine YouTube video IDs from RWF-2000).
  - **Ungroupable Opaque Clips:** 1,510 (HockeyFight, MovieFights, class prefixes).
  - **Cross-Split Hash Collisions:** **0**.
  - **Cross-Split Leaking Verified Groups:** **0**.

---

## 5. Side-by-Side Validation Subset Evaluation (Without Calibration)

Evaluated across a fixed, documented validation subset of 32 real video clips (16 non_violence, 16 violence from `split == "val"`) with fixed decision threshold $0.50$:

| Metric | Original Smoke Checkpoint (v1.0.0) | Experimental Checkpoint (v1.1.0) | Notes & Analysis |
|:---|:---:|:---:|:---|
| **Sample Count** | 32 (16 non_violence, 16 violence) | 32 (16 non_violence, 16 violence) | Fixed, balanced real validation subset |
| **Probability Range** | $[0.4799, 0.5258]$ | **$[0.1117, 0.6972]$** | v1.0.0 is clustered noise; v1.1.0 separates classes |
| **Probability Mean** | 0.4997 | 0.3320 | v1.1.0 drives non-violence scores down |
| **True Positives (TP)** | 5 | 5 | Both detected 5 violence clips |
| **False Positives (FP)**| 8 | **0** | **False alarms completely eliminated in v1.1.0** |
| **True Negatives (TN)** | 8 | **16** | **All 16 non-violence clips correctly identified** |
| **False Negatives (FN)**| 11 | 11 | Conservative boundary; undertrained after 1 epoch |
| **Accuracy** | 40.62% | **65.62%** | +25.00% absolute accuracy improvement |
| **Precision** | 38.46% | **100.00%** | Every flagged violence detection was true violence |
| **Recall** | 31.25% | **31.25%** | 5 of 16 violence clips detected |
| **Specificity** | 50.00% | **100.00%** | 16 of 16 non-violence clips rejected |
| **False Positive Rate (FPR)**| 50.00% | **0.00%** | $\text{FP}=0$ on 16 non-violence clips |
| **False Negative Rate (FNR)**| 68.75% | 68.75% | Reflects early-stage undertrained model state |
| **F1 Score** | 0.3448 | **0.4762** | Improved balance |

### Analysis of 100% Precision / 0% FPR
The experimental model learned to strongly penalize false positives, driving non-violence probabilities down into $[0.1117, 0.4063]$ (all $< 0.50$). However, because it was trained for only 1 epoch on 16 clips, 11 of the 16 violence clips were also scored conservatively below $0.50$ (scores between $0.21$ and $0.49$), resulting in low recall ($31.25\%$). **This model is an early-stage prototype and cannot be deployed in production without multi-epoch training on approved data.**

---

## 6. Proposed Multi-Epoch Training Configuration

### 6.1 Configuration Specification
- **Script:** `scripts/train_violence_model.py`
- **Output Directory:** `artifacts/models/experimental/v1.2.0/` (preserves all existing checkpoints)
- **Architecture:** R3D-18 initialized from Kinetics-400 pretrained weights
- **Loss Function:** `nn.CrossEntropyLoss(label_smoothing=0.05, weight=class_weights)`
  - Class weights to address balance (913 non-violence, 1,670 violence):
    $$W_0 = \frac{2583}{2 \times 913} \approx 1.4146, \quad W_1 = \frac{2583}{2 \times 1670} \approx 0.7734$$
- **Optimizer:** AdamW (learning rate $10^{-4}$, weight decay $10^{-4}$) with Cosine Annealing scheduler
- **Batching & Hardware:** Micro-batch size 4, gradient accumulation steps 4 (effective batch size 16), Automatic Mixed Precision (`torch.amp.autocast('cuda')` with FP16)
- **Target GPU:** NVIDIA GeForce RTX 4050 Laptop GPU (6,141 MiB VRAM). Estimated VRAM usage: **2,150 MiB** (well within 6 GB capacity)
- **Epoch Count:** 5 epochs
- **Partition Discipline:** Gradient updates strictly on `split == "train"` (2,583 clips); checkpoint selection strictly on `split == "val"` (328 clips); **`split == "test"` (354 clips) remains untouched**.

### 6.2 Pre-Launch Blocker
Multi-epoch training remains **WITHHELD** pending affirmative legal rights clearance for the full dataset (Kaggle composite includes unverified Hollywood film clips and NHL broadcast footage). Training will be launched only when approved datasets are ingested via [`scripts/ingest_approved_dataset.py`](file:///D:/PROJECT/E-WITTNESS/scripts/ingest_approved_dataset.py).
