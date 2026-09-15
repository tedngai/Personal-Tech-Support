"""macOS platform adapter.

Window identity comes from CGWindowList, pixels from ScreenCaptureKit,
accessibility text from an isolated AXUIElement probe, and the global
hotkey from pynput. Permission problems surface as readable capture/UI
statuses; screenshot-only support remains available without Accessibility
permission.
"""

from __future__ import annotations

from typing import Callable

from labguide.config import CaptureConfig
from labguide.models import (
    CaptureTrigger,
    CapturedScreenshot,
    TargetWindow,
    UISnapshot,
)
from labguide.platforms.contracts import HotkeyListener, PlatformCapabilities


class MacOSAdapter:
    name = "macos"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            screenshot=True, window_capture=True, accessibility=True, global_hotkey=True
        )

    def ensure_ready(self) -> None:
        return None

    def start_hotkey_listener(
        self, chord: str, callback: Callable[[CaptureTrigger], None]
    ) -> HotkeyListener:
        from labguide.platforms.macos.hotkey import MacOSHotkeyListener

        listener = MacOSHotkeyListener(chord, callback)
        listener.start()
        return listener

    def get_foreground_target(self) -> int:
        from labguide.platforms.macos.window import get_foreground_window_id

        return get_foreground_window_id()

    def is_own_terminal(self, target: int) -> bool:
        from labguide.platforms.macos.window import is_own_terminal

        return is_own_terminal(target)

    def get_window_below(self, target: int) -> int:
        from labguide.platforms.macos.window import get_window_below

        return get_window_below(target)

    def freeze_target(self, target: int) -> TargetWindow:
        from labguide.platforms.macos.window import freeze_target_window

        return freeze_target_window(target)

    def capture_target(
        self, target: TargetWindow, config: CaptureConfig
    ) -> CapturedScreenshot:
        from labguide.platforms.macos.screenshot import capture_window

        return capture_window(target, config)

    def probe_accessibility(
        self, target: TargetWindow, config: CaptureConfig
    ) -> UISnapshot:
        from labguide.platforms.macos.accessibility import run_ax_probe

        return run_ax_probe(
            target,
            timeout_seconds=config.ui_timeout_seconds,
            max_nodes=config.ui_max_nodes,
            max_depth=config.ui_max_depth,
            include_offscreen=config.ui_include_offscreen,
        )
