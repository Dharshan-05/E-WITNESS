"""Group-based video dataset ingestion, deduplication, and canonical manifest generation (Phase 62 & Task P1.1).

Enforces:
1. Exact SHA-256 deduplication to eliminate cross-partition data leakage.
2. Verified binary label mapping:
   - Violence (1): Fight, HockeyFight, MovieFights
   - Non-Violence (0): NonFight
   - Rejects or reports ambiguous folder names without inventing labels.
3. Scene grouping where metadata supports it (RWF-2000 YouTube IDs).
4. Explicit disclosure of ungroupable sub-sources (HockeyFight, MovieFights) rather than false leakage-free claims.
5. Partitioning into:
   - train: Preserved from author's train partition (minus cross-split duplicates).
   - val: 50% of author's val partition (used for checkpoint selection and Platt calibration).
   - test: 50% of author's val partition (isolated held-out test set).
6. Deterministic canonical manifest SHA-256 calculation via `compute_manifest_sha256()`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

import cv2
from sklearn.model_selection import GroupShuffleSplit

# Import governance functions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.app.core.ai import compute_manifest_sha256

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_dataset")

CONFIRMED_VIOLENCE_CLASSES = frozenset({"fight", "hockeyfight", "moviefights"})
CONFIRMED_NON_VIOLENCE_CLASSES = frozenset({"nonfight"})
SUPPORTED_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})


def compute_file_sha256(file_path: Path) -> str:
    """Calculate cryptographic SHA-256 digest of a video file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


CLASS_PREFIX_BLOCKLIST = frozenset(
    {"V", "NV", "F", "NF", "FIGHT", "NONFIGHT", "VIOLENCE", "NONVIOLENCE", "FI", "POS", "NEG", "REG"}
)


def extract_scene_group_id(file_name: str, folder_name: str) -> tuple[str, str]:
    """Extract scene grouping identifier and confidence level.

    Returns:
        tuple of (group_id, grouping_confidence)
        where grouping_confidence is 'scene_prefix_verified' or 'ungroupable_opaque_id'.
    """
    stem = Path(file_name).stem

    # Exclude files ending with _xvid (HockeyFight)
    if stem.lower().endswith("_xvid"):
        return stem, "ungroupable_opaque_id"

    # RWF-2000 surveillance pattern: YouTube video ID + '_' + clip number
    # Example: '_6-B11R9FJM_0.avi' -> video ID '_6-B11R9FJM' (length >= 5)
    # Rejects category abbreviations ('V', 'NV', 'Fight') and short index prefixes
    if "_" in stem:
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            prefix = parts[0]
            if len(prefix) >= 5 and prefix.upper() not in CLASS_PREFIX_BLOCKLIST:
                return prefix, "scene_prefix_verified"

    # Numbered stems, class prefixes, or files lacking verifiable source metadata
    return stem, "ungroupable_opaque_id"


def map_folder_to_label(folder_name: str) -> tuple[str, int]:
    """Strictly map confirmed folder name to category and integer label.

    Raises ValueError if folder name is unknown or ambiguous.
    """
    clean = folder_name.strip().lower()
    if clean in CONFIRMED_NON_VIOLENCE_CLASSES:
        return "non_violence", 0
    if clean in CONFIRMED_VIOLENCE_CLASSES:
        return "violence", 1
    raise ValueError(f"Ambiguous or unconfirmed class folder: '{folder_name}'. Cannot safely invent label.")


def prepare_dataset_splits(
    input_dir: Path,
    output_manifest: Path,
    dataset_name: str = "yash07yadav-violence-detection-combined",
    dataset_version: str = "1.0.0",
    val_test_split_ratio: float = 0.50,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Scan dataset, deduplicate, group by scene where verified, generate canonical manifest."""
    logger.info("Scanning dataset in %s", input_dir)
    video_files = [
        p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not video_files:
        raise ValueError(f"No video files found in {input_dir}")

    logger.info("Found %d video files. Extracting metadata and computing hashes...", len(video_files))

    raw_by_hash: dict[str, dict[str, Any]] = {}
    duplicates_detected: list[dict[str, Any]] = []
    ungroupable_count = 0
    grouped_count = 0

    for idx, fpath in enumerate(video_files, start=1):
        if idx % 500 == 0 or idx == len(video_files):
            logger.info("Processed %d/%d video files...", idx, len(video_files))

        rel_path = str(fpath.relative_to(input_dir)).replace("\\", "/")
        parts = fpath.relative_to(input_dir).parts

        # Detect author partition (train or val)
        author_partition = "train"
        for part in parts:
            if part.lower() in {"train", "val"}:
                author_partition = part.lower()
                break

        class_folder = fpath.parent.name
        try:
            category, label = map_folder_to_label(class_folder)
        except ValueError as exc:
            logger.error("Skipping file %s: %s", rel_path, exc)
            continue

        file_sha256 = compute_file_sha256(fpath)
        group_id, group_conf = extract_scene_group_id(fpath.name, class_folder)

        if group_conf == "scene_prefix_verified":
            grouped_count += 1
        else:
            ungroupable_count += 1

        # Check for cross-partition duplicate files (exact SHA-256 collision)
        if file_sha256 in raw_by_hash:
            existing = raw_by_hash[file_sha256]
            duplicates_detected.append(
                {
                    "sha256": file_sha256,
                    "first_seen_path": existing["path"],
                    "first_seen_partition": existing["author_partition"],
                    "duplicate_path": rel_path,
                    "duplicate_partition": author_partition,
                }
            )
            # If the duplicate appears in val but was already registered in train, skip adding it to val
            if existing["author_partition"] == "train" and author_partition == "val":
                logger.warning(
                    "Cross-split duplicate detected and removed: %s (in val) matches %s (in train)",
                    rel_path,
                    existing["path"],
                )
                continue

        cap = cv2.VideoCapture(str(fpath))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) if cap.isOpened() else 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap.isOpened() else 0
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if cap.isOpened() else 0
        duration = float(frame_count) / fps if fps > 0 else 0.0
        cap.release()

        raw_by_hash[file_sha256] = {
            "path": rel_path,
            "sha256": file_sha256,
            "class_name": category,
            "raw_class_folder": class_folder,
            "label": label,
            "group_id": group_id,
            "grouping_confidence": group_conf,
            "author_partition": author_partition,
            "duration_seconds": round(duration, 2),
            "frame_count": frame_count,
            "fps": round(fps, 2),
            "width": width,
            "height": height,
            "size_bytes": fpath.stat().st_size,
        }

    all_items = list(raw_by_hash.values())
    logger.info("Total unique videos after exact deduplication: %d", len(all_items))
    logger.info("Duplicates detected and resolved: %d", len(duplicates_detected))

    # Split Strategy:
    # 1. train partition: all items where author_partition == 'train'
    # 2. val partition: author_partition == 'val' split into val (50%) and test (50%)
    # Using GroupShuffleSplit on val items using group_id to ensure clips from same video stay together
    train_items: list[dict[str, Any]] = []
    val_pool_items: list[dict[str, Any]] = []

    for it in all_items:
        if it["author_partition"] == "train":
            it_copy = dict(it)
            it_copy["split"] = "train"
            train_items.append(it_copy)
        else:
            val_pool_items.append(it)

    val_groups = [it["group_id"] for it in val_pool_items]
    val_labels = [it["label"] for it in val_pool_items]

    gss = GroupShuffleSplit(n_splits=1, train_size=val_test_split_ratio, random_state=random_seed)
    val_sub_idx, test_sub_idx = next(gss.split(val_pool_items, val_labels, groups=val_groups))

    val_items: list[dict[str, Any]] = []
    test_items: list[dict[str, Any]] = []

    for i in val_sub_idx:
        it_copy = dict(val_pool_items[i])
        it_copy["split"] = "val"
        val_items.append(it_copy)

    for i in test_sub_idx:
        it_copy = dict(val_pool_items[i])
        it_copy["split"] = "test"
        test_items.append(it_copy)

    manifest_items = train_items + val_items + test_items

    # Verify no SHA256 hashes cross partitions
    train_hashes = {it["sha256"] for it in train_items}
    val_hashes = {it["sha256"] for it in val_items}
    test_hashes = {it["sha256"] for it in test_items}

    if train_hashes & val_hashes:
        raise ValueError("Critical: Train and Val share identical files!")
    if train_hashes & test_hashes:
        raise ValueError("Critical: Train and Test share identical files!")
    if val_hashes & test_hashes:
        raise ValueError("Critical: Val and Test share identical files!")

    # Verify no scene group_ids cross between val and test
    val_group_set = {it["group_id"] for it in val_items if it["grouping_confidence"] == "scene_prefix_verified"}
    test_group_set = {it["group_id"] for it in test_items if it["grouping_confidence"] == "scene_prefix_verified"}
    leakage_val_test = val_group_set & test_group_set
    if leakage_val_test:
        raise ValueError(f"Leakage between val and test for verified scene groups: {leakage_val_test}")

    # Compute deterministic canonical manifest SHA-256
    manifest_sha256 = compute_manifest_sha256(manifest_items)

    # Statistics
    split_stats = {}
    for sp_name, sp_list in [("train", train_items), ("val", val_items), ("test", test_items)]:
        v_cnt = sum(1 for it in sp_list if it["label"] == 1)
        nv_cnt = sum(1 for it in sp_list if it["label"] == 0)
        split_stats[sp_name] = {
            "total": len(sp_list),
            "violence": v_cnt,
            "non_violence": nv_cnt,
            "unique_groups": len({it["group_id"] for it in sp_list}),
        }

    scene_governance_notes = (
        "Partial scene-level leakage prevention: Clips from RWF-2000 are grouped by YouTube surveillance "
        "video ID prefix. Clips from HockeyFight and MovieFights lack scene metadata in the raw Kaggle "
        "archive and are tracked as ungroupable opaque IDs. Exact SHA-256 duplicates across train/val "
        "have been purged from validation and test."
    )

    manifest = {
        "dataset_name": dataset_name,
        "version": dataset_version,
        "manifest_sha256": manifest_sha256,
        "total_items": len(manifest_items),
        "total_deduplicated_cross_split_files": len(duplicates_detected),
        "scene_grouping_audit": {
            "verified_scene_prefix_clips": grouped_count,
            "ungroupable_opaque_clips": ungroupable_count,
            "governance_note": scene_governance_notes,
        },
        "split_stats": split_stats,
        "duplicates_purged": duplicates_detected,
        "items": manifest_items,
    }

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Manifest generated successfully: %s", output_manifest)
    logger.info("Manifest SHA-256 Digest: %s", manifest_sha256)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare dataset and generate canonical manifest.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to raw dataset directory",
    )
    parser.add_argument(
        "--output-manifest",
        type=Path,
        default=Path("data/manifest.json"),
        help="Path to output manifest JSON file",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="yash07yadav-violence-detection-combined",
        help="Dataset name identifier",
    )
    parser.add_argument(
        "--version",
        type=str,
        default="1.0.0",
        help="Dataset semantic version",
    )

    args = parser.parse_args()

    try:
        manifest = prepare_dataset_splits(
            args.input_dir,
            args.output_manifest,
            dataset_name=args.dataset_name,
            dataset_version=args.version,
        )
        print("\n" + "=" * 65)
        print("         E-WITNESS DATASET MANIFEST GENERATED")
        print("=" * 65)
        print(f"Dataset:            {manifest['dataset_name']} (v{manifest['version']})")
        print(f"Manifest SHA256:    {manifest['manifest_sha256']}")
        print(f"Total Videos:       {manifest['total_items']}")
        print(f"Purged Duplicates:  {manifest['total_deduplicated_cross_split_files']}")
        print("\nPartitions:")
        for sp, stats in manifest["split_stats"].items():
            print(
                f"  - {sp:12s}: {stats['total']:5d} items "
                f"({stats['violence']} violent, {stats['non_violence']} non-violent, {stats['unique_groups']} groups)"
            )
        print("\nScene Grouping Audit:")
        print(f"  * Verified Scene Prefix: {manifest['scene_grouping_audit']['verified_scene_prefix_clips']} clips")
        print(f"  * Ungroupable Opaque:    {manifest['scene_grouping_audit']['ungroupable_opaque_clips']} clips")
        print(f"  * Advisory: {manifest['scene_grouping_audit']['governance_note']}")
        print("=" * 65 + "\n")
    except Exception as exc:
        logger.error("Failed to prepare dataset: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
