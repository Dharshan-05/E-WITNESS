# E-WITNESS Real-World Performance & Operational Stress Testing Plan

**Model:** `violence-r3d18` (v`1.0.0`)
**Status:** **`NOT VALIDATED`**
**Evaluation Type:** `SOFTWARE_SMOKE_TEST`

---

## 1. Operational Stress Test Matrix

The model was subjected to 8 controlled digital perturbations simulating real-world operational challenges:

| Stress Condition | Description | Accuracy | Precision | Recall | False Alarms (FP) | Missed Events (FN) | Mean Score |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`baseline`** | Original unperturbed video stream | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5378 |
| **`low_light`** | Low ambient illumination (intensity x0.40) | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5935 |
| **`bright_glare`** | Direct glare / overexposure (intensity x1.60) | 50.0% | N/A | 0.0% | 0 | 8 | 0.4614 |
| **`low_resolution`** | Heavy spatial compression (56x56 downsampled & restored) | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5992 |
| **`camera_motion_blur`** | Horizontal camera pan / motion shake blur | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5836 |
| **`spatial_occlusion`** | Partial scene occlusion (32x32 center masking) | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5590 |
| **`sensor_noise`** | Additive sensor noise (sigma=0.15 Gaussian noise) | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5418 |
| **`temporal_truncation`** | Short clip / frame stutter (half-sequence repetition) | 50.0% | 50.0% | 100.0% | 8 | 0 | 0.5402 |

---

## 2. Dataset Split & Leakage Review

- **Total Inspected Items:** 0
- **Cross-Split Bitwise Hash Leakage:** **NONE DETECTED (PASS)**
- **Hash Overlap Details:** {}
- **Verifiable Scene-Prefix Clips:** 0
- **Ungroupable Opaque Clips (HockeyFight/MovieFights):** 0
- **Class Balance by Split:**
  - `train`: {}
  - `val`: {}
  - `test`: {}

---

## 3. Real-World Readiness & Deployment Verdict

- **Production Readiness:** **`NOT READY`**
- **Reason:** Model has only undergone software pipeline verification and synthetic/smoke evaluation. Full training is gated behind upstream dataset rights clearance.
- **Prerequisites for Future Deployment:**
  1. Acquisition of commercially approved, consensual surveillance dataset.
  2. Multi-epoch training on NVIDIA RTX 4050 GPU under Python 3.12/3.13 LTS.
  3. Real-world validation on at least $N \ge 100$ held-out operational video clips.
  4. Human-in-the-loop audit verification.
