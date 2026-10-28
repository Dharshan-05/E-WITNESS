import json
import logging
import sys
from pathlib import Path

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
from scripts.evaluate_violence_model import apply_stress_condition
from scripts.train_violence_model import ViolenceVideoDataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_stress_validation")


def compute_ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> tuple[float, float]:
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    mce = 0.0
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
    return float(ece), float(mce)


def evaluate_condition(model, loader, device, cond, seed=42):
    if cond == "sensor_noise":
        torch.manual_seed(seed)

    all_targets, all_probs = [], []
    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            if cond != "baseline":
                inputs = apply_stress_condition(inputs, cond)
            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                outputs = model(inputs)
                probs = torch.softmax(outputs, dim=1)
            all_targets.extend(targets.numpy().tolist())
            all_probs.extend(probs[:, 1].cpu().numpy().tolist())

    y_true = np.array(all_targets, dtype=int)
    y_prob = np.array(all_probs, dtype=float)
    y_pred = (y_prob >= 0.50).astype(int)

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
    ece, mce = compute_ece(y_prob, y_true)

    # Verification of mathematical consistency between CM and metrics
    math_acc = (tp + tn) / len(y_true)
    math_prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    math_rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    math_spec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    math_f1 = (2 * math_prec * math_rec / (math_prec + math_rec)) if (math_prec + math_rec) > 0 else 0.0

    cm_math_consistent = (
        abs(acc - math_acc) < 1e-4 and
        abs(prec - math_prec) < 1e-4 and
        abs(rec - math_rec) < 1e-4 and
        abs(spec - math_spec) < 1e-4 and
        abs(f1 - math_f1) < 1e-4
    )

    return {
        "condition": cond,
        "sample_count": len(y_true),
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
            "ece": round(ece, 4),
            "mce": round(mce, 4),
            "mean_violence_score": round(float(np.mean(y_prob)), 4),
        },
        "cm_math_consistent": cm_math_consistent,
    }


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifest_path = Path("data/manifest.json")
    data_dir = Path("data/raw")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    val_items = [it for it in manifest.get("items", []) if it.get("split") == "val"]
    val_items = [
        it for it in val_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]

    dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=False)
    loader = DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)

    conditions = [
        "baseline",
        "camera_motion_blur",
        "low_resolution",
        "sensor_noise",
        "bright_glare",
        "low_light",
        "temporal_truncation",
        "spatial_occlusion",
    ]

    # Evaluate v1.3.0
    ckpt_path = Path("artifacts/models/experimental/v1.3.0/violence-r3d18-experiment-v1.3.0.pt")
    model = r3d_18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 2)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"], strict=True)
    model.to(device)
    model.eval()

    v130_stress_results = {}
    for cond in conditions:
        logger.info("Evaluating condition: %s", cond)
        res = evaluate_condition(model, loader, device, cond)
        v130_stress_results[cond] = res

    # Load reported comparison JSON
    rep_path = Path("artifacts/reports/validation/v120_vs_v130_validation_comparison.json")
    with open(rep_path, encoding="utf-8") as f:
        rep_data = json.load(f)

    reported_v130 = rep_data.get("stress_matrix_v1.3.0", {})

    discrepancies = []
    print("\n=== STRESS TEST AUDIT & REPRODUCTION TABLE (v1.3.0, N=262, threshold=0.50) ===")
    print(f"{'Condition':<22} | {'Repro CM [TN,FP,FN,TP]':<23} | {'Repro Acc':<10} | {'Repro Rec':<10} | {'Repro Prec':<10} | {'Reported Match'}")
    print("-" * 95)

    for cond in conditions:
        repro = v130_stress_results[cond]
        reported = reported_v130.get(cond, {})

        repro_cm = repro["confusion_matrix_array"]
        reported_cm = [
            reported.get("confusion_matrix", {}).get("tn"),
            reported.get("confusion_matrix", {}).get("fp"),
            reported.get("confusion_matrix", {}).get("fn"),
            reported.get("confusion_matrix", {}).get("tp"),
        ]

        cm_match = (repro_cm == reported_cm)
        acc_match = (repro["metrics"]["accuracy"] == reported.get("accuracy"))
        rec_match = (repro["metrics"]["recall"] == reported.get("recall"))
        prec_match = (repro["metrics"]["precision"] == reported.get("precision"))

        overall_match = cm_match and acc_match and rec_match and prec_match
        if not overall_match:
            discrepancies.append({
                "condition": cond,
                "repro_cm": repro_cm,
                "reported_cm": reported_cm,
                "repro_acc": repro["metrics"]["accuracy"],
                "reported_acc": reported.get("accuracy"),
            })

        print(f"{cond:<22} | {repro_cm!s:<23} | {repro['metrics']['accuracy']*100:>8.2f}% | {repro['metrics']['recall']*100:>8.2f}% | {repro['metrics']['precision']*100:>8.2f}% | {overall_match!s}")

    print("=" * 95)
    print(f"Total Discrepancies Found: {len(discrepancies)}")

    audit_out = {
        "status": "VERIFIED" if len(discrepancies) == 0 else "DISCREPANCY_FOUND",
        "conditions_evaluated": len(conditions),
        "discrepancy_count": len(discrepancies),
        "results": v130_stress_results,
    }

    out_file = Path("artifacts/reports/validation/v130_stress_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_out, f, indent=2)
    logger.info("Saved stress audit to: %s", out_file)


if __name__ == "__main__":
    main()
