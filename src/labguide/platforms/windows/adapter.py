"""Windows platform adapter.

Wraps the existing Win32 modules (win32_window, global_hotkey, ui_probe)
behind the shared PlatformAdapter contract. No behavior change.
"""

from __future__ import annotations

from typing import Callable

from labguide.capture import capture_window_region, encode_image, is_blank_image
from labguide.config import CaptureConfig
from labguide.global_hotkey import GlobalHotkeyListener
from labguide.models import (
    CaptureTrigger,
    CapturedScreenshot,
    TargetWindow,
    UISnapshot,
)
from labguide.platforms.contracts import HotkeyListener, PlatformCapabilities, WindowChoice
from labguide.ui_probe import run_ui_probe
from labguide.win32_window import (
    capture_printwindow,
    ensure_dpi_awareness,
    freeze_target_window,
    get_foreground_hwnd,
    get_window_below,
    is_own_terminal,
    list_candidate_windows,
)


class WindowsAdapter:
    name = "windows"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            screenshot=True, window_capture=True, accessibility=True, global_hotkey=True
        )

    def ensure_ready(self) -> None:
        ensure_dpi_awareness()

    def start_hotkey_listener(
        self, chord: str, callback: Callable[[CaptureTrigger], None]
    ) -> HotkeyListener:
        listener = GlobalHotkeyListener(chord, callback)
        listener.start()
        return listener

    def get_foreground_target(self) -> int:
        return get_foreground_hwnd()

    def is_own_terminal(self, target: int) -> bool:
        return is_own_terminal(target)

    def get_window_below(self, target: int) -> int:
        return get_window_below(target)

    def list_capture_targets(self) -> list[WindowChoice]:
        return list_candidate_windows()

    def freeze_target(self, target: int) -> TargetWindow:
        return freeze_target_window(target)

    def capture_target(
        self, target: TargetWindow, config: CaptureConfig
    ) -> CapturedScreenshot:
        rendered = capture_printwindow(target.hwnd)
        if rendered is not None and not is_blank_image(rendered):
            # Window's own pixels, including when another window covers it.
            return encode_image(
                rendered.convert("RGB"),
                config.jpeg_quality,
                max_dimension=config.jpeg_max_dimension,
                max_bytes=config.jpeg_max_bytes,
            )
        # PrintWindow failed or returned a blank bitmap (common for some
        # GPU-rendered windows). The desktop crop shows whatever is painted
        # on top; say so instead of pretending it is the window's contents.
        screenshot = capture_window_region(
            target.x,
            target.y,
            target.width,
            target.height,
            config.jpeg_quality,
            max_dimension=config.jpeg_max_dimension,
            max_bytes=config.jpeg_max_bytes,
        )
        screenshot.warnings.append(
            "this window's own contents could not be read while it was covered; "
            "the screenshot shows the visible desktop. Bring it forward and capture again"
        )
        return screenshot

    def probe_accessibility(
        self, target: TargetWindow, config: CaptureConfig
    ) -> UISnapshot:
        return run_ui_probe(
            target.hwnd,
            timeout_seconds=config.ui_timeout_seconds,
            max_nodes=config.ui_max_nodes,
            max_depth=config.ui_max_depth,
            include_offscreen=config.ui_include_offscreen,
        )
