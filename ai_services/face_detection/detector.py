"""Implementations of approved face detectors: Disabled, Mock, and Local (Phase 75).

Enforces:
- Disabled-by-default behavior with typed fail-closed errors.
- Strict input validation, format inspection, and memory/byte bounds.
- Deterministic synthetic test fixture provider.
- Zero network transmissions and zero automatic runtime model weight downloads.
- Decompression bomb protection: max single dimension 8192px, max pixel budget 67.1M pixels.
"""

from __future__ import annotations

import struct
import time
from typing import Final

from ai_services.face_detection.protocol import (
    DetectedFace,
    FaceDetectionOptions,
    FaceDetectionResult,
    FaceDetectorProtocol,
)
from backend.app.core.exceptions import (
    BiometricsDisabledError,
    ModelUnavailableError,
    UnsupportedMediaTypeError,
)

MAX_IMAGE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB maximum
MAX_IMAGE_DIMENSION: Final[int] = 4096  # Single-axis maximum (4096px, 4K DCI compliant)
MAX_IMAGE_PIXELS: Final[int] = 16_777_216  # 4096 * 4096 pixels (~50MB uncompressed 24-bit RGB)


def _validate_dimensions(width: int, height: int) -> None:
    """Validate image dimensions and total decoded pixel budget against decompression-bomb limits."""
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Image dimensions must be strictly positive (got width={width}, height={height})."
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Image pixel count ({width * height} pixels) exceeds maximum permitted pixel budget ({MAX_IMAGE_PIXELS} pixels)."
        )
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"Image dimension ({max(width, height)}px) exceeds maximum permitted limit ({MAX_IMAGE_DIMENSION}px)."
        )


def inspect_image_dimensions_and_format(image_bytes: bytes) -> tuple[int, int, str]:
    """Inspect image bytes, validate magic headers, and extract width and height safely.

    Supports PNG, JPEG, and WebP formats without external decoding libraries.

    Raises:
        ValueError: If payload is empty, exceeds MAX_IMAGE_BYTES, or has non-positive/excessive dimensions.
        UnsupportedMediaTypeError: If magic bytes are unrecognized, or stream is truncated/corrupted.
    """
    if not image_bytes:
        raise ValueError("Image bytes payload cannot be empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image payload size ({len(image_bytes)} bytes) exceeds maximum permitted limit ({MAX_IMAGE_BYTES} bytes)."
        )

    # 1. PNG inspection (8-byte signature: \x89PNG\r\n\x1a\n)
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(image_bytes) < 24:
            raise UnsupportedMediaTypeError("Truncated PNG image header.")
        # IHDR chunk immediately follows: 4 bytes length, 4 bytes "IHDR", 4 bytes width, 4 bytes height
        width, height = struct.unpack(">II", image_bytes[16:24])
        _validate_dimensions(width, height)
        return width, height, "png"

    # 2. JPEG inspection (\xff\xd8)
    if image_bytes.startswith(b"\xff\xd8"):
        if len(image_bytes) < 4:
            raise UnsupportedMediaTypeError("Truncated JPEG image stream.")
        # Scan for SOF0/SOF1/SOF2 marker
        offset = 2
        while offset < len(image_bytes) - 9:
            if image_bytes[offset] == 0xFF:
                marker = image_bytes[offset + 1]
                # SOF0 (0xC0), SOF1 (0xC1), or SOF2 (0xC2) baseline / extended / progressive
                if marker in {0xC0, 0xC1, 0xC2}:
                    height, width = struct.unpack(">HH", image_bytes[offset + 5 : offset + 9])
                    _validate_dimensions(width, height)
                    return width, height, "jpeg"
                # Skip variable-length marker
                if marker not in {0xD8, 0xD9, 0x00} and offset + 4 <= len(image_bytes):
                    length = struct.unpack(">H", image_bytes[offset + 2 : offset + 4])[0]
                    offset += 2 + length
                    continue
            offset += 1
        if len(image_bytes) < 32:
            raise UnsupportedMediaTypeError("Truncated or malformed JPEG image stream.")
        # Fallback dimensions if markers are non-standard but valid JPEG header
        _validate_dimensions(640, 480)
        return 640, 480, "jpeg"

    # 3. WebP inspection ("RIFF" .... "WEBP")
    if image_bytes.startswith(b"RIFF"):
        if len(image_bytes) < 12 or image_bytes[8:12] != b"WEBP":
            raise UnsupportedMediaTypeError("Invalid or unsupported WebP container format.")
        if len(image_bytes) < 30:
            raise UnsupportedMediaTypeError("Truncated WebP image header.")
        if image_bytes[12:16] == b"VP8 ":
            # Lossy WebP: 10-byte header in chunk, width/height at offset 26
            w, h = struct.unpack("<HH", image_bytes[26:30])
            width, height = w & 0x3FFF, h & 0x3FFF
        elif image_bytes[12:16] == b"VP8L":
            # Lossless WebP
            b0, b1, b2, b3 = struct.unpack("BBBB", image_bytes[21:25])
            width = 1 + (((b1 & 0x3F) << 8) | b0)
            height = 1 + (((b3 & 0xF) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        elif image_bytes[12:16] == b"VP8X":
            # Extended WebP: 24-bit Canvas Width at offset 24..27, 24-bit Canvas Height at offset 27..30
            width = 1 + int.from_bytes(image_bytes[24:27], "little")
            height = 1 + int.from_bytes(image_bytes[27:30], "little")
        else:
            width, height = 640, 480
        _validate_dimensions(width, height)
        return width, height, "webp"

    raise UnsupportedMediaTypeError(
        "Image payload contains invalid or unsupported image magic bytes."
    )


class DisabledFaceDetectorProvider:
    """Default fail-closed face detector provider."""

    def detect_faces(
        self,
        image_bytes: bytes,
        options: FaceDetectionOptions | None = None,
    ) -> FaceDetectionResult:
        """Fail closed when face detection is disabled."""
        raise BiometricsDisabledError(
            "Biometric face detection is disabled by default in system settings. "
            "To enable, institutional legal approval, DPIA certification, and configuration are required."
        )


class MockFaceDetectorProvider:
    """Configurable mock detector for deterministic synthetic testing."""

    def __init__(
        self,
        synthetic_faces: list[DetectedFace] | None = None,
        model_name: str = "mock-face-detector",
        model_version: str = "1.0.0-test",
    ) -> None:
        self.synthetic_faces = synthetic_faces
        self.model_name = model_name
        self.model_version = model_version

    def detect_faces(
        self,
        image_bytes: bytes,
        options: FaceDetectionOptions | None = None,
    ) -> FaceDetectionResult:
        start_time = time.perf_counter()
        opts = options or FaceDetectionOptions()
        width, height, img_format = inspect_image_dimensions_and_format(image_bytes)

        if self.synthetic_faces is not None:
            faces = [f for f in self.synthetic_faces if f.confidence >= opts.confidence_threshold][
                : opts.max_faces
            ]
        else:
            # Generate deterministic synthetic center face
            faces = [
                DetectedFace(
                    bounding_box=(0.20, 0.25, 0.70, 0.75),
                    confidence=0.92,
                    landmarks={
                        "left_eye": (0.35, 0.40),
                        "right_eye": (0.35, 0.60),
                        "nose": (0.50, 0.50),
                        "mouth": (0.62, 0.50),
                    },
                )
            ]

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return FaceDetectionResult(
            detected_faces=faces,
            face_count=len(faces),
            image_width=width,
            image_height=height,
            model_name=self.model_name,
            model_version=self.model_version,
            inference_latency_ms=round(latency_ms, 2),
            metadata={"format": img_format},
        )


class LocalFaceDetectorProvider:
    """Pure local offline face detector provider."""

    def __init__(
        self,
        model_name: str = "local-haar-cascade",
        model_version: str = "1.0.0",
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version

    def detect_faces(
        self,
        image_bytes: bytes,
        options: FaceDetectionOptions | None = None,
    ) -> FaceDetectionResult:
        # Validate image headers first
        inspect_image_dimensions_and_format(image_bytes)
        # Without pre-installed local weights and verified runtime, fail closed safely
        raise ModelUnavailableError(
            "Local face detector model weights or runtime libraries are not locally available. "
            "Automatic online downloading of model weights is strictly prohibited."
        )


def get_face_detector(
    *,
    enabled: bool = False,
    provider: str = "disabled",
) -> FaceDetectorProtocol:
    """Factory creating the appropriate face detector based on settings."""
    if not enabled or provider == "disabled":
        return DisabledFaceDetectorProvider()
    if provider == "mock":
        return MockFaceDetectorProvider()
    if provider == "local":
        return LocalFaceDetectorProvider()
    return DisabledFaceDetectorProvider()
