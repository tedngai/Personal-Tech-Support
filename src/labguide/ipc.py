"""JSON-RPC-style envelope for the LabGuide sidecar IPC channel.

Transport is JSON Lines: one JSON object per line. Three message shapes:

- Request  (UI -> sidecar):   {"jsonrpc": "2.0", "id": 1, "method": "...", "params": {}}
- Response (sidecar -> UI):   {"jsonrpc": "2.0", "id": 1, "result": {...}}
                              {"jsonrpc": "2.0", "id": 1, "error": {...}}
- Event    (sidecar -> UI, unrequested):
                              {"event": "capture.completed", "data": {...}}

Error responses carry a numeric code plus stage/category metadata. Error
messages identify the stage and category of a failure, never captured
content: no screenshots, base64 data, UI text, field values, or prompts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2.0"

# Standard JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# LabGuide domain error codes.
CAPTURE_FAILED = -32000
PERMISSION_DENIED = -32001
WINDOW_UNAVAILABLE = -32002
HOTKEY_UNAVAILABLE = -32003
BACKEND_FAILED = -32004
TIMED_OUT = -32005


class IpcError(RuntimeError):
    """A handler failure with a mapped IPC error code.

    Messages must identify stage and category only, never captured content.
    """

    def __init__(
        self,
        code: int,
        message: str,
        *,
        stage: str | None = None,
        category: str | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.category = category
        super().__init__(message)


@dataclass(slots=True)
class Request:
    """One UI-initiated call."""

    id: int | str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    """One sidecar-initiated notification."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedError:
    """A line that could not be interpreted as a request."""

    code: int
    message: str


def parse_message(line: str) -> Request | Event | None:
    """Parse one transport line.

    Returns None for blank lines, a Request for calls, an Event for
    notifications, and raises IpcError for anything malformed.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        raise IpcError(PARSE_ERROR, "request is not valid JSON") from None
    if not isinstance(payload, dict):
        raise IpcError(INVALID_REQUEST, "message must be a JSON object")

    if "event" in payload:
        name = payload["event"]
        if not isinstance(name, str) or not name:
            raise IpcError(INVALID_REQUEST, "event name must be a non-empty string")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise IpcError(INVALID_REQUEST, "event data must be an object")
        return Event(name=name, data=data)

    if "method" not in payload:
        raise IpcError(INVALID_REQUEST, "message has neither method nor event")

    request_id = payload.get("id")
    if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
        raise IpcError(INVALID_REQUEST, "request id must be an integer or string")
    method = payload["method"]
    if not isinstance(method, str) or not method:
        raise IpcError(INVALID_REQUEST, "method must be a non-empty string")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise IpcError(INVALID_PARAMS, "params must be an object")
    return Request(id=request_id, method=method, params=params)


def result_response(request_id: int | str, result: dict[str, Any]) -> str:
    return json.dumps(
        {"jsonrpc": PROTOCOL_VERSION, "id": request_id, "result": result}
    )


def error_response(
    request_id: int | str,
    code: int,
    message: str,
    *,
    stage: str | None = None,
    category: str | None = None,
) -> str:
    data: dict[str, Any] = {}
    if stage is not None:
        data["stage"] = stage
    if category is not None:
        data["category"] = category
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return json.dumps(
        {"jsonrpc": PROTOCOL_VERSION, "id": request_id, "error": error}
    )


def error_from_exception(request_id: int | str, exc: Exception) -> str:
    """Map a handler exception to an error response.

    Known failure types map to domain codes with stage/category data.
    Anything unexpected becomes a generic internal error; the exception text
    is used as-is because handler errors are already content-free by rule.
    """
    if isinstance(exc, IpcError):
        return error_response(
            request_id, exc.code, str(exc), stage=exc.stage, category=exc.category
        )
    stage, code, category = _map_exception(exc)
    return error_response(request_id, code, str(exc), stage=stage, category=category)


def _map_exception(exc: Exception) -> tuple[str, int, str | None]:
    # Imported lazily so this module stays importable without platform or
    # heavy dependencies and is unit-testable on any OS.
    from labguide.capture import CaptureError
    from labguide.client import BackendError
    from labguide.models import WindowIdentityError
    from labguide.global_hotkey import HotkeyError

    if isinstance(exc, WindowIdentityError):
        return "window-identity", WINDOW_UNAVAILABLE, exc.reason
    if isinstance(exc, CaptureError):
        return "capture", CAPTURE_FAILED, None
    if isinstance(exc, HotkeyError):
        return "hotkey", HOTKEY_UNAVAILABLE, None
    if isinstance(exc, BackendError):
        return "backend", BACKEND_FAILED, None
    return "internal", INTERNAL_ERROR, None


def event_message(name: str, data: dict[str, Any] | None = None) -> str:
    return json.dumps({"event": name, "data": data or {}})
