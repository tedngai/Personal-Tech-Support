from __future__ import annotations

import base64
from datetime import datetime, timezone
from io import BytesIO
import platform

from mss import mss
from PIL import Image

from labguide.models import CapturedScreenshot, ScreenContext


def capture_primary_display(jpeg_quality: int) -> CapturedScreenshot:
    with mss() as screen_capture:
        monitor = screen_capture.monitors[1]
        shot = screen_capture.grab(monitor)

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
