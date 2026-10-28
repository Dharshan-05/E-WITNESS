import hashlib
import json
import logging
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
from scripts.train_violence_model import ViolenceVideoDataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_clean_val_v130")


def compute_ece_details(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> dict[str, Any]:
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    mce = 0.0
    n = len(probs)
    bins_info = []

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

        bins_info.append({
            "bin_idx": i,
            "bin_range": [round(float(low), 2), round(float(high), 2)],
            "count": int(count),
            "empirical_accuracy": round(bin_acc, 4) if bin_acc is not None else None,
            "mean_confidence": round(bin_conf, 4),
            "absolute_error": round(bin_err, 4),
        })

    return {
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "bin_boundaries": [round(float(b), 2) for b in bin_boundaries],
        "bins": bins_info,
    }


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Evaluation device: %s", device)

    ckpt_path = Path("artifacts/models/experimental/v1.3.0/violence-r3d18-experiment-v1.3.0.pt")
    manifest_path = Path("data/manifest.json")
    data_dir = Path("data/raw")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    val_items = [it for it in manifest.get("items", []) if it.get("split") == "val"]
    val_items = [
        it for it in val_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]

    logger.info("Authorized validation items: %d", len(val_items))
    if len(val_items) != 262:
        raise ValueError(f"Expected 262 items, got {len(val_items)}")

    c0 = sum(1 for it in val_items if it["label"] == 0)
    c1 = sum(1 for it in val_items if it["label"] == 1)
    logger.info("Class distribution: Class 0 (non_violence)=%d, Class 1 (violence)=%d", c0, c1)

    dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=False)
    loader = DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)

    # Load model strictly
    model = r3d_18(weights=None)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, 2)

    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"], strict=True)
    model.to(device)
    model.eval()

    all_targets = []
    all_logits_diff = []
    all_raw_logits = []
    all_probs = []

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                outputs = model(inputs)  # [B, 2]
                probs = torch.softmax(outputs, dim=1)

            diff = (outputs[:, 1] - outputs[:, 0]).cpu().numpy()
            v_probs = probs[:, 1].cpu().numpy()
            raw_logits = outputs.cpu().numpy()

            all_targets.extend(targets.numpy().tolist())
            all_logits_diff.extend(diff.tolist())
            all_raw_logits.extend(raw_logits.tolist())
            all_probs.extend(v_probs.tolist())

    y_true = np.array(all_targets, dtype=int)
    y_prob = np.array(all_probs, dtype=float)
    threshold = 0.50
    y_pred = (y_prob >= threshold).astype(int)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = int(cm[0, 0]), int(cm[0, 1]), int(cm[1, 0]), int(cm[1, 1])

    acc = float(accuracy_score(y_true, y_pred))
    prec = float(precision_score(y_true, y_pred, zero_division=0))
    rec = float(recall_score(y_true, y_pred, zero_division=0))
    spec = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0
    f1 = float(f1_score(y_true, y_pred, zero_division=0))
    brier = float(np.mean((y_prob - y_true) ** 2))
    roc_auc = float(roc_auc_score(y_true, y_prob))
    pr_auc = float(average_precision_score(y_true, y_prob))

    ece_details = compute_ece_details(y_prob, y_true, n_bins=10)

    # Prepare sample records (anonymized hash of path to avoid PII)
    sample_records = []
    for idx, (item, raw_logit, diff_logit, prob, pred, true_label) in enumerate(
        zip(val_items, all_raw_logits, all_logits_diff, all_probs, y_pred.tolist(), y_true.tolist(), strict=True)
    ):
        path_hash = hashlib.sha256(item["path"].encode("utf-8")).hexdigest()[:12]
        sample_records.append({
            "sample_index": idx,
            "sample_id": f"val_{idx:03d}_{path_hash}",
            "ground_truth_label": true_label,
            "ground_truth_class": "violence" if true_label == 1 else "non_violence",
            "predicted_label": pred,
            "predicted_class": "violence" if pred == 1 else "non_violence",
            "is_correct": bool(pred == true_label),
            "raw_logits": [round(float(logit_val), 4) for logit_val in raw_logit],
            "differential_logit": round(float(diff_logit), 4),
            "violence_probability": round(float(prob), 4),
        })

    audit_result = {
        "model_checkpoint": str(ckpt_path),
        "checkpoint_epoch": ckpt.get("epoch"),
        "best_epoch_in_checkpoint": 4,
        "sample_count": len(y_true),
        "threshold": threshold,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "confusion_matrix_array": [tn, fp, fn, tp],
        "metrics": {
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "specificity": round(spec, 4),
            "false_positive_rate": round(fpr, 4),
            "false_negative_rate": round(fnr, 4),
            "f1_score": round(f1, 4),
            "brier_score": round(brier, 4),
            "roc_auc": round(roc_auc, 4),
            "pr_auc": round(pr_auc, 4),
            "ece": ece_details["ece"],
            "mce": ece_details["mce"],
        },
        "ece_details": ece_details,
        "reported_match_check": {
            "expected_cm": [155, 5, 15, 87],
            "reproduced_cm": [tn, fp, fn, tp],
            "cm_matches": bool([tn, fp, fn, tp] == [155, 5, 15, 87]),
            "expected_acc": 0.9237,
            "reproduced_acc": round(acc, 4),
            "acc_matches": bool(round(acc, 4) == 0.9237),
            "expected_prec": 0.9457,
            "reproduced_prec": round(prec, 4),
            "prec_matches": bool(round(prec, 4) == 0.9457),
            "expected_rec": 0.8529,
            "reproduced_rec": round(rec, 4),
            "rec_matches": bool(round(rec, 4) == 0.8529),
            "expected_spec": 0.9688,
            "reproduced_spec": round(spec, 4),
            "spec_matches": bool(round(spec, 4) == 0.9688),
            "expected_f1": 0.8969,
            "reproduced_f1": round(f1, 4),
            "f1_matches": bool(round(f1, 4) == 0.8969),
            "expected_roc_auc": 0.9763,
            "reproduced_roc_auc": round(roc_auc, 4),
            "roc_auc_matches": bool(round(roc_auc, 4) == 0.9763),
            "expected_pr_auc": 0.9680,
            "reproduced_pr_auc": round(pr_auc, 4),
            "pr_auc_matches": bool(round(pr_auc, 4) == 0.9680),
            "expected_brier": 0.0629,
            "reproduced_brier": round(brier, 4),
            "brier_matches": bool(round(brier, 4) == 0.0629),
            "expected_ece": 0.0469,
            "reproduced_ece": ece_details["ece"],
            "ece_matches": bool(ece_details["ece"] == 0.0469),
        },
        "predictions": sample_records,
    }

    out_file = Path("artifacts/reports/validation/v130_clean_validation_audit.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, indent=2)

    logger.info("Audit result saved to: %s", out_file)
    logger.info("Confusion Matrix Match: %s ([TN=%d, FP=%d, FN=%d, TP=%d])",
                audit_result["reported_match_check"]["cm_matches"], tn, fp, fn, tp)
    logger.info("Accuracy: %.4f (Match: %s)", acc, audit_result["reported_match_check"]["acc_matches"])
    logger.info("Precision: %.4f (Match: %s)", prec, audit_result["reported_match_check"]["prec_matches"])
    logger.info("Recall: %.4f (Match: %s)", rec, audit_result["reported_match_check"]["rec_matches"])
    logger.info("Specificity: %.4f (Match: %s)", spec, audit_result["reported_match_check"]["spec_matches"])
    logger.info("F1 Score: %.4f (Match: %s)", f1, audit_result["reported_match_check"]["f1_matches"])
    logger.info("ROC-AUC: %.4f (Match: %s)", roc_auc, audit_result["reported_match_check"]["roc_auc_matches"])
    logger.info("PR-AUC: %.4f (Match: %s)", pr_auc, audit_result["reported_match_check"]["pr_auc_matches"])
    logger.info("Brier Score: %.4f (Match: %s)", brier, audit_result["reported_match_check"]["brier_matches"])
    logger.info("ECE: %.4f (Match: %s)", ece_details["ece"], audit_result["reported_match_check"]["ece_matches"])


if __name__ == "__main__":
    main()
