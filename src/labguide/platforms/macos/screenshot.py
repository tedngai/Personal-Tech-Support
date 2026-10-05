"""macOS window capture: ScreenCaptureKit with a CGWindowList fallback.

Primary path is ScreenCaptureKit (true window contents, desktop-independent).
On macOS 26 the PyObjC 11.x bindings lag the framework: SCScreenshotConfiguration
lost its +configuration factory and its pixelFormat accessors, so the
framework's own selector walk raises "unrecognized selector" mid-capture.
Those exceptions arrive in Python as NSInvalidArgumentException -> ValueError
and are caught; capture then falls back to CGWindowListCreateImage, which
remains functional on Tahoe (deprecated, may be removed by a future release;
a None result becomes a readable CaptureError).

The runtime shim (_ensure_sck_stubs) bridges the missing accessors at the
ObjC level so the SCK path can complete on OS/binding combinations where the
class is intact; an incomplete walk degrades cleanly to the fallback.

Bounded waits: every async framework call is wrapped in a threading.Event
wait so a stuck call cannot hang the capture worker forever.
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

_stubs_applied = False


def capture_window(target: TargetWindow, config: CaptureConfig) -> CapturedScreenshot:
    if not screen_capture_granted():
        raise CaptureError(
            "screen recording permission not granted; enable it in "
            "System Settings > Privacy & Security > Screen Recording"
        )
    errors: list[str] = []
    cgimage = None
    try:
        cgimage = _capture_window_cgimage_sck(target.hwnd)
    except Exception:
        # Bridging gaps surface as NSInvalidArgumentException (ValueError);
        # stage and category only, never captured content.
        errors.append("ScreenCaptureKit path")
    if cgimage is None:
        try:
            cgimage = _capture_window_cgimage_cgl(target.hwnd)
        except Exception:
            errors.append("CGWindowList path")
    if cgimage is None:
        detail = " and ".join(errors) if errors else "window closed or not capturable"
        raise CaptureError(f"window capture failed ({detail})")
    png_bytes = _cgimage_to_png(cgimage)
    image = Image.open(BytesIO(png_bytes))
    image.load()
    return encode_image(
        image.convert("RGB"),
        config.jpeg_quality,
        max_dimension=config.jpeg_max_dimension,
        max_bytes=config.jpeg_max_bytes,
    )


def _capture_window_cgimage_sck(window_id: int):
    """ScreenCaptureKit path. Raises CaptureError on capture-level failures."""
    try:
        import ScreenCaptureKit as SCK
    except ImportError as exc:
        raise CaptureError("ScreenCaptureKit bindings are not installed") from exc
    _ensure_sck_stubs(SCK)

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
    try:
        configuration.setIgnoreClipping_(True)
    except Exception:
        pass
    # frame is in points; pointPixelScale converts to physical pixels so the
    # JPEG matches the window's real resolution on Retina displays.
    scale = _point_pixel_scale(content_filter)
    frame = sc_window.frame()
    configuration.setWidth_(max(1, int(frame.size.width * scale)))
    configuration.setHeight_(max(1, int(frame.size.height * scale)))

    image, error = _await_screenshot(SCK, content_filter, configuration)
    if image is None:
        raise CaptureError("screenshot failed (window closed or capture denied)")
    return image


def _capture_window_cgimage_cgl(window_id: int):
    """CGWindowListCreateImage path (deprecated API, functional on macOS 26).

    Captures the window without shadow framing at best available resolution.
    Returns None when the API has been removed or the window is gone.
    """
    from Quartz import (
        CGWindowListCreateImage,
        CGRectMake,
        kCGWindowImageBestResolution,
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowListOptionIncludingWindow,
    )

    rect = CGRectMake(0, 0, 0, 0)
    options = kCGWindowImageBestResolution | kCGWindowImageBoundsIgnoreFraming
    return CGWindowListCreateImage(
        rect, kCGWindowListOptionIncludingWindow, window_id, options
    )


def _point_pixel_scale(content_filter) -> float:
    try:
        if content_filter.respondsToSelector_("pointPixelScale"):
            return float(content_filter.pointPixelScale()) or 1.0
    except Exception:
        pass
    return 1.0


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


def _ensure_sck_stubs(SCK) -> None:
    """Bridge SCScreenshotConfiguration accessors missing from PyObjC 11.x.

    macOS 26 renamed/removed several internals (pixelFormat, +configuration)
    while the framework still walks them by selector. classAddMethods supplies
    ObjC-level implementations backed by a Python dict so the walk can
    complete. Handlers are void and return exactly None; a wrong return type
    from a bridged handler aborts the process (OC_PythonException), so
    struct-returning properties use plain tuples with matching signatures.
    An incomplete walk raises inside captureImage... and is caught by
    capture_window, which falls back to CGWindowListCreateImage.
    """
    global _stubs_applied
    if _stubs_applied:
        return
    _stubs_applied = True

    import objc

    try:
        from CoreMedia import kCMPixelFormat_32BGRA
    except Exception:
        kCMPixelFormat_32BGRA = int.from_bytes(b"BGRA", "big")

    store: dict[int, int] = {}
    cls = SCK.SCScreenshotConfiguration

    def _setPixelFormat_(self, value) -> None:
        store[id(self)] = value

    def _pixelFormat(self):
        return store.get(id(self), kCMPixelFormat_32BGRA)

    def _setCaptureResolution_(self, value) -> None:
        pass

    def _captureResolution(self):
        return 0

    def _captureDynamicRange(self):
        return 0  # SCScreenshotDynamicRangeStandard

    def _setCaptureDynamicRange_(self, value) -> None:
        pass

    def _copyWithZone_(self, zone):
        new = cls.alloc().init()
        try:
            new.setShowsCursor_(bool(self.showsCursor()))
            new.setIgnoreClipping_(bool(self.ignoreClipping()))
            new.setWidth_(int(self.width()))
            new.setHeight_(int(self.height()))
        except Exception:
            pass
        return new

    def _capturesAudio(self):
        return False

    def _setCapturesAudio_(self, value) -> None:
        pass

    def _queueDepth(self):
        return 3

    def _setQueueDepth_(self, value) -> None:
        pass

    def _showMouseClicks(self):
        return False

    def _setShowMouseClicks_(self, value) -> None:
        pass

    def _mouseClickRadius(self):
        return 0.0

    def _setMouseClickRadius_(self, value) -> None:
        pass

    def _mouseClickColor(self):
        return None

    def _setMouseClickColor_(self, value) -> None:
        pass

    def _cursorScale(self):
        return 1.0

    def _setCursorScale_(self, value) -> None:
        pass

    def _destinationColorSpace(self):
        return None

    def _setDestinationColorSpace_(self, value) -> None:
        pass

    def _minimumFrameInterval(self):
        # macOS 26's internal CMTime layout has 5 members.
        return (1, 30, 0, 0, 0)

    def _setMinimumFrameInterval_(self, value) -> None:
        pass

    def _scalesToFit(self):
        return False

    def _setScalesToFit_(self, value) -> None:
        pass

    def _ignoresShadows(self):
        return bool(self.ignoreClipping())

    def _setIgnoresShadows_(self, value) -> None:
        pass

    def _preservesAspectRatio(self):
        return True

    def _setPreservesAspectRatio_(self, value) -> None:
        pass

    def _excludesCurrentProcessAudio(self):
        return False

    def _setExcludesCurrentProcessAudio_(self, value) -> None:
        pass

    def _cropNewsroomToUpperLeftCorner(self):
        return False

    def _setCropNewsroomToUpperLeftCorner_(self, value) -> None:
        pass

    def _presentsWithTransaction(self):
        return False

    def _setPresentsWithTransaction_(self, value) -> None:
        pass

    def _minimumQueueDepth(self):
        return 3

    def _setMinimumQueueDepth_(self, value) -> None:
        pass

    def _deliverDisplayFrameNotifications(self):
        return False

    def _setDeliverDisplayFrameNotifications_(self, value) -> None:
        pass

    def _presenterOverlayPrivacyAlertSetting(self):
        return 0

    def _setPresenterOverlayPrivacyAlertSetting_(self, value) -> None:
        pass

    def _screenCaptureMode(self):
        return 0

    def _setScreenCaptureMode_(self, value) -> None:
        pass

    def _sampleRate(self):
        return 0

    def _setSampleRate_(self, value) -> None:
        pass

    def _channelCount(self):
        return 0

    def _setChannelCount_(self, value) -> None:
        pass

    def _isScreenshot(self):
        return True

    def _setScreenshot_(self, value) -> None:
        pass

    def _backgroundColor(self):
        return None

    def _setBackgroundColor_(self, value) -> None:
        pass

    def _contentWidth(self):
        return int(self.width())

    def _setContentWidth_(self, value) -> None:
        pass

    def _contentHeight(self):
        return int(self.height())

    def _setContentHeight_(self, value) -> None:
        pass

    selectors = [
        objc.selector(_setPixelFormat_, selector=b"setPixelFormat:", signature=b"v@:I"),
        objc.selector(_pixelFormat, selector=b"pixelFormat", signature=b"I@:"),
        objc.selector(_setCaptureResolution_, selector=b"setCaptureResolution:", signature=b"v@:I"),
        objc.selector(_captureResolution, selector=b"captureResolution", signature=b"I@:"),
        objc.selector(_captureDynamicRange, selector=b"captureDynamicRange", signature=b"Q@:"),
        objc.selector(_setCaptureDynamicRange_, selector=b"setCaptureDynamicRange:", signature=b"v@:Q"),
        objc.selector(_copyWithZone_, selector=b"copyWithZone:", signature=b"@@:^{_NSZone=}"),
        objc.selector(_capturesAudio, selector=b"capturesAudio", signature=b"Z@:"),
        objc.selector(_setCapturesAudio_, selector=b"setCapturesAudio:", signature=b"v@:Z"),
        objc.selector(_queueDepth, selector=b"queueDepth", signature=b"Q@:"),
        objc.selector(_setQueueDepth_, selector=b"setQueueDepth:", signature=b"v@:Q"),
        objc.selector(_showMouseClicks, selector=b"showMouseClicks", signature=b"Z@:"),
        objc.selector(_setShowMouseClicks_, selector=b"setShowMouseClicks:", signature=b"v@:Z"),
        objc.selector(_mouseClickRadius, selector=b"mouseClickRadius", signature=b"d@:"),
        objc.selector(_setMouseClickRadius_, selector=b"setMouseClickRadius:", signature=b"v@:d"),
        objc.selector(_mouseClickColor, selector=b"mouseClickColor", signature=b"@@:"),
        objc.selector(_setMouseClickColor_, selector=b"setMouseClickColor:", signature=b"v@:@"),
        objc.selector(_cursorScale, selector=b"cursorScale", signature=b"d@:"),
        objc.selector(_setCursorScale_, selector=b"setCursorScale:", signature=b"v@:d"),
        objc.selector(_destinationColorSpace, selector=b"destinationColorSpace", signature=b"@@:"),
        objc.selector(_setDestinationColorSpace_, selector=b"setDestinationColorSpace:", signature=b"v@:@"),
        objc.selector(_minimumFrameInterval, selector=b"minimumFrameInterval", signature=b"{CMTime=qqqqq}@:"),
        objc.selector(_setMinimumFrameInterval_, selector=b"setMinimumFrameInterval:", signature=b"v@:{CMTime=qqqqq}"),
        objc.selector(_scalesToFit, selector=b"scalesToFit", signature=b"Z@:"),
        objc.selector(_setScalesToFit_, selector=b"setScalesToFit:", signature=b"v@:Z"),
        objc.selector(_ignoresShadows, selector=b"ignoresShadows", signature=b"Z@:"),
        objc.selector(_setIgnoresShadows_, selector=b"setIgnoresShadows:", signature=b"v@:Z"),
        objc.selector(_preservesAspectRatio, selector=b"preservesAspectRatio", signature=b"Z@:"),
        objc.selector(_setPreservesAspectRatio_, selector=b"setPreservesAspectRatio:", signature=b"v@:Z"),
        objc.selector(_excludesCurrentProcessAudio, selector=b"excludesCurrentProcessAudio", signature=b"Z@:"),
        objc.selector(_setExcludesCurrentProcessAudio_, selector=b"setExcludesCurrentProcessAudio:", signature=b"v@:Z"),
        objc.selector(_cropNewsroomToUpperLeftCorner, selector=b"cropNewsroomToUpperLeftCorner", signature=b"Z@:"),
        objc.selector(_setCropNewsroomToUpperLeftCorner_, selector=b"setCropNewsroomToUpperLeftCorner:", signature=b"v@:Z"),
        objc.selector(_presentsWithTransaction, selector=b"presentsWithTransaction", signature=b"Z@:"),
        objc.selector(_setPresentsWithTransaction_, selector=b"setPresentsWithTransaction:", signature=b"v@:Z"),
        objc.selector(_minimumQueueDepth, selector=b"minimumQueueDepth", signature=b"Q@:"),
        objc.selector(_setMinimumQueueDepth_, selector=b"setMinimumQueueDepth:", signature=b"v@:Q"),
        objc.selector(_deliverDisplayFrameNotifications, selector=b"deliverDisplayFrameNotifications", signature=b"Z@:"),
        objc.selector(_setDeliverDisplayFrameNotifications_, selector=b"setDeliverDisplayFrameNotifications:", signature=b"v@:Z"),
        objc.selector(_presenterOverlayPrivacyAlertSetting, selector=b"presenterOverlayPrivacyAlertSetting", signature=b"Q@:"),
        objc.selector(_setPresenterOverlayPrivacyAlertSetting_, selector=b"setPresenterOverlayPrivacyAlertSetting:", signature=b"v@:Q"),
        objc.selector(_screenCaptureMode, selector=b"screenCaptureMode", signature=b"Q@:"),
        objc.selector(_setScreenCaptureMode_, selector=b"setScreenCaptureMode:", signature=b"v@:Q"),
        objc.selector(_sampleRate, selector=b"sampleRate", signature=b"Q@:"),
        objc.selector(_setSampleRate_, selector=b"setSampleRate:", signature=b"v@:Q"),
        objc.selector(_channelCount, selector=b"channelCount", signature=b"Q@:"),
        objc.selector(_setChannelCount_, selector=b"setChannelCount:", signature=b"v@:Q"),
        objc.selector(_isScreenshot, selector=b"isScreenshot", signature=b"Z@:"),
        objc.selector(_setScreenshot_, selector=b"setScreenshot:", signature=b"v@:Z"),
        objc.selector(_backgroundColor, selector=b"backgroundColor", signature=b"@@:"),
        objc.selector(_setBackgroundColor_, selector=b"setBackgroundColor:", signature=b"v@:@"),
        objc.selector(_contentWidth, selector=b"contentWidth", signature=b"Q@:"),
        objc.selector(_setContentWidth_, selector=b"setContentWidth:", signature=b"v@:Q"),
        objc.selector(_contentHeight, selector=b"contentHeight", signature=b"Q@:"),
        objc.selector(_setContentHeight_, selector=b"setContentHeight:", signature=b"v@:Q"),
    ]

    try:
        objc.classAddMethods(cls, selectors)
    except Exception:
        # Stubs are best-effort; the CGL fallback covers capture regardless.
        pass
