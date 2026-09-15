"""Win32 global hotkey adapter.

Owns RegisterHotKey/UnregisterHotKey and a dedicated message-loop thread.
Reports an immutable capture trigger (foreground HWND + timestamp); contains
no screenshot, UIA, backend, or prompt logic.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Callable

from labguide.models import CaptureTrigger
from labguide.win32_window import get_foreground_hwnd

__all__ = ["CaptureTrigger", "HotkeyError", "parse_hotkey", "GlobalHotkeyListener"]

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOTKEY_ID = 1

_MODIFIER_NAMES = {
    "alt": _MOD_ALT,
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
    "win": _MOD_WIN,
}

_KEY_NAMES = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "printscreen": 0x2C,
}
_KEY_NAMES.update({f"f{number}": 0x70 + number - 1 for number in range(1, 25)})

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class HotkeyError(RuntimeError):
    pass


def parse_hotkey(chord: str) -> tuple[int, int]:
    """Parse 'ctrl+shift+space' into (modifier flags, virtual key code)."""
    parts = [part.strip().lower() for part in chord.split("+") if part.strip()]
    modifiers = 0
    key: str | None = None
    for part in parts:
        if part in _MODIFIER_NAMES:
            modifiers |= _MODIFIER_NAMES[part]
        elif key is None:
            key = part
        else:
            raise ValueError(f"hotkey has multiple keys: {chord!r}")
    if key is None:
        raise ValueError(f"hotkey has no key: {chord!r}")
    if key in _KEY_NAMES:
        vk = _KEY_NAMES[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown hotkey key: {key!r}")
    return (modifiers, vk)


class GlobalHotkeyListener:
    """Registers one hotkey and invokes callback(CaptureTrigger) per press.

    The callback runs on the hotkey thread; it must be cheap and thread-safe
    (for example, Textual's App.call_from_thread).
    """

    def __init__(self, chord: str, callback: Callable[[CaptureTrigger], None]) -> None:
        self._modifiers, self._vk = parse_hotkey(chord)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._start_error: HotkeyError | None = None

    def start(self) -> None:
        if sys.platform != "win32":
            raise HotkeyError("global hotkey requires Windows")
        self._thread = threading.Thread(target=self._run, name="labguide-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise HotkeyError("hotkey thread did not start")
        if self._start_error is not None:
            raise self._start_error

    def stop(self) -> None:
        if sys.platform != "win32" or self._thread is None:
            return
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        self._thread_id = int(_kernel32.GetCurrentThreadId())
        registered = _user32.RegisterHotKey(
            None, _HOTKEY_ID, self._modifiers | _MOD_NOREPEAT, self._vk
        )
        if not registered:
            self._start_error = HotkeyError(
                "hotkey is already registered by another application; "
                "choose a different capture.global_hotkey chord"
            )
            self._ready.set()
            return
        self._ready.set()
        try:
            message = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message != _WM_HOTKEY:
                    continue
                trigger = CaptureTrigger(
                    hwnd=get_foreground_hwnd(),
                    triggered_at=datetime.now(timezone.utc).isoformat(),
                )
                try:
                    self._callback(trigger)
                except Exception:
                    # A bad callback must never kill the message loop.
                    pass
        finally:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)
