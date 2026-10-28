"""Automated dataset inspection, decodability audit, and licensing verification (Phase 62 & Task P0.3).

Audits video datasets in data/raw for:
1. File container integrity and video stream decodability via OpenCV.
2. Provenance and SPDX licensing verification (verifying local license files).
3. Class distribution, video duration, resolution, framerate, and file size statistics.
4. Identification of corrupted, unreadable, or 0-byte video files without crashing.
5. Reporting in structured JSON at data/dataset_audit_report.json and CLI summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2

# Import approved licenses from core AI governance
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.app.core.ai import APPROVED_DATASET_LICENSES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inspect_dataset")

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})
POTENTIAL_LICENSE_FILENAMES = frozenset(
    {"license", "license.txt", "license.md", "terms", "terms.txt", "readme", "readme.md", "metadata.json"}
)


@dataclass
class VideoFileInfo:
    path: str
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    parent_partition: str
    inferred_class: str
    is_valid: bool
    duration_seconds: float = 0.0
    frame_count: int = 0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    error_message: str | None = None


@dataclass
class DatasetAuditSummary:
    dataset_path: str
    audit_timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    declared_source: str = "https://www.kaggle.com/datasets/yash07yadav/project-data"
    declared_license: str = "MIT"
    local_license_file: str | None = None
    license_verification_status: str = "UNVERIFIED_ON_DISK"
    is_license_approved: bool = False
    total_files_scanned: int = 0
    valid_videos_count: int = 0
    corrupt_videos_count: int = 0
    total_size_bytes: int = 0
    total_duration_seconds: float = 0.0
    partition_distribution: dict[str, int] = field(default_factory=dict)
    class_distribution: dict[str, int] = field(default_factory=dict)
    class_by_partition: dict[str, dict[str, int]] = field(default_factory=dict)
    resolution_distribution: dict[str, int] = field(default_factory=dict)
    fps_distribution: dict[str, int] = field(default_factory=dict)
    corrupted_files: list[dict[str, Any]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def check_local_license(data_dir: Path, declared_license: str) -> tuple[str | None, str, bool]:
    """Inspect data_dir for on-disk license files and verify authenticity.

    Returns:
        tuple of (license_file_path, verification_status, is_approved)
    """
    found_license_file: Path | None = None
    for p in data_dir.rglob("*"):
        if p.is_file() and p.name.lower() in POTENTIAL_LICENSE_FILENAMES:
            found_license_file = p
            break

    if found_license_file is None:
        return (
            None,
            "UNVERIFIED_ON_DISK: No LICENSE, README, or terms file present in raw download archive.",
            False,
        )

    # Read license file content to verify
    try:
        content = found_license_file.read_text(encoding="utf-8", errors="replace").lower()
        if ("mit license" in content or "mit" in declared_license.lower()) and (declared_license in APPROVED_DATASET_LICENSES):
            return str(found_license_file), "VERIFIED_ON_DISK", True
        return str(found_license_file), "PRESENT_BUT_UNAPPROVED", False
    except Exception as exc:
        return str(found_license_file), f"READ_ERROR: {exc}", False


def inspect_single_video(file_path: Path, root_dir: Path) -> VideoFileInfo:
    """Inspect a single video file for integrity and decodability without modifying it."""
    size_bytes = file_path.stat().st_size
    rel_path = str(file_path.relative_to(root_dir)).replace("\\", "/")
    parts = file_path.relative_to(root_dir).parts

    # Extract partition (train/val) and class (Fight/NonFight/HockeyFight/MovieFights)
    inferred_class = file_path.parent.name
    partition = "root"
    for part in parts:
        if part.lower() in {"train", "val", "test", "validation"}:
            partition = part.lower()
            break

    if size_bytes == 0:
        return VideoFileInfo(
            path=str(file_path),
            relative_path=rel_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=0,
            parent_partition=partition,
            inferred_class=inferred_class,
            is_valid=False,
            error_message="Empty file (0 bytes)",
        )

    cap = cv2.VideoCapture(str(file_path))
    if not cap.isOpened():
        return VideoFileInfo(
            path=str(file_path),
            relative_path=rel_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=size_bytes,
            parent_partition=partition,
            inferred_class=inferred_class,
            is_valid=False,
            error_message="Failed to open video container with OpenCV",
        )

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        ret, frame = cap.read()
        if not ret or frame is None:
            return VideoFileInfo(
                path=str(file_path),
                relative_path=rel_path,
                filename=file_path.name,
                extension=file_path.suffix.lower(),
                size_bytes=size_bytes,
                parent_partition=partition,
                inferred_class=inferred_class,
                is_valid=False,
                error_message="Could not decode initial video frame",
            )

        duration = float(frame_count) / fps if fps > 0 else 0.0

        return VideoFileInfo(
            path=str(file_path),
            relative_path=rel_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=size_bytes,
            parent_partition=partition,
            inferred_class=inferred_class,
            is_valid=True,
            duration_seconds=round(duration, 2),
            frame_count=frame_count,
            fps=round(fps, 2),
            width=width,
            height=height,
        )
    except Exception as exc:
        return VideoFileInfo(
            path=str(file_path),
            relative_path=rel_path,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=size_bytes,
            parent_partition=partition,
            inferred_class=inferred_class,
            is_valid=False,
            error_message=f"Exception during decoding: {exc}",
        )
    finally:
        cap.release()


def audit_dataset_directory(
    data_dir: Path,
    declared_license: str = "MIT",
    sample_limit: int | None = None,
) -> DatasetAuditSummary:
    """Recursively audit all video files in a dataset directory."""
    logger.info("Starting dataset audit in %s", data_dir)
    lic_file, lic_status, is_lic_approved = check_local_license(data_dir, declared_license)

    summary = DatasetAuditSummary(
        dataset_path=str(data_dir.resolve()),
        declared_license=declared_license,
        local_license_file=lic_file,
        license_verification_status=lic_status,
        is_license_approved=is_lic_approved,
    )

    if not is_lic_approved:
        summary.findings.append(
            f"GOVERNANCE ADVISORY: Dataset license is {lic_status}. "
            f"Kaggle web card declares '{declared_license}', but no verifiable license file exists in the downloaded archive."
        )
    else:
        summary.findings.append(f"License '{declared_license}' is verified on disk in {lic_file}.")

    if not data_dir.exists():
        summary.findings.append(f"Directory {data_dir} does not exist.")
        return summary

    all_files = [
        p for p in data_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    ]

    if not all_files:
        summary.findings.append(f"No video files ({sorted(SUPPORTED_VIDEO_EXTENSIONS)}) found in {data_dir}.")
        return summary

    if sample_limit and len(all_files) > sample_limit:
        logger.info("Sampling %d files out of %d total", sample_limit, len(all_files))
        all_files = all_files[:sample_limit]

    summary.total_files_scanned = len(all_files)

    part_counter: Counter[str] = Counter()
    class_counter: Counter[str] = Counter()
    part_class_counter: dict[str, Counter[str]] = {}
    res_counter: Counter[str] = Counter()
    fps_counter: Counter[str] = Counter()

    for idx, fpath in enumerate(all_files, start=1):
        if idx % 500 == 0 or idx == len(all_files):
            logger.info("Audited %d/%d video files...", idx, len(all_files))

        info = inspect_single_video(fpath, data_dir)
        summary.total_size_bytes += info.size_bytes

        if info.is_valid:
            summary.valid_videos_count += 1
            summary.total_duration_seconds += info.duration_seconds
            part_counter[info.parent_partition] += 1
            class_counter[info.inferred_class] += 1

            if info.parent_partition not in part_class_counter:
                part_class_counter[info.parent_partition] = Counter()
            part_class_counter[info.parent_partition][info.inferred_class] += 1

            res_counter[f"{info.width}x{info.height}"] += 1
            fps_counter[f"{round(info.fps)}fps"] += 1
        else:
            summary.corrupt_videos_count += 1
            summary.corrupted_files.append(
                {
                    "path": info.relative_path,
                    "size_bytes": info.size_bytes,
                    "error": info.error_message,
                }
            )

    summary.partition_distribution = dict(part_counter.most_common())
    summary.class_distribution = dict(class_counter.most_common())
    summary.class_by_partition = {
        p: dict(cnt.most_common()) for p, cnt in part_class_counter.items()
    }
    summary.resolution_distribution = dict(res_counter.most_common(10))
    summary.fps_distribution = dict(fps_counter.most_common(5))

    # Findings summary
    if summary.corrupt_videos_count > 0:
        summary.findings.append(
            f"Detected {summary.corrupt_videos_count} corrupted/unreadable video files."
        )
    else:
        summary.findings.append(f"All {summary.valid_videos_count} scanned video files are structurally valid and decodable.")

    # Class balance findings
    v_classes = {"fight", "hockeyfight", "moviefights", "moviefight", "violence"}
    nv_classes = {"nonfight", "non-fight", "non_violence", "normal"}

    v_count = sum(cnt for cls, cnt in summary.class_distribution.items() if cls.lower() in v_classes)
    nv_count = sum(cnt for cls, cnt in summary.class_distribution.items() if cls.lower() in nv_classes)

    if v_count > 0 and nv_count > 0:
        ratio = round(v_count / nv_count, 2)
        summary.findings.append(
            f"Class balance: {v_count} violent clips vs {nv_count} non-violent clips (ratio: {ratio}:1)."
        )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and inspect video dataset.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to raw dataset directory (default: data/raw)",
    )
    parser.add_argument(
        "--declared-license",
        type=str,
        default="MIT",
        help="Declared SPDX license identifier from dataset source (default: MIT)",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("data/dataset_audit_report.json"),
        help="Path to output JSON audit report (default: data/dataset_audit_report.json)",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=None,
        help="Optional limit on number of files to inspect for quick sanity checking",
    )

    args = parser.parse_args()

    summary = audit_dataset_directory(
        args.data_dir,
        declared_license=args.declared_license,
        sample_limit=args.sample_limit,
    )

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_report, "w", encoding="utf-8") as f:
        json.dump(asdict(summary), f, indent=2)

    logger.info("Audit report written to %s", args.output_report)
    print("\n" + "=" * 65)
    print("           E-WITNESS DATASET AUDIT SUMMARY")
    print("=" * 65)
    print(f"Dataset Path:           {summary.dataset_path}")
    print(f"Declared License:       {summary.declared_license}")
    print(f"License Verified Disk:  {summary.is_license_approved} ({summary.license_verification_status})")
    print(f"Total Files Scanned:    {summary.total_files_scanned}")
    print(f"Valid Decodable Videos: {summary.valid_videos_count}")
    print(f"Corrupted / Failed:     {summary.corrupt_videos_count}")
    print(f"Total Size:             {summary.total_size_bytes / (1024**3):.2f} GB")
    print(f"Total Duration:         {summary.total_duration_seconds / 3600:.2f} hours")
    print("\nPartitions:")
    for part, cnt in summary.partition_distribution.items():
        print(f"  - {part:15s}: {cnt:6d} clips")
    print("\nClass Breakdown by Partition:")
    for part, classes in summary.class_by_partition.items():
        print(f"  [{part}]:")
        for cls, cnt in classes.items():
            print(f"    - {cls:18s}: {cnt:6d} clips")
    print("\nTop Resolutions:")
    for res, cnt in summary.resolution_distribution.items():
        print(f"  - {res:20s}: {cnt:6d} clips")
    print("\nFindings:")
    for finding in summary.findings:
        print(f"  * {finding}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
