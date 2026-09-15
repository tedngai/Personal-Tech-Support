from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


class WindowIdentityError(RuntimeError):
    """The frozen target window cannot be captured.

    The reason is a category, never captured content: "closed", "minimized",
    "zero_size", or "unavailable".
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class CaptureTrigger:
    """Foreground target identity frozen at the global-hotkey event.

    ``hwnd`` is the platform-native window reference (Win32 HWND on Windows,
    CGWindowID on macOS). It is opaque outside the platform adapter.
    """

    hwnd: int
    triggered_at: str


@dataclass(slots=True)
class Message:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class ScreenContext:
    os_name: str
    screen_width: int
    screen_height: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class TargetWindow:
    """Identity and geometry of the foreground window frozen at capture time.

    Bounds are physical screen pixels. Element bounds inside a UISnapshot are
    relative to this window's origin.
    """

    hwnd: int
    pid: int
    process_name: str
    window_title: str
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "process_name": self.process_name,
            "window_title": self.window_title,
            "bounds": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
        }


# Status values for UISnapshot.status.
UI_STATUS_COMPLETE = "complete"
UI_STATUS_PARTIAL = "partial"
UI_STATUS_UNSUPPORTED = "unsupported"
UI_STATUS_TIMED_OUT = "timed_out"
UI_STATUS_INACCESSIBLE = "inaccessible"
UI_STATUS_FAILED = "failed"

# Control types worth keeping even when they carry no text, because they are
# interactive anchors the model should know about.
INTERACTIVE_CONTROL_TYPES = frozenset(
    {
        "Button",
        "CheckBox",
        "ComboBox",
        "Edit",
        "Hyperlink",
        "ListItem",
        "MenuItem",
        "RadioButton",
        "Slider",
        "Spinner",
        "TabItem",
        "TreeItem",
    }
)


@dataclass(slots=True)
class UIElement:
    """One node of the captured accessibility tree.

    Bounds are relative to the captured window origin when available.
    """

    depth: int
    control_type: str
    name: str | None = None
    value: str | None = None
    text: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    states: list[str] = field(default_factory=list)
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    is_password: bool = False

    def has_content(self) -> bool:
        return bool((self.name or "").strip() or (self.value or "").strip() or (self.text or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "control_type": self.control_type,
            "name": self.name,
            "value": self.value,
            "text": self.text,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "states": list(self.states),
            "bounds": _bounds_dict(self.x, self.y, self.width, self.height),
            "is_password": self.is_password,
        }


@dataclass(slots=True)
class UISnapshot:
    """Canonical structured UI context for one capture event.

    Contains no image data and is safe to serialize independently.
    """

    status: str
    elements: list[UIElement] = field(default_factory=list)
    node_count: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "elements": [element.to_dict() for element in self.elements],
            "node_count": self.node_count,
            "truncated": self.truncated,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UISnapshot:
        elements: list[UIElement] = []
        for raw in payload.get("elements", []):
            if not isinstance(raw, dict):
                continue
            bounds = raw.get("bounds") or {}
            elements.append(
                UIElement(
                    depth=int(raw.get("depth", 0)),
                    control_type=str(raw.get("control_type", "Unknown")),
                    name=raw.get("name"),
                    value=raw.get("value"),
                    text=raw.get("text"),
                    automation_id=raw.get("automation_id"),
                    class_name=raw.get("class_name"),
                    states=[str(state) for state in raw.get("states", [])],
                    x=bounds.get("x"),
                    y=bounds.get("y"),
                    width=bounds.get("width"),
                    height=bounds.get("height"),
                    is_password=bool(raw.get("is_password", False)),
                )
            )
        return cls(
            status=str(payload.get("status", UI_STATUS_FAILED)),
            elements=elements,
            node_count=int(payload.get("node_count", len(elements))),
            truncated=bool(payload.get("truncated", False)),
            warnings=[str(warning) for warning in payload.get("warnings", [])],
        )


@dataclass(slots=True)
class CapturedScreenshot:
    image_base64: str
    context: ScreenContext
    byte_count: int
    target: TargetWindow | None = None
    ui: UISnapshot | None = None
    # Unique per capture event. Used so a slow in-flight request can never
    # clear a newer pending attachment by accident.
    capture_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(slots=True)
class AnalyzeResult:
    answer: str
    model: str | None = None
    latency_ms: int | None = None
    confidence: float | None = None
    request_id: str | None = None


@dataclass(slots=True)
class HealthResult:
    reachable: bool
    service: str | None = None
    model: str | None = None
    detail: str | None = None


def _bounds_dict(
    x: int | None, y: int | None, width: int | None, height: int | None
) -> dict[str, int] | None:
    if x is None or y is None or width is None or height is None:
        return None
    return {"x": x, "y": y, "width": width, "height": height}
