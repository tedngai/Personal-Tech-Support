"""Isolated, read-only Windows UI Automation probe.

Child-process usage (machine-readable contract):

    python -m labguide.ui_probe --hwnd 12345 --max-nodes 500 --max-depth 20

Writes exactly one JSON object to stdout describing the window's UIA Control
View. Diagnostics go to stderr and must not contain captured field values.
The parent enforces the hard timeout through :func:`run_ui_probe` and kills
the probe when a provider hangs.

The probe never invokes, clicks, focuses, selects, sets values, or sends
keyboard input to the target application.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from typing import Any, Callable, TypeVar

from labguide.models import (
    INTERACTIVE_CONTROL_TYPES,
    UI_STATUS_COMPLETE,
    UI_STATUS_FAILED,
    UI_STATUS_INACCESSIBLE,
    UI_STATUS_PARTIAL,
    UI_STATUS_TIMED_OUT,
    UI_STATUS_UNSUPPORTED,
    UIElement,
    UISnapshot,
)
from labguide.ui_outline import redact_password_elements

T = TypeVar("T")

_MAX_WARNINGS = 20
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_DEFAULT_MAX_ELEMENT_CHARS = 4000

_ACCESS_DENIED_HRESULTS = {-2147024891, -2147024890}  # E_ACCESSDENIED, E_FAIL-adjacent


def _safe(getter: Callable[[], T], default: T | None = None) -> T | None:
    """Guard one UIA property read; a single failure never discards a node."""
    try:
        return getter()
    except Exception:
        return default


def _short_control_type(control_type_name: str) -> str:
    if control_type_name.endswith("Control"):
        return control_type_name[: -len("Control")] or control_type_name
    return control_type_name


def _is_access_denied(exc: BaseException) -> bool:
    hresult = getattr(exc, "hresult", None)
    if hresult in _ACCESS_DENIED_HRESULTS:
        return True
    return "0x80070005" in str(exc)


class _Probe:
    """Single-window UIA traversal with node, depth, and text limits."""

    def __init__(
        self,
        hwnd: int,
        max_nodes: int,
        max_depth: int,
        include_offscreen: bool,
        max_element_chars: int,
    ) -> None:
        self._hwnd = hwnd
        self._max_nodes = max(1, max_nodes)
        self._max_depth = max(0, max_depth)
        self._include_offscreen = include_offscreen
        self._max_element_chars = max(16, max_element_chars)
        self._warnings: list[str] = []
        self._visited = 0
        self._truncated = False

    def run(self) -> UISnapshot:
        import uiautomation as auto

        try:
            root = auto.ControlFromHandle(self._hwnd)
        except Exception as exc:
            if _is_access_denied(exc):
                return self._finish(UI_STATUS_INACCESSIBLE, [], "window is not accessible at this integrity level")
            return self._finish(UI_STATUS_UNSUPPORTED, [], f"UIA root unavailable: {type(exc).__name__}")
        if root is None:
            return self._finish(UI_STATUS_UNSUPPORTED, [], "no UIA element for window handle")

        origin = _safe(lambda: root.BoundingRectangle)
        origin_left = getattr(origin, "left", 0) or 0
        origin_top = getattr(origin, "top", 0) or 0

        elements: list[UIElement] = []
        stack: list[tuple[Any, int]] = [(root, 0)]
        while stack:
            control, depth = stack.pop()
            if self._visited >= self._max_nodes:
                self._truncated = True
                self._warn(f"node limit {self._max_nodes} reached")
                break
            self._visited += 1

            element = self._extract(control, depth, origin_left, origin_top)
            if element is _SKIP_SUBTREE:
                continue
            if element is not None:
                elements.append(element)

            if depth >= self._max_depth:
                children = _safe(control.GetChildren, []) or []
                if children:
                    self._truncated = True
                    self._warn(f"depth limit {self._max_depth} reached")
                continue

            children = _safe(control.GetChildren, None)
            if children is None:
                self._warn(f"children unavailable at depth {depth}")
                continue
            for child in reversed(children):
                stack.append((child, depth + 1))

        status = UI_STATUS_PARTIAL if self._warnings else UI_STATUS_COMPLETE
        return self._finish(status, elements, "")

    def _extract(
        self, control: Any, depth: int, origin_left: int, origin_top: int
    ) -> UIElement | object | None:
        """Extract one node.

        Returns the element, None to skip the node but keep traversing, or
        _SKIP_SUBTREE to drop the node and its children.
        """
        is_offscreen = bool(_safe(lambda: control.IsOffscreen, False))
        if is_offscreen and not self._include_offscreen:
            # Skip the node itself; children of offscreen containers are
            # almost always offscreen too, so drop the whole subtree.
            return _SKIP_SUBTREE

        control_type = _short_control_type(str(_safe(lambda: control.ControlTypeName, "Unknown") or "Unknown"))
        password_prop = _safe(
            lambda: control.GetPropertyValue(_property("IsPasswordProperty")), None
        )
        if password_prop is None or bool(password_prop):
            # Emit only a redacted marker. Never read Name, values, or text
            # patterns from a password control. When the IsPassword property
            # cannot be read at all, treat the control as sensitive rather
            # than risk collecting a secret.
            return UIElement(depth=depth, control_type=control_type, is_password=True)

        name = _none_if_empty(_safe(lambda: control.Name))
        text: str | None = None
        value: str | None = None

        # Text extraction priority: TextPattern -> ValuePattern -> Name ->
        # LegacyIAccessible. Name is always read (it is the primary label);
        # the patterns fill value/text in priority order.
        text_pattern = _safe(lambda: control.GetPattern(_pattern("TextPattern")))
        if text_pattern:
            raw = _safe(lambda: text_pattern.DocumentRange.GetText(self._max_element_chars))
            text = _none_if_empty(raw)

        if not text:
            value_pattern = _safe(lambda: control.GetPattern(_pattern("ValuePattern")))
            if value_pattern:
                value = _none_if_empty(_safe(lambda: value_pattern.Value))

        if not text and not value and not name:
            legacy = _safe(lambda: control.GetPattern(_pattern("LegacyIAccessiblePattern")))
            if legacy:
                value = _none_if_empty(_safe(lambda: legacy.Value))
                if not value:
                    name = _none_if_empty(_safe(lambda: legacy.Name))

        states: list[str] = []
        if _safe(lambda: control.IsEnabled, True):
            states.append("enabled")
        if _safe(lambda: control.GetPropertyValue(_property("HasKeyboardFocusProperty")), False):
            states.append("focused")

        toggle = _safe(lambda: control.GetPattern(_pattern("TogglePattern")))
        if toggle:
            toggle_state = _safe(lambda: int(toggle.ToggleState))
            if toggle_state == 1:
                states.append("checked")
            elif toggle_state == 2:
                states.append("indeterminate")

        selection = _safe(lambda: control.GetPattern(_pattern("SelectionItemPattern")))
        if selection and _safe(lambda: selection.IsSelected, False):
            states.append("selected")

        expand = _safe(lambda: control.GetPattern(_pattern("ExpandCollapsePattern")))
        if expand:
            expand_state = _safe(lambda: int(expand.ExpandCollapseState))
            if expand_state == 1:
                states.append("expanded")
            elif expand_state == 0:
                states.append("collapsed")

        if is_offscreen:
            states.append("offscreen")

        rect = _safe(lambda: control.BoundingRectangle)
        x = y = width = height = None
        if rect is not None:
            left = getattr(rect, "left", 0) or 0
            top = getattr(rect, "top", 0) or 0
            width = max(0, (getattr(rect, "right", 0) or 0) - left)
            height = max(0, (getattr(rect, "bottom", 0) or 0) - top)
            x = left - origin_left
            y = top - origin_top

        element = UIElement(
            depth=depth,
            control_type=control_type,
            name=name,
            value=value,
            text=text,
            automation_id=_none_if_empty(_safe(lambda: control.AutomationId)),
            class_name=_none_if_empty(_safe(lambda: control.ClassName)),
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


def _pattern(name: str) -> int:
    import uiautomation as auto

    return getattr(auto.PatternId, name)


def _property(name: str) -> int:
    import uiautomation as auto

    return getattr(auto.PropertyId, name)


def _none_if_empty(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def probe_window(
    hwnd: int,
    max_nodes: int,
    max_depth: int,
    include_offscreen: bool,
    max_element_chars: int = _DEFAULT_MAX_ELEMENT_CHARS,
) -> UISnapshot:
    """Run the probe in-process. Callers should prefer run_ui_probe()."""
    probe = _Probe(hwnd, max_nodes, max_depth, include_offscreen, max_element_chars)
    try:
        snapshot = probe.run()
    except Exception as exc:
        status = UI_STATUS_INACCESSIBLE if _is_access_denied(exc) else UI_STATUS_FAILED
        snapshot = UISnapshot(status=status, warnings=[f"probe error: {type(exc).__name__}"])
    return redact_password_elements(snapshot)


def run_ui_probe(
    hwnd: int,
    *,
    timeout_seconds: float,
    max_nodes: int,
    max_depth: int,
    include_offscreen: bool,
) -> UISnapshot:
    """Run the probe in a child process with a parent-enforced hard timeout.

    A hung UIA provider can block a thread forever; only a process boundary
    guarantees LabGuide stays responsive.
    """
    if sys.platform != "win32":
        return UISnapshot(status=UI_STATUS_UNSUPPORTED, warnings=["UIA probe requires Windows"])

    command = [
        sys.executable,
        "-m",
        "labguide.ui_probe",
        "--hwnd",
        str(hwnd),
        "--max-nodes",
        str(max_nodes),
        "--max-depth",
        str(max_depth),
    ]
    if include_offscreen:
        command.append("--include-offscreen")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        return UISnapshot(status=UI_STATUS_FAILED, warnings=[f"could not start probe: {exc}"])

    try:
        stdout, stderr = process.communicate(timeout=max(0.5, timeout_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=1.0)
        except Exception:
            pass
        return UISnapshot(
            status=UI_STATUS_TIMED_OUT,
            warnings=[f"UI probe exceeded {timeout_seconds:.1f}s and was terminated"],
        )

    if len(stdout) > _MAX_STDOUT_BYTES:
        return UISnapshot(status=UI_STATUS_FAILED, warnings=["UI probe output exceeded size limit"])

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        diagnostic = stderr.decode("utf-8", errors="replace").strip()[:300]
        warning = "UI probe returned unreadable output"
        if diagnostic:
            warning = f"{warning}: {diagnostic}"
        return UISnapshot(status=UI_STATUS_FAILED, warnings=[warning])

    if not isinstance(payload, dict):
        return UISnapshot(status=UI_STATUS_FAILED, warnings=["UI probe returned unexpected output"])

    return redact_password_elements(UISnapshot.from_dict(payload))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labguide.ui_probe",
        description=(
            "Read-only Windows UI Automation probe. Writes one JSON snapshot of "
            "the target window's accessibility tree to stdout."
        ),
    )
    parser.add_argument("--hwnd", type=int, required=True, help="target window handle (decimal)")
    parser.add_argument("--max-nodes", type=int, default=500, help="maximum UIA nodes to visit")
    parser.add_argument("--max-depth", type=int, default=20, help="maximum traversal depth")
    parser.add_argument(
        "--include-offscreen",
        action="store_true",
        help="include off-screen controls (excluded by default for privacy)",
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
    if sys.platform != "win32":
        json.dump(UISnapshot(status=UI_STATUS_UNSUPPORTED, warnings=["requires Windows"]).to_dict(), sys.stdout)
        return 0

    # Keep the stdout channel clean: any library noise goes to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        snapshot = probe_window(
            hwnd=args.hwnd,
            max_nodes=args.max_nodes,
            max_depth=args.max_depth,
            include_offscreen=args.include_offscreen,
            max_element_chars=args.max_element_chars,
        )
    sys.stdout.write(json.dumps(snapshot.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
