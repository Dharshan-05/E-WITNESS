"""Non-identifying photometric evidence quality assessment module (Phase 76).

Enforces:
- Strictly non-identifying measurements: sharpness (Laplacian variance), exposure (underexposure,
  overexposure), contrast (luminance dynamic range), and clipping percentage.
- Complete segregation from biometric recognition: zero embeddings, zero descriptors, zero identity templates.
- Finite numerical validation: strict rejection of NaN, infinity, negative dimensions, or empty buffers.
- Pre-allocation dimension checks: enforce MAX_IMAGE_DIMENSION (4096px) and MAX_IMAGE_PIXELS (16.8 MP).
- Pillow warning escalation: Image.DecompressionBombWarning caught and escalated to fatal error.
- Mandatory advisory disclaimer: quality scores reflect technical imaging metrics only and never prove
  anonymization, complete face detection, or legal compliance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import io
import math
from typing import Any, Final
import warnings

import numpy as np
from PIL import Image

from ai_services.face_detection.detector import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    _validate_dimensions,
    inspect_image_dimensions_and_format,
)
from ai_services.face_detection.redaction import _sanitize_error_message
from backend.app.core.exceptions import UnsupportedMediaTypeError

# Configure Pillow decoder-level decompression bomb threshold
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER: Final[str] = (
    "NON-BIOMETRIC QUALITY ADVISORY: Photometric quality metrics (sharpness, exposure, contrast, clipping) "
    "evaluate technical imaging characteristics only. They do not evaluate identity, facial recognition "
    "viability, or demographic attributes, and do not prove or certify that all faces or evidence details "
    "are detectable or that evidence is suitable for every investigative purpose."
)


class PhotometricQualityStatus(StrEnum):
    """Categorical assessment of photometric imaging quality."""

    ACCEPTABLE = "acceptable"
    DEGRADED = "degraded"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PhotometricQualityThresholds:
    """Configurable heuristics for photometric quality assessment.

    NOTE: Thresholds such as Laplacian variance < 100.0 are provisional heuristics,
    not universal scientific constants. They are used to trigger human review.
    """

    min_sharpness_variance: float = 100.0
    min_sharpness_score: float = 0.15
    max_underexposed_fraction: float = 0.25
    max_overexposed_fraction: float = 0.25
    max_clipped_fraction: float = 0.15
    min_contrast_score: float = 0.15
    underexposed_pixel_threshold: int = 25  # Pixels with gray <= 25 are underexposed
    overexposed_pixel_threshold: int = 230  # Pixels with gray >= 230 are overexposed
    black_clipping_threshold: int = 5  # Pixels with gray <= 5 are black-clipped
    white_clipping_threshold: int = 250  # Pixels with gray >= 250 are white-clipped
    laplacian_norm_k: float = 500.0  # Rational normalization scale: x / (x + K)

    def __post_init__(self) -> None:
        if self.min_sharpness_variance <= 0.0 or not math.isfinite(self.min_sharpness_variance):
            raise ValueError("min_sharpness_variance must be positive and finite.")
        if not (0.0 <= self.min_sharpness_score <= 1.0):
            raise ValueError("min_sharpness_score must be between 0.0 and 1.0.")
        if not (0.0 <= self.max_underexposed_fraction <= 1.0):
            raise ValueError("max_underexposed_fraction must be between 0.0 and 1.0.")
        if not (0.0 <= self.max_overexposed_fraction <= 1.0):
            raise ValueError("max_overexposed_fraction must be between 0.0 and 1.0.")
        if not (0.0 <= self.max_clipped_fraction <= 1.0):
            raise ValueError("max_clipped_fraction must be between 0.0 and 1.0.")
        if not (0.0 <= self.min_contrast_score <= 1.0):
            raise ValueError("min_contrast_score must be between 0.0 and 1.0.")
        if self.laplacian_norm_k <= 0.0 or not math.isfinite(self.laplacian_norm_k):
            raise ValueError("laplacian_norm_k must be positive and finite.")


@dataclass(frozen=True)
class PhotometricQualityResult:
    """Structured result of a photometric evidence quality evaluation."""

    sharpness_score: float
    exposure_score: float
    contrast_score: float
    underexposed_fraction: float
    overexposed_fraction: float
    clipped_fraction: float
    quality_status: PhotometricQualityStatus
    requires_human_review: bool
    review_reasons: list[str]
    raw_metrics: dict[str, float]
    image_width: int
    image_height: int
    image_format: str
    metric_version: str = "1.0.0"
    disclaimer: str = PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER

    def __post_init__(self) -> None:
        for name, val in [
            ("sharpness_score", self.sharpness_score),
            ("exposure_score", self.exposure_score),
            ("contrast_score", self.contrast_score),
            ("underexposed_fraction", self.underexposed_fraction),
            ("overexposed_fraction", self.overexposed_fraction),
            ("clipped_fraction", self.clipped_fraction),
        ]:
            if not math.isfinite(val) or not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be a finite float within [0.0, 1.0] (got {val}).")
        if self.image_width < 1 or self.image_height < 1:
            raise ValueError("image_width and image_height must be positive integers.")


def assess_photometric_quality(
    image_bytes: bytes,
    thresholds: PhotometricQualityThresholds | None = None,
) -> PhotometricQualityResult:
    """Assess non-identifying photometric quality of an evidence image.

    Calculates:
    - Focus / Sharpness: Variance of discrete 2D Laplacian operator. Normalized monotonically via x / (x + K).
    - Exposure Balance: Fraction of underexposed and overexposed pixels.
    - Contrast: RMS luminance variation across pixels normalized to [0.0, 1.0].
    - Clipping: Combined extreme black and white clipping fraction.

    Raises:
        ValueError: If image_bytes is empty or exceeds MAX_IMAGE_BYTES.
        UnsupportedMediaTypeError: If image container is invalid, corrupted, or exceeds decompression limits.
    """
    if not image_bytes:
        raise ValueError("Image bytes payload cannot be empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image payload size ({len(image_bytes)} bytes) exceeds maximum permitted limit ({MAX_IMAGE_BYTES} bytes)."
        )

    thresh = thresholds or PhotometricQualityThresholds()

    # Pre-inspect headers before full decoding
    try:
        width, height, img_format = inspect_image_dimensions_and_format(image_bytes)
        _validate_dimensions(width, height)
    except (ValueError, UnsupportedMediaTypeError) as exc:
        sanitized = _sanitize_error_message(exc)
        raise UnsupportedMediaTypeError(
            f"Image exceeds safe dimension or decompression limits: {sanitized}"
        ) from exc

    try:
        with warnings.catch_warnings():
            # Escalate Pillow decompression bomb warnings to exceptions
            warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as pil_img:
                dec_width, dec_height = pil_img.size
                _validate_dimensions(dec_width, dec_height)
                # Convert to grayscale 8-bit luminance
                gray_img = pil_img.convert("L")
                gray = np.asarray(gray_img, dtype=np.float64)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError) as exc:
        sanitized = _sanitize_error_message(exc)
        raise UnsupportedMediaTypeError(
            f"Image exceeds safe dimension or decompression limits: {sanitized}"
        ) from exc
    except Exception as exc:
        sanitized = _sanitize_error_message(exc)
        raise UnsupportedMediaTypeError(
            f"Failed to decode image for quality assessment: {sanitized}"
        ) from exc

    h, w = gray.shape
    total_pixels = h * w
    if total_pixels == 0:
        raise UnsupportedMediaTypeError("Decoded image has zero pixel area.")

    # 1. Sharpness calculation: Discrete 2D Laplacian variance
    # Discrete kernel: [[0, 1, 0], [1, -4, 1], [0, 1, 0]]
    if h >= 3 and w >= 3:
        laplacian = (
            gray[:-2, 1:-1]
            + gray[2:, 1:-1]
            + gray[1:-1, :-2]
            + gray[1:-1, 2:]
            - 4.0 * gray[1:-1, 1:-1]
        )
        raw_laplacian_var = float(np.var(laplacian))
    else:
        # Micro image: cannot compute 3x3 kernel
        raw_laplacian_var = 0.0

    if not math.isfinite(raw_laplacian_var) or raw_laplacian_var < 0.0:
        raw_laplacian_var = 0.0

    # Rational normalization: score in [0.0, 1.0)
    sharpness_score = float(raw_laplacian_var / (raw_laplacian_var + thresh.laplacian_norm_k))
    sharpness_score = max(0.0, min(1.0, sharpness_score))

    # 2. Exposure metrics: Underexposure and Overexposure fractions
    underexposed_count = int(np.sum(gray <= thresh.underexposed_pixel_threshold))
    overexposed_count = int(np.sum(gray >= thresh.overexposed_pixel_threshold))

    underexposed_fraction = float(underexposed_count / total_pixels)
    overexposed_fraction = float(overexposed_count / total_pixels)

    # Exposure score: 1.0 if perfectly balanced, penalized as extremes increase
    exposure_penalty = min(1.0, underexposed_fraction + overexposed_fraction)
    exposure_score = max(0.0, min(1.0, 1.0 - exposure_penalty))

    # 3. Clipping metric: Black and White clipping fractions
    black_clip_count = int(np.sum(gray <= thresh.black_clipping_threshold))
    white_clip_count = int(np.sum(gray >= thresh.white_clipping_threshold))
    clipped_fraction = float((black_clip_count + white_clip_count) / total_pixels)
    clipped_fraction = max(0.0, min(1.0, clipped_fraction))

    # 4. Contrast metric: Standard deviation of luminance normalized by dynamic range
    mean_luminance = float(np.mean(gray))
    std_luminance = float(np.std(gray))
    # Normalized contrast: std dev divided by 64.0 (half of maximum possible std dev 127.5)
    contrast_score = max(0.0, min(1.0, float(std_luminance / 64.0)))

    # Raw metrics dictionary for auditable inspection
    raw_metrics: dict[str, float] = {
        "raw_laplacian_variance": round(raw_laplacian_var, 3),
        "mean_luminance": round(mean_luminance, 2),
        "std_luminance": round(std_luminance, 2),
        "min_luminance": float(np.min(gray)),
        "max_luminance": float(np.max(gray)),
        "black_clipped_count": float(black_clip_count),
        "white_clipped_count": float(white_clip_count),
    }

    # Evaluate heuristic thresholds and collect review reasons
    review_reasons: list[str] = []

    if raw_laplacian_var < thresh.min_sharpness_variance:
        review_reasons.append(
            f"Low sharpness / high blur: Laplacian variance ({raw_laplacian_var:.1f}) is below threshold ({thresh.min_sharpness_variance:.1f})."
        )
    if underexposed_fraction > thresh.max_underexposed_fraction:
        review_reasons.append(
            f"Excessive underexposure: {underexposed_fraction * 100.0:.1f}% of pixels are underexposed (threshold: {thresh.max_underexposed_fraction * 100.0:.1f}%)."
        )
    if overexposed_fraction > thresh.max_overexposed_fraction:
        review_reasons.append(
            f"Excessive overexposure / washout: {overexposed_fraction * 100.0:.1f}% of pixels are overexposed (threshold: {thresh.max_overexposed_fraction * 100.0:.1f}%)."
        )
    if clipped_fraction > thresh.max_clipped_fraction:
        review_reasons.append(
            f"Severe pixel clipping: {clipped_fraction * 100.0:.1f}% of pixels are clipped at extreme black/white levels (threshold: {thresh.max_clipped_fraction * 100.0:.1f}%)."
        )
    if contrast_score < thresh.min_contrast_score:
        review_reasons.append(
            f"Low dynamic range / flat contrast: contrast score ({contrast_score:.2f}) is below threshold ({thresh.min_contrast_score:.2f})."
        )

    # Determine categorical quality status
    if len(review_reasons) == 0:
        quality_status = PhotometricQualityStatus.ACCEPTABLE
        requires_human_review = False
    elif (
        len(review_reasons) >= 3
        or (clipped_fraction > 0.40)
        or (raw_laplacian_var < 10.0 and (underexposed_fraction > 0.50 or overexposed_fraction > 0.50))
    ):
        quality_status = PhotometricQualityStatus.REJECTED
        requires_human_review = True
    else:
        quality_status = PhotometricQualityStatus.DEGRADED
        requires_human_review = True

    return PhotometricQualityResult(
        sharpness_score=round(sharpness_score, 4),
        exposure_score=round(exposure_score, 4),
        contrast_score=round(contrast_score, 4),
        underexposed_fraction=round(underexposed_fraction, 4),
        overexposed_fraction=round(overexposed_fraction, 4),
        clipped_fraction=round(clipped_fraction, 4),
        quality_status=quality_status,
        requires_human_review=requires_human_review,
        review_reasons=review_reasons,
        raw_metrics=raw_metrics,
        image_width=w,
        image_height=h,
        image_format=img_format,
        metric_version="1.0.0",
        disclaimer=PHOTOMETRIC_QUALITY_ADVISORY_DISCLAIMER,
    )
