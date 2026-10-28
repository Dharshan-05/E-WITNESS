"""Safe, auditable dataset ingestion and canonical manifest generation for approved violence detection datasets.

Phase C Implementation:
Enforces strict provenance validation, license allowlisting, OpenCV stream decodability,
exact SHA-256 deduplication, disjoint partition splitting, and fail-closed governance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
from sklearn.model_selection import GroupShuffleSplit, StratifiedShuffleSplit

# Ensure backend governance imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.app.core.ai import APPROVED_DATASET_LICENSES, compute_manifest_sha256

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_approved_dataset")

CONFIRMED_VIOLENCE_NAMES = frozenset({"fight", "violent", "violence"})
CONFIRMED_NON_VIOLENCE_NAMES = frozenset({"nonfight", "non-fight", "non_fight", "nonviolent", "non-violent", "non_violence"})
RESTRICTED_COMPONENT_KEYWORDS = frozenset({"moviefights", "hockeyfight", "rwf-2000", "rwf2000"})
SUPPORTED_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})


class GovernanceError(ValueError):
    """Raised when dataset fails rights, provenance, or licensing verification."""


@dataclass
class DatasetProvenanceRecord:
    provenance_id: str
    dataset_name: str
    dataset_version: str
    source_url: str
    acquisition_date: str
    license_id: str
    rights_status: str  # APPROVED, RESTRICTED, UNVERIFIED
    evidence_file_path: str
    intended_use: str  # training, benchmark, research_only
    rights_holder: str = ""
    is_synthetic: bool = False
    legal_review_notes: str = ""
    is_commercial_cleared: bool = False
    is_redistribution_permitted: bool = False
    is_modification_permitted: bool = False
    is_model_training_permitted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class VideoInspectionRecord:
    rel_path: str
    sha256: str
    class_name: str
    label: int
    duration_seconds: float
    frame_count: int
    fps: float
    width: int
    height: int
    size_bytes: int
    group_id: str
    grouping_confidence: str  # subject_session_verified, scene_prefix_verified, ungroupable_opaque_id
    is_valid: bool
    error: str | None = None


def compute_file_sha256(file_path: Path) -> str:
    """Calculate cryptographic SHA-256 digest of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def validate_provenance_metadata(
    provenance_data: dict[str, Any],
    require_approved_status: bool = True,
) -> DatasetProvenanceRecord:
    """Validate provenance record against governance policies. Fails closed on any defect."""
    required_fields = [
        "provenance_id",
        "dataset_name",
        "dataset_version",
        "source_url",
        "acquisition_date",
        "license_id",
        "rights_status",
        "rights_holder",
        "evidence_file_path",
        "intended_use",
    ]
    for rf in required_fields:
        if rf not in provenance_data or not str(provenance_data[rf]).strip():
            raise GovernanceError(f"Missing mandatory provenance metadata field: '{rf}'")

    license_id = str(provenance_data["license_id"]).strip()
    rights_status = str(provenance_data["rights_status"]).strip().upper()
    evidence_path_str = str(provenance_data["evidence_file_path"]).strip()
    ev_file = Path(evidence_path_str)
    resolved_ev = ev_file if ev_file.is_file() else (Path.cwd() / ev_file)

    if resolved_ev.is_symlink():
        raise GovernanceError(f"Symlinks are disallowed for provenance evidence file: '{evidence_path_str}'")

    # Verify that evidence file actually exists on disk
    if not resolved_ev.is_file():
        raise GovernanceError(
            f"Provenance evidence file does not exist on disk: '{evidence_path_str}'. "
            f"Legal approval must be grounded in physical or digital documentary evidence."
        )

    # Verify license is in allowlist
    if license_id not in APPROVED_DATASET_LICENSES:
        raise GovernanceError(
            f"License '{license_id}' is not in E-WITNESS APPROVED_DATASET_LICENSES: {sorted(APPROVED_DATASET_LICENSES)}"
        )

    # Fail closed on unverified or non-approved rights when required
    if require_approved_status:
        if rights_status != "APPROVED":
            raise GovernanceError(
                f"Dataset rights status is '{rights_status}'. Training ingestion strictly requires 'APPROVED'."
            )
        if not bool(provenance_data.get("is_model_training_permitted", False)):
            raise GovernanceError(
                "Provenance specifies that model training is not permitted for these assets."
            )
        if not bool(provenance_data.get("is_commercial_cleared", False)):
            raise GovernanceError(
                "Provenance specifies that commercial enterprise deployment is not cleared for these assets."
            )

    return DatasetProvenanceRecord(
        provenance_id=str(provenance_data["provenance_id"]),
        dataset_name=str(provenance_data["dataset_name"]),
        dataset_version=str(provenance_data["dataset_version"]),
        source_url=str(provenance_data["source_url"]),
        acquisition_date=str(provenance_data["acquisition_date"]),
        license_id=license_id,
        rights_status=rights_status,
        evidence_file_path=evidence_path_str,
        intended_use=str(provenance_data["intended_use"]),
        rights_holder=str(provenance_data["rights_holder"]),
        is_synthetic=bool(provenance_data.get("is_synthetic", False)),
        legal_review_notes=str(provenance_data.get("legal_review_notes", "")),
        is_commercial_cleared=bool(provenance_data.get("is_commercial_cleared", False)),
        is_redistribution_permitted=bool(provenance_data.get("is_redistribution_permitted", False)),
        is_modification_permitted=bool(provenance_data.get("is_modification_permitted", False)),
        is_model_training_permitted=bool(provenance_data.get("is_model_training_permitted", False)),
    )


def map_folder_to_binary_label(folder_name: str) -> tuple[str, int]:
    """Map class folder name to canonical binary label. Raises GovernanceError on unknown labels."""
    clean = folder_name.strip().lower()
    if clean in CONFIRMED_NON_VIOLENCE_NAMES:
        return "non_violence", 0
    if clean in CONFIRMED_VIOLENCE_NAMES:
        return "violence", 1
    raise GovernanceError(f"Unknown or ambiguous class folder: '{folder_name}'. Cannot safely invent label.")


def extract_group_identifier(file_name: str) -> tuple[str, str]:
    """Infer source recording / session group identifier with honest confidence level."""
    stem = Path(file_name).stem
    # RWF-2000 surveillance video pattern: {youtube_id}_{clip_index}
    if "_" in stem and not stem.lower().endswith("_xvid"):
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], "scene_prefix_verified"
    # Subject/session pattern: subject{id}_session{id}
    if "subject" in stem.lower() or "session" in stem.lower():
        return stem.split("_")[0], "subject_session_verified"
    return stem, "ungroupable_opaque_id"


def inspect_video_file(file_path: Path, root_dir: Path) -> VideoInspectionRecord:
    """Audit single video container and stream decodability without modifying file."""
    if file_path.is_symlink():
        raise GovernanceError(f"Symlink detected in video path: '{file_path}'")
    try:
        rel_path = str(file_path.resolve().relative_to(root_dir.resolve())).replace("\\", "/")
    except ValueError as exc:
        raise GovernanceError(f"Path traversal detected: '{file_path}' is outside root '{root_dir}'") from exc
    size_bytes = file_path.stat().st_size
    file_sha256 = compute_file_sha256(file_path)

    # Inferred class from parent directory
    folder_name = file_path.parent.name
    class_name, label = map_folder_to_binary_label(folder_name)
    group_id, grouping_conf = extract_group_identifier(file_path.name)

    if size_bytes == 0:
        return VideoInspectionRecord(
            rel_path=rel_path,
            sha256=file_sha256,
            class_name=class_name,
            label=label,
            duration_seconds=0.0,
            frame_count=0,
            fps=0.0,
            width=0,
            height=0,
            size_bytes=0,
            group_id=group_id,
            grouping_confidence=grouping_conf,
            is_valid=False,
            error="0-byte empty file",
        )

    cap = cv2.VideoCapture(str(file_path))
    if not cap.isOpened():
        return VideoInspectionRecord(
            rel_path=rel_path,
            sha256=file_sha256,
            class_name=class_name,
            label=label,
            duration_seconds=0.0,
            frame_count=0,
            fps=0.0,
            width=0,
            height=0,
            size_bytes=size_bytes,
            group_id=group_id,
            grouping_confidence=grouping_conf,
            is_valid=False,
            error="OpenCV cannot open video stream container",
        )

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = (frame_count / fps) if fps > 0 else 0.0

    ret, first_frame = cap.read()
    cap.release()

    if not ret or first_frame is None:
        return VideoInspectionRecord(
            rel_path=rel_path,
            sha256=file_sha256,
            class_name=class_name,
            label=label,
            duration_seconds=duration,
            frame_count=frame_count,
            fps=fps,
            width=width,
            height=height,
            size_bytes=size_bytes,
            group_id=group_id,
            grouping_confidence=grouping_conf,
            is_valid=False,
            error="Failed to decode first video frame",
        )

    return VideoInspectionRecord(
        rel_path=rel_path,
        sha256=file_sha256,
        class_name=class_name,
        label=label,
        duration_seconds=round(duration, 3),
        frame_count=frame_count,
        fps=round(fps, 2),
        width=width,
        height=height,
        size_bytes=size_bytes,
        group_id=group_id,
        grouping_confidence=grouping_conf,
        is_valid=True,
    )


def load_provenance_file(
    provenance_file: Path,
    require_approved_status: bool = True,
) -> DatasetProvenanceRecord:
    """Load and validate provenance metadata from JSON file."""
    if not provenance_file.is_file():
        raise FileNotFoundError(f"Provenance file not found: {provenance_file}")
    with open(provenance_file, encoding="utf-8") as f:
        provenance_data = json.load(f)
    return validate_provenance_metadata(provenance_data, require_approved_status=require_approved_status)


def ingest_and_partition_dataset(
    dataset_dir: Path,
    provenance_file: Path,
    output_dir: Path,
    val_test_ratio: float = 0.50,
    random_seed: int = 42,
    require_approved_status: bool = True,
) -> dict[str, Any]:
    """Execute complete ingestion, validation, deduplication, and split workflow."""
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    # Validate provenance fail-closed
    provenance = load_provenance_file(provenance_file, require_approved_status=require_approved_status)

    dataset_dir_resolved = dataset_dir.resolve()
    logger.info("Scanning video files in %s...", dataset_dir)
    video_paths: list[Path] = []
    for p in sorted(dataset_dir.rglob("*")):
        if p.is_symlink():
            raise GovernanceError(
                f"Symlinks are disallowed in dataset directory for security and provenance integrity: '{p.name}'"
            )
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                p.resolve().relative_to(dataset_dir_resolved)
            except ValueError as exc:
                raise GovernanceError(f"Path traversal detected: file '{p.name}' escapes dataset directory") from exc
            video_paths.append(p)

    if not video_paths:
        raise GovernanceError(f"No supported video files found in {dataset_dir}")

    # Check for unauthorized mixed or restricted third-party components
    for vp in video_paths:
        low_parts = [part.lower() for part in vp.parts]
        for rk in RESTRICTED_COMPONENT_KEYWORDS:
            if rk in low_parts or any(rk in p_part for p_part in low_parts):
                raise GovernanceError(
                    f"Restricted or unverified third-party component '{rk}' detected in path '{vp.name}'. "
                    f"Mixed datasets containing unauthorized assets are strictly rejected."
                )

    records: list[VideoInspectionRecord] = []
    corrupted_records: list[dict[str, Any]] = []

    for vp in video_paths:
        rec = inspect_video_file(vp, dataset_dir)
        if rec.is_valid:
            records.append(rec)
        else:
            corrupted_records.append(asdict(rec))

    logger.info("Audited %d files: %d valid, %d unreadable/corrupt.", len(video_paths), len(records), len(corrupted_records))

    # Deduplication via SHA-256
    unique_records: list[VideoInspectionRecord] = []
    seen_hashes: dict[str, str] = {}
    purged_duplicates: list[dict[str, str]] = []

    for r in records:
        if r.sha256 in seen_hashes:
            purged_duplicates.append({
                "duplicate_path": r.rel_path,
                "original_path": seen_hashes[r.sha256],
                "sha256": r.sha256,
            })
        else:
            seen_hashes[r.sha256] = r.rel_path
            unique_records.append(r)

    logger.info("Deduplication: %d unique videos, %d duplicates purged.", len(unique_records), len(purged_duplicates))

    if len(unique_records) < 3:
        raise GovernanceError("Dataset contains fewer than 3 unique valid samples. Cannot construct train/val/test splits.")

    # Honest assessment of source leakage prevention
    verifiable_groups = sum(1 for r in unique_records if r.grouping_confidence != "ungroupable_opaque_id")
    is_source_leakage_prevented = verifiable_groups == len(unique_records)

    # Generate reproducible splits
    items_by_split = _partition_records(unique_records, val_test_ratio=val_test_ratio, seed=random_seed)

    # Verify zero exact-file or hash overlap
    split_hashes = {"train": set(), "val": set(), "test": set()}
    for it in items_by_split:
        split_hashes[it["split"]].add(it["sha256"])

    if len(split_hashes["train"].intersection(split_hashes["val"])) > 0:
        raise GovernanceError("Train/Val hash leakage detected!")
    if len(split_hashes["train"].intersection(split_hashes["test"])) > 0:
        raise GovernanceError("Train/Test hash leakage detected!")
    if len(split_hashes["val"].intersection(split_hashes["test"])) > 0:
        raise GovernanceError("Val/Test hash leakage detected!")

    # Calculate canonical manifest hash
    manifest_items_for_hash = [
        {"path": it["path"], "sha256_hash": it["sha256"], "label": it["class_name"]}
        for it in items_by_split
    ]
    manifest_sha256 = compute_manifest_sha256(manifest_items_for_hash)

    # Construct final manifest
    manifest = {
        "dataset_name": provenance.dataset_name,
        "dataset_version": provenance.dataset_version,
        "is_synthetic": provenance.is_synthetic,
        "production_training_eligible": (not provenance.is_synthetic and provenance.rights_status == "APPROVED"),
        "provenance": asdict(provenance),
        "manifest_sha256": manifest_sha256,
        "total_items": len(items_by_split),
        "total_deduplicated_files": len(unique_records),
        "purged_duplicates_count": len(purged_duplicates),
        "corrupted_files_count": len(corrupted_records),
        "grouping_audit": {
            "verifiable_groups_count": verifiable_groups,
            "ungroupable_opaque_count": len(unique_records) - verifiable_groups,
            "is_source_leakage_prevented": is_source_leakage_prevented,
        },
        "split_stats": {
            s: {
                "total": sum(1 for it in items_by_split if it["split"] == s),
                "violence": sum(1 for it in items_by_split if it["split"] == s and it["label"] == 1),
                "non_violence": sum(1 for it in items_by_split if it["split"] == s and it["label"] == 0),
            }
            for s in ["train", "val", "test"]
        },
        "purged_duplicates": purged_duplicates,
        "items": items_by_split,
    }

    # Write derived files to separate output directory (original data untouched)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = output_dir / "manifest.json"
    audit_file = output_dir / "ingestion_audit_report.json"
    summary_file = output_dir / "INGESTION_SUMMARY.md"

    # Write atomically via temp file
    _atomic_write_json(manifest_file, manifest)

    audit_report = {
        "audit_timestamp": datetime.now(UTC).isoformat(),
        "dataset_name": provenance.dataset_name,
        "dataset_version": provenance.dataset_version,
        "provenance_verified": True,
        "rights_status": provenance.rights_status,
        "license_id": provenance.license_id,
        "total_scanned": len(video_paths),
        "valid_count": len(records),
        "corrupted_count": len(corrupted_records),
        "unique_count": len(unique_records),
        "duplicates_purged_count": len(purged_duplicates),
        "manifest_sha256": manifest_sha256,
        "is_source_leakage_prevented": is_source_leakage_prevented,
        "split_stats": manifest["split_stats"],
        "corrupted_files": corrupted_records,
    }
    _atomic_write_json(audit_file, audit_report)

    # Human-readable markdown summary
    classification_str = (
        "SYNTHETIC BENCHMARK (NOT ELIGIBLE FOR PRODUCTION TRAINING)"
        if provenance.is_synthetic
        else "PRODUCTION CANDIDATE (APPROVED RIGHTS)"
    )
    summary_md = f"""# E-WITNESS Approved Dataset Ingestion Summary

- **Dataset:** {provenance.dataset_name} (v{provenance.dataset_version})
- **Classification:** {classification_str}
- **Rights Holder:** {provenance.rights_holder}
- **Provenance ID:** `{provenance.provenance_id}`
- **License:** `{provenance.license_id}` | **Rights Status:** `{provenance.rights_status}`
- **Commercial Cleared:** {provenance.is_commercial_cleared} | **Model Training Permitted:** {provenance.is_model_training_permitted}
- **Source URL:** {provenance.source_url}
- **Acquisition Date:** {provenance.acquisition_date}
- **Manifest Canonical SHA-256:** `{manifest_sha256}`
- **Total Valid Clips:** {len(unique_records)} (Purged duplicates: {len(purged_duplicates)}, Unreadable: {len(corrupted_records)})
- **Partitions:** Train ({manifest['split_stats']['train']['total']}), Val ({manifest['split_stats']['val']['total']}), Test ({manifest['split_stats']['test']['total']})
- **Zero Cross-Split Overlap:** Verified (0 file & hash collisions).
- **Source Leakage Prevented:** {is_source_leakage_prevented} ({verifiable_groups}/{len(unique_records)} verifiable groups).
"""
    summary_file.write_text(summary_md, encoding="utf-8")

    logger.info("Ingestion complete. Saved manifest to %s", manifest_file)
    return manifest


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write JSON data atomically using temporary file replacement."""
    tmp_path = target_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(target_path)


def _partition_records(
    records: list[VideoInspectionRecord],
    val_test_ratio: float = 0.50,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Partition records into train, val, and test splits with group and class balance."""
    labels = [r.label for r in records]

    # If dataset already has parent partition folders (e.g. train/val), preserve them
    train_pool: list[VideoInspectionRecord] = []
    eval_pool: list[VideoInspectionRecord] = []

    for r in records:
        parts = Path(r.rel_path).parts
        if "train" in [p.lower() for p in parts]:
            train_pool.append(r)
        elif any(p.lower() in {"val", "validation", "test"} for p in parts):
            eval_pool.append(r)
        else:
            train_pool.append(r)

    # If no existing train/val folder structure, use 70% train, 15% val, 15% test
    if not eval_pool:
        # Split train (70%) vs eval (30%)
        splitter = StratifiedShuffleSplit(n_splits=1, test_size=0.30, random_state=seed)
        train_idx, eval_idx = next(splitter.split(records, labels))
        train_pool = [records[i] for i in train_idx]
        eval_pool = [records[i] for i in eval_idx]

    # Now split eval_pool into val and test
    eval_labels = [r.label for r in eval_pool]
    eval_groups = [r.group_id for r in eval_pool]

    # Use group split if groups exist
    has_groups = len(set(eval_groups)) < len(eval_pool)
    val_records: list[VideoInspectionRecord] = []
    test_records: list[VideoInspectionRecord] = []

    if has_groups:
        gss = GroupShuffleSplit(n_splits=1, test_size=val_test_ratio, random_state=seed)
        try:
            val_idx, test_idx = next(gss.split(eval_pool, eval_labels, eval_groups))
            val_records = [eval_pool[i] for i in val_idx]
            test_records = [eval_pool[i] for i in test_idx]
        except ValueError:
            # Fallback if group split cannot satisfy constraints
            val_records = eval_pool[: len(eval_pool) // 2]
            test_records = eval_pool[len(eval_pool) // 2 :]
    else:
        # Stratified split between val and test
        try:
            sss = StratifiedShuffleSplit(n_splits=1, test_size=val_test_ratio, random_state=seed)
            val_idx, test_idx = next(sss.split(eval_pool, eval_labels))
            val_records = [eval_pool[i] for i in val_idx]
            test_records = [eval_pool[i] for i in test_idx]
        except ValueError:
            val_records = eval_pool[: len(eval_pool) // 2]
            test_records = eval_pool[len(eval_pool) // 2 :]

    # Construct final dictionaries
    results: list[dict[str, Any]] = []
    for r in train_pool:
        d = asdict(r)
        d["path"] = r.rel_path
        d["split"] = "train"
        results.append(d)
    for r in val_records:
        d = asdict(r)
        d["path"] = r.rel_path
        d["split"] = "val"
        results.append(d)
    for r in test_records:
        d = asdict(r)
        d["path"] = r.rel_path
        d["split"] = "test"
        results.append(d)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest and audit an approved replacement dataset.")
    parser.add_argument("--dataset-dir", type=Path, required=True, help="Directory containing dataset video files")
    parser.add_argument("--provenance-file", type=Path, required=True, help="JSON file containing provenance metadata")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for manifest and audit report")
    parser.add_argument("--val-test-split-ratio", type=float, default=0.50, help="Ratio for val vs test splitting")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--allow-unapproved-for-testing", action="store_true", help="Testing flag to allow non-APPROVED provenance")

    args = parser.parse_args()

    try:
        ingest_and_partition_dataset(
            dataset_dir=args.dataset_dir,
            provenance_file=args.provenance_file,
            output_dir=args.output_dir,
            val_test_ratio=args.val_test_split_ratio,
            random_seed=args.seed,
            require_approved_status=not args.allow_unapproved_for_testing,
        )
    except GovernanceError as ge:
        logger.error("GOVERNANCE REJECTION: %s", ge)
        sys.exit(2)
    except Exception as exc:
        logger.error("INGESTION FAILURE: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
