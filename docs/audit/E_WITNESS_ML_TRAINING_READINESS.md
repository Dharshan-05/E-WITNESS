# E-WITNESS — MACHINE LEARNING TRAINING READINESS AUDIT

**Document Reference**: `docs/audit/E_WITNESS_ML_TRAINING_READINESS.md`  
**Target Subsystem**: `ai_services/violence_detection`  
**Audit Baseline**: Local Video AI Fine-Tuning Pipeline & Dataset Readiness  
**Audit Date**: October 26, 2026  
**Auditor**: Senior Machine Learning Engineer & Full-Stack Architect  

---

## 1. Local Hardware Environment Assessment

A hardware probe of the host system was executed during the audit:

| Hardware Component | Verified Specification | Operational Feasibility for Training |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Home Single Language (64-bit) | Supported by PyTorch with CUDA 12.1/12.4. |
| **GPU** | **NVIDIA GeForce RTX 4050 Laptop GPU** | **6,141 MiB (~6 GB) GDDR6 VRAM**, Ada Lovelace architecture with 4th Gen Tensor Cores supporting FP16 and BF16 mixed precision. |
| **GPU Driver & CUDA** | Driver `616.92`, CUDA UMD Version `13.4` | Compatible with PyTorch CUDA 12.1 / 12.4 prebuilt wheels. |
| **System RAM** | **16,053,040 KB (~16 GB physical RAM)** | Sufficient for training with `DataLoader(num_workers=2)`. ~4.3 GB currently free; closing browser and background processes before training is recommended. |
| **Drive D: Storage** | **99.59 GB Free** | **PRIMARY TRAINING STORAGE**: Ample capacity to store video datasets (10–25 GB), decoded frames, and checkpoint weights. |
| **Drive C: Storage** | **14.65 GB Free** | **CONSTRAINED**: Do NOT store datasets or model checkpoints on Drive C. Set `TORCH_HOME=D:\PROJECT\E-WITTNESS\.cache\torch` and `HF_HOME=D:\PROJECT\E-WITTNESS\.cache\huggingface`. |

---

## 2. Python & PyTorch Runtime Setup Requirements

### 2.1 Active Runtime Baseline: Python 3.15 & Unified Virtual Environment
The host environment has been upgraded to **Python 3.15.2** (64-bit). The dedicated project virtual environment has been provisioned at `D:\PROJECT\E-WITTNESS\.venv` and all baseline development dependencies (`requirements-dev.txt`) are installed. **100% of unit tests (995/995) pass** under Python 3.15.

### 2.2 PyTorch 2.15.0 with CUDA 12.6 Acceleration

PyTorch officially supports Python 3.15 (`cp315` and free-threaded `cp315t`) starting with **PyTorch 2.15.0**. Prebuilt Windows AMD64 wheels with CUDA 12.6 acceleration are hosted via PyTorch's official index:

1. **Install PyTorch 2.15.0 + Torchvision + Torchaudio (CUDA 12.6)**:
   ```powershell
   .\.venv\Scripts\pip.exe install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu126
   ```
2. **Install Computer Vision & Video Decoding Utilities**:
   ```powershell
   .\.venv\Scripts\pip.exe install opencv-python av scikit-learn
   ```
3. **Verify CUDA Availability on RTX 4050**:
   ```powershell
   .\.venv\Scripts\python.exe -c "import torch; print('CUDA available:', torch.cuda.is_available(), '| Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
   ```
5. **Install Computer Vision & Video Decoding Utilities**:
   ```powershell
   .\.venv\Scripts\pip.exe install opencv-python av scikit-learn
   ```
6. **Verify CUDA Availability**:
   ```powershell
   .\.venv\Scripts\python.exe -c "import torch; print('CUDA available:', torch.cuda.is_available(), '| Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
   ```

---

## 3. Kaggle Dataset Readiness & Verification Checklist

### 3.1 Dataset Under Consideration
- **Target URL**: `https://www.kaggle.com/datasets/yash07yadav/project-data`
- **Audit Constraint Enforced**: In strict compliance with Audit Rule 13, the dataset was **NOT downloaded** during this audit.
- **Current Verification Status**: **UNVERIFIED**.

### 3.2 What Can and Cannot Be Established

| Property | Current Verification Status | Detail / Finding from Research |
| :--- | :---: | :--- |
| **Identity & Author** | **PROBABLE** | Kaggle user `yash07yadav` hosts violence detection datasets (e.g. `violence-detection-combined`). |
| **Dataset Contents** | **UNVERIFIED** | Whether `project-data` contains raw MP4s, extracted frame folders, or optical flow features is unknown. |
| **License (SPDX)** | **UNVERIFIED** | Must be inspected upon download. Must match `backend/app/core/ai.py::APPROVED_DATASET_LICENSES` (e.g., CC-BY-4.0, CC0-1.0, MIT, Apache-2.0). |
| **Archive Size** | **UNVERIFIED** | Estimated between 2 GB and 15 GB based on related Kaggle violence datasets. |
| **Class Balance** | **UNVERIFIED** | Number of violent vs non-violent clips is unverified. Potential class imbalance must be measured. |
| **Split Quality** | **UNVERIFIED** | Whether pre-split into train/val/test, and whether clips from the same scene/camera leak across splits, is unverified. |
| **Subject Consent** | **UNVERIFIED** | Public surveillance vs staged movie fights vs real-world physical altercations must be audited. |

### 3.3 Safe Local Inspection Plan (Prior to Training)

Before training begins, a safe, non-destructive inspection must be executed:

```powershell
# Step 1: Download dataset to Drive D using Kaggle CLI (do not put on C:)
$env:KAGGLE_CONFIG_DIR = "D:\PROJECT\E-WITTNESS\.kaggle"
kaggle datasets download -d yash07yadav/project-data -p D:\PROJECT\E-WITTNESS\data\raw\ --unzip

# Step 2: Execute inspection script (to be written)
.\.venv\Scripts\python.exe scripts/inspect_dataset.py --data-dir D:\PROJECT\E-WITTNESS\data\raw
```

The inspection script must report:
1. Exact total archive size and directory hierarchy.
2. File format distribution (`.mp4`, `.avi`, `.jpg`, `.npy`).
3. Video properties: Duration (min, max, mean), resolution distribution ($W \times H$), frame rates (FPS), and decodability with OpenCV/PyAV.
4. Class counts: Total violent vs non-violent clips.
5. Detection of duplicate or near-identical clips via perceptual hash or file size/name patterns.
6. Verification against SPDX license requirements in `backend/app/core/ai.py`.

---

## 4. Train, Validation & Test Split Strategy

To prevent subtle **data leakage** (a severe failure mode in video classification where adjacent frames or different camera angles of the same fight appear in both training and test sets):

1. **Group-Based Splitting**:
   - Split must be grouped by **scene/event identifier** or **source video**, not randomly by clip.
   - All clips derived from a single camera recording or YouTube URL must reside strictly within one partition.
2. **Three-Way Partition**:
   - **Training Set (70%)**: Used solely for updating model weights during backpropagation.
   - **Validation Set (15%)**: Used solely for early stopping, learning rate scheduling, and **fitting the confidence calibration engine** (Platt scaling / Isotonic regression).
   - **Test Set (15%)**: Held-out benchmark evaluated only once after final model selection. Under `ai_services/violence_detection/calibration.py::CalibrationArtifact.validate_compatibility()`, fitting calibration on the test set raises `CalibrationIncompatibilityError` to prevent leakage.
3. **Canonical Manifest Generation**:
   - A JSON manifest recording relative path, label (`violence` / `non_violence`), split (`train` / `val` / `test`), duration, and video SHA-256 must be generated.
   - The manifest's composite SHA-256 digest will be computed via `backend/app/core/ai.py::compute_manifest_sha256()`.

---

## 5. Model Selection & Architecture Justification

### 5.1 Architecture Evaluation for 6 GB VRAM

| Model Architecture | Parameters | Checkpoint Size | VRAM Training Peak (FP16, Batch=4) | Suitability for RTX 4050 Laptop (6 GB) |
| :--- | :---: | :---: | :---: | :--- |
| **ResNet3D-18 (R3D-18)** | **33.4 M** | **~130 MB** | **~3.2 – 4.2 GB** | **RECOMMENDED (HIGH)**: Proven spatial-temporal 3D-CNN; natively supported by `torchvision.models.video`; fits comfortably within 6 GB VRAM. |
| **Mixed 3D Convolution (MC3-18)** | 31.8 M | ~125 MB | ~3.0 – 4.0 GB | **RECOMMENDED ALTERNATIVE**: Similar footprint to R3D-18; 3D convs in early layers, 2D in late. |
| **MoViNet (A0 / A2)** | 3.1 M – 5.2 M | ~15 – 25 MB | ~2.5 – 3.5 GB | **VIABLE ALTERNATIVE**: Very lightweight mobile architecture; requires custom PyTorch port. |
| **TimeSformer-Base** | 121 M | ~480 MB | ~7.5 – 9.0 GB | **NOT SUITABLE**: Exceeds 6 GB VRAM without aggressive gradient checkpointing and micro-batch size of 1. |
| **VideoMAE-Base** | 86 M | ~340 MB | ~6.5 – 8.0 GB | **NOT SUITABLE**: High memory consumption during attention computation across 16 frames. |

### 5.2 R3D-18 Model Selection Verdict
**R3D-18 is the optimal choice** for this laptop environment. It provides robust temporal feature extraction across video frames while operating well within the 6 GB VRAM budget.

---

## 6. Memory-Efficient Training Configuration

To fine-tune R3D-18 on the RTX 4050 without encountering CUDA Out-Of-Memory (OOM) errors:

1. **Automatic Mixed Precision (AMP)**:
   - Use `torch.cuda.amp.autocast(dtype=torch.float16)` and `torch.cuda.amp.GradScaler()`.
   - Halves activation memory and accelerates Tensor Core matrix multiplication.
2. **Micro-Batch Sizing & Gradient Accumulation**:
   - `micro_batch_size = 4` (or 8 depending on clip length).
   - `gradient_accumulation_steps = 4` (effective batch size = 16 or 32).
3. **Clip Length & Resolution**:
   - Temporal window: **16 frames per clip** sampled at 4–8 FPS.
   - Spatial resolution: **$112 \times 112$ pixels** (or $224 \times 224$ with micro-batch 4).
   - Normalization: ImageNet statistics (Mean: `[0.485, 0.456, 0.406]`, Std: `[0.229, 0.224, 0.225]`).
4. **Backbone Layer Freezing (Optional Warmup)**:
   - Epochs 1–2: Freeze `stem`, `layer1`, and `layer2`; train only `layer3`, `layer4`, and the classification head.
   - Epochs 3+: Unfreeze full network with a reduced learning rate ($1 \times 10^{-4} \rightarrow 1 \times 10^{-5}$) using AdamW or SGD with cosine annealing.
5. **DataLoader Memory Discipline**:
   - `num_workers = 2` (prevents overwhelming 16 GB system RAM).
   - `pin_memory = True` for fast host-to-device DMA transfers.
   - Clear CUDA cache between validation epochs via `torch.cuda.empty_cache()`.

---

## 7. Model Evaluation & Calibration Methodology

In accordance with project requirements in `docs/architecture/ai-violence-detection-requirements.md` and Phase 67/68 specifications:

### 7.1 Quantitative Evaluation Metrics
- **Classification Performance**: Precision, Recall, F1-Score, PR-AUC, and ROC-AUC.
- **False Alarm Discipline**: Measure False Positive Rate (FPR) specifically on non-violent high-motion activities (sports, running, dancing, play-fighting, crowd density).
- **Missed Detection Discipline**: Measure False Negative Rate (FNR) on low-light, occluded, or distant altercations.

### 7.2 Confidence Calibration
Raw neural network sigmoid/softmax scores are notoriously overconfident and uncalibrated.
- Fit **Platt Scaling** (logistic regression on logits) or **Isotonic Regression** using the dedicated validation split.
- Measure **Expected Calibration Error (ECE)** with 10 bins:
  $$ECE = \sum_{m=1}^{M} \frac{|B_m|}{N} \left| \text{acc}(B_m) - \text{conf}(B_m) \right|$$
  Target: $ECE \le 0.08$ on calibrated validation predictions.

### 7.3 Uncertainty Verdicts
The model wrapper will map calibrated scores into the typed verdicts specified in `backend/app/core/ai.py`:
- `calibrated_score >= 0.70` $\rightarrow$ `HIGH_CONFIDENCE`
- `0.45 <= calibrated_score < 0.70` $\rightarrow$ `BORDERLINE` (Flagged for mandatory review)
- `calibrated_score < 0.45` $\rightarrow$ `LOW_CONFIDENCE`
- Ambiguous/adversarial conditions $\rightarrow$ `UNCERTAIN`

---

## 8. Checkpoint Packaging & FastAPI Integration Plan

### 8.1 Checkpoint Artifacts
Upon training completion, the training pipeline will save:
1. `artifacts/models/violence-r3d18-v1.0.0.pt`: PyTorch `state_dict` weights.
2. `artifacts/models/violence-r3d18-v1.0.0.json`: Model metadata:
   - Base architecture: `r3d_18`
   - Input resolution: `[16, 3, 112, 112]`
   - Weights SHA-256 digest
   - Training hyperparameters & validation metrics
   - Platt scaling parameters ($A, B$)

### 8.2 Registration in Approved Provenance Catalog
Register the new model identifier in `backend/app/core/ai.py`:
```python
APPROVED_AI_MODELS: Final[dict[str, frozenset[str]]] = {
    "violence-classifier": frozenset({"0.1.0", "1.0.0"}),
    "violence-timesformer-b16": frozenset({"1.0.0"}),
    "violence-r3d18": frozenset({"1.0.0"}),  # <-- Added registered model
    "mock-violence-classifier": frozenset({"0.1.0-test"}),
}
```

### 8.3 Provider Implementation in `ai_services/violence_detection/classifier.py`
Replace the `NotImplementedError` in `PretrainedVideoClassifierProvider` with PyTorch weight loading and evaluation inference, ensuring that:
- Weights SHA-256 is checked on initialization.
- If weights are absent, it raises `ModelUnavailableError(AI_MODEL_FALLBACK_DISCLAIMER)` without fabricating mock scores.
- Video bytes are preprocessed into normalized tensors.
- Forward pass executes under `torch.no_grad()`.

---

## 9. ML Prerequisites & Risk Summary

| Risk / Prerequisite | Severity | Mitigation Strategy |
| :--- | :---: | :--- |
| **Python 3.11 Incompatibility** | **HIGH (BLOCKER)** | Install Python 3.12+ and build clean `.venv`. |
| **Missing PyTorch / CUDA** | **HIGH (BLOCKER)** | Install PyTorch 2.x with CUDA 12.1 prebuilt binaries. |
| **Unverified Dataset License** | **MEDIUM** | Inspect Kaggle dataset license upon download; verify against SPDX allowlist. |
| **6 GB VRAM Exhaustion** | **MEDIUM** | Use R3D-18 with FP16 AMP, micro-batch 4, and gradient accumulation. |
| **Drive C Storage Pressure** | **MEDIUM** | Force all dataset caches and checkpoints to Drive D: (99.6 GB free). |
| **Data Leakage Across Splits** | **MEDIUM** | Enforce camera/scene group-based splitting before training. |
| **Overconfident Raw Scores** | **LOW** | Enforce validation-split Platt/Isotonic confidence calibration. |
