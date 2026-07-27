"""Narrow ctypes adapter for Win32 foreground-window identity and geometry.

Kept separate from capture and UIA logic so platform calls stay behind one
boundary. All coordinates are physical pixels; call ensure_dpi_awareness()
early in every process that mixes Win32, mss, and UIA geometry.
"""

from __future__ import annotations

import ctypes
import ntpath
import sys
from ctypes import wintypes
from dataclasses import dataclass

from labguide.models import TargetWindow

_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_GW_HWNDNEXT = 2

# Window classes of terminals LabGuide may run inside. Capturing these means
# the user pointed the global hotkey at the support tool itself.
_TERMINAL_CLASS_NAMES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _dwmapi = ctypes.windll.dwmapi

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    _kernel32.GetConsoleWindow.restype = wintypes.HWND
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


class WindowIdentityError(RuntimeError):
    """The frozen foreground window cannot be captured.

    The reason is a category, never captured content: "closed", "minimized",
    "zero_size", or "unavailable".
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def ensure_dpi_awareness() -> None:
    """Request Per-Monitor-V2 so Win32, mss, and UIA share physical pixels."""
    if sys.platform != "win32":
        return
    try:
        _user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        pass


def get_foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    hwnd = _user32.GetForegroundWindow()
    return int(hwnd) if hwnd else 0


def get_console_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    hwnd = _kernel32.GetConsoleWindow()
    return int(hwnd) if hwnd else 0


def get_window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    try:
        length = _user32.GetClassNameW(hwnd, buffer, len(buffer))
    except Exception:
        return ""
    return buffer.value if length else ""


def is_own_terminal(hwnd: int) -> bool:
    """Best-effort check that the target is LabGuide's own terminal window."""
    if sys.platform != "win32" or not hwnd:
        return False
    console = get_console_hwnd()
    if console and hwnd == console:
        return True
    if get_window_class_name(hwnd) in _TERMINAL_CLASS_NAMES:
        # A conhost window is only ours if it is our console; under Windows
        # Terminal the console handle may be unavailable, so reject known
        # terminal classes outright. Documented tradeoff: other terminals
        # cannot be capture targets either.
        return True
    try:
        pid = get_window_pid(hwnd)
    except WindowIdentityError:
        return False
    import os

    return pid == os.getpid()


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    if not _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        raise WindowIdentityError("unavailable")
    return int(pid.value)


def get_window_title(hwnd: int) -> str:
    try:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        return ""


def get_process_name(pid: int) -> str:
    """Image name for a PID, or 'unknown'. Never fails the capture."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "unknown"
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ntpath.basename(buffer.value) or "unknown"
        return "unknown"
    except Exception:
        return "unknown"
    finally:
        _kernel32.CloseHandle(handle)


def get_window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """Physical pixel bounds (x, y, width, height).

    Prefers the DWM extended frame bounds (visible window, excludes the
    invisible resize border) and falls back to GetWindowRect.
    """
    rect = wintypes.RECT()
    try:
        result = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(_DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return _rect_to_bounds(rect)
    except Exception:
        pass
    if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise WindowIdentityError("unavailable")
    return _rect_to_bounds(rect)


def _rect_to_bounds(rect: wintypes.RECT) -> tuple[int, int, int, int]:
    return (
        int(rect.left),
        int(rect.top),
        max(0, int(rect.right) - int(rect.left)),
        max(0, int(rect.bottom) - int(rect.top)),
    )


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    hwnd: int
    visible: bool
    title: str
    is_terminal: bool


def select_window_below(candidates: list[WindowCandidate]) -> int | None:
    """Pick the window the user most likely means from z-order candidates.

    Pure function, unit-tested. Prefers the first visible, non-terminal,
    titled window; falls back to any visible non-terminal window.
    """
    usable = [candidate for candidate in candidates if candidate.visible and not candidate.is_terminal]
    for candidate in usable:
        if candidate.title.strip():
            return candidate.hwnd
    return usable[0].hwnd if usable else None


def get_window_below(hwnd: int, *, max_hops: int = 20) -> int:
    """HWND of the next usable window below hwnd in z-order, or 0.

    Used when LabGuide's terminal is foreground and the user means "the app
    I was just in". Walks GW_HWNDNEXT from the given window.
    """
    if sys.platform != "win32" or not hwnd:
        return 0
    candidates: list[WindowCandidate] = []
    current = int(hwnd)
    for _ in range(max_hops):
        next_hwnd = _user32.GetWindow(wintypes.HWND(current), _GW_HWNDNEXT)
        if not next_hwnd:
            break
        current = int(next_hwnd)
        candidates.append(
            WindowCandidate(
                hwnd=current,
                visible=bool(_user32.IsWindowVisible(wintypes.HWND(current))),
                title=get_window_title(current),
                is_terminal=is_own_terminal(current),
            )
        )
    return select_window_below(candidates) or 0


def freeze_target_window(hwnd: int) -> TargetWindow:
    """Snapshot the identity and geometry of a window at the capture instant."""
    if sys.platform != "win32":
        raise WindowIdentityError("unavailable")
    if not hwnd or not _user32.IsWindow(hwnd):
        raise WindowIdentityError("closed")
    if _user32.IsIconic(hwnd):
        raise WindowIdentityError("minimized")
    x, y, width, height = get_window_bounds(hwnd)
    if width <= 0 or height <= 0:
        raise WindowIdentityError("zero_size")
    pid = get_window_pid(hwnd)
    return TargetWindow(
        hwnd=int(hwnd),
        pid=pid,
        process_name=get_process_name(pid),
        window_title=get_window_title(hwnd),
        x=x,
        y=y,
        width=width,
        height=height,
    )
