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
from scripts.evaluate_violence_model import apply_stress_condition
from scripts.train_violence_model import ViolenceVideoDataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("compare_v120_v130")


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


def evaluate_model_on_val(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    threshold: float = 0.50,
    stress_condition: str = "baseline",
    seed: int = 42,
) -> dict[str, Any]:
    model.eval()
    all_targets: list[int] = []
    all_logits: list[float] = []
    all_probs: list[float] = []

    if stress_condition == "sensor_noise":
        torch.manual_seed(seed)

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            if stress_condition != "baseline":
                inputs = apply_stress_condition(inputs, stress_condition)

            with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                outputs = model(inputs)
                probs = torch.softmax(outputs, dim=1)

            diff_logits = (outputs[:, 1] - outputs[:, 0]).cpu().numpy()
            v_probs = probs[:, 1].cpu().numpy()

            all_targets.extend(targets.numpy().tolist())
            all_logits.extend(diff_logits.tolist())
            all_probs.extend(v_probs.tolist())

    y_true = np.array(all_targets, dtype=int)
    y_prob = np.array(all_probs, dtype=float)
    y_pred = (y_prob >= threshold).astype(int)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = int(cm[0, 0]), int(cm[0, 1]), int(cm[1, 0]), int(cm[1, 1])

    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    spec = (tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    fpr = (fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = (fn / (fn + tp)) if (fn + tp) > 0 else 0.0
    f1 = f1_score(y_true, y_pred, zero_division=0)
    brier = float(np.mean((y_prob - y_true) ** 2))

    try:
        roc_auc = float(roc_auc_score(y_true, y_prob))
    except Exception:
        roc_auc = None

    try:
        pr_auc = float(average_precision_score(y_true, y_prob))
    except Exception:
        pr_auc = None

    ece, mce = compute_ece(y_prob, y_true, n_bins=10)

    return {
        "condition": stress_condition,
        "sample_count": len(y_true),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "accuracy": round(float(acc), 4),
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "specificity": round(float(spec), 4),
        "false_positive_rate": round(float(fpr), 4),
        "false_negative_rate": round(float(fnr), 4),
        "f1": round(float(f1), 4),
        "brier_score": round(float(brier), 4),
        "roc_auc": round(float(roc_auc), 4) if roc_auc is not None else None,
        "pr_auc": round(float(pr_auc), 4) if pr_auc is not None else None,
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "mean_violence_score": round(float(np.mean(y_prob)), 4),
    }


def load_model(checkpoint_path: Path, device: torch.device) -> nn.Module:
    logger.info("Loading checkpoint: %s", checkpoint_path)
    model = r3d_18(weights=None)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, 2)

    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    state_dict = ckpt.get("model_state_dict", ckpt)
    model.load_state_dict(state_dict, strict=True)
    model.to(device)
    model.eval()
    return model


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Device for evaluation: %s", device)

    manifest_path = Path("data/manifest.json")
    data_dir = Path("data/raw")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    items = manifest.get("items", [])
    val_items = [it for it in items if it.get("split") == "val"]
    val_items = [
        it for it in val_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]
    logger.info("Authorized validation items: %d (Class 0: %d, Class 1: %d)",
                len(val_items),
                sum(1 for it in val_items if it["label"] == 0),
                sum(1 for it in val_items if it["label"] == 1))

    dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=False)
    loader = DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)

    v120_ckpt = Path("artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.pt")
    v130_ckpt = Path("artifacts/models/experimental/v1.3.0/violence-r3d18-experiment-v1.3.0.pt")

    conditions = [
        "baseline",
        "low_light",
        "bright_glare",
        "low_resolution",
        "camera_motion_blur",
        "spatial_occlusion",
        "sensor_noise",
        "temporal_truncation",
    ]

    model_v120 = load_model(v120_ckpt, device)
    v120_results = {}
    for cond in conditions:
        logger.info("Evaluating v1.2.0 on condition: %s", cond)
        res = evaluate_model_on_val(model_v120, loader, device, threshold=0.50, stress_condition=cond)
        v120_results[cond] = res
    del model_v120
    torch.cuda.empty_cache()

    model_v130 = load_model(v130_ckpt, device)
    v130_results = {}
    for cond in conditions:
        logger.info("Evaluating v1.3.0 on condition: %s", cond)
        res = evaluate_model_on_val(model_v130, loader, device, threshold=0.50, stress_condition=cond)
        v130_results[cond] = res
    del model_v130
    torch.cuda.empty_cache()

    comparison = {
        "benchmark_dataset": "Authorized Academic Surveillance Validation Subset",
        "sample_size": len(val_items),
        "class_support": {"class_0_non_violence": 160, "class_1_violence": 102},
        "decision_threshold": 0.50,
        "v1.2.0_checkpoint": str(v120_ckpt),
        "v1.3.0_checkpoint": str(v130_ckpt),
        "clean_baseline_comparison": {
            "v1.2.0": v120_results["baseline"],
            "v1.3.0": v130_results["baseline"],
        },
        "stress_matrix_v1.2.0": v120_results,
        "stress_matrix_v1.3.0": v130_results,
    }

    out_file = Path("artifacts/reports/validation/v120_vs_v130_validation_comparison.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)
    logger.info("Saved comparison report to: %s", out_file)

    # Print summary table
    print("\n" + "=" * 95)
    print(f"{'Condition':<22} | {'v1.2.0 Recall':<14} | {'v1.3.0 Recall':<14} | {'v1.2.0 FPR':<12} | {'v1.3.0 FPR':<12} | {'Recall Delta':<12}")
    print("-" * 95)
    for cond in conditions:
        r120 = v120_results[cond]["recall"] * 100
        r130 = v130_results[cond]["recall"] * 100
        fpr120 = v120_results[cond]["false_positive_rate"] * 100
        fpr130 = v130_results[cond]["false_positive_rate"] * 100
        delta = r130 - r120
        delta_str = f"{delta:+.2f}%"
        print(f"{cond:<22} | {r120:>12.2f}% | {r130:>12.2f}% | {fpr120:>10.2f}% | {fpr130:>10.2f}% | {delta_str:>12}")
    print("=" * 95)


if __name__ == "__main__":
    main()
