"""Temporally consistent video data augmentation pipeline for violence detection robustness (v1.3.0).

Enforces:
- Label-preserving transformations (does not flip upside down or erase entire scene).
- Temporal consistency: video-level parameters (e.g., brightness offset, cutout bounding box,
  blur direction) are sampled once per clip and applied uniformly across all T temporal frames.
- Applied strictly to training split in RGB float32 [0.0, 1.0] space before Kinetics standardization.
- Deterministic reproducibility when an explicit random seed or RandomState is provided.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("video_augmentation")


@dataclass
class VideoAugmentationConfig:
    """Configuration for video robustness augmentation in v1.3.0."""

    enabled: bool = False
    horizontal_flip_prob: float = 0.50
    brightness_contrast_prob: float = 0.35
    brightness_range: float = 0.12
    contrast_range: float = 0.20
    motion_blur_prob: float = 0.30
    motion_blur_kernel_size: int = 5
    spatial_cutout_prob: float = 0.30
    cutout_min_ratio: float = 0.15
    cutout_max_ratio: float = 0.30
    low_res_prob: float = 0.25
    low_res_factor: float = 0.50
    sensor_noise_prob: float = 0.25
    sensor_noise_std: float = 0.025
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VideoAugmentationPipeline:
    """Applies temporally consistent spatial, optical, and sensor augmentations to video clips.

    Expects input frames array of shape (T, H, W, C) with values in range [0.0, 1.0] (float32).
    Returns transformed frames array of identical shape (T, H, W, C) in [0.0, 1.0] (float32).
    """

    def __init__(self, config: VideoAugmentationConfig | None = None) -> None:
        self.config = config or VideoAugmentationConfig()
        self.rng = np.random.RandomState(self.config.seed)

    def set_seed(self, seed: int) -> None:
        self.config.seed = seed
        self.rng = np.random.RandomState(seed)

    def augment(self, frames: np.ndarray) -> np.ndarray:
        """Apply active augmentations to a video sequence of shape (T, H, W, C)."""
        if not self.config.enabled:
            return frames

        t, h, w, _c = frames.shape
        out = frames.copy()

        # 1. Temporally consistent Horizontal Flip
        if self.config.horizontal_flip_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.horizontal_flip_prob:
            out = np.flip(out, axis=2)  # Flip along width axis for all frames

        # 2. Temporally consistent Brightness & Contrast variation
        if self.config.brightness_contrast_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.brightness_contrast_prob:
            alpha = self.rng.uniform(1.0 - self.config.contrast_range, 1.0 + self.config.contrast_range)
            beta = self.rng.uniform(-self.config.brightness_range, self.config.brightness_range)
            out = np.clip(out * alpha + beta, 0.0, 1.0)

        # 3. Temporally consistent Camera Motion Blur
        if self.config.motion_blur_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.motion_blur_prob:
            k = max(3, self.config.motion_blur_kernel_size | 1)  # Ensure odd
            # Sample horizontal (angle=0) or diagonal motion blur kernel
            kernel = np.zeros((k, k), dtype=np.float32)
            if self.rng.uniform(0.0, 1.0) < 0.60:
                kernel[k // 2, :] = 1.0 / k  # Horizontal motion blur
            else:
                np.fill_diagonal(kernel, 1.0 / k)  # Diagonal motion blur
            for i in range(t):
                out[i] = cv2.filter2D(out[i], -1, kernel)

        # 4. Temporally consistent Low-Resolution Downsampling & Interpolation
        if self.config.low_res_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.low_res_prob:
            scale = max(0.25, self.config.low_res_factor)
            dw = max(16, int(w * scale))
            dh = max(16, int(h * scale))
            for i in range(t):
                small = cv2.resize(out[i], (dw, dh), interpolation=cv2.INTER_LINEAR)
                out[i] = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

        # 5. Temporally consistent Random Spatial Cutout / Static Occlusion
        # Simulates static pole, wall pillar, or partial pedestrian blockage
        if self.config.spatial_cutout_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.spatial_cutout_prob:
            ch = int(h * self.rng.uniform(self.config.cutout_min_ratio, self.config.cutout_max_ratio))
            cw = int(w * self.rng.uniform(self.config.cutout_min_ratio, self.config.cutout_max_ratio))
            y0 = self.rng.randint(0, max(1, h - ch))
            x0 = self.rng.randint(0, max(1, w - cw))
            # Fill with neutral gray (0.50) across ALL frames in the clip
            fill_val = self.rng.uniform(0.10, 0.50)
            out[:, y0 : y0 + ch, x0 : x0 + cw, :] = fill_val

        # 6. Sensor Noise (Gaussian shot noise)
        if self.config.sensor_noise_prob > 0.0 and self.rng.uniform(0.0, 1.0) < self.config.sensor_noise_prob:
            sigma = self.rng.uniform(0.01, self.config.sensor_noise_std)
            noise = self.rng.normal(0.0, sigma, size=out.shape).astype(np.float32)
            out = np.clip(out + noise, 0.0, 1.0)

        return out.astype(np.float32)
