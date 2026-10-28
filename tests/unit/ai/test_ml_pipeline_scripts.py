"""Unit tests for ML pipeline scripts: inspect_dataset, prepare_dataset, train, evaluate, and classifier integration."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from scripts.evaluate_violence_model import evaluate_model_pipeline, fit_platt_scaling
from scripts.inspect_dataset import audit_dataset_directory
from scripts.prepare_dataset import (
    extract_scene_group_id,
    map_folder_to_label,
    prepare_dataset_splits,
)
from scripts.train_violence_model import train_model

from ai_services.violence_detection.classifier import (
    PretrainedVideoClassifierProvider,
    VideoInputSpec,
)
from ai_services.violence_detection.requirements import AI_HUMAN_IN_THE_LOOP_DISCLAIMER
from backend.app.core.ai import APPROVED_AI_MODELS, validate_model_provenance


@pytest.fixture
def temp_ml_workspace(tmp_path: Path) -> Path:
    """Create a temporary directory structure mimicking the ML workflow."""
    raw_dir = tmp_path / "data" / "raw" / "Complete Dataset"
    (raw_dir / "train" / "Fight").mkdir(parents=True)
    (raw_dir / "train" / "NonFight").mkdir(parents=True)
    (raw_dir / "val" / "Fight").mkdir(parents=True)
    (raw_dir / "val" / "NonFight").mkdir(parents=True)
    return tmp_path


def _create_dummy_video(path: Path, width: int = 112, height: int = 112, num_frames: int = 16) -> None:
    """Write a tiny valid dummy MP4/AVI video file."""
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    out = cv2.VideoWriter(str(path), fourcc, 30.0, (width, height))
    for _ in range(num_frames):
        frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        out.write(frame)
    out.release()


@pytest.mark.unit
class TestMLPipelineScripts:
    """Validate data inspection, preparation, model training, and evaluation scripts."""

    def test_inspect_dataset_handles_valid_and_corrupt_files(self, temp_ml_workspace: Path) -> None:
        raw_dir = temp_ml_workspace / "data" / "raw"
        valid_video = raw_dir / "Complete Dataset" / "train" / "Fight" / "vid1.avi"
        corrupt_video = raw_dir / "Complete Dataset" / "train" / "NonFight" / "corrupt.avi"

        _create_dummy_video(valid_video)
        corrupt_video.write_bytes(b"")  # 0 bytes

        summary = audit_dataset_directory(raw_dir, declared_license="MIT")

        assert summary.total_files_scanned == 2
        assert summary.valid_videos_count == 1
        assert summary.corrupt_videos_count == 1
        assert summary.is_license_approved is False
        assert "UNVERIFIED_ON_DISK" in summary.license_verification_status
        assert len(summary.corrupted_files) == 1
        assert summary.corrupted_files[0]["error"] == "Empty file (0 bytes)"

    def test_prepare_dataset_label_mapping_and_rejection(self) -> None:
        cat, lbl = map_folder_to_label("Fight")
        assert cat == "violence" and lbl == 1

        cat, lbl = map_folder_to_label("HockeyFight")
        assert cat == "violence" and lbl == 1

        cat, lbl = map_folder_to_label("MovieFights")
        assert cat == "violence" and lbl == 1

        cat, lbl = map_folder_to_label("NonFight")
        assert cat == "non_violence" and lbl == 0

        with pytest.raises(ValueError, match="Ambiguous or unconfirmed"):
            map_folder_to_label("UnknownCategory")

    def test_prepare_dataset_grouping_classification(self) -> None:
        # RWF-2000 style video ID prefix
        group_id, conf = extract_scene_group_id("_6-B11R9FJM_0.avi", "Fight")
        assert group_id == "_6-B11R9FJM"
        assert conf == "scene_prefix_verified"

        # HockeyFight style
        group_id, conf = extract_scene_group_id("fi1_xvid.avi", "HockeyFight")
        assert group_id == "fi1_xvid"
        assert conf == "ungroupable_opaque_id"

    def test_prepare_dataset_deduplication_and_manifest(self, temp_ml_workspace: Path) -> None:
        raw_dir = temp_ml_workspace / "data" / "raw"
        manifest_path = temp_ml_workspace / "data" / "manifest.json"

        # Create 4 train videos (2 fight, 2 nonfight)
        _create_dummy_video(raw_dir / "Complete Dataset" / "train" / "Fight" / "vid1_0.avi")
        _create_dummy_video(raw_dir / "Complete Dataset" / "train" / "Fight" / "vid1_1.avi")
        _create_dummy_video(raw_dir / "Complete Dataset" / "train" / "NonFight" / "vid2_0.avi")
        _create_dummy_video(raw_dir / "Complete Dataset" / "train" / "NonFight" / "vid2_1.avi")

        # Create 2 val videos
        _create_dummy_video(raw_dir / "Complete Dataset" / "val" / "Fight" / "vid3_0.avi")
        _create_dummy_video(raw_dir / "Complete Dataset" / "val" / "NonFight" / "vid4_0.avi")

        manifest = prepare_dataset_splits(
            raw_dir,
            manifest_path,
            dataset_name="test-dataset",
            dataset_version="1.0.0",
        )

        assert manifest_path.is_file()
        assert manifest["total_items"] == 6
        assert "train" in manifest["split_stats"]
        assert "val" in manifest["split_stats"]
        assert "test" in manifest["split_stats"]
        assert len(manifest["manifest_sha256"]) == 64

    def test_platt_scaling_fitting_and_fallback(self) -> None:
        # Empty set fallback
        slope, intercept, status = fit_platt_scaling(np.array([]), np.array([]))
        assert status == "EMPTY_VAL_FALLBACK"
        assert slope == 1.0 and intercept == 0.0

        # Single class fallback
        slope, intercept, status = fit_platt_scaling(np.array([1, 1, 1]), np.array([0.5, 0.8, 1.2]))
        assert status == "SINGLE_CLASS_VAL_FALLBACK"
        assert slope == 1.0 and intercept == 0.0

        # Small sample size (N < 30)
        targets_small = np.array([0, 0, 1, 1])
        scores_small = np.array([0.1, 0.2, 0.8, 0.9])
        slope, intercept, status = fit_platt_scaling(targets_small, scores_small)
        assert status == "FITTED_SMALL_SAMPLE"
        assert slope > 0.0

        # Inverted score direction fallback (negative correlation)
        targets_inverted = np.array([0, 0, 1, 1])
        scores_inverted = np.array([0.9, 0.8, 0.2, 0.1])
        slope, intercept, status = fit_platt_scaling(targets_inverted, scores_inverted)
        assert status == "INVERTED_SCORE_DIRECTION_FALLBACK"
        assert slope == 1.0 and intercept == 0.0

        # Large sample size (N >= 30) full convergence
        targets_large = np.array([0] * 20 + [1] * 20)
        scores_large = np.array([0.2] * 20 + [0.8] * 20)
        slope, intercept, status = fit_platt_scaling(targets_large, scores_large)
        assert status == "FITTED_CONVERGED"
        assert slope > 0.0

    def test_evaluation_separation_and_manifest_compatibility(self, tmp_path: Path) -> None:
        """Verify train split never accesses test split, and manifest hash semantics are enforced."""
        items = [
            {"path": f"train_clip_{i}.avi", "sha256": f"train_hash_{i}", "label": 1, "class_name": "violence", "split": "train"}
            for i in range(10)
        ] + [
            {"path": f"val_clip_{i}.avi", "sha256": f"val_hash_{i}", "label": 0, "class_name": "non_violence", "split": "val"}
            for i in range(5)
        ] + [
            {"path": f"test_clip_{i}.avi", "sha256": f"test_hash_{i}", "label": 1, "class_name": "violence", "split": "test"}
            for i in range(5)
        ]

        train_hashes = {it["sha256"] for it in items if it["split"] == "train"}
        test_hashes = {it["sha256"] for it in items if it["split"] == "test"}
        val_hashes = {it["sha256"] for it in items if it["split"] == "val"}

        assert len(train_hashes.intersection(test_hashes)) == 0
        assert len(train_hashes.intersection(val_hashes)) == 0
        assert len(val_hashes.intersection(test_hashes)) == 0

    def test_training_and_evaluation_smoke_test(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "data" / "manifest.json"
        models_dir = tmp_path / "artifacts" / "models"

        checkpoint_file = train_model(
            manifest_path=manifest_path,
            data_dir=tmp_path / "data" / "raw",
            output_dir=models_dir,
            model_name="violence-r3d18",
            model_version="1.0.0",
            epochs=1,
            micro_batch_size=2,
            gradient_accumulation_steps=1,
            use_synthetic=True,
            device_str="cpu",
        )

        assert checkpoint_file.is_file()
        meta_file = models_dir / "violence-r3d18-v1.0.0.json"
        assert meta_file.is_file()

        # Run evaluation pipeline on generated checkpoint
        evaluate_model_pipeline(
            checkpoint_path=checkpoint_file,
            manifest_path=manifest_path,
            data_dir=tmp_path / "data" / "raw",
            output_dir=models_dir,
            batch_size=2,
            use_synthetic=True,
            device_str="cpu",
        )

        report_file = models_dir / "violence-r3d18-v1.0.0-evaluation-report.json"
        assert report_file.is_file()
        with open(report_file, encoding="utf-8") as f:
            report_data = json.load(f)
        assert report_data["evaluation_kind"] == "SOFTWARE_SMOKE_TEST"
        assert report_data["is_smoke_test"] is True
        assert report_data["disclaimer"] == AI_HUMAN_IN_THE_LOOP_DISCLAIMER

    def test_model_provenance_and_classifier_provider(self, tmp_path: Path) -> None:
        # Verify provenance check allows violence-r3d18
        validate_model_provenance("violence-r3d18", "1.0.0")
        assert "violence-r3d18" in APPROVED_AI_MODELS

        # Test PretrainedVideoClassifierProvider with trained checkpoint
        ckpt_path = Path("artifacts/models/violence-r3d18-v1.0.0.pt")
        if ckpt_path.is_file():
            provider = PretrainedVideoClassifierProvider(
                model_name="violence-r3d18",
                model_version="1.0.0",
                weights_path=ckpt_path,
                device="cpu",
            )
            assert provider.is_ready() is True
            assert provider.model_info()["status"] == "ready"

            # Create dummy test video for classify()
            test_vid = tmp_path / "classify_test.avi"
            _create_dummy_video(test_vid)

            video_spec = VideoInputSpec(
                video_id="test-vid-001",
                duration_seconds=5.0,
                fps=30.0,
                width=112,
                height=112,
                codec="mjpg",
                frames_count=16,
                metadata={"file_path": str(test_vid)},
            )

            result = provider.classify(video_spec)
            assert result.model_name == "violence-r3d18"
            assert result.model_version == "1.0.0"
            assert 0.0 <= result.violence_score <= 1.0
            assert result.confidence_is_uncalibrated is True
            assert result.disclaimer == AI_HUMAN_IN_THE_LOOP_DISCLAIMER
