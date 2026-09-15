"""macOS global hotkey listener built on pynput.

pynput's GlobalHotKeys uses a CGEvent tap, which requires Accessibility
permission on macOS. The listener freezes the foreground window identity on
the listener thread at the moment the chord fires, mirroring the Windows
adapter's CaptureTrigger semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from labguide.global_hotkey import HotkeyError
from labguide.models import CaptureTrigger

_MODIFIER_TOKENS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "option": "<alt>",
    "cmd": "<cmd>",
    "win": "<cmd>",
}

_KEY_TOKENS = {
    "space": "<space>",
    "tab": "<tab>",
    "enter": "<enter>",
    "return": "<enter>",
    "escape": "<esc>",
    "esc": "<esc>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "insert": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pageup": "<page_up>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
    "printscreen": "<print_screen>",
}
_KEY_TOKENS.update({f"f{number}": f"<f{number}>" for number in range(1, 25)})


def parse_chord(chord: str) -> str:
    """Convert 'ctrl+shift+space' to pynput's '<ctrl>+<shift>+<space>'."""
    parts = [part.strip().lower() for part in chord.split("+") if part.strip()]
    tokens: list[str] = []
    key: str | None = None
    for part in parts:
        if part in _MODIFIER_TOKENS:
            tokens.append(_MODIFIER_TOKENS[part])
        elif key is None:
            key = part
        else:
            raise ValueError(f"hotkey has multiple keys: {chord!r}")
    if key is None:
        raise ValueError(f"hotkey has no key: {chord!r}")
    if key in _KEY_TOKENS:
        tokens.append(_KEY_TOKENS[key])
    elif len(key) == 1 and key.isalnum():
        tokens.append(key)
    else:
        raise ValueError(f"unknown hotkey key: {key!r}")
    return "+".join(tokens)


class MacOSHotkeyListener:
    """Registers one global chord and invokes callback(CaptureTrigger)."""

    def __init__(self, chord: str, callback: Callable[[CaptureTrigger], None]) -> None:
        self._spec = parse_chord(chord)
        self._callback = callback
        self._listener = None

    def start(self) -> None:
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise HotkeyError("pynput is required for the macOS global hotkey") from exc
        try:
            self._listener = keyboard.GlobalHotKeys({self._spec: self._on_activate})
            self._listener.start()
        except Exception as exc:
            raise HotkeyError(
                "could not start the global hotkey listener; on macOS this "
                "usually means Accessibility permission is missing"
            ) from exc

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _on_activate(self) -> None:
        from labguide.platforms.macos.window import get_foreground_window_id

        trigger = CaptureTrigger(
            hwnd=get_foreground_window_id(),
            triggered_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            self._callback(trigger)
        except Exception:
            # A bad callback must never kill the listener.
            pass
