"""Platform capability contracts shared by the Windows and macOS adapters.

Native window references (Win32 HWND, CGWindowID) stay inside the adapters;
the application only sees TargetWindow/CapturedScreenshot/UISnapshot models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from labguide.config import CaptureConfig
from labguide.models import (
    UI_STATUS_UNSUPPORTED,
    CaptureTrigger,
    CapturedScreenshot,
    TargetWindow,
    UISnapshot,
    WindowIdentityError,
)


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    """What the current platform adapter can actually do.

    Tracked independently: a platform may capture screenshots without
    supporting global hotkeys or accessibility extraction.
    """

    screenshot: bool = True
    window_capture: bool = False
    accessibility: bool = False
    global_hotkey: bool = False


class HotkeyListener(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PlatformAdapter(Protocol):
    """Narrow boundary between the app and one operating system."""

    name: str

    def capabilities(self) -> PlatformCapabilities: ...

    def ensure_ready(self) -> None:
        """Process-level setup (e.g. DPI awareness on Windows)."""
        ...

    def start_hotkey_listener(
        self, chord: str, callback: Callable[[CaptureTrigger], None]
    ) -> HotkeyListener:
        """Register the global capture hotkey and start listening."""
        ...

    def get_foreground_target(self) -> int:
        """Native reference of the current foreground window, or 0."""
        ...

    def is_own_terminal(self, target: int) -> bool:
        """True when the target is LabGuide's own terminal window."""
        ...

    def get_window_below(self, target: int) -> int:
        """Best-effort "app the user was just in" below target, or 0."""
        ...

    def freeze_target(self, target: int) -> TargetWindow:
        """Snapshot identity and geometry of a window at the capture instant."""
        ...

    def capture_target(
        self, target: TargetWindow, config: CaptureConfig
    ) -> CapturedScreenshot:
        """Capture the target window's pixels."""
        ...

    def probe_accessibility(
        self, target: TargetWindow, config: CaptureConfig
    ) -> UISnapshot:
        """Read-only accessibility extraction for the target window."""
        ...


class UnsupportedAdapter:
    """Fallback for platforms without a dedicated adapter (e.g. Linux).

    Text-only support and primary-display screenshots may still work;
    window capture, accessibility, and global hotkeys are reported as
    unavailable instead of failing obscurely.
    """

    name = "unsupported"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            screenshot=True, window_capture=False, accessibility=False, global_hotkey=False
        )

    def ensure_ready(self) -> None:
        return None

    def start_hotkey_listener(
        self, chord: str, callback: Callable[[CaptureTrigger], None]
    ) -> HotkeyListener:
        from labguide.global_hotkey import HotkeyError

        raise HotkeyError(f"global hotkey is not supported on this platform")

    def get_foreground_target(self) -> int:
        return 0

    def is_own_terminal(self, target: int) -> bool:
        return False

    def get_window_below(self, target: int) -> int:
        return 0

    def freeze_target(self, target: int) -> TargetWindow:
        raise WindowIdentityError("unavailable")

    def capture_target(
        self, target: TargetWindow, config: CaptureConfig
    ) -> CapturedScreenshot:
        from labguide.capture import CaptureError

        raise CaptureError("window capture is not supported on this platform")

    def probe_accessibility(
        self, target: TargetWindow, config: CaptureConfig
    ) -> UISnapshot:
        return UISnapshot(
            status=UI_STATUS_UNSUPPORTED,
            warnings=["accessibility capture is not supported on this platform"],
        )
