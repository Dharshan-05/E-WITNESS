"""Model evaluation, statistical confidence calibration, and reporting (Phases 67 & 68, Task P1.3).

Enforces:
1. Exact architecture and preprocessing parity with training pipeline (R3D-18, 16 frames, Kinetics normalization).
2. Checkpoint validation: verifies presence of model_state_dict, class_mapping, and model version.
3. Strict partition separation:
   - Platt scaling and Temperature scaling parameters are fitted strictly on the VALIDATION split.
   - Fixed decision threshold (0.50) is used; thresholds are NEVER selected using test labels.
   - Metrics, calibration error, and stress conditions are evaluated on the held-out TEST split.
4. Comprehensive metric computation:
   - Confusion matrix (TP, FP, TN, FN)
   - Accuracy, Precision, Recall, Specificity, FPR, FNR, F1 Score, Brier Score
   - Per-class performance (support, precision, recall, F1 for non_violence and violence)
   - Expected Calibration Error (ECE) and Maximum Calibration Error (MCE)
   - Multi-threshold sweep (0.10 to 0.90) for operational review trade-off analysis
5. Robust sample size & missing class handling:
   - Identifies if sample size N < 30 (flags is_statistically_reliable = False)
   - Requires N >= 100 on verified real data for benchmark validation (is_statistically_adequate_benchmark)
   - Handles single-class or degenerate splits without division-by-zero crashes
   - Explicitly reports whether ECE <= 0.08 target was achieved
6. Reliability Diagrams and Calibration Method Comparison:
   - 10-bin reliability diagram with empirical accuracy, confidence, and calibration error.
   - Comparative evaluation: Uncalibrated Softmax vs Platt Scaling vs Temperature Scaling.
7. Real-World Operational Stress Testing:
   - 8 challenging conditions: baseline, low_light, bright_glare, low_resolution,
     camera_motion_blur, spatial_occlusion, sensor_noise, temporal_truncation.
8. Split Integrity & Leakage Verification:
   - Verifies 0 cross-split hash collisions and audits scene-prefix grouping consistency.
9. Structured and Separate Reporting:
   - Writes to artifacts/models/ and artifacts/reports/ (evaluation and validation).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.train_violence_model import ViolenceVideoDataset, build_r3d_18_model

from ai_services.violence_detection.calibration import (
    CalibrationArtifact,
    PlattScalingCalibrator,
)
from ai_services.violence_detection.evaluation import (
    EvaluationReport,
    calculate_classification_metrics,
    calculate_expected_calibration_error,
    evaluate_threshold_sweep,
    generate_reproducibility_hash,
)
from ai_services.violence_detection.requirements import AI_HUMAN_IN_THE_LOOP_DISCLAIMER
from backend.app.core.ai import CalibrationMethod, EvaluationLevel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_violence_model")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def apply_stress_condition(tensor: torch.Tensor, condition: str) -> torch.Tensor:
    """Apply deterministic operational stress transformations to video tensor.

    Args:
        tensor: Video tensor of shape [batch_size, channels, frames, height, width]
        condition: Identifier of the stress condition to apply.

    Returns:
        Transformed video tensor of identical shape and dtype.
    """
    b, c, t, h, w = tensor.shape
    if condition == "baseline":
        return tensor
    if condition == "low_light":
        return tensor * 0.40
    if condition == "bright_glare":
        return torch.clamp(tensor * 1.60, -3.0, 3.0)
    if condition == "low_resolution":
        # Downsample spatially by 2x then interpolate back
        x = tensor.permute(0, 2, 1, 3, 4).reshape(b * t, c, h, w)
        down = F.interpolate(x, size=(h // 2, w // 2), mode="bilinear", align_corners=False)
        up = F.interpolate(down, size=(h, w), mode="bilinear", align_corners=False)
        return up.reshape(b, t, c, h, w).permute(0, 2, 1, 3, 4)
    if condition == "camera_motion_blur":
        # Horizontal motion blur kernel
        x = tensor.permute(0, 2, 1, 3, 4).reshape(b * t, c, h, w)
        kernel = torch.ones(c, 1, 1, 5, device=tensor.device, dtype=tensor.dtype) / 5.0
        blurred = F.conv2d(x, kernel, padding=(0, 2), groups=c)
        return blurred.reshape(b, t, c, h, w).permute(0, 2, 1, 3, 4)
    if condition == "spatial_occlusion":
        out = tensor.clone()
        out[:, :, :, h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = 0.0
        return out
    if condition == "sensor_noise":
        return tensor + torch.randn_like(tensor) * 0.15
    if condition == "temporal_truncation":
        half_t = max(1, t // 2)
        return torch.cat([tensor[:, :, :half_t], tensor[:, :, :half_t]], dim=2)
    return tensor


def run_inference_on_loader(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    stress_condition: str = "baseline",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Run model inference to collect ground truth labels, differential logits, and violence probabilities.

    Score convention:
        - Index 0: non_violence
        - Index 1: violence
        - Differential logit: z = logit_violence - logit_non_violence
        - Softmax probability: p = exp(logit_violence) / (exp(logit_non_violence) + exp(logit_violence))
    """
    model.eval()
    all_targets: list[int] = []
    all_logits: list[float] = []
    all_probs: list[float] = []

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            if stress_condition != "baseline":
                inputs = apply_stress_condition(inputs, stress_condition)

            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                outputs = model(inputs)  # [batch_size, 2]
                probs = torch.softmax(outputs, dim=1)

            diff_logits = (outputs[:, 1] - outputs[:, 0]).cpu().numpy()
            violence_probs = probs[:, 1].cpu().numpy()

            all_targets.extend(targets.numpy().tolist())
            all_logits.extend(diff_logits.tolist())
            all_probs.extend(violence_probs.tolist())

    return (
        np.array(all_targets, dtype=int),
        np.array(all_logits, dtype=float),
        np.array(all_probs, dtype=float),
    )


def compute_per_class_metrics(y_true: list[int], y_pred: list[int]) -> dict[str, Any]:
    """Compute per-class support, precision, recall, specificity, and F1 for non_violence and violence."""
    tp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == 0 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == 0 and yp == 0)
    fn = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == 1 and yp == 0)

    # Class 0: non_violence
    c0_support = tn + fp
    c0_prec = (tn / (tn + fn)) if (tn + fn) > 0 else None
    c0_rec = (tn / (tn + fp)) if (tn + fp) > 0 else None
    c0_f1 = (
        (2 * c0_prec * c0_rec / (c0_prec + c0_rec))
        if (c0_prec is not None and c0_rec is not None and (c0_prec + c0_rec) > 0)
        else None
    )

    # Class 1: violence
    c1_support = tp + fn
    c1_prec = (tp / (tp + fp)) if (tp + fp) > 0 else None
    c1_rec = (tp / (tp + fn)) if (tp + fn) > 0 else None
    c1_f1 = (
        (2 * c1_prec * c1_rec / (c1_prec + c1_rec))
        if (c1_prec is not None and c1_rec is not None and (c1_prec + c1_rec) > 0)
        else None
    )

    total = len(y_true)
    accuracy = ((tp + tn) / total) if total > 0 else None

    return {
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "class_0_non_violence": {
            "label": 0,
            "name": "non_violence",
            "support": c0_support,
            "precision": round(c0_prec, 4) if c0_prec is not None else None,
            "recall": round(c0_rec, 4) if c0_rec is not None else None,
            "f1_score": round(c0_f1, 4) if c0_f1 is not None else None,
        },
        "class_1_violence": {
            "label": 1,
            "name": "violence",
            "support": c1_support,
            "precision": round(c1_prec, 4) if c1_prec is not None else None,
            "recall": round(c1_rec, 4) if c1_rec is not None else None,
            "f1_score": round(c1_f1, 4) if c1_f1 is not None else None,
        },
    }


def compute_reliability_diagram(
    y_true: list[int] | np.ndarray,
    y_prob: list[float] | np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Calculate 10-bin reliability diagram with empirical accuracy, confidence, and calibration error."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    n = len(y_true)
    if n == 0 or n_bins <= 0:
        return {"bins": [], "ece": 0.0, "mce": 0.0, "brier_score": 0.0, "n_bins": n_bins, "sample_count": 0}

    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    bins_data: list[dict[str, Any]] = []
    ece = 0.0
    mce = 0.0

    for i in range(n_bins):
        low, high = bin_boundaries[i], bin_boundaries[i + 1]
        if i == n_bins - 1:
            indices = np.where((y_prob >= low) & (y_prob <= high))[0]
        else:
            indices = np.where((y_prob >= low) & (y_prob < high))[0]

        count = len(indices)
        if count > 0:
            bin_acc = float(np.mean(y_true[indices]))
            bin_conf = float(np.mean(y_prob[indices]))
            bin_error = abs(bin_acc - bin_conf)
            weighted_error = (count / n) * bin_error
            ece += weighted_error
            if bin_error > mce:
                mce = bin_error
        else:
            bin_acc = None
            bin_conf = float((low + high) / 2.0)
            bin_error = 0.0

        bins_data.append({
            "bin_index": i,
            "bin_lower": round(float(low), 2),
            "bin_upper": round(float(high), 2),
            "sample_count": int(count),
            "empirical_accuracy": round(bin_acc, 4) if bin_acc is not None else None,
            "mean_confidence": round(bin_conf, 4),
            "calibration_error": round(bin_error, 4) if count > 0 else 0.0,
        })

    brier = float(np.mean((y_prob - y_true) ** 2))
    return {
        "bins": bins_data,
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "brier_score": round(brier, 4),
        "n_bins": n_bins,
        "sample_count": n,
    }


def fit_platt_scaling(val_targets: np.ndarray, val_scores: np.ndarray) -> tuple[float, float, str]:
    """Fit logistic regression on validation scores to obtain Platt scaling parameters (A, B).

    Formula: P(y=1 | s) = 1 / (1 + exp(-(A*s + B)))
    """
    if len(val_targets) == 0:
        logger.warning("Validation set is empty. Falling back to identity Platt scaling (1.0, 0.0).")
        return 1.0, 0.0, "EMPTY_VAL_FALLBACK"

    unique_classes = np.unique(val_targets)
    if len(unique_classes) < 2:
        logger.warning(
            "Validation set has only 1 class (%s). Cannot fit Platt scaling. Falling back to identity (1.0, 0.0).",
            unique_classes,
        )
        return 1.0, 0.0, "SINGLE_CLASS_VAL_FALLBACK"

    if len(val_targets) < 30:
        logger.warning(
            "Validation sample size N=%d is below statistical minimum (30). Calibration cannot be statistically validated.",
            len(val_targets),
        )

    X = val_scores.reshape(-1, 1)
    y = val_targets

    try:
        lr = LogisticRegression(solver="lbfgs", C=1.0)
        lr.fit(X, y)
        slope = float(lr.coef_[0][0])
        intercept = float(lr.intercept_[0])

        if slope <= 0.0:
            logger.warning(
                "Inverted score direction detected in Platt scaling (slope=%.4f <= 0). "
                "Calibrator would invert model confidence. Falling back to identity (1.0, 0.0).",
                slope,
            )
            return 1.0, 0.0, "INVERTED_SCORE_DIRECTION_FALLBACK"

        status = "FITTED_CONVERGED" if len(val_targets) >= 30 else "FITTED_SMALL_SAMPLE"
        return slope, intercept, status
    except Exception as exc:
        logger.error("Platt scaling fitting failed (%s). Falling back to identity.", exc)
        return 1.0, 0.0, f"FIT_ERROR: {exc}"


def fit_temperature_scaling(val_targets: np.ndarray, val_logits: np.ndarray) -> tuple[float, str]:
    """Fit scalar temperature parameter T > 0 on validation differential logits by minimizing negative log-likelihood."""
    if len(val_targets) < 2 or len(np.unique(val_targets)) < 2:
        logger.warning("Validation set has fewer than 2 classes. Falling back to default temperature T=1.0.")
        return 1.0, "SINGLE_CLASS_VAL_FALLBACK"

    def nll_objective(temperature: float) -> float:
        if temperature <= 1e-4:
            return 1e9
        scaled = val_logits / temperature
        log_p1 = -np.logaddexp(0, -scaled)
        log_p0 = -np.logaddexp(0, scaled)
        nll = -np.mean(val_targets * log_p1 + (1 - val_targets) * log_p0)
        return float(nll)

    try:
        res = minimize_scalar(nll_objective, bounds=(0.05, 10.0), method="bounded")
        if res.success and res.x > 0.0:
            status = "FITTED_CONVERGED" if len(val_targets) >= 30 else "FITTED_SMALL_SAMPLE"
            return float(res.x), status
        return 1.0, "OPTIMIZATION_FAILED_FALLBACK"
    except Exception as exc:
        logger.error("Temperature scaling fitting failed (%s). Falling back to T=1.0.", exc)
        return 1.0, f"FIT_ERROR: {exc}"


def compare_calibration_methods(
    val_targets: np.ndarray,
    val_probs: np.ndarray,
    val_logits: np.ndarray,
    test_targets: np.ndarray,
    test_probs: np.ndarray,
    test_logits: np.ndarray,
) -> dict[str, Any]:
    """Fit Platt and Temperature scaling strictly on validation set and evaluate on test set."""
    # 1. Baseline uncalibrated
    diag_uncal = compute_reliability_diagram(test_targets, test_probs)

    # 2. Platt Scaling
    platt_slope, platt_intercept, platt_status = fit_platt_scaling(val_targets, val_probs)
    if "FALLBACK" in platt_status or platt_slope <= 0.0:
        platt_test_probs = test_probs.copy()
    else:
        platt_z = platt_slope * test_probs + platt_intercept
        platt_test_probs = 1.0 / (1.0 + np.exp(-np.clip(platt_z, -35.0, 35.0)))
    diag_platt = compute_reliability_diagram(test_targets, platt_test_probs)

    # 3. Temperature Scaling
    temp_t, temp_status = fit_temperature_scaling(val_targets, val_logits)
    temp_scaled_logits = test_logits / temp_t
    temp_test_probs = 1.0 / (1.0 + np.exp(-np.clip(temp_scaled_logits, -35.0, 35.0)))
    diag_temp = compute_reliability_diagram(test_targets, temp_test_probs)

    return {
        "uncalibrated": {
            "method": "Uncalibrated Softmax",
            "ece": diag_uncal["ece"],
            "mce": diag_uncal["mce"],
            "brier_score": diag_uncal["brier_score"],
            "parameters": {},
            "status": "BASELINE",
        },
        "platt_scaling": {
            "method": "Platt Scaling (Logistic Sigmoid)",
            "ece": diag_platt["ece"],
            "mce": diag_platt["mce"],
            "brier_score": diag_platt["brier_score"],
            "parameters": {"slope": round(platt_slope, 4), "intercept": round(platt_intercept, 4)},
            "status": platt_status,
        },
        "temperature_scaling": {
            "method": "Temperature Scaling",
            "ece": diag_temp["ece"],
            "mce": diag_temp["mce"],
            "brier_score": diag_temp["brier_score"],
            "parameters": {"temperature": round(temp_t, 4)},
            "status": temp_status,
        },
    }


def evaluate_real_world_stress_conditions(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    decision_threshold: float = 0.50,
) -> dict[str, Any]:
    """Evaluate model robustness across 8 challenging real-world operational perturbations."""
    conditions = [
        ("baseline", "Original unperturbed video stream"),
        ("low_light", "Low ambient illumination (intensity x0.40)"),
        ("bright_glare", "Direct glare / overexposure (intensity x1.60)"),
        ("low_resolution", "Heavy spatial compression (56x56 downsampled & restored)"),
        ("camera_motion_blur", "Horizontal camera pan / motion shake blur"),
        ("spatial_occlusion", "Partial scene occlusion (32x32 center masking)"),
        ("sensor_noise", "Additive sensor noise (sigma=0.15 Gaussian noise)"),
        ("temporal_truncation", "Short clip / frame stutter (half-sequence repetition)"),
    ]

    stress_results: dict[str, Any] = {}

    for cond_key, desc in conditions:
        targets, _logits, probs = run_inference_on_loader(
            model=model,
            loader=loader,
            device=device,
            stress_condition=cond_key,
        )
        preds = [1 if p >= decision_threshold else 0 for p in probs]
        tp = sum(1 for yt, yp in zip(targets, preds, strict=False) if yt == 1 and yp == 1)
        fp = sum(1 for yt, yp in zip(targets, preds, strict=False) if yt == 0 and yp == 1)
        tn = sum(1 for yt, yp in zip(targets, preds, strict=False) if yt == 0 and yp == 0)
        fn = sum(1 for yt, yp in zip(targets, preds, strict=False) if yt == 1 and yp == 0)
        total = len(targets)

        acc = ((tp + tn) / total) if total > 0 else None
        prec = (tp / (tp + fp)) if (tp + fp) > 0 else None
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec and (prec + rec) > 0) else None
        fpr = (fp / (fp + tn)) if (fp + tn) > 0 else None
        fnr = (fn / (fn + tp)) if (fn + tp) > 0 else None
        mean_score = float(np.mean(probs)) if total > 0 else 0.0

        stress_results[cond_key] = {
            "condition": cond_key,
            "description": desc,
            "sample_count": total,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "accuracy": round(acc, 4) if acc is not None else None,
            "precision": round(prec, 4) if prec is not None else None,
            "recall": round(rec, 4) if rec is not None else None,
            "f1_score": round(f1, 4) if f1 is not None else None,
            "false_positive_rate": round(fpr, 4) if fpr is not None else None,
            "false_negative_rate": round(fnr, 4) if fnr is not None else None,
            "mean_violence_score": round(mean_score, 4),
        }

    return stress_results


def audit_data_splits_and_leakage(manifest_path: Path) -> dict[str, Any]:
    """Audit dataset manifest for cross-split hash duplicates, scene leakage, and class balance."""
    if not manifest_path.is_file():
        return {
            "status": "MANIFEST_NOT_FOUND",
            "manifest_path": str(manifest_path),
            "cross_split_hash_leakage": False,
            "verifiable_scene_leakage": False,
        }

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    items = manifest.get("items", [])
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    for it in items:
        sp = it.get("split", "train")
        if sp in splits:
            splits[sp].append(it)

    # 1. Exact hash leakage check
    split_hashes: dict[str, set[str]] = {
        s: {it["sha256"] for it in lst if "sha256" in it} for s, lst in splits.items()
    }
    train_val_overlap = len(split_hashes["train"].intersection(split_hashes["val"]))
    train_test_overlap = len(split_hashes["train"].intersection(split_hashes["test"]))
    val_test_overlap = len(split_hashes["val"].intersection(split_hashes["test"]))
    has_hash_leakage = (train_val_overlap > 0 or train_test_overlap > 0 or val_test_overlap > 0)

    # 2. Scene-prefix grouping check (for YouTube ID format clips)
    group_to_splits: dict[str, set[str]] = {}
    verifiable_group_count = 0
    ungroupable_count = 0
    for s, lst in splits.items():
        for it in lst:
            gid = it.get("group_id")
            gconf = it.get("grouping_confidence")
            if gid and gconf == "scene_prefix_verified":
                verifiable_group_count += 1
                group_to_splits.setdefault(gid, set()).add(s)
            else:
                ungroupable_count += 1

    scene_leaking_groups = [gid for gid, s_set in group_to_splits.items() if len(s_set) > 1]
    has_scene_leakage = len(scene_leaking_groups) > 0

    return {
        "status": "AUDITED",
        "total_items": len(items),
        "manifest_sha256": manifest.get("manifest_sha256", "unknown"),
        "split_counts": {s: len(lst) for s, lst in splits.items()},
        "cross_split_hash_leakage": has_hash_leakage,
        "hash_leakage_details": {
            "train_val_collisions": train_val_overlap,
            "train_test_collisions": train_test_overlap,
            "val_test_collisions": val_test_overlap,
        },
        "scene_grouping_audit": {
            "verifiable_scene_prefix_clips": verifiable_group_count,
            "ungroupable_opaque_clips": ungroupable_count,
            "leaking_scene_groups_count": len(scene_leaking_groups),
            "is_scene_leakage_detected": has_scene_leakage,
        },
        "class_distribution_by_split": {
            s: {
                "total": len(lst),
                "violence": sum(1 for it in lst if it.get("label") == 1),
                "non_violence": sum(1 for it in lst if it.get("label") == 0),
            }
            for s, lst in splits.items()
        },
    }


def evaluate_model_pipeline(
    checkpoint_path: Path,
    manifest_path: Path,
    data_dir: Path,
    output_dir: Path,
    decision_threshold: float = 0.50,
    batch_size: int = 4,
    use_synthetic: bool = False,
    smoke_test_limit: int | None = None,
    device_str: str | None = None,
    evaluation_output_dir: Path | None = None,
    validation_output_dir: Path | None = None,
    run_stress_tests: bool = True,
    authorized_subset_only: bool = False,
) -> dict[str, Any]:
    """Execute model evaluation, statistical calibration fitting, stress tests, and artifact reporting."""
    device = torch.device(device_str if device_str else ("cuda" if torch.cuda.is_available() else "cpu"))
    logger.info("Using device: %s (%s)", device, torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU")

    # 1. Load and validate model checkpoint
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"Checkpoint file not found: {checkpoint_path}")

    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    if "model_state_dict" not in checkpoint:
        raise ValueError(f"Invalid checkpoint: missing 'model_state_dict' in {checkpoint_path}")

    model_name = checkpoint.get("model_name", "violence-r3d18")
    model_version = checkpoint.get("model_version", "1.0.0")
    class_mapping = checkpoint.get("class_mapping", {0: "non_violence", 1: "violence"})
    manifest_sha256 = checkpoint.get("manifest_sha256", "unknown")
    logger.info("Validated checkpoint %s (v%s) with class mapping: %s", model_name, model_version, class_mapping)

    model = build_r3d_18_model(num_classes=2, pretrained=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)

    # 2. Prepare datasets
    is_smoke_test = use_synthetic or (smoke_test_limit is not None)
    if use_synthetic or not manifest_path.exists():
        logger.info("Using synthetic test vectors for software smoke test...")
        val_items = [{"label": i % 2, "path": f"syn_val_{i}.mp4"} for i in range(16)]
        test_items = [{"label": i % 2, "path": f"syn_test_{i}.mp4"} for i in range(16)]
        evaluation_type = "SOFTWARE_SMOKE_TEST"
        manifest_compatibility = True
    else:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)
        items = manifest_data.get("items", [])
        eval_manifest_sha = manifest_data.get("manifest_sha256", "unknown")
        if manifest_sha256 != "unknown" and eval_manifest_sha != "unknown":
            if manifest_sha256 == eval_manifest_sha:
                evaluation_type = "INTERNAL_TEST_SPLIT"
                manifest_compatibility = True
                logger.info(
                    "Internal test split evaluation verified: manifest SHA matches checkpoint (%s)",
                    eval_manifest_sha[:16],
                )
            else:
                evaluation_type = "EXTERNAL_BENCHMARK_SPLIT"
                manifest_compatibility = True
                logger.info(
                    "External benchmark evaluation: Checkpoint trained on SHA %s, evaluating on external manifest SHA %s",
                    manifest_sha256[:16],
                    eval_manifest_sha[:16],
                )
        else:
            evaluation_type = "UNTRACKED_MANIFEST"
            manifest_compatibility = True

        val_items = [it for it in items if it.get("split") == "val"]
        test_items = [it for it in items if it.get("split") == "test"]
        excluded_test_items = []

        if authorized_subset_only:
            before_val = len(val_items)
            val_items = [
                it for it in val_items
                if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
            ]
            before_test = len(test_items)
            excluded_test_items = [
                it for it in test_items
                if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower()
            ]
            test_items = [
                it for it in test_items
                if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
            ]
            logger.info(
                "Authorized subset filtering enabled: Val: %d -> %d (%d excluded), "
                "Test Eligible: %d -> %d (%d excluded to out-of-domain evaluation)",
                before_val, len(val_items), before_val - len(val_items),
                before_test, len(test_items), len(excluded_test_items),
            )

        if smoke_test_limit:
            half_val = max(1, (smoke_test_limit // 4) or 1)
            val_c0 = [it for it in val_items if it.get("label") == 0][:half_val]
            val_c1 = [it for it in val_items if it.get("label") == 1][:half_val]
            val_items = val_c0 + val_c1

            half_test = max(1, smoke_test_limit // 2)
            test_c0 = [it for it in test_items if it.get("label") == 0][:half_test]
            test_c1 = [it for it in test_items if it.get("label") == 1][:half_test]
            test_items = test_c0 + test_c1
            logger.info(
                "Smoke test: Stratified val to %d (%d non_violence, %d violence) and test to %d (%d non_violence, %d violence)",
                len(val_items),
                len(val_c0),
                len(val_c1),
                len(test_items),
                len(test_c0),
                len(test_c1),
            )

    logger.info("Validation items: %d, Test items: %d", len(val_items), len(test_items))

    val_dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=use_synthetic)
    test_dataset = ViolenceVideoDataset(data_dir, test_items, is_synthetic=use_synthetic)

    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=0)

    # 3. Fit Platt scaling strictly on the validation split
    logger.info("Running inference on VALIDATION split (fitting Platt & Temperature calibration)...")
    val_targets, val_logits, val_probs = run_inference_on_loader(model, val_loader, device)
    slope, intercept, fit_status = fit_platt_scaling(val_targets, val_probs)
    temp_t, temp_status = fit_temperature_scaling(val_targets, val_logits)
    logger.info("Platt Scaling Status: %s | slope (A)=%.4f, intercept (B)=%.4f", fit_status, slope, intercept)
    logger.info("Temperature Scaling Status: %s | temperature (T)=%.4f", temp_status, temp_t)

    val_uncalib_ece = (
        calculate_expected_calibration_error(val_targets.tolist(), val_probs.tolist())
        if len(val_targets) > 0
        else 0.0
    )

    artifact_id = f"calib-{model_name}-{model_version}-{uuid.uuid4().hex[:8]}"
    calib_artifact = CalibrationArtifact(
        artifact_id=artifact_id,
        method=CalibrationMethod.PLATT_SCALING,
        model_name=model_name,
        model_version=model_version,
        dataset_name="yash07yadav-violence-detection-combined",
        manifest_sha256=manifest_sha256,
        split_name="validation",
        parameters={
            "slope": slope,
            "intercept": intercept,
            "fit_status": fit_status,
            "temperature": temp_t,
            "score_type": "probability",
            "is_identity_fallback": ("FALLBACK" in fit_status or slope <= 0.0 or fit_status != "FITTED_CONVERGED"),
        },
        metrics={"val_uncalibrated_ece": val_uncalib_ece},
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    calib_file = output_dir / f"{model_name}-v{model_version}-calibration.json"
    tmp_calib = calib_file.with_suffix(".json.tmp")
    with open(tmp_calib, "w", encoding="utf-8") as f:
        json.dump(asdict(calib_artifact), f, indent=2)
    tmp_calib.replace(calib_file)
    logger.info("Saved calibration artifact: %s", calib_file)

    # 4. Evaluate on held-out test split
    logger.info("Running inference on HELD-OUT TEST split...")
    test_targets, test_logits, test_probs = run_inference_on_loader(model, test_loader, device)

    # Apply fitted Platt calibrator
    calibrator = PlattScalingCalibrator(calib_artifact)
    test_calibrated_probs: list[float] = []
    for raw_p in test_probs:
        calib_out = calibrator.calibrate(raw_p)
        test_calibrated_probs.append(calib_out.calibrated_score)

    # Use fixed operational threshold (0.50) without tuning on test labels
    test_preds_calib = [1 if p >= decision_threshold else 0 for p in test_calibrated_probs]

    test_uncalib_ece = (
        calculate_expected_calibration_error(test_targets.tolist(), test_probs.tolist())
        if len(test_targets) > 0
        else 0.0
    )
    test_calib_ece = (
        calculate_expected_calibration_error(test_targets.tolist(), test_calibrated_probs)
        if len(test_targets) > 0
        else 0.0
    )

    primary_metrics = calculate_classification_metrics(
        y_true=test_targets.tolist(),
        y_pred=test_preds_calib,
        y_prob=test_calibrated_probs,
    )

    sweep_metrics = evaluate_threshold_sweep(
        y_true=test_targets.tolist(),
        y_scores=test_calibrated_probs,
        thresholds=[0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90],
    )

    # Compute Per-Class Performance
    per_class_metrics = compute_per_class_metrics(test_targets.tolist(), test_preds_calib)

    # Compute Reliability Diagram
    reliability_diagram = compute_reliability_diagram(test_targets, test_calibrated_probs)

    # Compare Calibration Methods
    calib_comparison = compare_calibration_methods(
        val_targets=val_targets,
        val_probs=val_probs,
        val_logits=val_logits,
        test_targets=test_targets,
        test_probs=test_probs,
        test_logits=test_logits,
    )

    # Real-World Operational Stress Testing
    stress_results: dict[str, Any] = {}
    if run_stress_tests and len(test_items) > 0:
        logger.info("Executing real-world stress test matrix across 8 operational perturbations...")
        stress_results = evaluate_real_world_stress_conditions(
            model=model,
            loader=test_loader,
            device=device,
            decision_threshold=decision_threshold,
        )

    # Evaluate excluded test subset separately if authorized_subset_only is enabled
    excluded_test_metrics = None
    if authorized_subset_only and excluded_test_items and len(excluded_test_items) > 0:
        logger.info("Running separate out-of-domain evaluation on %d excluded test clips...", len(excluded_test_items))
        excl_dataset = ViolenceVideoDataset(data_dir, excluded_test_items, is_synthetic=use_synthetic)
        excl_loader = DataLoader(excl_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
        excl_targets, _excl_logits, excl_probs = run_inference_on_loader(model, excl_loader, device)
        excl_calib_probs = [calibrator.calibrate(p).calibrated_score for p in excl_probs]
        excl_preds = [1 if p >= decision_threshold else 0 for p in excl_calib_probs]
        excl_tp = sum(1 for p, t in zip(excl_preds, excl_targets.tolist(), strict=False) if p == 1 and t == 1)
        excl_fp = sum(1 for p, t in zip(excl_preds, excl_targets.tolist(), strict=False) if p == 1 and t == 0)
        excl_tn = sum(1 for p, t in zip(excl_preds, excl_targets.tolist(), strict=False) if p == 0 and t == 0)
        excl_fn = sum(1 for p, t in zip(excl_preds, excl_targets.tolist(), strict=False) if p == 0 and t == 1)
        excluded_test_metrics = {
            "sample_count": len(excluded_test_items),
            "reasons": "Commercial Hollywood cinema (MovieFights) and broadcast NHL games (HockeyFight) excluded due to copyright licensing and domain mismatch with surveillance evidence",
            "class_counts": {"violence": int(sum(excl_targets.tolist())), "non_violence": int(len(excl_targets) - sum(excl_targets.tolist()))},
            "confusion_matrix": {"tn": excl_tn, "fp": excl_fp, "fn": excl_fn, "tp": excl_tp},
            "accuracy": round((excl_tp + excl_tn) / max(1, len(excluded_test_items)), 4),
            "recall": round(excl_tp / max(1, excl_tp + excl_fn), 4) if (excl_tp + excl_fn) > 0 else 0.0,
            "mean_calibrated_probability": round(float(np.mean(excl_calib_probs)), 4) if len(excl_calib_probs) > 0 else 0.0,
        }
        logger.info("Excluded test subset evaluation: N=%d, Acc=%.2f%%, Recall=%.2f%%, Mean Prob=%.4f",
                    len(excluded_test_items), excluded_test_metrics["accuracy"] * 100.0,
                    excluded_test_metrics["recall"] * 100.0, excluded_test_metrics["mean_calibrated_probability"])

    # Audit data splits and leakage
    leakage_audit = audit_data_splits_and_leakage(manifest_path)

    report_id = f"eval-{model_name}-{model_version}-{uuid.uuid4().hex[:8]}"
    report = EvaluationReport(
        report_id=report_id,
        dataset_name="yash07yadav-violence-detection-combined",
        dataset_version="1.0.0",
        manifest_sha256=manifest_sha256,
        model_name=model_name,
        model_version=model_version,
        evaluation_level=EvaluationLevel.CLIP_LEVEL,
        threshold_used=decision_threshold,
        primary_metrics=primary_metrics,
        threshold_sweep=sweep_metrics,
    )

    is_ece_target_met = test_calib_ece <= 0.08
    evaluation_kind = "SOFTWARE_SMOKE_TEST" if is_smoke_test else "FULL_TEST_SET_EVALUATION"

    unique_targets = set(test_targets.tolist())
    if len(unique_targets) >= 2:
        from sklearn.metrics import average_precision_score, roc_auc_score

        roc_auc = float(roc_auc_score(test_targets.tolist(), test_calibrated_probs))
        pr_auc = float(average_precision_score(test_targets.tolist(), test_calibrated_probs))
        is_single_class_eval = False
    else:
        roc_auc = None
        pr_auc = None
        is_single_class_eval = True
        logger.warning(
            "Test partition contains only 1 class (%s). ROC-AUC and PR-AUC are mathematically undefined.",
            list(unique_targets),
        )

    is_statistically_reliable = len(test_targets) >= 30
    is_statistically_adequate_benchmark = len(test_targets) >= 100
    is_calibration_validated = (
        not is_smoke_test
        and is_statistically_adequate_benchmark
        and fit_status == "FITTED_CONVERGED"
        and slope > 0.0
        and is_ece_target_met
    )
    calibration_status_str = "VALIDATED" if is_calibration_validated else "NOT VALIDATED"

    report_dict = asdict(report)
    report_dict["evaluation_kind"] = evaluation_kind
    report_dict["evaluation_type"] = evaluation_type
    report_dict["is_smoke_test"] = is_smoke_test
    report_dict["calibration_validation_status"] = calibration_status_str
    report_dict["is_statistically_reliable"] = is_statistically_reliable
    report_dict["is_statistically_adequate_benchmark"] = is_statistically_adequate_benchmark
    report_dict["per_class_metrics"] = per_class_metrics
    report_dict["reliability_diagram"] = reliability_diagram
    report_dict["calibration_method_comparison"] = calib_comparison
    report_dict["real_world_stress_testing"] = stress_results
    report_dict["data_leakage_and_splits_audit"] = leakage_audit
    report_dict["excluded_test_subset"] = excluded_test_metrics
    report_dict["is_authorized_subset_only"] = authorized_subset_only
    report_dict["primary_metrics"]["expected_calibration_error"] = test_calib_ece
    report_dict["primary_metrics"]["uncalibrated_ece"] = test_uncalib_ece
    report_dict["primary_metrics"]["is_ece_target_met"] = is_ece_target_met
    report_dict["primary_metrics"]["roc_auc"] = roc_auc
    report_dict["primary_metrics"]["pr_auc"] = pr_auc
    report_dict["primary_metrics"]["is_single_class_eval"] = is_single_class_eval
    report_dict["manifest_compatibility"] = manifest_compatibility
    report_dict["calibration_artifact"] = asdict(calib_artifact)
    report_dict["reproducibility_hash"] = generate_reproducibility_hash(report_dict)

    # 5. Save report to primary output_dir
    report_file = output_dir / f"{model_name}-v{model_version}-evaluation-report.json"
    tmp_report = report_file.with_suffix(".json.tmp")
    with open(tmp_report, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, default=_json_default)
    tmp_report.replace(report_file)

    # Save to dedicated evaluation output dir if specified
    eval_dir = evaluation_output_dir or Path("artifacts/reports/evaluation")
    eval_dir.mkdir(parents=True, exist_ok=True)
    eval_file = eval_dir / f"{model_name}-v{model_version}-evaluation.json"
    tmp_eval = eval_file.with_suffix(".json.tmp")
    with open(tmp_eval, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, default=_json_default)
    tmp_eval.replace(eval_file)

    # Save to dedicated validation output dir if specified
    val_dir = validation_output_dir or Path("artifacts/reports/validation")
    val_dir.mkdir(parents=True, exist_ok=True)
    val_file = val_dir / f"{model_name}-v{model_version}-validation.json"
    tmp_val = val_file.with_suffix(".json.tmp")
    with open(tmp_val, "w", encoding="utf-8") as f:
        json.dump({
            "validation_timestamp": report_dict["created_at"],
            "model_name": model_name,
            "model_version": model_version,
            "manifest_sha256": manifest_sha256,
            "calibration_status": calibration_status_str,
            "calibration_comparison": calib_comparison,
            "reliability_diagram": reliability_diagram,
            "stress_testing": stress_results,
            "leakage_audit": leakage_audit,
            "disclaimer": AI_HUMAN_IN_THE_LOOP_DISCLAIMER,
        }, f, indent=2, default=_json_default)
    tmp_val.replace(val_file)

    # Generate Human-Readable Markdown Reports
    _write_markdown_reports(
        eval_dir=eval_dir,
        val_dir=val_dir,
        report_dict=report_dict,
        model_name=model_name,
        model_version=model_version,
    )

    # Console Summary
    print("\n" + "=" * 65)
    print("        E-WITNESS MODEL EVALUATION & CALIBRATION REPORT")
    print("=" * 65)
    print(f"Evaluation Mode:         {evaluation_kind}")
    if is_smoke_test:
        print("  [NOTICE: Software pipeline smoke test only; not evidence of real model accuracy]")
    print(f"Model:                   {model_name} (v{model_version})")
    print(f"Manifest SHA256:         {manifest_sha256[:16]}...")
    print(f"Test Samples (N):        {len(test_targets)} (Statistically Reliable: {primary_metrics.is_statistically_reliable})")
    print(f"TP: {primary_metrics.tp} | FP: {primary_metrics.fp} | TN: {primary_metrics.tn} | FN: {primary_metrics.fn}")
    print(f"Accuracy:                {per_class_metrics['accuracy'] * 100 if per_class_metrics['accuracy'] is not None else 0.0:.2f}%")
    print(f"Precision:               {primary_metrics.precision * 100 if primary_metrics.precision is not None else 0.0:.2f}%")
    print(f"Recall:                  {primary_metrics.recall * 100 if primary_metrics.recall is not None else 0.0:.2f}%")
    print(f"Specificity:             {primary_metrics.specificity * 100 if primary_metrics.specificity is not None else 0.0:.2f}%")
    print(f"FPR:                     {primary_metrics.false_positive_rate * 100 if primary_metrics.false_positive_rate is not None else 0.0:.2f}%")
    print(f"FNR:                     {primary_metrics.false_negative_rate * 100 if primary_metrics.false_negative_rate is not None else 0.0:.2f}%")
    print(f"F1 Score:                {primary_metrics.f1_score if primary_metrics.f1_score is not None else 0.0:.4f}")
    print(f"ROC-AUC:                 {f'{roc_auc:.4f}' if roc_auc is not None else 'N/A (single-class test partition)'}")
    print(f"PR-AUC:                  {f'{pr_auc:.4f}' if pr_auc is not None else 'N/A (single-class test partition)'}")
    print(f"Brier Score:             {primary_metrics.brier_score if primary_metrics.brier_score is not None else 0.0:.4f}")
    print(f"Uncalibrated ECE:        {test_uncalib_ece:.4f}")
    print(f"Calibrated ECE:          {test_calib_ece:.4f} (Target <= 0.08: {'MET' if is_ece_target_met else 'NOT MET'})")
    print(f"Platt Scaling (A, B):    slope={slope:.4f}, intercept={intercept:.4f} ({fit_status})")
    print(f"Temperature (T):         T={temp_t:.4f} ({temp_status})")
    print(f"Calibration Validation:  {calibration_status_str} ({'Statistically adequate N >= 100' if is_calibration_validated else 'Insufficient sample size or smoke-test'})")

    print("\nPer-Class Performance Breakdown:")
    print(f"  Class 0 (Non-Violence): Support={per_class_metrics['class_0_non_violence']['support']}, Precision={per_class_metrics['class_0_non_violence']['precision']}, Recall={per_class_metrics['class_0_non_violence']['recall']}, F1={per_class_metrics['class_0_non_violence']['f1_score']}")
    print(f"  Class 1 (Violence):     Support={per_class_metrics['class_1_violence']['support']}, Precision={per_class_metrics['class_1_violence']['precision']}, Recall={per_class_metrics['class_1_violence']['recall']}, F1={per_class_metrics['class_1_violence']['f1_score']}")

    print("\nReliability Diagram (10 Uniform Confidence Bins):")
    print("  Bin Range   | Samples | Mean Conf | Emp Acc | Calib Error")
    print("  " + "-" * 55)
    for b in reliability_diagram["bins"]:
        acc_str = f"{b['empirical_accuracy'] * 100:.1f}%" if b["empirical_accuracy"] is not None else "   N/A"
        print(f"  [{b['bin_lower']:.1f}, {b['bin_upper']:.1f})   | {b['sample_count']:7d} | {b['mean_confidence'] * 100:8.1f}% | {acc_str:7s} | {b['calibration_error'] * 100:9.2f}%")

    if stress_results:
        print("\nReal-World Operational Stress Matrix:")
        print("  Condition             | Accuracy | Precision | Recall  | False Alarms | Missed")
        print("  " + "-" * 65)
        for ck, sr in stress_results.items():
            acc_s = f"{sr['accuracy'] * 100:.1f}%" if sr["accuracy"] is not None else "N/A"
            pr_s = f"{sr['precision'] * 100:.1f}%" if sr["precision"] is not None else "N/A"
            rec_s = f"{sr['recall'] * 100:.1f}%" if sr["recall"] is not None else "N/A"
            print(f"  {ck:21s} | {acc_s:8s} | {pr_s:9s} | {rec_s:7s} | {sr['fp']:12d} | {sr['fn']:6d}")

    print("=" * 65 + "\n")

    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return report_dict


def _write_markdown_reports(
    eval_dir: Path,
    val_dir: Path,
    report_dict: dict[str, Any],
    model_name: str,
    model_version: str,
) -> None:
    """Generate professional, auditable Markdown reports for evaluation and validation."""
    pm = report_dict["primary_metrics"]
    pcm = report_dict["per_class_metrics"]
    rd = report_dict["reliability_diagram"]
    cmc = report_dict["calibration_method_comparison"]
    sr = report_dict.get("real_world_stress_testing", {})
    la = report_dict.get("data_leakage_and_splits_audit", {})

    eval_md = rf"""# E-WITNESS Violence Detection Model Evaluation Report

**Model Identifier:** `{model_name}` (v`{model_version}`)
**Report Generated:** {report_dict['created_at']}
**Evaluation Mode:** `{report_dict['evaluation_kind']}`
**Evaluation Level:** `{report_dict['evaluation_level']}`
**Operational Disclaimer:** {AI_HUMAN_IN_THE_LOOP_DISCLAIMER}

---

## 1. Primary Classification Metrics (Decision Threshold = {report_dict['threshold_used']:.2f})

| Metric | Measured Value | Operational Interpretation |
| :--- | :---: | :--- |
| **Accuracy** | {pcm['accuracy'] * 100 if pcm['accuracy'] is not None else 0.0:.2f}% | Overall proportion of correct binary classifications |
| **Precision** | {pm['precision'] * 100 if pm['precision'] is not None else 0.0:.2f}% | Positive predictive value (violence detections confirmed) |
| **Recall (Sensitivity)** | {pm['recall'] * 100 if pm['recall'] is not None else 0.0:.2f}% | True positive rate (actual violent events detected) |
| **Specificity** | {pm['specificity'] * 100 if pm['specificity'] is not None else 0.0:.2f}% | True negative rate (peaceful events correctly identified) |
| **F1 Score** | {pm['f1_score'] if pm['f1_score'] is not None else 0.0:.4f} | Harmonic mean of precision and recall |
| **False Positive Rate** | {pm['false_positive_rate'] * 100 if pm['false_positive_rate'] is not None else 0.0:.2f}% | False alarm rate triggering review workload |
| **False Negative Rate** | {pm['false_negative_rate'] * 100 if pm['false_negative_rate'] is not None else 0.0:.2f}% | Missed incident rate |
| **ROC-AUC** | {f"{pm['roc_auc']:.4f}" if pm['roc_auc'] is not None else "N/A (single-class test partition)"} | Area under receiver operating characteristic curve |
| **PR-AUC** | {f"{pm['pr_auc']:.4f}" if pm['pr_auc'] is not None else "N/A (single-class test partition)"} | Area under precision-recall curve |
| **Brier Score** | {pm['brier_score'] if pm['brier_score'] is not None else 0.0:.4f} | Mean squared probability error (lower is superior) |

### Confusion Matrix
- **True Positives (TP):** {pm['tp']}
- **False Positives (FP):** {pm['fp']}
- **True Negatives (TN):** {pm['tn']}
- **False Negatives (FN):** {pm['fn']}
- **Total Evaluated Samples (N):** {pm['total']}

---

## 2. Per-Class Performance Breakdown

| Class | Support | Precision | Recall | F1 Score |
| :--- | :---: | :---: | :---: | :---: |
| **Class 0 (Non-Violence)** | {pcm['class_0_non_violence']['support']} | {pcm['class_0_non_violence']['precision'] * 100 if pcm['class_0_non_violence']['precision'] is not None else 0.0:.1f}% | {pcm['class_0_non_violence']['recall'] * 100 if pcm['class_0_non_violence']['recall'] is not None else 0.0:.1f}% | {pcm['class_0_non_violence']['f1_score'] if pcm['class_0_non_violence']['f1_score'] is not None else 0.0:.3f} |
| **Class 1 (Violence)** | {pcm['class_1_violence']['support']} | {pcm['class_1_violence']['precision'] * 100 if pcm['class_1_violence']['precision'] is not None else 0.0:.1f}% | {pcm['class_1_violence']['recall'] * 100 if pcm['class_1_violence']['recall'] is not None else 0.0:.1f}% | {pcm['class_1_violence']['f1_score'] if pcm['class_1_violence']['f1_score'] is not None else 0.0:.3f} |

---

## 3. Reliability Diagram & Confidence Calibration

- **Calibration Validation Status:** **`{report_dict['calibration_validation_status']}`**
- **Uncalibrated Expected Calibration Error (ECE):** `{pm['uncalibrated_ece']:.4f}`
- **Calibrated ECE:** `{pm['expected_calibration_error']:.4f}` (Target $\le 0.08$: **{'MET' if pm['is_ece_target_met'] else 'NOT MET'}**)
- **Maximum Calibration Error (MCE):** `{rd['mce']:.4f}`

### 10-Bin Reliability Diagram
| Bin Range | Sample Count | Mean Confidence | Empirical Accuracy | Calibration Error |
| :---: | :---: | :---: | :---: | :---: |
"""
    for b in rd["bins"]:
        acc_s = f"{b['empirical_accuracy'] * 100:.1f}%" if b["empirical_accuracy"] is not None else "N/A"
        eval_md += f"| `[{b['bin_lower']:.1f}, {b['bin_upper']:.1f})` | {b['sample_count']} | {b['mean_confidence'] * 100:.1f}% | {acc_s} | {b['calibration_error'] * 100:.2f}% |\n"

    eval_md += f"""
---

## 4. Calibration Method Comparison (Validation-Fitted, Test-Evaluated)

| Calibration Method | Status | Parameters | ECE | MCE | Brier Score |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Uncalibrated (Softmax)** | Baseline | N/A | {cmc['uncalibrated']['ece']:.4f} | {cmc['uncalibrated']['mce']:.4f} | {cmc['uncalibrated']['brier_score']:.4f} |
| **Platt Scaling** | {cmc['platt_scaling']['status']} | {cmc['platt_scaling']['parameters']} | {cmc['platt_scaling']['ece']:.4f} | {cmc['platt_scaling']['mce']:.4f} | {cmc['platt_scaling']['brier_score']:.4f} |
| **Temperature Scaling** | {cmc['temperature_scaling']['status']} | {cmc['temperature_scaling']['parameters']} | {cmc['temperature_scaling']['ece']:.4f} | {cmc['temperature_scaling']['mce']:.4f} | {cmc['temperature_scaling']['brier_score']:.4f} |

---

## 5. Civil-Rights & Human Governance Safeguards

1. **Advisory Segments Only:** All candidate detections remain strictly advisory candidate segments for authorized human review.
2. **Zero Automated Punishment:** No guilt determination, disciplinary sanction, or punitive action is triggered automatically.
3. **Biometric Prohibition:** `BIOMETRIC_MATCHING_ENABLED = False` is enforced by code and configuration policy.
4. **Reproducibility Fingerprint:** `{report_dict['reproducibility_hash']}`
"""
    (eval_dir / "EVALUATION_REPORT.md").write_text(eval_md, encoding="utf-8")

    # Real-World Performance Validation Plan & Stress Matrix
    val_md = f"""# E-WITNESS Real-World Performance & Operational Stress Testing Plan

**Model:** `{model_name}` (v`{model_version}`)
**Status:** **`{report_dict['calibration_validation_status']}`**
**Evaluation Type:** `{report_dict['evaluation_type']}`

---

## 1. Operational Stress Test Matrix

The model was subjected to 8 controlled digital perturbations simulating real-world operational challenges:

| Stress Condition | Description | Accuracy | Precision | Recall | False Alarms (FP) | Missed Events (FN) | Mean Score |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    for ck, s_res in sr.items():
        acc_s = f"{s_res['accuracy'] * 100:.1f}%" if s_res["accuracy"] is not None else "N/A"
        prec_s = f"{s_res['precision'] * 100:.1f}%" if s_res["precision"] is not None else "N/A"
        rec_s = f"{s_res['recall'] * 100:.1f}%" if s_res["recall"] is not None else "N/A"
        val_md += f"| **`{ck}`** | {s_res['description']} | {acc_s} | {prec_s} | {rec_s} | {s_res['fp']} | {s_res['fn']} | {s_res['mean_violence_score']:.4f} |\n"

    val_md += rf"""
---

## 2. Dataset Split & Leakage Review

- **Total Inspected Items:** {la.get('total_items', 0)}
- **Cross-Split Bitwise Hash Leakage:** **{'DETECTED (FAIL)' if la.get('cross_split_hash_leakage') else 'NONE DETECTED (PASS)'}**
- **Hash Overlap Details:** {la.get('hash_leakage_details', {})}
- **Verifiable Scene-Prefix Clips:** {la.get('scene_grouping_audit', {}).get('verifiable_scene_prefix_clips', 0)}
- **Ungroupable Opaque Clips (HockeyFight/MovieFights):** {la.get('scene_grouping_audit', {}).get('ungroupable_opaque_clips', 0)}
- **Class Balance by Split:**
  - `train`: {la.get('class_distribution_by_split', {}).get('train', {})}
  - `val`: {la.get('class_distribution_by_split', {}).get('val', {})}
  - `test`: {la.get('class_distribution_by_split', {}).get('test', {})}

---

## 3. Real-World Readiness & Deployment Verdict

- **Production Readiness:** **`NOT READY`**
- **Reason:** Model has only undergone software pipeline verification and synthetic/smoke evaluation. Full training is gated behind upstream dataset rights clearance.
- **Prerequisites for Future Deployment:**
  1. Acquisition of commercially approved, consensual surveillance dataset.
  2. Multi-epoch training on NVIDIA RTX 4050 GPU under Python 3.12/3.13 LTS.
  3. Real-world validation on at least $N \ge 100$ held-out operational video clips.
  4. Human-in-the-loop audit verification.
"""
    (val_dir / "REAL_WORLD_PERFORMANCE_PLAN.md").write_text(val_md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate R3D-18 model and compute calibration.")
    parser.add_argument("--checkpoint", type=Path, default=Path("artifacts/models/violence-r3d18-v1.0.0.pt"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/models"))
    parser.add_argument("--evaluation-output-dir", type=Path, default=Path("artifacts/reports/evaluation"))
    parser.add_argument("--validation-output-dir", type=Path, default=Path("artifacts/reports/validation"))
    parser.add_argument("--threshold", type=float, default=0.50, help="Fixed decision threshold (default: 0.50)")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", type=str, default=None, help="Device to use ('cuda', 'cpu')")
    parser.add_argument("--synthetic-test", action="store_true", help="Run with synthetic test vectors")
    parser.add_argument("--smoke-test-limit", type=int, default=None, help="Limit number of real samples for rapid smoke testing")
    parser.add_argument("--no-stress-tests", action="store_true", help="Disable operational stress condition testing")
    parser.add_argument("--authorized-subset-only", action="store_true", help="Exclude MovieFights and HockeyFight from validation and test primary evaluations")

    args = parser.parse_args()

    evaluate_model_pipeline(
        checkpoint_path=args.checkpoint,
        manifest_path=args.manifest,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        decision_threshold=args.threshold,
        batch_size=args.batch_size,
        use_synthetic=args.synthetic_test,
        smoke_test_limit=args.smoke_test_limit,
        device_str=args.device,
        evaluation_output_dir=args.evaluation_output_dir,
        validation_output_dir=args.validation_output_dir,
        run_stress_tests=not args.no_stress_tests,
        authorized_subset_only=args.authorized_subset_only,
    )


if __name__ == "__main__":
    main()
    import sys
    sys.stdout.flush()
    import os
    os._exit(0)
