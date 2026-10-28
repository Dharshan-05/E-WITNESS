# E-WITNESS — Experimental Model Training v1.2.0 Execution Report

**Date:** 2026-10-27  
**Model Architecture:** ResNet3D-18 (`r3d_18`) with Kinetics-400 Pretrained Weights  
**Model Name:** `violence-r3d18-experiment`  
**Model Version:** `1.2.0`  
**Target Device:** `cuda` (NVIDIA GeForce RTX 4050 Laptop GPU, 6,140.5 MiB VRAM)  
**Safety & Governance Status:** Non-Production Experimental Prototype (`BIOMETRIC_MATCHING_ENABLED = False`)

---

## 1. Executive Summary & Verification Gates

The experimental training run for **v1.2.0** of the E-WITNESS violence detection candidate detector has completed successfully. All strict governance and verification gates were satisfied prior to and throughout execution:

1. **Environment Verification:** Verified Python 3.15.2, PyTorch 2.15.0.dev20260907+cu126 (CUDA 12.6), and NVIDIA GeForce RTX 4050 Laptop GPU.
2. **Dataset Governance Clearance:** Excluded unauthorized commercial movie footage (`MovieFights`, 188 train clips) and sports broadcast media (`HockeyFight`, 400 train clips). Restricted training strictly to the **authorized academic surveillance subset** (`Fight` and `NonFight` from RWF-2000 and Real Life Violence Situations benchmarks).
3. **Partition & Label Integrity:** Verified binary {0: non_violence, 1: violence} labels across 1,995 training clips and 262 validation clips. The held-out test partition (354 clips) remained strictly untouched during training and model selection.
4. **GPU Smoke Test:** Completed a 2-batch smoke test with AMP FP16 and gradient accumulation. Peak VRAM was 878.75 MiB (<15% GPU capacity), losses were finite (0.9526, 0.5267), and atomic checkpoint serialization was verified.
5. **Checkpoint Preservation:** Bit-for-bit SHA-256 hashes of baseline checkpoints `v1.0.0.pt` and `v1.1.0.pt` were confirmed identical before and after training.

---

## 2. Dataset Partitioning & Governance Breakdown

| Split | Raw Kaggle Manifest | Excluded (Unauthorized Movies/Hockey) | Authorized Academic Surveillance Subset | Violence (Class 1) | Non-Violence (Class 0) | Class Ratio |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Train** | 2,583 | 588 | **1,995** | 996 (49.92%) | 999 (50.08%) | 1.003 : 1.0 |
| **Val** | 328 | 66 | **262** | 102 (38.93%) | 160 (61.07%) | 1.569 : 1.0 |
| **Test** | 354 | 0 (Untouched) | **354** (Held-Out) | Held-Out | Held-Out | Held-Out |

Dynamic balanced class weighting was computed and applied to the cross-entropy loss function:
- Class 0 (`non_violence`): $w_0 = \frac{1995}{2 \times 999} = 0.9985$
- Class 1 (`violence`): $w_1 = \frac{1995}{2 \times 996} = 1.0015$

---

## 3. Training Execution & Per-Epoch Metrics

Training was executed with effective batch size 16 (micro-batch size 4, gradient accumulation steps 4), AdamW optimizer ($\text{lr} = 1 \times 10^{-4}$), label smoothing $\epsilon = 0.05$, mixed precision (AMP FP16), and random seed 42.

| Epoch | Train Loss | Train Acc | Val Loss | Val Acc | Val Precision | Val Recall | Val F1 | Confusion Matrix [TN, FP, FN, TP] | Model Selection Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 0.4972 | 77.84% | 0.3785 | 85.50% | 80.19% | 83.33% | 0.8173 | [TN=139, FP=21, FN=17, TP=85] | Checkpoint Created |
| **2** | 0.3280 | 89.12% | 0.3220 | 88.93% | 84.76% | 87.25% | 0.8599 | [TN=144, FP=16, FN=13, TP=89] | Best Val Acc Updated |
| **3** | **0.2781** | **92.23%** | **0.2934** | **90.08%** | **85.85%** | **89.22%** | **0.8750** | **[TN=145, FP=15, FN=11, TP=91]** | **Final Best Checkpoint** |

### Convergence & Performance Dynamics
- **Validation Accuracy:** Improved from 85.50% to **90.08%**.
- **Validation F1-Score:** Improved from 0.8173 to **0.8750**.
- **Recall (Violence Sensitivity):** Improved from 83.33% to **89.22%** (FN reduced from 17 to 11).
- **Precision:** Improved from 80.19% to **85.85%** (FP reduced from 21 to 15).
- **Best Epoch:** Epoch 3 achieved both lowest validation loss (0.2934) and highest validation accuracy (90.08%).

---

## 4. Hardware Utilization & Runtime Profile

- **Compute Device:** NVIDIA GeForce RTX 4050 Laptop GPU (Dedicated VRAM: 6,140.5 MiB).
- **CUDA Capability / Driver:** SM 8.9 / CUDA 12.6.
- **VRAM Utilization:** Peak memory allocated during training: ~1,250 MiB (~20.3% of capacity), leaving >4.8 GiB headroom.
- **Total Runtime:** 1,136.72 seconds (~18 minutes and 56 seconds across 3 full epochs).
- **Throughput:** ~5.26 video sequences processed per second (including temporal frame extraction, 112x112 resizing, spatial augmentation, forward/backward passes, and validation inference).

---

## 5. Artifact Directory & Cryptographic Integrity

All model assets were saved atomically using `.tmp` write-and-replace to prevent corruption.

| Asset File | Size (Bytes) | SHA-256 Checksum | Description |
| :--- | :---: | :---: | :--- |
| `artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.pt` | 398,150,767 | `d18daa747d8c6f8774e7f8cd1356f949fd18e976caa5a7a43020cf5df5f32c10` | Best model weights & optimizer state (Epoch 3) |
| `artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.json` | 2,394 | `b18f889c0ad5d45084920b22a00908892d192cae6c8e31a19fb665d9103c8fc9` | Training metadata, history, and hyperparameter log |
| `artifacts/models/experimental/v1.2.0/training.log` | 1,638 | `e5bc68a6d6e2e5ec4668b20ff44e3115457ef0c5547dbb1f41d6b0542171578b` | Full per-epoch training output and governance log |

### Preservation of Historical Checkpoints

| Checkpoint | Expected Hash | Verified On-Disk Hash | Status |
| :--- | :---: | :---: | :---: |
| `artifacts/models/violence-r3d18-v1.0.0.pt` | `e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9` | `e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9` | **Bit-for-bit MATCH** |
| `artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt` | `2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2` | `2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2` | **Bit-for-bit MATCH** |

---

## 6. Civil-Rights & Human Governance Safeguards

1. **Biometric Prohibition:** `BIOMETRIC_MATCHING_ENABLED = False` is hardcoded across all platform layers. No face recognition, facial embeddings, gait biometrics, or demographic profiling exist in this model or pipeline.
2. **Advisory Candidate Segments Only:** Model classifications are non-binding advisory indicators designed exclusively to highlight video intervals for human review.
3. **Zero Automated Punitive Actions:** No disciplinary action, detention, citation, or formal incident filing may occur on the basis of model inference alone.
4. **Non-Production Prototype Notice:** Experimental model `v1.2.0` is strictly restricted to sandbox evaluation and research. It is **not cleared for production deployment**.

---

## 7. Known Limitations & Next Steps

1. **Environmental and Optical Limitations:** Current training is restricted to 112x112 spatial resolution over 16-frame sub-sampled clips. Performance may degrade under severe low-light, dense camera occlusions, or extreme distance.
2. **Temporal Coverage:** Multi-scale temporal aggregation (e.g., sliding window with temporal consensus) should be evaluated to handle long-duration surveillance feeds.
3. **Formal Test Split Benchmark:** The 354 held-out test clips remain unexposed and available for independent out-of-sample evaluation, Platt scaling calibration verification, and operational stress matrix testing.
