"""macOS window capture through ScreenCaptureKit (macOS 14+).

Captures the actual window contents (desktop-independent), not a crop of
the visible desktop. ScreenCaptureKit is asynchronous; each call is wrapped
in a bounded threading.Event wait so a stuck framework call cannot hang
the capture worker forever.
"""

from __future__ import annotations

import threading
from io import BytesIO

from PIL import Image

from labguide.capture import CaptureError, encode_image
from labguide.config import CaptureConfig
from labguide.models import CapturedScreenshot, TargetWindow
from labguide.platforms.macos.permissions import screen_capture_granted

_SHAREABLE_CONTENT_TIMEOUT = 5.0
_SCREENSHOT_TIMEOUT = 5.0


def capture_window(target: TargetWindow, config: CaptureConfig) -> CapturedScreenshot:
    if not screen_capture_granted():
        raise CaptureError(
            "screen recording permission not granted; enable it in "
            "System Settings > Privacy & Security > Screen Recording"
        )
    cgimage = _capture_window_cgimage(target.hwnd)
    png_bytes = _cgimage_to_png(cgimage)
    image = Image.open(BytesIO(png_bytes))
    image.load()
    return encode_image(
        image.convert("RGB"),
        config.jpeg_quality,
        max_dimension=config.jpeg_max_dimension,
        max_bytes=config.jpeg_max_bytes,
    )


def _capture_window_cgimage(window_id: int):
    try:
        import ScreenCaptureKit as SCK
    except ImportError as exc:
        raise CaptureError("ScreenCaptureKit bindings are not installed") from exc

    content, error = _await_shareable_content(SCK)
    if content is None:
        raise CaptureError("screen content unavailable (permission revoked or system error)")

    sc_window = None
    for window in content.windows():
        if int(window.windowID()) == int(window_id):
            sc_window = window
            break
    if sc_window is None:
        raise CaptureError("window is no longer capturable")

    content_filter = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(sc_window)
    configuration = SCK.SCScreenshotConfiguration.alloc().init()
    configuration.setShowsCursor_(False)
    # frame is in points; pointPixelScale converts to physical pixels so the
    # JPEG matches the window's real resolution on Retina displays.
    scale = float(content_filter.pointPixelScale()) or 1.0
    frame = sc_window.frame()
    configuration.setWidth_(max(1, int(frame.size.width * scale)))
    configuration.setHeight_(max(1, int(frame.size.height * scale)))

    image, error = _await_screenshot(SCK, content_filter, configuration)
    if image is None:
        raise CaptureError("screenshot failed (window closed or capture denied)")
    return image


def _await_shareable_content(SCK):
    done = threading.Event()
    result: dict = {"content": None, "error": None}

    def handler(content, error) -> None:
        result["content"] = content
        result["error"] = error
        done.set()

    SCK.SCShareableContent.getShareableContentWithCompletionHandler_(handler)
    if not done.wait(_SHAREABLE_CONTENT_TIMEOUT):
        raise CaptureError("ScreenCaptureKit content query timed out")
    return result["content"], result["error"]


def _await_screenshot(SCK, content_filter, configuration):
    done = threading.Event()
    result: dict = {"image": None, "error": None}

    def handler(image, error) -> None:
        result["image"] = image
        result["error"] = error
        done.set()

    SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
        content_filter, configuration, handler
    )
    if not done.wait(_SCREENSHOT_TIMEOUT):
        raise CaptureError("ScreenCaptureKit screenshot timed out")
    return result["image"], result["error"]


def _cgimage_to_png(cgimage) -> bytes:
    from Foundation import NSMutableData
    from Quartz import (
        CGImageDestinationAddImage,
        CGImageDestinationCreateWithData,
        CGImageDestinationFinalize,
    )

    data = NSMutableData.alloc().init()
    destination = CGImageDestinationCreateWithData(data, "public.png", 1, None)
    if destination is None:
        raise CaptureError("could not create image encoder")
    CGImageDestinationAddImage(destination, cgimage, None)
    if not CGImageDestinationFinalize(destination):
        raise CaptureError("image encoding failed")
    return bytes(data)
