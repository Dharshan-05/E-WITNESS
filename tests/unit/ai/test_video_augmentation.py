import json

import numpy as np
import pytest

from ai_services.violence_detection.augmentation import (
    VideoAugmentationConfig,
    VideoAugmentationPipeline,
)


@pytest.mark.unit
class TestVideoAugmentationPipeline:
    def test_disabled_pipeline_preserves_input_identity(self) -> None:
        config = VideoAugmentationConfig(enabled=False)
        pipeline = VideoAugmentationPipeline(config)
        frames = np.random.uniform(0.0, 1.0, (16, 112, 112, 3)).astype(np.float32)

        augmented = pipeline.augment(frames)
        np.testing.assert_array_equal(augmented, frames)

    def test_shape_and_dtype_preservation(self) -> None:
        config = VideoAugmentationConfig(
            enabled=True,
            horizontal_flip_prob=1.0,
            brightness_contrast_prob=1.0,
            motion_blur_prob=1.0,
            spatial_cutout_prob=1.0,
            low_res_prob=1.0,
            sensor_noise_prob=1.0,
            seed=42,
        )
        pipeline = VideoAugmentationPipeline(config)
        frames = np.random.uniform(0.1, 0.9, (16, 112, 112, 3)).astype(np.float32)

        augmented = pipeline.augment(frames)
        assert augmented.shape == (16, 112, 112, 3)
        assert augmented.dtype == np.float32
        assert np.all(augmented >= 0.0)
        assert np.all(augmented <= 1.0)

    def test_temporal_consistency_spatial_cutout(self) -> None:
        # Enable ONLY spatial cutout
        config = VideoAugmentationConfig(
            enabled=True,
            horizontal_flip_prob=0.0,
            brightness_contrast_prob=0.0,
            motion_blur_prob=0.0,
            spatial_cutout_prob=1.0,
            low_res_prob=0.0,
            sensor_noise_prob=0.0,
            cutout_min_ratio=0.25,
            cutout_max_ratio=0.25,
            seed=123,
        )
        pipeline = VideoAugmentationPipeline(config)
        # Uniform 1.0 input
        frames = np.ones((16, 112, 112, 3), dtype=np.float32)

        augmented = pipeline.augment(frames)

        # Detect the cutout mask in frame 0
        diff_frame0 = np.abs(augmented[0] - frames[0]) > 0.1
        assert np.any(diff_frame0), "Cutout mask must alter some pixels"

        # Check that the EXACT same pixels are altered in all subsequent frames
        for t in range(1, 16):
            diff_framet = np.abs(augmented[t] - frames[t]) > 0.1
            np.testing.assert_array_equal(
                diff_frame0,
                diff_framet,
                err_msg=f"Spatial cutout mask must be identical between frame 0 and frame {t}",
            )

    def test_temporal_consistency_brightness_shift(self) -> None:
        # Enable ONLY brightness/contrast
        config = VideoAugmentationConfig(
            enabled=True,
            horizontal_flip_prob=0.0,
            brightness_contrast_prob=1.0,
            contrast_range=0.0,  # Alpha = 1.0
            brightness_range=0.10,  # Beta sampled in [-0.10, +0.10]
            motion_blur_prob=0.0,
            spatial_cutout_prob=0.0,
            low_res_prob=0.0,
            sensor_noise_prob=0.0,
            seed=42,
        )
        pipeline = VideoAugmentationPipeline(config)
        # Identical constant frames 0.50
        frames = np.full((16, 112, 112, 3), 0.50, dtype=np.float32)

        augmented = pipeline.augment(frames)

        # Value in frame 0
        val_0 = augmented[0, 0, 0, 0]
        # Must be identical across all frames t
        for t in range(1, 16):
            val_t = augmented[t, 0, 0, 0]
            assert np.isclose(val_0, val_t, atol=1e-5), f"Brightness shift differed at frame {t}"

    def test_reproducible_seeding(self) -> None:
        config1 = VideoAugmentationConfig(enabled=True, seed=999)
        pipeline1 = VideoAugmentationPipeline(config1)

        config2 = VideoAugmentationConfig(enabled=True, seed=999)
        pipeline2 = VideoAugmentationPipeline(config2)

        frames = np.random.uniform(0.0, 1.0, (16, 112, 112, 3)).astype(np.float32)

        aug1 = pipeline1.augment(frames)
        aug2 = pipeline2.augment(frames)
        np.testing.assert_array_equal(aug1, aug2)

    def test_config_json_serializability(self) -> None:
        config = VideoAugmentationConfig(enabled=True, seed=42)
        d = config.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized["enabled"] is True
        assert deserialized["seed"] == 42
