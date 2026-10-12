"""Narrow ctypes adapter for Win32 foreground-window identity and geometry.

Kept separate from capture and UIA logic so platform calls stay behind one
boundary. All coordinates are physical pixels; call ensure_dpi_awareness()
early in every process that mixes Win32, mss, and UIA geometry.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

from labguide.models import TargetWindow, WindowIdentityError

__all__ = [
    "WindowIdentityError",
    "ensure_dpi_awareness",
    "get_foreground_hwnd",
    "get_console_hwnd",
    "get_window_class_name",
    "is_own_terminal",
    "get_window_pid",
    "get_window_title",
    "get_process_name",
    "get_window_bounds",
    "WindowCandidate",
    "WindowChoice",
    "select_window_below",
    "get_window_below",
    "list_candidate_windows",
    "freeze_target_window",
]

_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_GW_HWNDNEXT = 2

# Window classes of terminals LabGuide may run inside. Capturing these means
# the user pointed the global hotkey at the support tool itself.
_TERMINAL_CLASS_NAMES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}

# Desktop shell windows. "The window below" must never resolve to the
# desktop itself, or a below-mode capture silently becomes a full-screen
# desktop crop.
_SHELL_CLASS_NAMES = {"Progman", "WorkerW"}

# PID of the desktop shell process (desktop.exe), set by the Tauri shell so
# the sidecar can recognize the LabGuide GUI as its own window. The TUI
# needs no such marker: it matches its own pid (or console) directly.
_OWN_SHELL_PID_ENV = "LABGUIDE_OWN_PID"

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
    if pid == os.getpid():
        return True
    # Desktop app: the GUI process is desktop.exe, a different process from
    # this sidecar. The shell announces its pid at spawn time.
    own_shell_pid = os.environ.get(_OWN_SHELL_PID_ENV)
    return bool(own_shell_pid and pid == int(own_shell_pid))


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
    is_shell_desktop: bool = False


@dataclass(frozen=True, slots=True)
class WindowChoice:
    """One user-selectable capture target for the window picker."""

    hwnd: int
    title: str
    process_name: str


def select_window_below(candidates: list[WindowCandidate]) -> int | None:
    """Pick the window the user most likely means from z-order candidates.

    Pure function, unit-tested. Prefers the first visible, non-terminal,
    non-shell, titled window; falls back to any remaining visible window.
    Shell desktop windows (Progman/WorkerW) are never capture targets: with
    the desktop app foreground they sit directly below in z-order, and
    selecting one silently turns a window capture into a full-screen crop.
    """
    usable = [
        candidate
        for candidate in candidates
        if candidate.visible
        and not candidate.is_terminal
        and not candidate.is_shell_desktop
    ]
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
                is_shell_desktop=get_window_class_name(current) in _SHELL_CLASS_NAMES,
            )
        )
    return select_window_below(candidates) or 0


_ENUM_WINDOWS = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_WS_EX_TOOLWINDOW = 0x0000_0080
_GWL_EXSTYLE = -20


def list_candidate_windows(*, limit: int = 30) -> list[WindowChoice]:
    """User-selectable capture targets, top-to-bottom in z-order.

    Drives the desktop app's window picker. Excludes shell desktop windows,
    LabGuide's own windows, tool windows, and untitled windows; keeps the
    first ``limit`` results so the picker stays readable on busy desktops.
    """
    if sys.platform != "win32":
        return []
    results: list[WindowChoice] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if len(results) >= limit:
            return False
        if not _user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        ex_style = _user32.GetWindowLongW(wintypes.HWND(hwnd), _GWL_EXSTYLE)
        if ex_style & _WS_EX_TOOLWINDOW:
            return True
        class_name = get_window_class_name(hwnd)
        if class_name in _SHELL_CLASS_NAMES:
            return True
        if is_own_terminal(hwnd):
            return True
        title = get_window_title(hwnd)
        if not title.strip():
            return True
        try:
            pid = get_window_pid(hwnd)
        except WindowIdentityError:
            return True
        results.append(
            WindowChoice(hwnd=hwnd, title=title, process_name=get_process_name(pid))
        )
        return True

    try:
        _user32.EnumWindows(_ENUM_WINDOWS(callback), 0)
    except Exception:
        # Enumeration is best-effort: an unreadable window must not break
        # the picker entirely.
        pass
    return results


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
