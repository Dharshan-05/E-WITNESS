"""Privacy-preserving face redaction module (Phase 75).

Enforces:
- Non-destructive processing: original evidence bytes and data are never mutated or overwritten.
- Fail-closed redaction: any parsing or decoding error halts processing safely.
- Multiple redaction styles: solid box (black/charcoal rectangle), Gaussian blur, pixelation.
- Configurable padding around detected bounding box (e.g. 10% default) to cover hairline/ears.
- Mandatory non-anonymization advisory disclaimer.
- Complete isolation: zero biometric template generation, zero identity matching.
- Explicit outcome semantics:
    - is_redacted = True only when at least one face region has been visually redacted.
    - requires_human_review = True when no faces are detected, when candidate faces fall below confidence threshold, or when bounding boxes clip to invalid dimensions.
    - review_reason provides an auditable reason why manual human inspection is required.
    - unredacted images are never represented as anonymized or redacted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import io
import re
from typing import Final
import warnings

from PIL import Image, ImageDraw, ImageFilter

from ai_services.face_detection.detector import MAX_IMAGE_PIXELS, _validate_dimensions
from ai_services.face_detection.protocol import DetectedFace
from backend.app.core.exceptions import UnsupportedMediaTypeError

# Configure Pillow decoder-level decompression bomb threshold
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

PRIVACY_REDACTION_ADVISORY_DISCLAIMER: Final[str] = (
    "PRIVACY REDACTION ADVISORY: Face redaction (blur/pixelate/mask) reduces visual "
    "identifiability of detected facial regions for privacy protection. It does not provide "
    "absolute anonymization or mathematical differential privacy guarantees. Contextual clues, "
    "clothing, gait, or background details may remain identifiable. Original unredacted evidence "
    "is preserved intact under strict chain-of-custody controls."
)


def _sanitize_error_message(exc: Exception) -> str:
    """Sanitize error messages to eliminate memory pointers, paths, and internal object representations."""
    raw = str(exc)
    # Strip hexadecimal memory addresses (e.g., at 0x000001A2B3C4)
    cleaned = re.sub(r"0x[0-9a-fA-F]+", "[redacted_address]", raw)
    # Strip Windows or Unix file paths
    cleaned = re.sub(r"(?:[a-zA-Z]:[\\/]|(?:\.{1,2}[\\/])|\/)[^\s:;,>'\"]+", "[redacted_path]", cleaned)
    # Strip <... at ...> object representations
    cleaned = re.sub(r"<[^>]+>", "[internal_object]", cleaned)
    first_line = cleaned.splitlines()[0] if cleaned else "Unknown error"
    return first_line.strip()


class RedactionStyle(StrEnum):
    """Approved visual redaction techniques."""

    SOLID_BOX = "solid_box"
    BLUR = "blur"
    PIXELATE = "pixelate"


@dataclass(frozen=True)
class RedactionPolicy:
    """Configurable parameters governing face redaction execution."""

    min_confidence: float = 0.5
    padding_ratio: float = 0.10  # 10% expansion on each side
    style: RedactionStyle = RedactionStyle.SOLID_BOX
    box_fill_color: tuple[int, int, int] = (18, 18, 18)  # Charcoal black for solid box
    blur_radius: int = 20  # Strong Gaussian blur radius
    pixelate_block_size: int = 16  # Block size for pixelation

    def __post_init__(self) -> None:
        if not (0.0 <= self.min_confidence <= 1.0):
            raise ValueError("min_confidence must be between 0.0 and 1.0.")
        if not (0.0 <= self.padding_ratio <= 0.5):
            raise ValueError("padding_ratio must be between 0.0 and 0.5.")
        if self.blur_radius < 1:
            raise ValueError("blur_radius must be at least 1.")
        if self.pixelate_block_size < 2:
            raise ValueError("pixelate_block_size must be at least 2.")


@dataclass(frozen=True)
class RedactedImageResult:
    """Structured result of a face redaction operation."""

    redacted_bytes: bytes
    redacted_faces_count: int
    image_format: str
    image_width: int
    image_height: int
    style: str
    is_redacted: bool = False
    requires_human_review: bool = False
    review_reason: str | None = None
    disclaimer: str = PRIVACY_REDACTION_ADVISORY_DISCLAIMER
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.redacted_faces_count < 0:
            raise ValueError("redacted_faces_count cannot be negative.")
        if self.image_width < 1 or self.image_height < 1:
            raise ValueError("image_width and image_height must be positive integers.")


def apply_face_redaction(
    image_bytes: bytes,
    detected_faces: list[DetectedFace],
    policy: RedactionPolicy | None = None,
) -> RedactedImageResult:
    """Apply privacy-preserving face redaction to an image without mutating original evidence.

    Raises:
        ValueError: If image_bytes is empty.
        UnsupportedMediaTypeError: If the image cannot be decoded.
    """
    if not image_bytes:
        raise ValueError("Image bytes payload cannot be empty.")

    pol = policy or RedactionPolicy()

    try:
        with warnings.catch_warnings():
            # Escalate Pillow decompression bomb warnings to exceptions so mid-range decompression
            # bombs (MAX_IMAGE_PIXELS < pixels <= 2*MAX_IMAGE_PIXELS) fail closed before allocating.
            warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as pil_img:
                # Pre-validate dimensions before triggering full raster decompression/copy
                width, height = pil_img.size
                _validate_dimensions(width, height)
                # Copy image to guarantee non-destructive immutability
                work_img = pil_img.copy()
                img_format = (pil_img.format or "PNG").upper()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError) as exc:
        sanitized = _sanitize_error_message(exc)
        raise UnsupportedMediaTypeError(
            f"Image exceeds safe dimension or decompression limits: {sanitized}"
        ) from exc
    except Exception as exc:
        sanitized = _sanitize_error_message(exc)
        raise UnsupportedMediaTypeError(
            f"Failed to decode image for redaction: {sanitized}"
        ) from exc

    # Ensure RGB or RGBA mode for drawing/filters
    if work_img.mode not in ("RGB", "RGBA"):
        work_img = work_img.convert("RGB")

    # Partition candidate detections by confidence threshold
    eligible_faces: list[DetectedFace] = []
    low_confidence_faces: list[DetectedFace] = []
    for face in detected_faces:
        if face.confidence >= pol.min_confidence:
            eligible_faces.append(face)
        else:
            low_confidence_faces.append(face)

    redacted_count = 0
    clipping_failure = False

    for face in eligible_faces:
        ymin, xmin, ymax, xmax = face.bounding_box
        box_w = xmax - xmin
        box_h = ymax - ymin

        # Apply padding
        pad_x = box_w * pol.padding_ratio
        pad_y = box_h * pol.padding_ratio

        top = max(0, int((ymin - pad_y) * height))
        left = max(0, int((xmin - pad_x) * width))
        bottom = min(height, int((ymax + pad_y) * height))
        right = min(width, int((xmax + pad_x) * width))

        if bottom <= top or right <= left:
            clipping_failure = True
            continue

        box_tuple = (left, top, right, bottom)

        if pol.style == RedactionStyle.SOLID_BOX:
            draw = ImageDraw.Draw(work_img)
            draw.rectangle(box_tuple, fill=pol.box_fill_color)
        elif pol.style == RedactionStyle.BLUR:
            region = work_img.crop(box_tuple)
            blurred = region.filter(ImageFilter.GaussianBlur(radius=pol.blur_radius))
            work_img.paste(blurred, box_tuple)
        elif pol.style == RedactionStyle.PIXELATE:
            region = work_img.crop(box_tuple)
            rw = max(1, (right - left) // pol.pixelate_block_size)
            rh = max(1, (bottom - top) // pol.pixelate_block_size)
            small = region.resize((rw, rh), resample=Image.Resampling.BILINEAR)
            pixelated = small.resize((right - left, bottom - top), resample=Image.Resampling.NEAREST)
            work_img.paste(pixelated, box_tuple)
        else:
            # Default fallback to solid box
            draw = ImageDraw.Draw(work_img)
            draw.rectangle(box_tuple, fill=pol.box_fill_color)

        redacted_count += 1

    # Encode to bytes preserving original format
    save_format = img_format if img_format in ("PNG", "JPEG", "WEBP") else "PNG"
    # JPEG does not support RGBA mode
    if save_format == "JPEG" and work_img.mode == "RGBA":
        work_img = work_img.convert("RGB")

    out_buf = io.BytesIO()
    work_img.save(out_buf, format=save_format)
    redacted_bytes = out_buf.getvalue()

    # Determine explicit outcome semantics
    is_redacted = redacted_count > 0
    requires_human_review = False
    review_reasons: list[str] = []

    if len(detected_faces) == 0:
        requires_human_review = True
        review_reasons.append(
            "No faces detected in input image; human review required to confirm no unredacted individuals or bystanders are present."
        )
    elif redacted_count == 0:
        requires_human_review = True
        review_reasons.append(
            f"No faces met detection confidence threshold (min_confidence={pol.min_confidence:.2f}); {len(low_confidence_faces)} candidate detection(s) below threshold require human review."
        )
    else:
        if len(low_confidence_faces) > 0:
            requires_human_review = True
            review_reasons.append(
                f"Partial redaction: {redacted_count} face(s) redacted, but {len(low_confidence_faces)} candidate detection(s) fell below confidence threshold ({pol.min_confidence:.2f}); human review required."
            )
        if clipping_failure:
            requires_human_review = True
            review_reasons.append(
                "One or more eligible detected face bounding boxes had non-positive dimensions after edge clipping and could not be drawn."
            )

    review_reason = " | ".join(review_reasons) if review_reasons else None

    return RedactedImageResult(
        redacted_bytes=redacted_bytes,
        redacted_faces_count=redacted_count,
        image_format=save_format.lower(),
        image_width=width,
        image_height=height,
        style=pol.style.value if isinstance(pol.style, RedactionStyle) else str(pol.style),
        is_redacted=is_redacted,
        requires_human_review=requires_human_review,
        review_reason=review_reason,
        disclaimer=PRIVACY_REDACTION_ADVISORY_DISCLAIMER,
        metadata={
            "redaction_style": pol.style.value
            if isinstance(pol.style, RedactionStyle)
            else str(pol.style),
            "min_confidence": str(pol.min_confidence),
            "padding_ratio": str(pol.padding_ratio),
            "is_redacted": str(is_redacted),
            "requires_human_review": str(requires_human_review),
        },
    )

