"""Unit tests for scripts/ingest_approved_dataset.py.

Validates fail-closed dataset governance, provenance schema checks, SHA-256 deduplication,
corrupt video handling, disjoint splits, evidence file verification, and output artifact creation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from scripts.ingest_approved_dataset import (
    DatasetProvenanceRecord,
    GovernanceError,
    ingest_and_partition_dataset,
    load_provenance_file,
    main,
)


def _create_synthetic_video(path: Path, width: int = 64, height: int = 64, num_frames: int = 8) -> None:
    """Create a minimal valid synthetic AVI file using MJPG fourcc."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    out = cv2.VideoWriter(str(path), fourcc, 15.0, (width, height))
    for _ in range(num_frames):
        frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        out.write(frame)
    out.release()


@pytest.fixture
def mock_evidence_file(tmp_path: Path) -> Path:
    """Create a temporary documentary evidence file."""
    ev_file = tmp_path / "mock_evidence.json"
    ev_file.write_text(json.dumps({"verified_by": "Legal Counsel", "status": "APPROVED"}), encoding="utf-8")
    return ev_file


@pytest.fixture
def sample_provenance_dict(mock_evidence_file: Path) -> dict[str, Any]:
    return {
        "provenance_id": "prov-synth-20261026",
        "dataset_name": "Synthetic-Approved-Benchmark",
        "dataset_version": "1.0.0",
        "source_url": "https://example.org/synthetic-dataset",
        "acquisition_date": "2026-10-26T00:00:00Z",
        "rights_holder": "Synthetic Open Source Team",
        "license_id": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "rights_status": "APPROVED",
        "evidence_file_path": str(mock_evidence_file),
        "intended_use": "Violence detection model training and evaluation",
        "is_commercial_cleared": True,
        "is_redistribution_permitted": True,
        "is_modification_permitted": True,
        "is_model_training_permitted": True,
        "is_synthetic": True,
        "legal_review_notes": "Verified synthetic test dataset.",
    }


@pytest.fixture
def mock_dataset_env(tmp_path: Path, sample_provenance_dict: dict[str, Any]) -> tuple[Path, Path, Path]:
    """Sets up a temporary mock raw dataset directory, provenance file, and output directory."""
    raw_dir = tmp_path / "raw_data"
    output_dir = tmp_path / "derived_data"
    prov_file = tmp_path / "provenance.json"

    # Create synthetic violence and non-violence clips
    for i in range(6):
        _create_synthetic_video(raw_dir / "Fight" / f"fight_clip_{i:02d}.avi")
        _create_synthetic_video(raw_dir / "NonFight" / f"normal_clip_{i:02d}.avi")

    prov_file.write_text(json.dumps(sample_provenance_dict, indent=2), encoding="utf-8")
    return raw_dir, prov_file, output_dir


@pytest.mark.unit
class TestDatasetMigrationTooling:
    """Validate approved-dataset ingestion tool governance, integrity, and output schemas."""

    def test_load_valid_provenance(self, tmp_path: Path, sample_provenance_dict: dict[str, Any]) -> None:
        prov_file = tmp_path / "prov.json"
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")
        rec = load_provenance_file(prov_file)
        assert isinstance(rec, DatasetProvenanceRecord)
        assert rec.license_id == "CC-BY-4.0"
        assert rec.rights_status == "APPROVED"
        assert rec.provenance_id.startswith("prov-")
        assert rec.rights_holder == "Synthetic Open Source Team"

    def test_provenance_rejects_missing_file(self, tmp_path: Path) -> None:
        non_existent = tmp_path / "does_not_exist.json"
        with pytest.raises(FileNotFoundError):
            load_provenance_file(non_existent)

    def test_provenance_rejects_missing_evidence_file(
        self, tmp_path: Path, sample_provenance_dict: dict[str, Any]
    ) -> None:
        sample_provenance_dict["evidence_file_path"] = str(tmp_path / "non_existent_evidence.pdf")
        prov_file = tmp_path / "prov.json"
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with pytest.raises(GovernanceError, match=r"Provenance evidence file does not exist"):
            load_provenance_file(prov_file)

    def test_governance_fail_closed_on_unapproved_rights_status(
        self, mock_dataset_env: tuple[Path, Path, Path], sample_provenance_dict: dict[str, Any]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        sample_provenance_dict["rights_status"] = "RESTRICTED"
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with pytest.raises(GovernanceError, match=r"Dataset rights status is 'RESTRICTED'"):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )

    def test_governance_fail_closed_on_unapproved_license(
        self, mock_dataset_env: tuple[Path, Path, Path], sample_provenance_dict: dict[str, Any]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        sample_provenance_dict["license_id"] = "CC-BY-NC-4.0"  # Non-commercial restricted
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with pytest.raises(GovernanceError, match=r"License 'CC-BY-NC-4.0' is not in E-WITNESS APPROVED_DATASET_LICENSES"):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )

    def test_governance_rejects_missing_commercial_clearance(
        self, mock_dataset_env: tuple[Path, Path, Path], sample_provenance_dict: dict[str, Any]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        sample_provenance_dict["is_commercial_cleared"] = False
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with pytest.raises(GovernanceError, match=r"commercial enterprise deployment is not cleared"):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )

    def test_governance_rejects_missing_model_training_permission(
        self, mock_dataset_env: tuple[Path, Path, Path], sample_provenance_dict: dict[str, Any]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        sample_provenance_dict["is_model_training_permitted"] = False
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with pytest.raises(GovernanceError, match=r"model training is not permitted"):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )

    def test_governance_rejects_mixed_restricted_components(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        # Create a video in a restricted component folder (e.g. MovieFights)
        restricted_dir = raw_dir / "MovieFights"
        _create_synthetic_video(restricted_dir / "movie_clip_01.avi")

        with pytest.raises(GovernanceError, match=r"Restricted or unverified third-party component 'moviefights' detected"):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )

    def test_successful_ingestion_and_artifact_generation(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env

        manifest = ingest_and_partition_dataset(
            dataset_dir=raw_dir,
            provenance_file=prov_file,
            output_dir=output_dir,
            val_test_ratio=0.50,
            random_seed=42,
            require_approved_status=True,
        )

        assert manifest["total_items"] == 12
        assert manifest["dataset_name"] == "Synthetic-Approved-Benchmark"
        assert manifest["is_synthetic"] is True
        assert manifest["production_training_eligible"] is False  # Synthetic cannot be mistaken for production
        assert len(manifest["manifest_sha256"]) == 64
        assert manifest["split_stats"]["train"]["total"] > 0
        assert manifest["split_stats"]["val"]["total"] > 0
        assert manifest["split_stats"]["test"]["total"] > 0

        # Verify disk outputs
        manifest_file = output_dir / "manifest.json"
        audit_file = output_dir / "ingestion_audit_report.json"
        summary_file = output_dir / "INGESTION_SUMMARY.md"

        assert manifest_file.exists()
        assert audit_file.exists()
        assert summary_file.exists()

        audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        assert audit_data["provenance_verified"] is True
        assert audit_data["rights_status"] == "APPROVED"
        assert audit_data["unique_count"] == 12

        summary_text = summary_file.read_text(encoding="utf-8")
        assert "**Zero Cross-Split Overlap:** Verified" in summary_text
        assert "SYNTHETIC BENCHMARK" in summary_text

    def test_deduplication_purges_exact_duplicate_files(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env

        # Create an exact bitwise duplicate of fight_clip_00.avi
        src_clip = raw_dir / "Fight" / "fight_clip_00.avi"
        dup_clip = raw_dir / "Fight" / "fight_clip_00_duplicate.avi"
        dup_clip.write_bytes(src_clip.read_bytes())

        manifest = ingest_and_partition_dataset(
            dataset_dir=raw_dir,
            provenance_file=prov_file,
            output_dir=output_dir,
            require_approved_status=True,
        )

        assert manifest["purged_duplicates_count"] == 1
        assert len(manifest["purged_duplicates"]) == 1
        assert manifest["total_deduplicated_files"] == 12  # 13 scanned, 1 duplicate purged
        assert dup_clip.name in manifest["purged_duplicates"][0]["duplicate_path"]

    def test_corrupted_videos_quarantined_without_crash(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env

        # Write empty (0-byte) file and garbage file
        empty_clip = raw_dir / "Fight" / "empty_video.mp4"
        empty_clip.write_bytes(b"")
        garbage_clip = raw_dir / "NonFight" / "garbage_video.avi"
        garbage_clip.write_bytes(b"NOT_A_VALID_VIDEO_CONTAINER_DATA" * 50)

        manifest = ingest_and_partition_dataset(
            dataset_dir=raw_dir,
            provenance_file=prov_file,
            output_dir=output_dir,
            require_approved_status=True,
        )

        assert manifest["corrupted_files_count"] == 2
        assert len(manifest["items"]) == 12  # All 12 valid clips kept

        audit_file = output_dir / "ingestion_audit_report.json"
        audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
        assert audit_data["corrupted_count"] == 2
        corrupt_errors = [c["error"] for c in audit_data["corrupted_files"]]
        assert any("empty file" in err.lower() for err in corrupt_errors)

    def test_zero_hash_leakage_across_splits(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env

        manifest = ingest_and_partition_dataset(
            dataset_dir=raw_dir,
            provenance_file=prov_file,
            output_dir=output_dir,
            require_approved_status=True,
        )

        splits = {"train": set(), "val": set(), "test": set()}
        for item in manifest["items"]:
            splits[item["split"]].add(item["sha256"])

        assert len(splits["train"].intersection(splits["val"])) == 0
        assert len(splits["train"].intersection(splits["test"])) == 0
        assert len(splits["val"].intersection(splits["test"])) == 0

    def test_cli_exit_code_on_governance_failure(
        self, mock_dataset_env: tuple[Path, Path, Path], sample_provenance_dict: dict[str, Any]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env
        sample_provenance_dict["rights_status"] = "UNVERIFIED"
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        test_args = [
            "ingest_approved_dataset.py",
            "--dataset-dir", str(raw_dir),
            "--provenance-file", str(prov_file),
            "--output-dir", str(output_dir),
        ]

        with patch.object(sys, "argv", test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    def test_governance_rejects_symlinked_evidence_file(
        self, tmp_path: Path, sample_provenance_dict: dict[str, Any]
    ) -> None:
        prov_file = tmp_path / "prov.json"
        prov_file.write_text(json.dumps(sample_provenance_dict), encoding="utf-8")

        with (
            patch("pathlib.Path.is_symlink", return_value=True),
            pytest.raises(GovernanceError, match=r"Symlinks are disallowed for provenance evidence file"),
        ):
            load_provenance_file(prov_file)

    def test_governance_rejects_symlinked_video_file(
        self, mock_dataset_env: tuple[Path, Path, Path]
    ) -> None:
        raw_dir, prov_file, output_dir = mock_dataset_env

        call_count = 0

        def mock_is_symlink(*args: Any, **kwargs: Any) -> bool:
            nonlocal call_count
            call_count += 1
            # First call is for evidence file in load_provenance_file -> False
            # Subsequent calls during video scanning -> True
            return call_count > 1

        with (
            patch.object(Path, "is_symlink", side_effect=mock_is_symlink),
            pytest.raises(GovernanceError, match=r"Symlinks are disallowed in dataset directory"),
        ):
            ingest_and_partition_dataset(
                dataset_dir=raw_dir,
                provenance_file=prov_file,
                output_dir=output_dir,
                require_approved_status=True,
            )
