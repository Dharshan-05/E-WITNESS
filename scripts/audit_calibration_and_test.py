import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
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
logger = logging.getLogger("audit_calibration_and_test")


def calc_ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> tuple[float, float, list[dict[str, Any]]]:
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    mce = 0.0
    bin_details = []
    n = len(p)
    for i in range(n_bins):
        low, high = bins[i], bins[i + 1]
        if i == n_bins - 1:
            idx = np.where((p >= low) & (p <= high))[0]
        else:
            idx = np.where((p >= low) & (p < high))[0]
        count = len(idx)
        if count > 0:
            acc = float(np.mean(y[idx]))
            conf = float(np.mean(p[idx]))
            err = abs(acc - conf)
            ece += (count / n) * err
            if err > mce:
                mce = err
        else:
            acc = None
            conf = float((low + high) / 2.0)
            err = 0.0
        bin_details.append({
            "bin": i,
            "range": [round(float(low), 2), round(float(high), 2)],
            "count": int(count),
            "acc": round(acc, 4) if acc is not None else None,
            "conf": round(conf, 4),
            "error": round(err, 4),
        })
    return float(ece), float(mce), bin_details


def main():
    logger.info("=== AUDIT CALIBRATION & TEST SET EVALUATION ===")
    
    # 1. Load validation cache
    val_cache_path = Path("artifacts/reports/validation/val_calibration_cache.json")
    with open(val_cache_path) as f:
        val_data = json.load(f)
        
    val_targets = np.array(val_data["val_targets"], dtype=int)
    val_probs = np.array(val_data["val_probs"], dtype=float)
    val_logits_raw = np.array(val_data["val_logits"], dtype=float)
    val_diff_logits = val_logits_raw[:, 1] - val_logits_raw[:, 0]
    
    logger.info("Validation samples: N=%d (Non-violence: %d, Violence: %d)",
                len(val_targets), sum(val_targets == 0), sum(val_targets == 1))
    
    # Fit Candidate Calibrators ONLY on Validation Data
    # A. Platt on Raw Differential Logits
    lr_logits = LogisticRegression(solver="lbfgs", C=1.0)
    lr_logits.fit(val_diff_logits.reshape(-1, 1), val_targets)
    slope_l = float(lr_logits.coef_[0][0])
    intercept_l = float(lr_logits.intercept_[0])
    logger.info("Fitted Platt on LOGITS: slope=%.4f, intercept=%.4f", slope_l, intercept_l)
    
    # B. Temperature Scaling on Raw Differential Logits
    def nll_opt(T):
        s = val_diff_logits / T
        eps = 1e-12
        p = 1.0 / (1.0 + np.exp(-np.clip(s, -35, 35)))
        p_c = np.clip(p, eps, 1 - eps)
        return -float(np.mean(val_targets * np.log(p_c) + (1 - val_targets) * np.log(1 - p_c)))
    
    res = minimize_scalar(nll_opt, bounds=(0.05, 10.0), method="bounded")
    temp_T = float(res.x)
    logger.info("Fitted Temperature Scaling on LOGITS: T=%.4f (min NLL=%.4f)", temp_T, float(res.fun))
    
    # C. Platt on Probabilities (historical implementation)
    lr_probs = LogisticRegression(solver="lbfgs", C=1.0)
    lr_probs.fit(val_probs.reshape(-1, 1), val_targets)
    slope_p = float(lr_probs.coef_[0][0])
    intercept_p = float(lr_probs.intercept_[0])
    logger.info("Fitted Platt on PROBABILITIES: slope=%.4f, intercept=%.4f", slope_p, intercept_p)
    
    # 2. Load model and evaluate on Held-Out Test Set (285 eligible + 69 excluded)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt_path = Path("artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.pt")
    data_dir = Path("data/raw")
    manifest_path = Path("data/manifest.json")
    
    model = r3d_18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 2)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"], strict=True)
    model.to(device)
    model.eval()
    
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    items = manifest.get("items", [])
    test_items = [it for it in items if it.get("split") == "test"]
    
    eligible_test = [it for it in test_items if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()]
    excluded_test = [it for it in test_items if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower()]
    
    assert len(eligible_test) == 285
    assert len(excluded_test) == 69
    
    logger.info("Eligible Test Subset: %d clips | Excluded Out-of-Domain: %d clips", len(eligible_test), len(excluded_test))
    
    def run_loader(item_list):
        ds = ViolenceVideoDataset(data_dir, item_list, is_synthetic=False)
        ld = DataLoader(ds, batch_size=4, shuffle=False, num_workers=0)
        y_true, y_logits, y_probs = [], [], []
        with torch.no_grad():
            for inp, tgt in ld:
                inp = inp.to(device)
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda")):
                    out = model(inp)
                    prob = torch.softmax(out, dim=1)
                diff = (out[:, 1] - out[:, 0]).cpu().numpy()
                y_true.extend(tgt.numpy().tolist())
                y_logits.extend(diff.tolist())
                y_probs.extend(prob[:, 1].cpu().numpy().tolist())
        return np.array(y_true, dtype=int), np.array(y_logits, dtype=float), np.array(y_probs, dtype=float)
    
    logger.info("Running inference on 285 eligible test clips...")
    test_y, test_logits, test_probs_uncal = run_loader(eligible_test)
    
    logger.info("Running inference on 69 excluded test clips...")
    excl_y, excl_logits, excl_probs_uncal = run_loader(excluded_test)
    
    # 3. Compute Probabilities for All Methods on Eligible Test Split
    test_p_platt_logits = 1.0 / (1.0 + np.exp(-(slope_l * test_logits + intercept_l)))
    test_p_temp = 1.0 / (1.0 + np.exp(-np.clip(test_logits / temp_T, -35, 35)))
    test_p_platt_probs = 1.0 / (1.0 + np.exp(-(slope_p * test_probs_uncal + intercept_p)))
    
    methods = {
        "Uncalibrated": test_probs_uncal,
        "Platt (from Logits)": test_p_platt_logits,
        "Temperature Scaling": test_p_temp,
        "Platt (from Probs - Historical)": test_p_platt_probs,
    }
    
    print("\n=== CALIBRATION METRICS ON ELIGIBLE HELD-OUT TEST SET (N=285) ===")
    print(f"{'Method':<32} | {'ECE':<8} | {'MCE':<8} | {'Brier':<8} | {'Acc (%)':<8} | {'Target <= 0.08':<14}")
    print("-" * 88)
    
    eval_audit_results = {}
    for name, p_arr in methods.items():
        ece, mce, bins = calc_ece(p_arr, test_y)
        brier = float(brier_score_loss(test_y, p_arr))
        preds = (p_arr >= 0.50).astype(int)
        acc = float(accuracy_score(test_y, preds)) * 100.0
        target_met = ece <= 0.08
        print(f"{name:<32} | {ece:<8.4f} | {mce:<8.4f} | {brier:<8.4f} | {acc:<8.2f} | {'MET' if target_met else 'NOT MET':<14}")
        eval_audit_results[name] = {
            "ece": round(ece, 4),
            "mce": round(mce, 4),
            "brier": round(brier, 4),
            "accuracy": round(acc, 2),
            "target_met": target_met,
            "bins": bins,
        }
        
    # 4. Out-of-domain evaluation check
    excl_preds = (excl_probs_uncal >= 0.50).astype(int)
    excl_tp = int(sum((excl_preds == 1) & (excl_y == 1)))
    excl_fn = int(sum((excl_preds == 0) & (excl_y == 1)))
    excl_tn = int(sum((excl_preds == 0) & (excl_y == 0)))
    excl_fp = int(sum((excl_preds == 1) & (excl_y == 0)))
    
    print("\n=== OUT-OF-DOMAIN EXCLUDED CLIPS AUDIT (N=69) ===")
    print(f"Total Excluded Clips: {len(excl_y)}")
    print(f"Ground Truth Violence: {sum(excl_y == 1)}, Ground Truth Non-violence: {sum(excl_y == 0)}")
    print(f"TP={excl_tp}, FN={excl_fn}, TN={excl_tn}, FP={excl_fp}")
    print(f"Recall (Sensitivity): {excl_tp / max(1, excl_tp + excl_fn) * 100:.2f}%")
    specificity = (excl_tn / (excl_tn + excl_fp)) if (excl_tn + excl_fp) > 0 else None
    print(f"Specificity: {specificity} (Expected: None / Undefined, since denominator TN + FP = 0)")
    
    # Save audit data
    audit_file = Path("artifacts/reports/evaluation/calibration_audit_v120.json")
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump({
            "validation_fitted_parameters": {
                "platt_logits": {"slope": slope_l, "intercept": intercept_l},
                "temperature": {"T": temp_T},
                "platt_probs": {"slope": slope_p, "intercept": intercept_p},
            },
            "test_calibration_comparison": eval_audit_results,
            "excluded_test_metrics": {
                "sample_count": 69,
                "confusion_matrix": {"tp": excl_tp, "fn": excl_fn, "tn": excl_tn, "fp": excl_fp},
                "recall": round(excl_tp / max(1, excl_tp + excl_fn), 4),
                "specificity": None,
                "specificity_note": "Mathematically undefined: 0 negative ground truth samples exist in the excluded set",
            },
        }, f, indent=2)
    logger.info("Saved calibration audit: %s", audit_file)
    
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
