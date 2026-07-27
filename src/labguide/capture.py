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


def capture_primary_display(jpeg_quality: int) -> CapturedScreenshot:
    with mss() as screen_capture:
        monitor = screen_capture.monitors[1]
        shot = screen_capture.grab(monitor)

    return _encode(shot, jpeg_quality)


def capture_window_region(
    x: int, y: int, width: int, height: int, jpeg_quality: int
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

    return _encode(shot, jpeg_quality)


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


def _encode(shot, jpeg_quality: int) -> CapturedScreenshot:
    image = Image.frombytes("RGB", shot.size, shot.rgb)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=jpeg_quality)
    image_bytes = buffer.getvalue()

    context = ScreenContext(
        os_name=_normalize_platform(platform.system()),
        screen_width=int(shot.width),
        screen_height=int(shot.height),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return CapturedScreenshot(
        image_base64=base64.b64encode(image_bytes).decode("ascii"),
        context=context,
        byte_count=len(image_bytes),
    )


def _normalize_platform(system_name: str) -> str:
    lowered = system_name.lower()
    if lowered.startswith("darwin"):
        return "macos"
    return lowered
