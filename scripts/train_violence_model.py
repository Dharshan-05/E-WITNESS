"""PyTorch video classification model training pipeline with AMP on NVIDIA RTX 4050 (Phase 64 & Task P1.2).

Enforces:
1. ResNet3D-18 (R3D-18) video classification backbone fine-tuned for binary violence detection.
2. Hardware optimization for 6 GB VRAM (RTX 4050 Laptop GPU):
   - Automatic Mixed Precision (torch.amp.autocast('cuda') with FP16).
   - Default micro-batch size 4 with 4-step gradient accumulation (effective batch size 16).
   - 16-frame uniform temporal sampling at 112x112 resolution.
   - Full CPU fallback support when CUDA is not present.
3. Cryptographic provenance and complete checkpoint metadata:
   - Saves epoch, optimizer state, model version, random seed, class mapping, hyperparameters, manifest SHA-256.
   - Computes SHA-256 digest of trained weights file and writes governance metadata JSON.
4. Safe error handling for incomplete batches, small batches, and corrupted video frames.
5. Strict partition discipline: Only train and val splits are accessed. Test split is NEVER touched.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision.models.video as video_models
from torch.utils.data import DataLoader, Dataset

# Import governance functions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_services.violence_detection.augmentation import (
    VideoAugmentationConfig,
    VideoAugmentationPipeline,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_violence_model")

# Standard Kinetics-400 video normalization constants
KINETICS_MEAN = np.array([0.43216, 0.394666, 0.37645], dtype=np.float32)
KINETICS_STD = np.array([0.22803, 0.22145, 0.216989], dtype=np.float32)
CLASS_MAPPING = {0: "non_violence", 1: "violence"}


def set_seed(seed: int = 42) -> None:
    """Set deterministic seeds across random, numpy, and torch."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class ViolenceVideoDataset(Dataset):
    """PyTorch Dataset loading uniform 16-frame clips from manifest with safe decode fallback."""

    def __init__(
        self,
        base_dir: Path,
        items: list[dict[str, Any]],
        num_frames: int = 16,
        target_resolution: tuple[int, int] = (112, 112),
        is_synthetic: bool = False,
        augmentation_pipeline: VideoAugmentationPipeline | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.items = items
        self.num_frames = num_frames
        self.target_resolution = target_resolution
        self.is_synthetic = is_synthetic
        self.augmentation_pipeline = augmentation_pipeline

    def __len__(self) -> int:
        return len(self.items)

    def _load_video_frames(self, video_path: Path) -> np.ndarray:
        """Extract num_frames uniformly sampled frames from video."""
        if not video_path.is_file():
            logger.warning("Video file missing: %s. Using zero tensor fallback.", video_path)
            return np.zeros((self.num_frames, self.target_resolution[1], self.target_resolution[0], 3), dtype=np.float32)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Cannot open video: %s. Using zero tensor fallback.", video_path)
            return np.zeros((self.num_frames, self.target_resolution[1], self.target_resolution[0], 3), dtype=np.float32)

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            total_frames = self.num_frames

        # Uniform sampling indices
        indices = np.linspace(0, max(0, total_frames - 1), self.num_frames, dtype=int)
        frames_list: list[np.ndarray] = []

        current_frame_idx = 0
        for target_idx in indices:
            while current_frame_idx < target_idx:
                cap.grab()
                current_frame_idx += 1
            ret, frame = cap.read()
            current_frame_idx += 1
            if ret and frame is not None:
                resized = cv2.resize(frame, self.target_resolution, interpolation=cv2.INTER_LINEAR)
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                frames_list.append(rgb)
            else:
                if frames_list:
                    frames_list.append(frames_list[-1].copy())
                else:
                    frames_list.append(np.zeros((self.target_resolution[1], self.target_resolution[0], 3), dtype=np.float32))

        cap.release()
        return np.array(frames_list, dtype=np.float32)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        item = self.items[idx]
        label = int(item.get("label", 0))

        if self.is_synthetic:
            # Deterministic synthetic video tensor (T, H, W, C)
            frames = np.random.uniform(0.0, 1.0, (self.num_frames, self.target_resolution[1], self.target_resolution[0], 3)).astype(np.float32)
        else:
            rel_path = item["path"]
            full_path = self.base_dir / rel_path
            frames = self._load_video_frames(full_path)

        # Apply label-preserving temporal augmentation if configured
        if self.augmentation_pipeline is not None:
            frames = self.augmentation_pipeline.augment(frames)

        # Normalize: (frames - mean) / std
        normalized = (frames - KINETICS_MEAN) / KINETICS_STD
        # Transpose from (T, H, W, C) to PyTorch video format (C, T, H, W)
        tensor = torch.from_numpy(normalized).permute(3, 0, 1, 2)
        return tensor, label


def build_r3d_18_model(num_classes: int = 2, pretrained: bool = True) -> nn.Module:
    """Instantiate R3D-18 backbone with a binary classification head."""
    if pretrained:
        try:
            weights = video_models.R3D_18_Weights.DEFAULT
            model = video_models.r3d_18(weights=weights)
            logger.info("Loaded pretrained R3D-18 backbone with Kinetics-400 weights.")
        except Exception as exc:
            logger.warning("Could not download weights (%s), initializing backbone from scratch.", exc)
            model = video_models.r3d_18(weights=None)
    else:
        model = video_models.r3d_18(weights=None)

    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)
    return model


def compute_file_sha256(path: Path) -> str:
    """Calculate cryptographic SHA-256 digest of saved model weights."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def train_model(
    manifest_path: Path,
    data_dir: Path,
    output_dir: Path,
    model_name: str = "violence-r3d18",
    model_version: str = "1.0.0",
    epochs: int = 5,
    micro_batch_size: int = 4,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 1e-4,
    seed: int = 42,
    use_synthetic: bool = False,
    smoke_test_limit: int | None = None,
    device_str: str | None = None,
    resume_from: Path | str | None = None,
    use_class_weights: bool = True,
    label_smoothing: float = 0.05,
    allow_unverified_dataset: bool = False,
    authorized_subset_only: bool = False,
    augmentation_config: VideoAugmentationConfig | None = None,
) -> Path:
    """Execute model training loop with AMP and save verified checkpoint."""
    set_seed(seed)
    device = torch.device(device_str if device_str else ("cuda" if torch.cuda.is_available() else "cpu"))
    logger.info("Using device: %s (%s)", device, torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU")

    output_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(output_dir / "training.log", mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    # Governance check: Withhold multi-epoch training on full unapproved dataset
    if epochs > 1 and not use_synthetic and not smoke_test_limit and not allow_unverified_dataset:
        if not authorized_subset_only:
            logger.error(
                "TRAINING HALTED: Multi-epoch training on full unapproved dataset is blocked by AI Governance policy. "
                "Manifest '%s' contains assets with unresolved rights (MovieFights, HockeyFight). "
                "To train on the authorized academic surveillance subset, set --authorized-subset-only. "
                "To override with explicit governance authorization, pass --allow-unverified-dataset.",
                manifest_path,
            )
            logger.removeHandler(file_handler)
            file_handler.close()
            raise PermissionError(
                f"Multi-epoch training halted: dataset '{manifest_path}' contains unapproved third-party assets."
            )
        logger.info(
            "GOVERNANCE CLEARANCE: Training authorized for experimental model v%s "
            "on authorized academic surveillance subset. MovieFights and HockeyFight are strictly purged. Not for production deployment.",
            model_version,
        )

    manifest_sha256 = "synthetic-manifest-sha256"
    if use_synthetic or not manifest_path.exists():
        logger.info("Running in software synthetic smoke-test mode (not evidence of real accuracy)...")
        train_items = [{"label": i % 2, "path": f"syn_{i}.mp4"} for i in range(16)]
        val_items = [{"label": i % 2, "path": f"syn_val_{i}.mp4"} for i in range(8)]
    else:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)
        manifest_sha256 = manifest_data.get("manifest_sha256", "unknown")
        items = manifest_data.get("items", [])
        # Strictly partition: ONLY train and val splits are used for training
        train_items = [it for it in items if it.get("split") == "train"]
        val_items = [it for it in items if it.get("split") == "val"]

        # Strict partition guard: test items must never be present in train or val sets
        if any(it.get("split") == "test" for it in train_items):
            raise RuntimeError("CRITICAL: Test split found in train_items!")
        if any(it.get("split") == "test" for it in val_items):
            raise RuntimeError("CRITICAL: Test split found in val_items!")

        if authorized_subset_only:
            before_train = len(train_items)
            before_val = len(val_items)
            train_items = [
                it for it in train_items
                if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
            ]
            val_items = [
                it for it in val_items
                if "moviefights" not in it["path"].lower() and "hockeyfight" not in it["path"].lower()
            ]
            logger.info(
                "Authorized subset filtering enabled: excluded MovieFights and HockeyFight. "
                "Train: %d -> %d (%d excluded), Val: %d -> %d (%d excluded)",
                before_train, len(train_items), before_train - len(train_items),
                before_val, len(val_items), before_val - len(val_items),
            )

        if smoke_test_limit:
            half_train = max(1, smoke_test_limit // 2)
            train_c0 = [it for it in train_items if it.get("label") == 0][:half_train]
            train_c1 = [it for it in train_items if it.get("label") == 1][:half_train]
            train_items = train_c0 + train_c1

            half_val = max(1, (smoke_test_limit // 4) or 1)
            val_c0 = [it for it in val_items if it.get("label") == 0][:half_val]
            val_c1 = [it for it in val_items if it.get("label") == 1][:half_val]
            val_items = val_c0 + val_c1
            logger.info(
                "Smoke test: Stratified train to %d (%d non_violence, %d violence) and val to %d (%d non_violence, %d violence)",
                len(train_items),
                len(train_c0),
                len(train_c1),
                len(val_items),
                len(val_c0),
                len(val_c1),
            )

    logger.info("Train items: %d, Validation items: %d", len(train_items), len(val_items))

    aug_pipe = VideoAugmentationPipeline(augmentation_config) if (augmentation_config and augmentation_config.enabled) else None
    if aug_pipe is not None:
        logger.info("Training data augmentation ENABLED: %s", augmentation_config.to_dict())
    else:
        logger.info("Training data augmentation DISABLED (clean frames)")

    train_dataset = ViolenceVideoDataset(data_dir, train_items, is_synthetic=use_synthetic, augmentation_pipeline=aug_pipe)
    val_dataset = ViolenceVideoDataset(data_dir, val_items, is_synthetic=use_synthetic, augmentation_pipeline=None)

    train_loader = DataLoader(
        train_dataset,
        batch_size=micro_batch_size,
        shuffle=True,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=micro_batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )

    model = build_r3d_18_model(num_classes=2, pretrained=(not use_synthetic and resume_from is None))
    model.to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)

    start_epoch = 1
    if resume_from:
        resume_path = Path(resume_from)
        if not resume_path.is_file():
            raise FileNotFoundError(f"Resume checkpoint not found: {resume_path}")
        logger.info("Resuming training from checkpoint: %s", resume_path)
        ckpt_data = torch.load(resume_path, map_location=device, weights_only=False)
        if "model_state_dict" in ckpt_data:
            model.load_state_dict(ckpt_data["model_state_dict"])
            logger.info("Loaded model_state_dict from %s", resume_path)
        elif isinstance(ckpt_data, dict):
            model.load_state_dict(ckpt_data)
            logger.info("Loaded raw state dict from %s", resume_path)

        if isinstance(ckpt_data, dict) and "optimizer_state_dict" in ckpt_data:
            try:
                optimizer.load_state_dict(ckpt_data["optimizer_state_dict"])
                logger.info("Loaded optimizer_state_dict from %s", resume_path)
            except Exception as exc:
                logger.warning("Could not load optimizer state (continuing with fresh optimizer): %s", exc)

        if isinstance(ckpt_data, dict) and "epoch" in ckpt_data:
            start_epoch = int(ckpt_data["epoch"]) + 1
            logger.info("Resuming from epoch %d (next epoch will be %d)", ckpt_data["epoch"], start_epoch)

    # Balanced class weights calculation: w_c = N / (2 * N_c)
    weights_tensor = None
    if use_class_weights and train_items:
        c0 = sum(1 for it in train_items if it.get("label") == 0)
        c1 = sum(1 for it in train_items if it.get("label") == 1)
        total_train = len(train_items)
        if c0 > 0 and c1 > 0:
            w0 = total_train / (2.0 * c0)
            w1 = total_train / (2.0 * c1)
            weights_tensor = torch.tensor([w0, w1], dtype=torch.float32, device=device)
            logger.info("Dynamic class weighting enabled: class 0 (non_violence)=%.4f, class 1 (violence)=%.4f", w0, w1)

    criterion = nn.CrossEntropyLoss(weight=weights_tensor, label_smoothing=label_smoothing)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, epochs))
    scaler = torch.amp.GradScaler('cuda', enabled=(device.type == "cuda"))

    best_val_loss = float("inf")
    best_val_acc = 0.0
    best_val_f1 = 0.0
    best_epoch = start_epoch
    checkpoint_file = output_dir / f"{model_name}-v{model_version}.pt"

    start_time = time.time()
    training_history: list[dict[str, Any]] = []

    end_epoch = start_epoch + epochs - 1 if resume_from else epochs
    for epoch in range(start_epoch, end_epoch + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0

        optimizer.zero_grad()

        for step, (inputs, targets) in enumerate(train_loader, start=1):
            inputs = inputs.to(device)
            targets = targets.to(device)

            with torch.amp.autocast('cuda', enabled=(device.type == "cuda")):
                outputs = model(inputs)
                loss = criterion(outputs, targets)
                loss = loss / gradient_accumulation_steps

            scaler.scale(loss).backward()

            if step % gradient_accumulation_steps == 0 or step == len(train_loader):
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad()

            running_loss += loss.item() * gradient_accumulation_steps * targets.size(0)
            preds = torch.argmax(outputs, dim=1)
            correct += (preds == targets).sum().item()
            total += targets.size(0)

        scheduler.step()
        train_loss = running_loss / max(1, total)
        train_acc = correct / max(1, total)

        # Validation loop
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        all_targets: list[int] = []
        all_preds: list[int] = []

        with torch.no_grad():
            for inputs, targets in val_loader:
                inputs = inputs.to(device)
                targets = targets.to(device)

                with torch.amp.autocast('cuda', enabled=(device.type == "cuda")):
                    outputs = model(inputs)
                    loss = criterion(outputs, targets)

                val_loss += loss.item() * targets.size(0)
                preds = torch.argmax(outputs, dim=1)
                val_correct += (preds == targets).sum().item()
                val_total += targets.size(0)
                all_targets.extend(targets.cpu().numpy().tolist())
                all_preds.extend(preds.cpu().numpy().tolist())

        epoch_val_loss = val_loss / max(1, val_total)
        epoch_val_acc = val_correct / max(1, val_total)

        tp = sum(1 for p, t in zip(all_preds, all_targets, strict=False) if p == 1 and t == 1)
        fp = sum(1 for p, t in zip(all_preds, all_targets, strict=False) if p == 1 and t == 0)
        tn = sum(1 for p, t in zip(all_preds, all_targets, strict=False) if p == 0 and t == 0)
        fn = sum(1 for p, t in zip(all_preds, all_targets, strict=False) if p == 0 and t == 1)

        val_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        val_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        val_specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        val_f1 = (2.0 * val_precision * val_recall) / (val_precision + val_recall) if (val_precision + val_recall) > 0 else 0.0

        logger.info(
            "Epoch [%d/%d] - Train Loss: %.4f, Train Acc: %.2f%% | Val Loss: %.4f, Val Acc: %.2f%% | "
            "Precision: %.2f%%, Recall: %.2f%%, Specificity: %.2f%%, F1: %.4f | CM: [TN=%d, FP=%d, FN=%d, TP=%d]",
            epoch,
            end_epoch,
            train_loss,
            train_acc * 100.0,
            epoch_val_loss,
            epoch_val_acc * 100.0,
            val_precision * 100.0,
            val_recall * 100.0,
            val_specificity * 100.0,
            val_f1,
            tn, fp, fn, tp,
        )

        training_history.append({
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "train_accuracy": round(train_acc, 4),
            "val_loss": round(epoch_val_loss, 4),
            "val_accuracy": round(epoch_val_acc, 4),
            "val_precision": round(val_precision, 4),
            "val_recall": round(val_recall, 4),
            "val_specificity": round(val_specificity, 4),
            "val_f1": round(val_f1, 4),
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        })

        if epoch_val_loss < best_val_loss:
            best_val_loss = epoch_val_loss
            best_val_acc = epoch_val_acc
            best_val_f1 = val_f1
            best_epoch = epoch
            tmp_checkpoint = checkpoint_file.with_suffix(".pt.tmp")
            ckpt_payload = {
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "model_name": model_name,
                "model_version": model_version,
                "random_seed": seed,
                "best_val_loss": best_val_loss,
                "best_val_acc": best_val_acc,
                "best_val_f1": best_val_f1,
                "manifest_sha256": manifest_sha256,
                "class_mapping": CLASS_MAPPING,
                "hyperparameters": {
                    "epochs": epochs,
                    "start_epoch": start_epoch,
                    "end_epoch": end_epoch,
                    "micro_batch_size": micro_batch_size,
                    "gradient_accumulation_steps": gradient_accumulation_steps,
                    "effective_batch_size": micro_batch_size * gradient_accumulation_steps,
                    "learning_rate": learning_rate,
                    "resolution": [112, 112],
                    "num_frames": 16,
                },
            }
            buf = io.BytesIO()
            torch.save(ckpt_payload, buf)
            tmp_checkpoint.write_bytes(buf.getvalue())
            for _ in range(5):
                try:
                    tmp_checkpoint.replace(checkpoint_file)
                    break
                except PermissionError:
                    time.sleep(0.1)

    elapsed = time.time() - start_time
    logger.info("Training complete in %.2f seconds. Best Val Acc: %.2f%%", elapsed, best_val_acc * 100.0)

    # Compute SHA-256 weight hash and write governance metadata JSON
    weight_sha256 = compute_file_sha256(checkpoint_file)
    metadata_file = output_dir / f"{model_name}-v{model_version}.json"

    metadata = {
        "model_name": model_name,
        "model_version": model_version,
        "weight_sha256": weight_sha256,
        "manifest_sha256": manifest_sha256,
        "architecture": "r3d_18",
        "input_frames": 16,
        "resolution": [112, 112],
        "class_mapping": CLASS_MAPPING,
        "random_seed": seed,
        "resumed_from": str(resume_from) if resume_from else None,
        "class_weights": [round(float(w), 4) for w in weights_tensor.tolist()] if weights_tensor is not None else None,
        "label_smoothing": label_smoothing,
        "start_time": datetime.fromtimestamp(start_time, tz=UTC).isoformat(),
        "end_time": datetime.now(UTC).isoformat(),
        "hyperparameters": {
            "epochs": epochs,
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "micro_batch_size": micro_batch_size,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "effective_batch_size": micro_batch_size * gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "label_smoothing": label_smoothing,
            "use_class_weights": use_class_weights,
            "augmentation": augmentation_config.to_dict() if (augmentation_config and augmentation_config.enabled) else {"enabled": False},
        },
        "metrics": {
            "best_epoch": best_epoch,
            "best_val_loss": round(best_val_loss, 4),
            "best_val_accuracy": round(best_val_acc, 4),
            "best_val_f1": round(best_val_f1, 4),
            "training_time_seconds": round(elapsed, 2),
        },
        "training_history": training_history,
        "device_used": str(device),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "saved_checkpoint": str(checkpoint_file.name),
        "evaluation_note": "Smoke-test checkpoint only" if (use_synthetic or smoke_test_limit) else "Full training checkpoint",
    }

    tmp_metadata = metadata_file.with_suffix(".json.tmp")
    with open(tmp_metadata, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    tmp_metadata.replace(metadata_file)

    logger.info("Saved model metadata: %s", metadata_file)
    logger.info("Model SHA-256 Hash: %s", weight_sha256)

    logger.removeHandler(file_handler)
    file_handler.close()

    del model, optimizer, scheduler, scaler
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return checkpoint_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Train R3D-18 violence detection model.")
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/models"))
    parser.add_argument("--model-name", type=str, default="violence-r3d18")
    parser.add_argument("--version", type=str, default="1.0.0")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--accum-steps", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", type=str, default=None, help="Device to use ('cuda', 'cpu')")
    parser.add_argument("--synthetic-test", action="store_true", help="Run 1 epoch with synthetic data to verify pipeline")
    parser.add_argument("--smoke-test-limit", type=int, default=None, help="Limit number of real samples for rapid smoke testing")
    parser.add_argument("--resume-from", type=Path, default=None, help="Path to checkpoint to resume training from")
    parser.add_argument("--no-class-weights", action="store_true", help="Disable dynamic balanced class weighting")
    parser.add_argument("--label-smoothing", type=float, default=0.05, help="Label smoothing epsilon for CrossEntropyLoss")
    parser.add_argument("--allow-unverified-dataset", action="store_true", help="Override governance gate to allow multi-epoch training on unverified datasets")
    parser.add_argument("--authorized-subset-only", action="store_true", help="Train only on authorized academic surveillance subset (purges MovieFights and HockeyFight)")
    parser.add_argument("--augment", action="store_true", help="Enable label-preserving training augmentations for robustness")
    parser.add_argument("--hflip-prob", type=float, default=0.50, help="Horizontal flip probability")
    parser.add_argument("--brightness-contrast-prob", type=float, default=0.35, help="Brightness & contrast variation probability")
    parser.add_argument("--motion-blur-prob", type=float, default=0.30, help="Motion blur probability")
    parser.add_argument("--spatial-cutout-prob", type=float, default=0.30, help="Spatial cutout probability")
    parser.add_argument("--low-res-prob", type=float, default=0.25, help="Resolution downsampling probability")
    parser.add_argument("--sensor-noise-prob", type=float, default=0.25, help="Sensor noise probability")

    args = parser.parse_args()

    epochs = 1 if (args.synthetic_test or args.smoke_test_limit) else args.epochs

    train_model(
        manifest_path=args.manifest,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        model_name=args.model_name,
        model_version=args.version,
        epochs=epochs,
        micro_batch_size=args.batch_size,
        gradient_accumulation_steps=args.accum_steps,
        learning_rate=args.lr,
        seed=args.seed,
        use_synthetic=args.synthetic_test,
        smoke_test_limit=args.smoke_test_limit,
        device_str=args.device,
        resume_from=args.resume_from,
        use_class_weights=not args.no_class_weights,
        label_smoothing=args.label_smoothing,
        allow_unverified_dataset=args.allow_unverified_dataset,
        authorized_subset_only=args.authorized_subset_only,
        augmentation_config=VideoAugmentationConfig(
            enabled=args.augment,
            horizontal_flip_prob=args.hflip_prob,
            brightness_contrast_prob=args.brightness_contrast_prob,
            motion_blur_prob=args.motion_blur_prob,
            spatial_cutout_prob=args.spatial_cutout_prob,
            low_res_prob=args.low_res_prob,
            sensor_noise_prob=args.sensor_noise_prob,
            seed=args.seed,
        ) if args.augment else None,
    )


if __name__ == "__main__":
    main()
    import os
    os._exit(0)
