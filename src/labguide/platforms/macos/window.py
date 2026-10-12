"""macOS foreground-window identity and geometry via CGWindowList.

Window references are CGWindowID integers. Bounds come from the window list
in screen coordinates; Retina scale is applied at capture time through the
ScreenCaptureKit content filter, not here.
"""

from __future__ import annotations

import os

from labguide.models import TargetWindow, WindowIdentityError

# Owners that mean "the user pointed the hotkey at the support tool itself".
_TERMINAL_OWNER_NAMES = {"Terminal", "iTerm2", "iTerm", "WezTerm", "Alacritty", "kitty"}

# Window-server and system owners that are never user apps.
_NON_APP_OWNERS = {"Window Server", "Dock", "SystemUIServer", "ControlCenter", "Wallpaper"}

# Window layers that are valid capture targets. Layer 0 is the normal
# application layer; layer 8 holds modal dialog panels (error dialogs,
# save panels), which sit above their owner and are the very thing a user
# points the hotkey at. Higher layers (menu bar 24, status items 25) are
# never capture targets. Verified on macOS 26: an osascript error dialog
# surfaces at layer 8 with an empty kCGWindowName.
_CAPTURE_WINDOW_LAYERS = {0, 8}


def _window_list() -> list[dict]:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionOnScreenOnly,
    )

    options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
    return list(windows) if windows else []


def list_candidate_windows(*, limit: int = 30) -> list[WindowChoice]:
    """User-selectable capture targets, front-to-back in z-order.

    Drives the desktop app's window picker. Uses the same candidate filter
    as foreground/below selection (layers 0 and 8, own terminal owners
    excluded). Window titles require Screen Recording permission; without
    it the owner name is used instead.
    """
    from labguide.platforms.contracts import WindowChoice

    results: list[WindowChoice] = []
    for info in _window_list():
        if len(results) >= limit:
            break
        if not _is_candidate(info):
            continue
        owner = str(info.get("kCGWindowOwnerName", "")).strip()
        if owner in _TERMINAL_OWNER_NAMES or owner in _NON_APP_OWNERS:
            continue
        title = str(info.get("kCGWindowName", "")).strip()
        if not title:
            # Owner-only entries (many dialogs) are still selectable; show
            # the owner as the label.
            if not owner:
                continue
            title = owner
        results.append(
            WindowChoice(
                hwnd=int(info.get("kCGWindowNumber", 0)),
                title=title,
                process_name=owner or "unknown",
            )
        )
    return results


def _window_info(window_id: int) -> dict | None:
    for info in _window_list():
        if int(info.get("kCGWindowNumber", 0)) == int(window_id):
            return info
    return None


def _is_candidate(info: dict) -> bool:
    # Layer 0 is the normal application window layer; layer 8 holds modal
    # dialog panels (error dialogs, save panels) that are legitimate capture
    # targets. Skip menu bars, docks, status items, and overlay panels.
    return int(info.get("kCGWindowLayer", -1)) in _CAPTURE_WINDOW_LAYERS


def get_foreground_window_id() -> int:
    """CGWindowID of the frontmost normal application window, or 0."""
    for info in _window_list():
        if _is_candidate(info):
            return int(info.get("kCGWindowNumber", 0))
    return 0


def is_own_terminal(window_id: int) -> bool:
    """Best-effort check that the target is LabGuide's own terminal."""
    if not window_id:
        return False
    info = _window_info(window_id)
    if info is None:
        return False
    if int(info.get("kCGWindowOwnerPID", -1)) == os.getpid():
        return True
    owner = str(info.get("kCGWindowOwnerName", "") or "")
    return owner in _TERMINAL_OWNER_NAMES


def get_window_below(window_id: int) -> int:
    """Next usable window below window_id in front-to-back order, or 0."""
    if not window_id:
        return 0
    windows = _window_list()
    seen_target = False
    for info in windows:
        if not _is_candidate(info):
            continue
        current = int(info.get("kCGWindowNumber", 0))
        if not seen_target:
            if current == int(window_id):
                seen_target = True
            continue
        if int(info.get("kCGWindowOwnerPID", -1)) == os.getpid():
            continue
        owner = str(info.get("kCGWindowOwnerName", "") or "")
        if owner in _TERMINAL_OWNER_NAMES:
            continue
        title = str(info.get("kCGWindowName", "") or "")
        if title.strip():
            return current
    return 0


def freeze_target_window(window_id: int) -> TargetWindow:
    """Snapshot identity and geometry of a window at the capture instant."""
    if not window_id:
        raise WindowIdentityError("unavailable")
    info = _window_info(window_id)
    if info is None:
        # The on-screen list excludes minimized windows; both cases are
        # reported through the same bounded category.
        raise WindowIdentityError("closed")

    bounds = info.get("kCGWindowBounds") or {}
    x = int(bounds.get("X", 0))
    y = int(bounds.get("Y", 0))
    width = int(bounds.get("Width", 0))
    height = int(bounds.get("Height", 0))
    if width <= 0 or height <= 0:
        raise WindowIdentityError("zero_size")

    pid = int(info.get("kCGWindowOwnerPID", 0))
    return TargetWindow(
        hwnd=int(window_id),
        pid=pid,
        process_name=str(info.get("kCGWindowOwnerName", "") or "unknown"),
        window_title=str(info.get("kCGWindowName", "") or ""),
        x=x,
        y=y,
        width=width,
        height=height,
    )
