# E-WITNESS Violence Detection Model Evaluation Report

**Model Identifier:** `violence-r3d18` (v`1.0.0`)
**Report Generated:** 2026-10-28T21:24:44.803153+00:00
**Evaluation Mode:** `SOFTWARE_SMOKE_TEST`
**Evaluation Level:** `clip_level`
**Operational Disclaimer:** NOTICE: AI-assisted violence detection outputs are probabilistic, advisory decision-support signals only. They do not constitute factual determinations of guilt, unlawful conduct, or disciplinary infractions. Every candidate detection requires mandatory independent human review by an authorized investigator or administrator prior to taking any investigative, disciplinary, or administrative action.

---

## 1. Primary Classification Metrics (Decision Threshold = 0.50)

| Metric | Measured Value | Operational Interpretation |
| :--- | :---: | :--- |
| **Accuracy** | 50.00% | Overall proportion of correct binary classifications |
| **Precision** | 50.00% | Positive predictive value (violence detections confirmed) |
| **Recall (Sensitivity)** | 100.00% | True positive rate (actual violent events detected) |
| **Specificity** | 0.00% | True negative rate (peaceful events correctly identified) |
| **F1 Score** | 0.6667 | Harmonic mean of precision and recall |
| **False Positive Rate** | 100.00% | False alarm rate triggering review workload |
| **False Negative Rate** | 0.00% | Missed incident rate |
| **ROC-AUC** | 0.2500 | Area under receiver operating characteristic curve |
| **PR-AUC** | 0.4018 | Area under precision-recall curve |
| **Brier Score** | 0.2573 | Mean squared probability error (lower is superior) |

### Confusion Matrix
- **True Positives (TP):** 8
- **False Positives (FP):** 8
- **True Negatives (TN):** 0
- **False Negatives (FN):** 0
- **Total Evaluated Samples (N):** 16

---

## 2. Per-Class Performance Breakdown

| Class | Support | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: | :---: |
| **Class 0 (Non-Violence)** | 8 | 0.0% | 0.0% | 0.000 |
| **Class 1 (Violence)** | 8 | 50.0% | 100.0% | 0.667 |

---

## 3. Reliability Diagram & Confidence Calibration

- **Calibration Validation Status:** **`NOT VALIDATED`**
- **Uncalibrated Expected Calibration Error (ECE):** `0.0417`
- **Calibrated ECE:** `0.0417` (Target $\le 0.08$: **MET**)
- **Maximum Calibration Error (MCE):** `0.0417`

### 10-Bin Reliability Diagram
| Bin Range | Sample Count | Mean Confidence | Empirical Accuracy | Calibration Error |
| :---: | :---: | :---: | :---: | :---: |
| `[0.0, 0.1)` | 0 | 5.0% | N/A | 0.00% |
| `[0.1, 0.2)` | 0 | 15.0% | N/A | 0.00% |
| `[0.2, 0.3)` | 0 | 25.0% | N/A | 0.00% |
| `[0.3, 0.4)` | 0 | 35.0% | N/A | 0.00% |
| `[0.4, 0.5)` | 0 | 45.0% | N/A | 0.00% |
| `[0.5, 0.6)` | 16 | 54.2% | 50.0% | 4.17% |
| `[0.6, 0.7)` | 0 | 65.0% | N/A | 0.00% |
| `[0.7, 0.8)` | 0 | 75.0% | N/A | 0.00% |
| `[0.8, 0.9)` | 0 | 85.0% | N/A | 0.00% |
| `[0.9, 1.0)` | 0 | 95.0% | N/A | 0.00% |

---

## 4. Calibration Method Comparison (Validation-Fitted, Test-Evaluated)

| Calibration Method | Status | Parameters | ECE | MCE | Brier Score |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Uncalibrated (Softmax)** | Baseline | N/A | 0.0417 | 0.0417 | 0.2573 |
| **Platt Scaling** | FITTED_SMALL_SAMPLE | {'slope': 0.0519, 'intercept': -0.0281} | 0.0626 | 0.0716 | 0.2501 |
| **Temperature Scaling** | FITTED_SMALL_SAMPLE | {'temperature': 0.5801} | 0.0714 | 0.0714 | 0.2647 |

---

## 5. Civil-Rights & Human Governance Safeguards

1. **Advisory Segments Only:** All candidate detections remain strictly advisory candidate segments for authorized human review.
2. **Zero Automated Punishment:** No guilt determination, disciplinary sanction, or punitive action is triggered automatically.
3. **Biometric Prohibition:** `BIOMETRIC_MATCHING_ENABLED = False` is enforced by code and configuration policy.
4. **Reproducibility Fingerprint:** `1fa11f9bcc39bdfdcb38bf89acfaa0a7072d4a27c34b15cda11fe924c91fd0a0`
