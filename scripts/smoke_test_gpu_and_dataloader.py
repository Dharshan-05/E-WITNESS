"""GPU and DataLoader smoke test for E-WITNESS violence detection pipeline.

Verifies:
1. CUDA device accessibility (RTX 4050).
2. Video frame loading & uniform 16-frame temporal sampling at 112x112.
3. Label validity (only 0 and 1).
4. Forward pass through R3D-18 with AMP autocast (FP16).
5. Loss calculation (strictly finite, no NaN, no Inf).
6. Backward pass & optimizer step with GradScaler.
7. VRAM usage and headroom on 6 GB GPU.
8. Atomic checkpoint serialization and SHA-256 computation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.train_violence_model import ViolenceVideoDataset, build_r3d_18_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_test")


def run_smoke_test(manifest_path: Path, data_dir: Path) -> dict[str, Any]:
    logger.info("=== Starting E-WITNESS GPU & DataLoader Smoke Test ===")

    # 1. Check CUDA
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. GPU smoke test requires an active CUDA device.")

    device = torch.device("cuda")
    gpu_name = torch.cuda.get_device_name(0)
    total_vram_mib = torch.cuda.get_device_properties(0).total_memory / (1024**2)
    logger.info("CUDA Device: %s (Total VRAM: %.1f MiB)", gpu_name, total_vram_mib)

    # 2. Check Manifest
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = json.load(f)

    items = manifest_data.get("items", [])
    train_items = [it for it in items if it.get("split") == "train"]
    val_items = [it for it in items if it.get("split") == "val"]

    # Filter to authorized subset
    authorized_train = [
        it for it in train_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]
    authorized_val = [
        it for it in val_items
        if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
    ]

    logger.info(
        "Authorized subset: %d train clips, %d val clips (purged MovieFights and HockeyFight)",
        len(authorized_train), len(authorized_val),
    )

    # Sample 8 train clips (4 non_violence, 4 violence) and 4 val clips
    c0_train = [it for it in authorized_train if it.get("label") == 0][:4]
    c1_train = [it for it in authorized_train if it.get("label") == 1][:4]
    sample_train = c0_train + c1_train

    c0_val = [it for it in authorized_val if it.get("label") == 0][:2]
    c1_val = [it for it in authorized_val if it.get("label") == 1][:2]
    sample_val = c0_val + c1_val

    # 3. Verify labels
    all_labels = {it["label"] for it in sample_train + sample_val}
    if not all_labels.issubset({0, 1}):
        raise ValueError(f"Invalid labels detected: {all_labels}")
    logger.info("Labels verified: %s", all_labels)

    # 4. DataLoader
    train_ds = ViolenceVideoDataset(data_dir, sample_train)
    val_ds = ViolenceVideoDataset(data_dir, sample_val)
    train_loader = DataLoader(train_ds, batch_size=4, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=4, shuffle=False)

    # 5. Model initialization
    logger.info("Building R3D-18 model with Kinetics-400 pretrained backbone...")
    model = build_r3d_18_model(num_classes=2, pretrained=True)
    model.to(device)

    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-4)
    scaler = torch.amp.GradScaler('cuda')

    # 6. Train micro-batches with AMP
    model.train()
    torch.cuda.reset_peak_memory_stats()
    train_losses = []

    start_t = time.time()
    for batch_idx, (inputs, targets) in enumerate(train_loader, start=1):
        inputs = inputs.to(device)
        targets = targets.to(device)

        if torch.isnan(inputs).any() or torch.isinf(inputs).any():
            raise ValueError(f"Batch {batch_idx}: Input tensor contains NaN or Inf!")

        optimizer.zero_grad()
        with torch.amp.autocast('cuda'):
            outputs = model(inputs)
            if torch.isnan(outputs).any() or torch.isinf(outputs).any():
                raise ValueError(f"Batch {batch_idx}: Model output contains NaN or Inf!")
            loss = criterion(outputs, targets)

        loss_val = loss.item()
        if torch.isnan(loss).any() or torch.isinf(loss).any():
            raise ValueError(f"Batch {batch_idx}: Loss is NaN or Inf!")

        train_losses.append(loss_val)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()

        preds = torch.argmax(outputs, dim=1)
        logger.info(
            "Smoke Batch %d/2 - Inputs: %s, Loss: %.4f, Targets: %s, Preds: %s",
            batch_idx, tuple(inputs.shape), loss_val, targets.tolist(), preds.tolist(),
        )

    # 7. Validation micro-batch
    model.eval()
    val_losses = []
    with torch.no_grad():
        for inputs, targets in val_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            with torch.amp.autocast('cuda'):
                outputs = model(inputs)
                loss = criterion(outputs, targets)
            val_losses.append(loss.item())

    peak_vram_mib = torch.cuda.max_memory_allocated() / (1024**2)
    elapsed = time.time() - start_t
    logger.info("Forward/Backward pass complete in %.2f seconds.", elapsed)
    logger.info("Peak VRAM Allocated: %.2f MiB / %.1f MiB", peak_vram_mib, total_vram_mib)

    # 8. Checkpoint saving & hash
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_ckpt_path = Path(tmp_dir) / "smoke_checkpoint.pt"
        tmp_target = test_ckpt_path.with_suffix(".pt.tmp")
        torch.save(
            {
                "epoch": 1,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "model_name": "smoke-test",
            },
            tmp_target,
        )
        tmp_target.replace(test_ckpt_path)

        if not test_ckpt_path.is_file():
            raise RuntimeError("Failed to write checkpoint file.")

        hasher = hashlib.sha256()
        with open(test_ckpt_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        size_bytes = test_ckpt_path.stat().st_size
        logger.info("Atomic checkpoint saved successfully: %d bytes, SHA-256: %s", size_bytes, digest)

    del model, optimizer, scaler
    torch.cuda.empty_cache()

    logger.info("=== GPU & DataLoader Smoke Test: PASS ===")
    return {
        "status": "PASS",
        "gpu_name": gpu_name,
        "peak_vram_mib": round(peak_vram_mib, 2),
        "total_vram_mib": round(total_vram_mib, 1),
        "train_losses": [round(val, 4) for val in train_losses],
        "val_losses": [round(val, 4) for val in val_losses],
        "elapsed_seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    manifest = Path("data/manifest.json")
    raw_data = Path("data/raw")
    results = run_smoke_test(manifest, raw_data)
    print("\nRESULTS_JSON:", json.dumps(results, indent=2))
