import hashlib
import json
import os
import sys
from pathlib import Path
import numpy as np
import torch
from torchvision.models.video import r3d_18

def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()

def main():
    print("=== PHASE 1: CHECKPOINT VERIFICATION FOR v1.2.0 ===")
    
    # 1. Existence check
    v120_ckpt_path = Path("artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.pt")
    v120_meta_path = Path("artifacts/models/experimental/v1.2.0/violence-r3d18-experiment-v1.2.0.json")
    v120_log_path = Path("artifacts/models/experimental/v1.2.0/training.log")
    
    v100_ckpt_path = Path("artifacts/models/violence-r3d18-v1.0.0.pt")
    v110_ckpt_path = Path("artifacts/models/experimental/violence-r3d18-experiment-v1.1.0.pt")
    
    for p in [v120_ckpt_path, v120_meta_path, v120_log_path, v100_ckpt_path, v110_ckpt_path]:
        assert p.is_file(), f"Missing file: {p}"
        print(f"[EXISTS] {p} ({p.stat().st_size:,} bytes)")
        
    # 2. SHA-256 Recalculation and Comparison
    expected_v100_hash = "e3b4337bea8b98c0a64b13b471d2d174526a31a29e2dbcc07944b6818eab5af9"
    expected_v110_hash = "2d001c4e9700fd113d340a5e643d40f191772ed44874801ce0f2f3cd4ed09ae2"
    
    v120_ckpt_hash = compute_sha256(v120_ckpt_path)
    v120_meta_hash = compute_sha256(v120_meta_path)
    v120_log_hash = compute_sha256(v120_log_path)
    v100_ckpt_hash = compute_sha256(v100_ckpt_path)
    v110_ckpt_hash = compute_sha256(v110_ckpt_path)
    
    print("\n--- Cryptographic Hashes ---")
    print(f"v1.2.0 Checkpoint SHA-256 : {v120_ckpt_hash}")
    print(f"v1.2.0 Metadata SHA-256   : {v120_meta_hash}")
    print(f"v1.2.0 Training Log SHA-256: {v120_log_hash}")
    print(f"v1.0.0 Checkpoint SHA-256 : {v100_ckpt_hash} (Expected: {expected_v100_hash})")
    print(f"v1.1.0 Checkpoint SHA-256 : {v110_ckpt_hash} (Expected: {expected_v110_hash})")
    
    assert v100_ckpt_hash == expected_v100_hash, "v1.0.0 hash mismatch!"
    assert v110_ckpt_hash == expected_v110_hash, "v1.1.0 hash mismatch!"
    print("[PASS] Baseline checkpoints v1.0.0 and v1.1.0 are verified bit-for-bit unchanged.")
    
    # 3. Read metadata and verify consistency
    with open(v120_meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    print(f"\n--- Metadata Validation ---")
    print(f"Model Name        : {meta.get('model_name')}")
    print(f"Model Version     : {meta.get('model_version')}")
    print(f"Weight SHA-256 in Meta: {meta.get('weight_sha256')}")
    assert meta.get("weight_sha256") == v120_ckpt_hash, f"Metadata weight_sha256 {meta.get('weight_sha256')} does not match actual {v120_ckpt_hash}!"
    print("[PASS] Metadata weight_sha256 exactly matches actual checkpoint SHA-256.")
    
    # 4. Strict State-Dict Validation & Weight Sanity
    print("\n--- Loading Checkpoint with Strict Validation ---")
    checkpoint = torch.load(v120_ckpt_path, map_location="cpu", weights_only=False)
    print("Top-level Checkpoint Keys:", list(checkpoint.keys()))
    
    state_dict = checkpoint["model_state_dict"]
    print(f"State dict entries: {len(state_dict)}")
    
    # Build architecture
    model = r3d_18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, 2)
    
    # Strict loading
    load_result = model.load_state_dict(state_dict, strict=True)
    print("[PASS] model.load_state_dict(strict=True) succeeded! Missing keys: [], Unexpected keys: []")
    
    # Check for NaN / Inf in weights
    non_finite_count = 0
    total_params = 0
    for name, param in model.named_parameters():
        total_params += param.numel()
        if not torch.isfinite(param).all():
            print(f"[FAIL] Non-finite weights found in parameter: {name}")
            non_finite_count += 1
    assert non_finite_count == 0, f"Found {non_finite_count} parameters with non-finite values!"
    print(f"[PASS] All {total_params:,} parameters are finite (zero NaN / Inf values).")
    
    # 5. Confirm class mapping, frame sampling, preprocessing
    print("\n--- Preprocessing & Architecture Constants ---")
    print("Checkpoint class_mapping:", checkpoint.get("class_mapping"))
    print("Metadata class_mapping  :", meta.get("class_mapping"))
    assert checkpoint.get("class_mapping") == {0: "non_violence", 1: "violence"}
    assert meta.get("class_mapping") == {"0": "non_violence", "1": "violence"}
    assert meta.get("resolution") == [112, 112]
    assert meta.get("input_frames") == 16
    print("[PASS] Class mapping (int in pt, str in json), resolution (112x112), and frame count (16) verified.")
    
    # Check forward pass
    model.eval()
    dummy_input = torch.randn(1, 3, 16, 112, 112)
    with torch.no_grad():
        out = model(dummy_input)
    assert out.shape == (1, 2)
    print(f"[PASS] Forward pass verified on dummy input: shape={out.shape}, logits={out.numpy().tolist()}")
    
    print("\n=== PHASE 1 VERIFICATION COMPLETE: ALL GATES PASSED ===")
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
