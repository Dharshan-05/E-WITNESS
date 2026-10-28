# E-WITNESS — MASTER AUDIT ACTION PLAN & ROADMAP FORWARD

**Document Reference**: `docs/audit/E_WITNESS_AUDIT_ACTION_PLAN.md`  
**Audit Baseline**: Post-Batch 11 Audit Baseline, Machine Learning Training & Frontend Preparation  
**Audit Date**: October 26, 2026  
**Auditor**: Senior Full-Stack Architect, Machine Learning Engineer & Lead QA  

---

## 1. Prioritization Framework

Remaining project tasks are prioritized based on technical dependency, architectural risk, and operational blocking status:

- **Priority 0 (P0) — Immediate Environmental & Dataset Prerequisites**: Critical blockers that prevent test execution, dependency resolution, and dataset validation. Must be resolved before any code or model development.
- **Priority 1 (P1) — Machine Learning Training, Calibration & Backend Integration**: Core requirements to train a local R3D-18 model on the RTX 4050 GPU, calibrate confidence scores, and wire inference into the FastAPI backend.
- **Priority 2 (P2) — Frontend UI Architecture & Workflows (Batch 12: Phases 111–118)**: Implementation of the user-facing web client in `frontend/` connecting to the 166 verified backend API endpoints.
- **Priority 3 (P3) — End-to-End Testing, Security Penetration & Handover (Phases 119–120)**: Full-stack browser testing, cross-browser validation, final acceptance verification, and production handover.

---

## 2. Prioritized Action Matrix

### Priority 0: Immediate Environmental & Dataset Prerequisites

#### Task P0.1 — Provision Python 3.12+ and Project Virtual Environment
- **Priority**: **P0 (BLOCKER)**
- **Description**: Install Python 3.12 (or 3.13) 64-bit on Windows and create a project-local virtual environment (`.venv`) in `D:\PROJECT\E-WITTNESS\.venv`.
- **Reason**: The existing codebase uses Python 3.12 syntax (PEP 695 generics `PaginatedResponse[ItemT]`), `pydantic-settings >= 2.15` (requiring `NoDecode`), and `pytest >= 9.0`. The current system Python 3.11.9 blocks test execution and server bootstrap.
- **Related Phase**: Phase 04 (Development Environment & Dependency Management).
- **Relevant Files**: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`.
- **Dependencies**: None.
- **Acceptance Criteria**:
  1. `.\.venv\Scripts\python.exe --version` outputs Python >= 3.12.0.
  2. `requirements-dev.txt` installs cleanly with zero dependency conflicts.
  3. `ruff check .` passes with 0 errors.
  4. `mypy backend/app/core/architecture.py` parses `PaginatedResponse[ItemT]` without syntax errors.
- **Suggested Verification Method**:
  ```powershell
  py -3.12 -m venv D:\PROJECT\E-WITTNESS\.venv
  .\.venv\Scripts\pip.exe install -r requirements-dev.txt
  .\.venv\Scripts\python.exe -m pytest tests/unit/architecture/test_layer_boundaries.py
  ```

---

#### Task P0.2 — Install PyTorch with CUDA Acceleration and CV Libraries
- **Priority**: **P0 (BLOCKER)**
- **Description**: Install PyTorch with CUDA 12.1/12.4 prebuilt wheels, `torchvision`, `torchaudio`, `opencv-python`, and `av` inside `.venv`.
- **Reason**: Video model training and inference require GPU-accelerated PyTorch on the NVIDIA RTX 4050 laptop GPU.
- **Related Phase**: Phase 64 (Video Classifier Protocol).
- **Relevant Files**: `.venv`, `pyproject.toml`.
- **Dependencies**: Task P0.1.
- **Acceptance Criteria**:
  1. `torch.cuda.is_available()` returns `True`.
  2. `torch.cuda.get_device_name(0)` returns `NVIDIA GeForce RTX 4050 Laptop GPU`.
  3. `cv2.__version__` and `av.__version__` are importable.
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\pip.exe install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
  .\.venv\Scripts\pip.exe install opencv-python av scikit-learn
  .\.venv\Scripts\python.exe -c "import torch; print('CUDA Ready:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
  ```

---

#### Task P0.3 — Download and Verify Kaggle Dataset to Drive D:
- **Priority**: **P0 (PREREQUISITE)**
- **Description**: Download the Kaggle dataset (`yash07yadav/project-data`) strictly to `D:\PROJECT\E-WITTNESS\data\raw\` (do not use Drive C due to 14.65 GB limit) and execute an automated integrity and licensing audit.
- **Reason**: The dataset is currently unverified. Licensing, file integrity, class distribution, and format compatibility must be proven before any training script is executed.
- **Related Phase**: Phase 62 (Video Ingestion & Dataset Governance).
- **Relevant Files**: `backend/app/core/ai.py` (`APPROVED_DATASET_LICENSES`), `scripts/inspect_dataset.py`.
- **Dependencies**: Tasks P0.1, P0.2, Kaggle API credentials.
- **Acceptance Criteria**:
  1. Dataset downloaded to `D:\PROJECT\E-WITTNESS\data\raw\`.
  2. SPDX license verified against `APPROVED_DATASET_LICENSES`.
  3. All video files checked for valid container headers and decodability.
  4. Class counts and duration distributions reported without data loss.
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\python.exe scripts/inspect_dataset.py --data-dir D:\PROJECT\E-WITTNESS\data\raw
  ```

---

### Priority 1: Machine Learning Training, Calibration & Backend Integration

#### Task P1.1 — Implement Group-Based Video Dataset Ingestion & Splitter
- **Priority**: **P1**
- **Description**: Develop `scripts/prepare_dataset.py` to generate canonical train (70%), validation (15%), and test (15%) splits grouped strictly by recording scene/event to eliminate data leakage.
- **Reason**: Frame-level or random clip splitting leaks source backgrounds and individuals across splits, producing artificially inflated metrics.
- **Related Phase**: Phase 62, Phase 63 (Temporal Sampling & Preprocessing).
- **Relevant Files**: `ai_services/video/preprocessing.py`, `scripts/prepare_dataset.py`.
- **Dependencies**: Task P0.3.
- **Acceptance Criteria**:
  1. Zero overlap of source scene identifiers between train, val, and test partitions.
  2. Generates canonical JSON manifest with SHA-256 digests (`compute_manifest_sha256`).
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\python.exe scripts/prepare_dataset.py --input-dir D:\PROJECT\E-WITTNESS\data\raw --output-manifest D:\PROJECT\E-WITTNESS\data\manifest.json
  ```

---

#### Task P1.2 — Implement Local R3D-18 Training Pipeline with AMP
- **Priority**: **P1**
- **Description**: Develop `scripts/train_violence_model.py` to fine-tune a pretrained `torchvision.models.video.r3d_18` model on 16-frame clips ($112 \times 112$ resolution) using PyTorch AMP (FP16) on the RTX 4050 GPU.
- **Reason**: Generates the authentic trained model weights required by the E-WITNESS platform.
- **Related Phase**: Phase 64 (Violence Detection Model Architecture).
- **Relevant Files**: `scripts/train_violence_model.py`, `ai_services/violence_detection/classifier.py`.
- **Dependencies**: Tasks P0.2, P1.1.
- **Acceptance Criteria**:
  1. Training runs without CUDA OOM on the 6 GB RTX 4050 (micro-batch size 4, gradient accumulation steps 4).
  2. Logs training and validation loss per epoch.
  3. Saves best model weights to `artifacts/models/violence-r3d18-v1.0.0.pt`.
  4. Computes and saves SHA-256 weight hash in `artifacts/models/violence-r3d18-v1.0.0.json`.
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\python.exe scripts/train_violence_model.py --manifest D:\PROJECT\E-WITTNESS\data\manifest.json --epochs 10 --batch-size 4 --accum-steps 4 --output-dir artifacts/models/
  ```

---

#### Task P1.3 — Implement Model Evaluation and Statistical Calibration
- **Priority**: **P1**
- **Description**: Develop `scripts/evaluate_violence_model.py` to evaluate the trained model on the held-out test split, fit Platt scaling on the validation split, and compute ECE and fairness metrics.
- **Reason**: The E-WITNESS governance framework strictly requires calibrated confidence outputs, uncertainty verdicts, and subgroup fairness evaluation before deployment.
- **Related Phase**: Phase 67 (Confidence Calibration), Phase 68 (Evaluation Metrics & Fairness).
- **Relevant Files**: `ai_services/violence_detection/calibration.py`, `ai_services/violence_detection/evaluation.py`.
- **Dependencies**: Task P1.2.
- **Acceptance Criteria**:
  1. Computes Precision, Recall, F1, PR-AUC, and ROC-AUC on the test split.
  2. Fits Platt scaling parameters ($A, B$) exclusively on the validation split.
  3. Measures Expected Calibration Error (ECE $\le 0.08$ target).
  4. Saves calibration artifact metadata JSON for runtime loading.
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\python.exe scripts/evaluate_violence_model.py --weights artifacts/models/violence-r3d18-v1.0.0.pt --manifest D:\PROJECT\E-WITTNESS\data\manifest.json
  ```

---

#### Task P1.4 — Wire PyTorch Model into `PretrainedVideoClassifierProvider`
- **Priority**: **P1**
- **Description**: Update `ai_services/violence_detection/classifier.py` to load the trained R3D-18 weights, verify the SHA-256 digest on startup, preprocess input video clips into normalized tensors, and execute PyTorch forward passes.
- **Reason**: Connects the trained model to the existing asynchronous backend job engine (`AIAnalysisJobService`).
- **Related Phase**: Phase 64, Phase 65 (AI Analysis Jobs & Worker Service), Phase 106 (Model Provenance).
- **Relevant Files**: `ai_services/violence_detection/classifier.py`, `backend/app/core/ai.py`.
- **Dependencies**: Tasks P1.2, P1.3.
- **Acceptance Criteria**:
  1. Model registered in `APPROVED_AI_MODELS` with exact name and semver.
  2. `PretrainedVideoClassifierProvider.is_ready()` returns `True` when weights are present and verified.
  3. `classify(video_spec)` returns a populated `VideoClassificationResult` without raising `NotImplementedError`.
  4. Existing unit tests in `tests/unit/ai/` pass.
- **Suggested Verification Method**:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/unit/ai/test_classifier_protocol.py tests/unit/ai/test_ai_job_service.py
  ```

---

### Priority 2: Frontend UI Development (Batch 12: Phases 111–118)

#### Task P2.1 — Initialize Frontend Workspace & Tooling (Phase 111)
- **Priority**: **P2**
- **Description**: Scaffold modern web application in `frontend/` using Vite + React 18 / Next.js with TypeScript, Tailwind CSS, and shadcn/ui components.
- **Reason**: The `frontend/` workspace currently contains only a placeholder `README.md`.
- **Related Phase**: Phase 111 (Frontend Project Architecture & Tooling).
- **Relevant Files**: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`.
- **Dependencies**: Node.js >= 20.x, npm / pnpm.
- **Acceptance Criteria**:
  1. `npm run build` succeeds without TypeScript or ESLint errors.
  2. Strict client-side security boundary configured (zero hardcoded backend secrets).
- **Suggested Verification Method**:
  ```powershell
  cd frontend; npm run build; npm run lint
  ```

---

#### Task P2.2 — Implement Authentication & Route Guards UI (Phase 112)
- **Priority**: **P2**
- **Description**: Build login screen, session refresh handler, password reset flow, and role-based route guards for Student, Staff, Investigator, Dept Admin, and Super Admin.
- **Reason**: Users require authenticated browser interfaces to interact with role-scoped endpoints.
- **Related Phase**: Phase 112 (Authentication, Session Management & Route Guards).
- **Relevant Files**: `frontend/src/features/auth/`, `frontend/src/routes/`.
- **Dependencies**: Task P2.1, Backend `/api/v1/auth` endpoints.
- **Acceptance Criteria**:
  1. Stores access token in memory with automatic rotation via HTTP-only refresh cookies / refresh endpoint.
  2. Redirects unauthorized roles away from restricted routes.
- **Suggested Verification Method**: Manual browser test + Playwright auth flow.

---

#### Task P2.3 — Implement Incident Intake & Evidence Upload UI (Phases 113–114)
- **Priority**: **P2**
- **Description**: Implement incident reporting forms, triage tables, chunked file uploader with client-side SHA-256 calculation, and upload session progress bars.
- **Reason**: Core institutional evidence intake workflow.
- **Related Phase**: Phases 113–114 (Incident Intake, Triage & Evidence Upload).
- **Relevant Files**: `frontend/src/features/incidents/`, `frontend/src/features/evidence/`.
- **Dependencies**: Tasks P2.1, P2.2, Backend `/api/v1/incidents` endpoints.
- **Acceptance Criteria**:
  1. Chunked streaming upload of video evidence up to 250 MB with progress indicator.
  2. Immediate client-side SHA-256 computation matching backend digest.
- **Suggested Verification Method**: Browser upload of sample MP4 file.

---

#### Task P2.4 — Implement Case Management & AI Review UI (Phases 115–116)
- **Priority**: **P2**
- **Description**: Build investigator case workspace, chain of custody timeline, interactive video player with candidate segment overlays, and human review decision forms.
- **Reason**: Enables authorized investigators to review AI advisory segment detections and record determinations.
- **Related Phase**: Phases 115–116 (Case Management & AI Analysis Review).
- **Relevant Files**: `frontend/src/features/cases/`, `frontend/src/features/ai-review/`.
- **Dependencies**: Tasks P1.4, P2.3, Backend `/api/v1/cases`, `/api/v1/ai` endpoints.
- **Acceptance Criteria**:
  1. Displays mandatory AI advisory legal disclaimers prominently.
  2. Video player jumps to flagged timestamps.
  3. Form captures reviewer verdict (`confirmed` / `rejected`) and notes.
- **Suggested Verification Method**: Video review interaction in browser.

---

#### Task P2.5 — Implement Dashboards, Analytics & Admin UI (Phases 117–118)
- **Priority**: **P2**
- **Description**: Implement operational KPI dashboards, reviewer workload tables, tamper-evident security audit viewer, and user/department administration views.
- **Reason**: Enables department administrators and super admins to monitor institutional workflows.
- **Related Phase**: Phases 117–118 (Dashboards, Analytics & Administrative Controls).
- **Relevant Files**: `frontend/src/features/dashboards/`, `frontend/src/features/admin/`.
- **Dependencies**: Task P2.4, Backend `/api/v1/dashboards`, `/api/v1/analytics`, `/api/v1/audit`.
- **Acceptance Criteria**:
  1. Charts render metrics scoped strictly to user's assigned department.
  2. Audit log displays cryptographic verification status.
- **Suggested Verification Method**: End-to-end dashboard rendering.

---

### Priority 3: End-to-End System Testing & Handover (Phases 119–120)

#### Task P3.1 — End-to-End System Integration & Browser Testing (Phase 119)
- **Priority**: **P3**
- **Description**: Implement automated Playwright integration test suite validating complete user journeys from student incident submission through chunked evidence upload, AI background processing, investigator review, and case closure.
- **Reason**: Verifies full-stack contract integrity across browser and backend.
- **Related Phase**: Phase 119 (End-to-End System Integration & Browser Testing).
- **Relevant Files**: `tests/e2e/`, `playwright.config.ts`.
- **Dependencies**: Tasks P1.4, P2.1–P2.5.
- **Acceptance Criteria**:
  1. 100% passing E2E Playwright test suite covering all 5 user roles.
  2. Zero unhandled API errors or schema deserialization mismatches.
- **Suggested Verification Method**:
  ```powershell
  npx playwright test
  ```

---

#### Task P3.2 — Final Production Acceptance & Handover (Phase 120)
- **Priority**: **P3**
- **Description**: Execute final end-to-end production readiness audit, container security scan, disaster recovery drill, and compile final system handover documentation.
- **Reason**: Formal sign-off and milestone closure of the 120-phase master roadmap.
- **Related Phase**: Phase 120 (Final Acceptance Testing & Handover).
- **Relevant Files**: `docs/deployment/`, `artifacts/PHASE_120_ACCEPTANCE_REPORT.md`.
- **Dependencies**: Task P3.1.
- **Acceptance Criteria**:
  1. All 120 roadmap phases certified GREEN.
  2. Container image builds cleanly and passes non-root security gates.
  3. Handover documentation signed off.
- **Suggested Verification Method**: Final audit review script.
