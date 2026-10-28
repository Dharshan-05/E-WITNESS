import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.utils.data import DataLoader
from torchvision.models.video import r3d_18

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.train_violence_model import ViolenceVideoDataset, KINETICS_MEAN, KINETICS_STD

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reproduce_validation_v120")


def compute_ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> tuple[float, float, list[dict[str, Any]]]:
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    mce = 0.0
    bins_data = []
    n = len(probs)
    
    for i in range(n_bins):
        low, high = bin_boundaries[i], bin_boundaries[i + 1]
        if i == n_bins - 1:
            indices = np.where((probs >= low) & (probs <= high))[0]
        else:
            indices = np.where((probs >= low) & (probs < high))[0]
        count = len(indices)
        if count > 0:
            bin_acc = float(np.mean(labels[indices]))
            bin_conf = float(np.mean(probs[indices]))
            bin_err = abs(bin_acc - bin_conf)
            ece += (count / n) * bin_err
            if bin_err > mce:
                mce = bin_err
        else:
            bin_acc = None
            bin_conf = float((low + high) / 2.0)
            bin_err = 0.0
        bins_data.append({
            "bin": i,
            "range": [round(float(low), 2), round(float(high), 2)],
            "count": int(count),
            "accuracy": round(bin_acc, 4) if bin_acc is not None else None,
            "confidence": round(bin_conf, 4),
            "error": round(bin_err, 4),
        })
    return float(ece), float(mce), bins_data


def main():
    logger.info("=== PHASE 2: REPRODUCE VALIDATION METRICS FOR v1.2.0 ===")
    
    manifest_path = Path("data/manifest.json")
    data_dir = Path("data/raw")
    ckpt_path = Path("artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.pt")
    out_dir = Path("artifacts/reports/validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    
    items = manifest.get("items", [])
    val_items = [it for it in items if it.get("split") == "val"]
    before_count = len(val_items)
    
    # Authorized academic surveillance subset filter
    val_items = [
        it for it in val_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]
    logger.info("Validation items filtered: %d -> %d (%d unauthorized excluded)", before_count, len(val_items), before_count - len(val_items))
    assert len(val_items) == 262, f"Expected 262 validation items, got {len(val_items)}"
    
    val_labels = [int(it["label"]) for it in val_items]
    c0_count = sum(1 for l in val_labels if l == 0)
    c1_count = sum(1 for l in val_labels if l == 1)
    logger.info("Class distribution: Class 0 (non_violence)=%d, Class 1 (violence)=%d", c0_count, c1_count)
    assert c0_count == 160 and c1_count == 102, f"Unexpected class split: c0={c0_count}, c1={c1_count}"
    
    dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=False)
    loader = DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)
    
    # Load model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Inference device: %s", device)
    
    model = r3d_18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 2)
    
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"], strict=True)
    model.to(device)
    model.eval()
    
    # Weight class balance loss calculation
    # Using class weights from training: w0=0.9985, w1=1.0015
    class_weights = torch.tensor([0.9985, 1.0015], dtype=torch.float32).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights, label_smoothing=0.05)
    
    total_loss = 0.0
    all_logits = []
    all_targets = []
    all_probs = []
    
    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            with torch.amp.autocast('cuda', enabled=(device.type == "cuda")):
                logits = model(inputs)
                loss = criterion(logits, targets)
            
            total_loss += loss.item() * targets.size(0)
            probs = torch.softmax(logits.float(), dim=1)
            
            all_logits.extend(logits.float().cpu().numpy().tolist())
            all_targets.extend(targets.cpu().numpy().tolist())
            all_probs.extend(probs[:, 1].cpu().numpy().tolist())
            
    val_loss = total_loss / len(val_items)
    targets_np = np.array(all_targets, dtype=int)
    probs_np = np.array(all_probs, dtype=float)
    preds_np = (probs_np >= 0.5).astype(int)
    
    # Metrics
    cm = confusion_matrix(targets_np, preds_np, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    
    acc = accuracy_score(targets_np, preds_np)
    prec = precision_score(targets_np, preds_np, pos_label=1, zero_division=0)
    rec = recall_score(targets_np, preds_np, pos_label=1, zero_division=0)
    spec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    f1 = f1_score(targets_np, preds_np, pos_label=1, zero_division=0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    roc_auc = roc_auc_score(targets_np, probs_np)
    pr_auc = average_precision_score(targets_np, probs_np)
    brier = float(np.mean((probs_np - targets_np) ** 2))
    ece, mce, bins = compute_ece(probs_np, targets_np, n_bins=10)
    
    report = {
        "model_name": "violence-r3d18-experiment",
        "model_version": "1.2.0",
        "checkpoint_sha256": ckpt.get("manifest_sha256", "d18daa747d8c6f8774e7f8cd1356f949fd18e976caa5a7a43020cf5df5f32c10"),
        "evaluation_partition": "validation_authorized_academic_subset",
        "sample_count": len(val_items),
        "class_counts": {"non_violence": int(c0_count), "violence": int(c1_count)},
        "loss": round(float(val_loss), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "metrics": {
            "accuracy": round(float(acc), 4),
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "specificity": round(float(spec), 4),
            "f1": round(float(f1), 4),
            "false_positive_rate": round(float(fpr), 4),
            "false_negative_rate": round(float(fnr), 4),
            "roc_auc": round(float(roc_auc), 4),
            "pr_auc": round(float(pr_auc), 4),
            "brier_score": round(float(brier), 4),
            "expected_calibration_error": round(float(ece), 4),
            "maximum_calibration_error": round(float(mce), 4),
        },
        "reliability_diagram": bins,
        "sample_sum_check": {
            "sum_cm": int(tn + fp + fn + tp),
            "matches_total": bool((tn + fp + fn + tp) == len(val_items)),
        },
    }
    
    print("\n--- REPRODUCED VALIDATION RESULTS ---")
    print(f"Sample Count : {len(val_items)} (Sum CM: {tn + fp + fn + tp})")
    print(f"Loss         : {val_loss:.4f} (Reported: 0.2934)")
    print(f"Confusion Mtx: TN={tn}, FP={fp}, FN={fn}, TP={tp}")
    print(f"Accuracy     : {acc * 100:.2f}% (Reported: 90.08%)")
    print(f"Precision    : {prec * 100:.2f}% (Reported: 85.85%)")
    print(f"Recall       : {rec * 100:.2f}% (Reported: 89.22%)")
    print(f"Specificity  : {spec * 100:.2f}% (Derived: 90.62%)")
    print(f"F1-Score     : {f1:.4f} (Reported: 0.8750)")
    print(f"FPR          : {fpr * 100:.2f}% (Derived: 9.38%)")
    print(f"FNR          : {fnr * 100:.2f}% (Derived: 10.78%)")
    print(f"ROC-AUC      : {roc_auc:.4f}")
    print(f"PR-AUC       : {pr_auc:.4f}")
    print(f"Brier Score  : {brier:.4f}")
    print(f"ECE          : {ece:.4f}")
    print(f"MCE          : {mce:.4f}")
    
    out_file = out_dir / "violence-r3d18-experiment-v1.2.0-validation-reproduction.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n[SAVED] {out_file}")
    
    # Save logits and targets for Phase 4 calibration
    calib_cache = {
        "val_logits": all_logits,
        "val_targets": all_targets,
        "val_probs": all_probs,
    }
    calib_cache_file = out_dir / "val_calibration_cache.json"
    with open(calib_cache_file, "w", encoding="utf-8") as f:
        json.dump(calib_cache, f, indent=2)
    print(f"[SAVED] {calib_cache_file}")
    
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
