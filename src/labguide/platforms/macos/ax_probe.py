"""Isolated, read-only macOS Accessibility (AXUIElement) probe.

Child-process usage (machine-readable contract):

    python -m labguide.platforms.macos.ax_probe --pid 1234 --window-title "Untitled"

Writes exactly one JSON object to stdout describing the window's AX tree in
the same UISnapshot schema as the Windows UIA probe. Diagnostics go to
stderr and must not contain captured field values. The parent enforces the
hard timeout and kills the probe when a provider hangs.

The probe never performs AX actions, sets values, focuses, or sends input.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any, Callable, TypeVar

from labguide.models import (
    INTERACTIVE_CONTROL_TYPES,
    UI_STATUS_COMPLETE,
    UI_STATUS_FAILED,
    UI_STATUS_INACCESSIBLE,
    UI_STATUS_PARTIAL,
    UI_STATUS_UNSUPPORTED,
    UIElement,
    UISnapshot,
)
from labguide.ui_outline import redact_password_elements

T = TypeVar("T")

_MAX_WARNINGS = 20
_DEFAULT_MAX_ELEMENT_CHARS = 4000

# AX role -> normalized control type, aligned with the Windows vocabulary so
# outline rendering and interactive-type filtering work unchanged.
_ROLE_MAP = {
    "AXWindow": "Window",
    "AXButton": "Button",
    "AXCheckBox": "CheckBox",
    "AXRadioButton": "RadioButton",
    "AXTextField": "Edit",
    "AXTextArea": "Edit",
    "AXSearchField": "Edit",
    "AXComboBox": "ComboBox",
    "AXPopUpButton": "ComboBox",
    "AXStaticText": "Text",
    "AXLink": "Hyperlink",
    "AXList": "List",
    "AXRow": "ListItem",
    "AXCell": "ListItem",
    "AXMenuItem": "MenuItem",
    "AXMenuBarItem": "MenuItem",
    "AXSlider": "Slider",
    "AXIncrementor": "Spinner",
    "AXTab": "TabItem",
    "AXTabGroup": "Tab",
    "AXOutline": "Tree",
    "AXOutlineRow": "TreeItem",
    "AXGroup": "Pane",
    "AXScrollArea": "ScrollArea",
    "AXToolbar": "ToolBar",
    "AXImage": "Image",
    "AXHeading": "Text",
    "AXWebArea": "Document",
    "AXSplitter": "Separator",
    "AXProgressIndicator": "ProgressBar",
    "AXValueIndicator": "ProgressBar",
}


def normalize_role(role: str | None) -> str:
    """Map an AX role to the shared control-type vocabulary."""
    if not role:
        return "Unknown"
    if role in _ROLE_MAP:
        return _ROLE_MAP[role]
    return role[2:] if role.startswith("AX") else role


def is_secure_role(role: str | None, subrole: str | None) -> bool:
    """True when the control may hold a secret (secure text entry)."""
    for value in (role, subrole):
        if value and "secure" in value.lower():
            return True
    return False


def _safe(getter: Callable[[], T], default: T | None = None) -> T | None:
    """Guard one AX attribute read; a single failure never discards a node."""
    try:
        return getter()
    except Exception:
        return default


def _none_if_empty(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _copy(element: Any, attribute: str) -> Any:
    """Read one AX attribute, returning None on any error."""
    from ApplicationServices import AXUIElementCopyAttributeValue

    error, value = AXUIElementCopyAttributeValue(element, attribute, None)
    if error != 0:
        return None
    return value


def _point(value: Any) -> tuple[int, int] | None:
    try:
        if hasattr(value, "pointValue"):
            point = value.pointValue()
            return int(point.x), int(point.y)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return int(value[0]), int(value[1])
    except Exception:
        return None
    return None


def _size(value: Any) -> tuple[int, int] | None:
    try:
        if hasattr(value, "sizeValue"):
            size = value.sizeValue()
            return int(size.width), int(size.height)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return int(value[0]), int(value[1])
    except Exception:
        return None
    return None


class _Probe:
    """Single-window AX traversal with node, depth, and text limits."""

    def __init__(
        self,
        pid: int,
        window_title: str | None,
        max_nodes: int,
        max_depth: int,
        include_offscreen: bool,
        max_element_chars: int,
    ) -> None:
        self._pid = pid
        self._window_title = window_title
        self._max_nodes = max(1, max_nodes)
        self._max_depth = max(0, max_depth)
        self._include_offscreen = include_offscreen
        self._max_element_chars = max(16, max_element_chars)
        self._warnings: list[str] = []
        self._visited = 0
        self._truncated = False

    def run(self) -> UISnapshot:
        from ApplicationServices import AXIsProcessTrusted, AXUIElementCreateApplication

        if not AXIsProcessTrusted():
            return self._finish(
                UI_STATUS_INACCESSIBLE,
                [],
                "accessibility permission not granted for this process",
            )

        app = AXUIElementCreateApplication(self._pid)
        if app is None:
            return self._finish(UI_STATUS_UNSUPPORTED, [], "no AX application for pid")

        root = self._select_window(app)
        if root is None:
            return self._finish(UI_STATUS_UNSUPPORTED, [], "no AX window for target")

        origin = _point(_safe(lambda: _copy(root, "AXPosition"))) or (0, 0)

        elements: list[UIElement] = []
        stack: list[tuple[Any, int]] = [(root, 0)]
        while stack:
            element_ref, depth = stack.pop()
            if self._visited >= self._max_nodes:
                self._truncated = True
                self._warn(f"node limit {self._max_nodes} reached")
                break
            self._visited += 1

            element = self._extract(element_ref, depth, origin)
            if element is _SKIP_SUBTREE:
                continue
            if element is not None:
                elements.append(element)

            if depth >= self._max_depth:
                children = _safe(lambda: _copy(element_ref, "AXChildren"), []) or []
                if children:
                    self._truncated = True
                    self._warn(f"depth limit {self._max_depth} reached")
                continue

            children = _safe(lambda: _copy(element_ref, "AXChildren"), None)
            if children is None:
                continue
            for child in reversed(list(children)):
                stack.append((child, depth + 1))

        status = UI_STATUS_PARTIAL if self._warnings else UI_STATUS_COMPLETE
        return self._finish(status, elements, "")

    def _select_window(self, app: Any) -> Any | None:
        """Pick the AX window matching the frozen target, main window first."""
        main_window = _safe(lambda: _copy(app, "AXMainWindow"))
        if main_window is not None:
            return main_window
        focused = _safe(lambda: _copy(app, "AXFocusedWindow"))
        if focused is not None:
            return focused
        windows = _safe(lambda: _copy(app, "AXWindows"), []) or []
        windows = list(windows)
        if self._window_title:
            for window in windows:
                title = _none_if_empty(_safe(lambda: _copy(window, "AXTitle")))
                if title and title == self._window_title:
                    return window
        return windows[0] if windows else None

    def _extract(
        self, element_ref: Any, depth: int, origin: tuple[int, int]
    ) -> UIElement | object | None:
        role = _safe(lambda: _copy(element_ref, "AXRole"))
        subrole = _safe(lambda: _copy(element_ref, "AXSubrole"))
        control_type = normalize_role(role if isinstance(role, str) else None)

        if is_secure_role(
            role if isinstance(role, str) else None,
            subrole if isinstance(subrole, str) else None,
        ):
            # Emit only a redacted marker. Never read titles or values from a
            # secure text control.
            return UIElement(depth=depth, control_type=control_type, is_password=True)

        hidden = bool(_safe(lambda: _copy(element_ref, "AXHidden"), False))
        if hidden and not self._include_offscreen:
            return _SKIP_SUBTREE

        title = _none_if_empty(_safe(lambda: _copy(element_ref, "AXTitle")))
        description = _none_if_empty(_safe(lambda: _copy(element_ref, "AXDescription")))
        name = title or description

        value: str | None = None
        text: str | None = None
        raw_value = _safe(lambda: _copy(element_ref, "AXValue"))
        if isinstance(raw_value, str):
            capped = raw_value[: self._max_element_chars]
            if control_type == "Edit":
                text = _none_if_empty(capped)
            else:
                value = _none_if_empty(capped)

        states: list[str] = []
        if _safe(lambda: _copy(element_ref, "AXEnabled"), True):
            states.append("enabled")
        if _safe(lambda: _copy(element_ref, "AXFocused"), False):
            states.append("focused")
        if control_type in {"CheckBox", "RadioButton", "TabItem", "MenuItem"}:
            if raw_value in (1, True):
                states.append("checked" if control_type in {"CheckBox", "RadioButton"} else "selected")
        if _safe(lambda: _copy(element_ref, "AXSelected"), False):
            if "selected" not in states:
                states.append("selected")
        expanded = _safe(lambda: _copy(element_ref, "AXExpanded"), None)
        if expanded is True:
            states.append("expanded")
        elif expanded is False and control_type in {"ComboBox", "Tree", "TreeItem", "Pane"}:
            states.append("collapsed")
        if hidden:
            states.append("offscreen")

        x = y = width = height = None
        position = _point(_safe(lambda: _copy(element_ref, "AXPosition")))
        size = _size(_safe(lambda: _copy(element_ref, "AXSize")))
        if position is not None and size is not None:
            x = position[0] - origin[0]
            y = position[1] - origin[1]
            width, height = size

        element = UIElement(
            depth=depth,
            control_type=control_type,
            name=name,
            value=value,
            text=text,
            states=states,
            x=x,
            y=y,
            width=width,
            height=height,
        )

        if depth > 0 and not _keep(element):
            return None
        return element

    def _warn(self, message: str) -> None:
        if len(self._warnings) < _MAX_WARNINGS:
            self._warnings.append(message)

    def _finish(self, status: str, elements: list[UIElement], warning: str) -> UISnapshot:
        if warning:
            self._warn(warning)
        return UISnapshot(
            status=status,
            elements=elements,
            node_count=self._visited,
            truncated=self._truncated,
            warnings=self._warnings,
        )


_SKIP_SUBTREE = object()


def _keep(element: UIElement) -> bool:
    if element.is_password:
        return True
    if element.has_content():
        return True
    if element.control_type in INTERACTIVE_CONTROL_TYPES:
        return True
    interesting = set(element.states) - {"enabled"}
    return bool(interesting)


def probe_window(
    pid: int,
    window_title: str | None,
    max_nodes: int,
    max_depth: int,
    include_offscreen: bool,
    max_element_chars: int = _DEFAULT_MAX_ELEMENT_CHARS,
) -> UISnapshot:
    """Run the probe in-process. Callers should prefer run_ax_probe()."""
    probe = _Probe(pid, window_title, max_nodes, max_depth, include_offscreen, max_element_chars)
    try:
        snapshot = probe.run()
    except Exception as exc:
        snapshot = UISnapshot(
            status=UI_STATUS_FAILED, warnings=[f"probe error: {type(exc).__name__}"]
        )
    return redact_password_elements(snapshot)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labguide.platforms.macos.ax_probe",
        description=(
            "Read-only macOS Accessibility probe. Writes one JSON snapshot of "
            "the target window's AX tree to stdout."
        ),
    )
    parser.add_argument("--pid", type=int, required=True, help="target application pid")
    parser.add_argument("--window-title", default=None, help="window title to match")
    parser.add_argument("--max-nodes", type=int, default=500, help="maximum AX nodes to visit")
    parser.add_argument("--max-depth", type=int, default=20, help="maximum traversal depth")
    parser.add_argument(
        "--include-offscreen",
        action="store_true",
        help="include hidden controls (excluded by default for privacy)",
    )
    parser.add_argument(
        "--max-element-chars",
        type=int,
        default=_DEFAULT_MAX_ELEMENT_CHARS,
        help="per-control text length cap",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if sys.platform != "darwin":
        json.dump(
            UISnapshot(status=UI_STATUS_UNSUPPORTED, warnings=["requires macOS"]).to_dict(),
            sys.stdout,
        )
        return 0

    # Keep the stdout channel clean: any library noise goes to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        snapshot = probe_window(
            pid=args.pid,
            window_title=args.window_title,
            max_nodes=args.max_nodes,
            max_depth=args.max_depth,
            include_offscreen=args.include_offscreen,
            max_element_chars=args.max_element_chars,
        )
    sys.stdout.write(json.dumps(snapshot.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
