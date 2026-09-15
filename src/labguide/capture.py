from __future__ import annotations

import base64
from datetime import datetime, timezone
from io import BytesIO
import platform

from mss import mss
from PIL import Image

from labguide.models import CapturedScreenshot, ScreenContext


class CaptureError(RuntimeError):
    """Pixel capture failed. Message is a category, never captured content."""


def capture_primary_display(
    jpeg_quality: int, *, max_dimension: int = 0, max_bytes: int = 0
) -> CapturedScreenshot:
    with mss() as screen_capture:
        monitor = screen_capture.monitors[1]
        shot = screen_capture.grab(monitor)

    return _encode(shot, jpeg_quality, max_dimension=max_dimension, max_bytes=max_bytes)


def capture_window_region(
    x: int,
    y: int,
    width: int,
    height: int,
    jpeg_quality: int,
    *,
    max_dimension: int = 0,
    max_bytes: int = 0,
) -> CapturedScreenshot:
    """Capture a physical-pixel region, clamped to the virtual screen.

    Supports negative coordinates and windows spanning secondary monitors.
    Raises CaptureError when the region has no visible area.
    """
    with mss() as screen_capture:
        virtual = screen_capture.monitors[0]
        region = clamp_region_to_virtual_screen(
            x,
            y,
            width,
            height,
            virtual_left=int(virtual["left"]),
            virtual_top=int(virtual["top"]),
            virtual_width=int(virtual["width"]),
            virtual_height=int(virtual["height"]),
        )
        if region is None:
            raise CaptureError("window is fully outside the visible desktop")
        left, top, clamped_width, clamped_height = region
        shot = screen_capture.grab(
            {"left": left, "top": top, "width": clamped_width, "height": clamped_height}
        )

    return _encode(shot, jpeg_quality, max_dimension=max_dimension, max_bytes=max_bytes)


def clamp_region_to_virtual_screen(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    virtual_left: int,
    virtual_top: int,
    virtual_width: int,
    virtual_height: int,
) -> tuple[int, int, int, int] | None:
    """Intersect a region with the virtual-screen bounding box.

    Pure helper, unit-tested without a display. Returns None when the region
    has no visible area.
    """
    left = max(x, virtual_left)
    top = max(y, virtual_top)
    right = min(x + width, virtual_left + virtual_width)
    bottom = min(y + height, virtual_top + virtual_height)
    if right - left < 1 or bottom - top < 1:
        return None
    return (left, top, right - left, bottom - top)


def encode_image(
    image: Image.Image,
    jpeg_quality: int,
    *,
    max_dimension: int = 0,
    max_bytes: int = 0,
) -> CapturedScreenshot:
    """Encode a PIL image as bounded JPEG/base64 capture data.

    ``max_dimension`` downscales the longest side before encoding.
    ``max_bytes`` first steps the JPEG quality down (to a floor of 30), then
    downscales the image further until the encoded payload fits. A zero
    value disables each limit.
    """
    if max_dimension > 0 and max(image.size) > max_dimension:
        image = image.copy()
        image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    quality = max(30, jpeg_quality)
    image_bytes = _save_jpeg(image, quality)
    while max_bytes > 0 and len(image_bytes) > max_bytes and quality > 30:
        quality = max(30, quality - 15)
        image_bytes = _save_jpeg(image, quality)

    # Quality floor reached but still too large: shrink dimensions until the
    # payload fits or the image becomes unreasonably small.
    while max_bytes > 0 and len(image_bytes) > max_bytes and max(image.size) > 320:
        image = image.resize(
            (max(1, int(image.width * 0.75)), max(1, int(image.height * 0.75))),
            Image.LANCZOS,
        )
        image_bytes = _save_jpeg(image, quality)

    context = ScreenContext(
        os_name=_normalize_platform(platform.system()),
        screen_width=int(image.width),
        screen_height=int(image.height),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return CapturedScreenshot(
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        context=context,
        byte_count=len(image_bytes),
    )


def _save_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _encode(
    shot, jpeg_quality: int, *, max_dimension: int = 0, max_bytes: int = 0
) -> CapturedScreenshot:
    image = Image.frombytes("RGB", shot.size, shot.rgb)
    return encode_image(
        image, jpeg_quality, max_dimension=max_dimension, max_bytes=max_bytes
    )


def _normalize_platform(system_name: str) -> str:
    lowered = system_name.lower()
    if lowered.startswith("darwin"):
        return "macos"
    return lowered
