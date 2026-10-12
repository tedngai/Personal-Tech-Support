"""Long-running JSON-RPC stdio service wrapping the LabGuide capture pipeline.

The service owns the state the desktop UI mirrors: the pending attachment,
conversation history, the global hotkey, and the session log. The UI can
never capture or send on its own; it can only call these methods.

Transport is JSON Lines (see labguide.ipc). The reader runs on its own
thread and posts lines into a queue; the main loop processes requests,
hotkey triggers, and EOF strictly in order, so state mutations never race.
Every request handler runs on a bounded thread: if it exceeds its deadline,
the caller gets a TIMED_OUT error response and the abandoned thread finishes
in the background (all underlying operations are internally bounded).

Stdout is protocol-only. Diagnostics go to stderr and never include
captured content.
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
from typing import Any, Callable

from labguide.capture import CaptureError, capture_primary_display
from labguide.client import BackendClient
from labguide.config import AppConfig, load_config
from labguide.global_hotkey import HotkeyError
from labguide.ipc import (
    CAPTURE_FAILED,
    INVALID_PARAMS,
    TIMED_OUT,
    Event,
    IpcError,
    Request,
    error_from_exception,
    error_response,
    event_message,
    map_exception,
    parse_message,
    result_response,
)
from labguide.models import (
    UI_STATUS_COMPLETE,
    UI_STATUS_PARTIAL,
    CaptureTrigger,
    CapturedScreenshot,
    Message,
    UISnapshot,
    WindowIdentityError,
)
from labguide.platforms import get_adapter
from labguide.platforms.contracts import HotkeyListener, PlatformAdapter
from labguide.session_log import SessionLogger, SessionLogEntry

_DEFAULT_DEADLINE_SECONDS = 15.0
_CAPTURE_DEADLINE_SECONDS = 30.0

_WINDOW_IDENTITY_MESSAGES = {
    "closed": "the target window closed before capture",
    "minimized": "the target window is minimized",
    "zero_size": "the target window has no visible area",
    "unavailable": "the target window is no longer available",
}


class SidecarService:
    """JSON-RPC sidecar: capture pipeline, pending attachment, backend client."""

    def __init__(
        self,
        *,
        reader,
        writer,
        config: AppConfig | None = None,
        adapter: PlatformAdapter | None = None,
        backend: BackendClient | None = None,
        logger: SessionLogger | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._config = config or load_config()
        self._adapter = adapter or get_adapter()
        self._backend = backend or BackendClient(self._config.backend)
        self._logger = logger or SessionLogger(self._config.session.log_path)

        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._running = False
        self._hotkey_listener: HotkeyListener | None = None

        self._pending: CapturedScreenshot | None = None
        self._history: list[Message] = []

        self._methods: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], float]] = {
            "hello": (self._hello, _DEFAULT_DEADLINE_SECONDS),
            "permissions.status": (self._permissions_status, _DEFAULT_DEADLINE_SECONDS),
            "capture.start": (self._capture_start, _CAPTURE_DEADLINE_SECONDS),
            "attachment.get": (self._attachment_get, _DEFAULT_DEADLINE_SECONDS),
            "submit": (self._submit, self._config.backend.timeout_seconds + 20.0),
            "conversation.reset": (self._conversation_reset, _DEFAULT_DEADLINE_SECONDS),
            "discard": (self._discard, _DEFAULT_DEADLINE_SECONDS),
            "shutdown": (self._shutdown, _DEFAULT_DEADLINE_SECONDS),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Serve until EOF or a shutdown request. Blocks the calling thread."""
        self._running = True
        self._adapter.ensure_ready()
        self._start_hotkey()
        reader_thread = threading.Thread(
            target=self._read_loop, name="labguide-sidecar-reader", daemon=True
        )
        reader_thread.start()
        try:
            while self._running:
                if not self.pump(timeout=0.2):
                    continue
        finally:
            self._stop_hotkey()

    def _read_loop(self) -> None:
        try:
            for raw in iter(self._reader.readline, ""):
                if not self._running:
                    break
                self._queue.put(("line", raw))
                if raw == "":
                    break
        except Exception:
            pass
        finally:
            self._queue.put(("eof", None))

    def post_line(self, line: str) -> None:
        """Inject one transport line (thread-safe; also the test seam)."""
        self._queue.put(("line", line))

    def post_hotkey(self, trigger: CaptureTrigger) -> None:
        """Feed a hotkey trigger as if it came from the listener (test seam)."""
        self._queue.put(("hotkey", trigger))

    def pump(self, timeout: float) -> bool:
        """Process exactly one queued item. Returns True when an item ran."""
        try:
            kind, payload = self._queue.get(timeout=timeout)
        except queue.Empty:
            return False
        if kind == "line":
            self._handle_line(payload)
        elif kind == "hotkey":
            self._handle_hotkey(payload)
        elif kind == "eof":
            self._running = False
        return True

    def _start_hotkey(self) -> None:
        if not self._adapter.capabilities().global_hotkey:
            self._emit(
                "degraded",
                {"reason": "hotkey_unsupported", "message": "Global hotkey unavailable on this platform."},
            )
            return
        chord = self._config.capture.global_hotkey
        try:
            self._hotkey_listener = self._adapter.start_hotkey_listener(
                chord, self._on_hotkey_from_thread
            )
        except (HotkeyError, ValueError) as exc:
            self._hotkey_listener = None
            self._emit(
                "degraded",
                {
                    "reason": "hotkey_unavailable",
                    "message": f"Global capture hotkey unavailable ({exc}).",
                },
            )

    def _stop_hotkey(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None

    def _on_hotkey_from_thread(self, trigger: CaptureTrigger) -> None:
        # The listener's thread must never run capture logic directly.
        self._queue.put(("hotkey", trigger))

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _handle_line(self, line: str) -> None:
        try:
            parsed = parse_message(line)
        except IpcError as exc:
            self._send(error_from_exception(None, exc))
            return
        if parsed is None:
            return
        if isinstance(parsed, Event):
            self._send(event_message(parsed.name, parsed.data))
            return
        self._dispatch(parsed)

    def _dispatch(self, request: Request) -> None:
        entry = self._methods.get(request.method)
        if entry is None:
            self._send(
                error_response(
                    request.id,
                    -32601,
                    f"unknown method: {request.method}",
                    stage="dispatch",
                )
            )
            return
        handler, deadline = entry
        try:
            result = self._run_bounded(handler, request.params, deadline, request.method)
        except IpcError as exc:
            self._send(error_from_exception(request.id, exc))
        except Exception as exc:  # noqa: BLE001 - mapped to a content-free error
            self._send(error_from_exception(request.id, exc))
        else:
            self._send(result_response(request.id, result))
        if getattr(self, "_exit_after_response", False) and getattr(self, "_hard_exit", False):
            # Hard exit after the response is on the wire: the reader daemon
            # stays blocked on stdin, and interpreter finalization with a
            # locked buffered reader crashes at shutdown.
            sys.stdout.flush()
            os._exit(0)

    def _run_bounded(
        self,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        params: dict[str, Any],
        deadline: float,
        method: str,
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {}

        def target() -> None:
            try:
                outcome["result"] = handler(params)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller side
                outcome["error"] = exc

        worker = threading.Thread(
            target=target, name=f"labguide-sidecar-call-{method}", daemon=True
        )
        worker.start()
        worker.join(deadline)
        if worker.is_alive():
            # The abandoned thread finishes in the background because every
            # underlying operation is internally bounded.
            raise IpcError(
                TIMED_OUT,
                f"request exceeded its {deadline:.0f}-second deadline",
                stage=method,
            )
        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome["result"]

    def _send(self, line: str) -> None:
        with self._write_lock:
            self._writer.write(line + "\n")
            self._writer.flush()

    def _emit(self, name: str, data: dict[str, Any] | None = None) -> None:
        self._send(event_message(name, data))

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------

    def _hello(self, params: dict[str, Any]) -> dict[str, Any]:
        capabilities = self._adapter.capabilities()
        return {
            "service": "labguide-sidecar",
            "protocol": "2.0",
            "adapter": self._adapter.name,
            "capabilities": {
                "screenshot": capabilities.screenshot,
                "window_capture": capabilities.window_capture,
                "accessibility": capabilities.accessibility,
                "global_hotkey": capabilities.global_hotkey,
            },
            "config": _config_summary(self._config),
        }

    def _permissions_status(self, params: dict[str, Any]) -> dict[str, Any]:
        capabilities = self._adapter.capabilities()
        result: dict[str, Any] = {
            "platform": self._adapter.name,
            "capabilities": {
                "screenshot": capabilities.screenshot,
                "window_capture": capabilities.window_capture,
                "accessibility": capabilities.accessibility,
                "global_hotkey": capabilities.global_hotkey,
            },
        }
        if self._adapter.name == "macos":
            result["permissions"] = _macos_permissions()
        return result

    def _capture_start(self, params: dict[str, Any]) -> dict[str, Any]:
        mode = params.get("mode", "foreground")
        if mode not in ("foreground", "below", "display"):
            raise IpcError(
                INVALID_PARAMS,
                "mode must be one of: foreground, below, display",
                stage="capture.start",
            )
        screenshot = self._capture_for_mode(mode)
        with self._state_lock:
            # Replace the pending attachment only after capture succeeds.
            self._pending = screenshot
        return {"pending": True, "capture": _capture_summary(screenshot)}

    def _attachment_get(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._state_lock:
            pending = self._pending
        if pending is None:
            return {"pending": False, "attachment": None}
        context = pending.context
        attachment: dict[str, Any] = {
            "capture_id": pending.capture_id,
            "image_base64": pending.image_base64,
            "byte_count": pending.byte_count,
            "width": context.screen_width,
            "height": context.screen_height,
            "target": _target_payload(pending.target),
            "ui": _ui_payload(pending.ui),
        }
        return {"pending": True, "attachment": attachment}

    def _submit(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt = str(params.get("prompt", "")).strip()
        if not prompt:
            raise IpcError(
                INVALID_PARAMS, "prompt must be a non-empty string", stage="submit"
            )
        with_capture = bool(params.get("with_capture", False))
        attach_pending = bool(params.get("attach_pending", True))

        screenshot: CapturedScreenshot | None = None
        used_pending = False
        if with_capture:
            screenshot = self._capture_for_mode("below")
        else:
            with self._state_lock:
                screenshot = self._pending if attach_pending else None
            used_pending = screenshot is not None

        result = asyncio.run(
            self._backend.analyze(
                message=prompt,
                screenshot=screenshot,
                history=self._recent_history(),
                ui_max_text_chars=self._config.capture.ui_max_text_chars,
            )
        )

        with self._state_lock:
            self._history.append(Message(role="user", content=prompt))
            self._history.append(Message(role="assistant", content=result.answer))
            max_messages = self._config.session.max_history_turns * 4
            if len(self._history) > max_messages:
                del self._history[: len(self._history) - max_messages]
            if used_pending and self._pending is not None:
                if self._pending.capture_id == screenshot.capture_id:  # type: ignore[union-attr]
                    # Cleared only after a successful send, and only the
                    # attachment that was actually sent.
                    self._pending = None

        self._logger.write(
            SessionLogEntry(
                success=True,
                latency_ms=result.latency_ms,
                backend_url=self._config.backend.base_url,
                model=result.model,
                confidence=result.confidence,
                **_capture_log_fields(screenshot, used_pending),
            )
        )
        return {
            "answer": result.answer,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "used_capture_id": screenshot.capture_id if used_pending and screenshot else None,
        }

    def _conversation_reset(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._state_lock:
            self._history.clear()
        return {"cleared": True}

    def _discard(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._state_lock:
            had = self._pending is not None
            self._pending = None
        return {"discarded": had}

    def _shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        # Stop the hotkey first so no new trigger races the shutdown path.
        self._stop_hotkey()
        self._running = False
        self._exit_after_response = True
        return {"stopping": True}

    # ------------------------------------------------------------------
    # Capture paths
    # ------------------------------------------------------------------

    def _capture_for_mode(self, mode: str) -> CapturedScreenshot:
        """Capture for a UI-initiated request. Bounded, off the pump thread."""
        capture_config = self._config.capture
        if mode == "display":
            return capture_primary_display(
                capture_config.jpeg_quality,
                max_dimension=capture_config.jpeg_max_dimension,
                max_bytes=capture_config.jpeg_max_bytes,
            )

        try:
            hwnd = self._resolve_target(mode)
            return self._capture_hwnd(hwnd)
        except (WindowIdentityError, CaptureError):
            if mode == "below":
                # Same fallback as the TUI Ctrl+S path: primary display.
                return capture_primary_display(
                    capture_config.jpeg_quality,
                    max_dimension=capture_config.jpeg_max_dimension,
                    max_bytes=capture_config.jpeg_max_bytes,
                )
            raise

    def _resolve_target(self, mode: str) -> int:
        foreground = self._adapter.get_foreground_target()
        if mode == "below":
            hwnd = self._adapter.get_window_below(foreground)
        else:
            hwnd = foreground
        if not hwnd:
            raise CaptureError("no capturable target window found")
        if self._adapter.is_own_terminal(hwnd):
            raise IpcError(
                CAPTURE_FAILED,
                "Capture ignored: the target is LabGuide's own window.",
                stage="capture.start",
                category="own_terminal",
            )
        return hwnd

    def _capture_hwnd(self, hwnd: int) -> CapturedScreenshot:
        """Freeze identity, grab pixels, then probe accessibility.

        Pixels come first because they are time-sensitive; accessibility
        extraction can be slow. An unexpected probe failure degrades to a
        screenshot-only capture instead of losing the pixels.
        """
        capture_config = self._config.capture
        target = self._adapter.freeze_target(hwnd)
        screenshot = self._adapter.capture_target(target, capture_config)
        try:
            ui_snapshot = self._adapter.probe_accessibility(target, capture_config)
        except Exception:
            ui_snapshot = UISnapshot(
                status="failed",
                warnings=["accessibility probe failed unexpectedly"],
            )
        screenshot.target = target
        screenshot.ui = ui_snapshot
        return screenshot

    # ------------------------------------------------------------------
    # Hotkey path (event-driven)
    # ------------------------------------------------------------------

    def _handle_hotkey(self, trigger: CaptureTrigger) -> None:
        if not trigger.hwnd:
            return
        if self._adapter.is_own_terminal(trigger.hwnd):
            self._emit(
                "capture.ignored",
                {"reason": "own_terminal", "message": "Capture ignored: LabGuide's own window is in front."},
            )
            return
        self._emit("hotkey.pressed", {"triggered_at": trigger.triggered_at})
        try:
            screenshot = self._run_bounded(
                lambda _params: self._capture_hwnd(trigger.hwnd), {}, _CAPTURE_DEADLINE_SECONDS, "hotkey.capture"
            )
        except IpcError as exc:
            self._emit_capture_failed(exc)
        except Exception as exc:  # noqa: BLE001 - mapped to a content-free event
            self._emit_capture_failed(exc)
        else:
            with self._state_lock:
                # Replace the pending attachment only after capture succeeds.
                self._pending = screenshot
            self._emit("capture.completed", {"capture": _capture_summary(screenshot)})

    def _emit_capture_failed(self, exc: Exception) -> None:
        if isinstance(exc, WindowIdentityError):
            message = _WINDOW_IDENTITY_MESSAGES.get(
                exc.reason, "the target window is unavailable"
            )
            payload = {
                "message": f"Capture failed: {message}. Previous capture kept.",
                "stage": "window-identity",
                "category": exc.reason,
            }
        else:
            stage, code, category = map_exception(exc)
            payload = {
                "message": f"Capture failed: {exc}. Previous capture kept.",
                "stage": stage,
                "category": category,
            }
        self._emit("capture.failed", payload)

    # ------------------------------------------------------------------
    # Conversation helpers
    # ------------------------------------------------------------------

    def _recent_history(self) -> list[Message]:
        max_messages = self._config.session.max_history_turns * 4
        return self._history[-max_messages:]


# ----------------------------------------------------------------------
# Pure payload/summary builders (metadata only, never captured content
# beyond what an explicit attachment.get pulls)
# ----------------------------------------------------------------------


def _config_summary(config: AppConfig) -> dict[str, Any]:
    return {
        "model": config.backend.model,
        "backend_url": config.backend.base_url,
        "ui_enabled": config.capture.ui_enabled,
        "global_hotkey": config.capture.global_hotkey,
        "jpeg_max_dimension": config.capture.jpeg_max_dimension,
        "jpeg_max_bytes": config.capture.jpeg_max_bytes,
        "ui_max_nodes": config.capture.ui_max_nodes,
        "max_history_turns": config.session.max_history_turns,
    }


def _target_payload(target) -> dict[str, Any] | None:
    if target is None:
        return None
    return {
        "process_name": target.process_name,
        "window_title": target.window_title,
        "bounds": {"x": target.x, "y": target.y, "width": target.width, "height": target.height},
    }


def _ui_payload(ui: UISnapshot | None) -> dict[str, Any] | None:
    if ui is None:
        return None
    return {
        "status": ui.status,
        "element_count": len(ui.elements),
        "truncated": ui.truncated,
        "warnings": list(ui.warnings),
    }


def _capture_summary(screenshot: CapturedScreenshot) -> dict[str, Any]:
    """Capture metadata for transcript display. Never includes content."""
    summary: dict[str, Any] = {
        "capture_id": screenshot.capture_id,
        "byte_count": screenshot.byte_count,
        "width": screenshot.context.screen_width,
        "height": screenshot.context.screen_height,
        "target": _target_payload(screenshot.target),
        "ui": _ui_payload(screenshot.ui),
    }
    ui = screenshot.ui
    if ui is not None and ui.status in (UI_STATUS_COMPLETE, UI_STATUS_PARTIAL):
        summary["ui_elements"] = len(ui.elements)
    return summary


def _capture_log_fields(
    screenshot: CapturedScreenshot | None,
    used_pending: bool,
) -> dict[str, Any]:
    """Non-content capture metadata for the session log."""
    if screenshot is None:
        return {"capture_kind": "none"}
    kind = "pending" if used_pending else ("window" if screenshot.target is not None else "primary")
    fields: dict[str, Any] = {"capture_kind": kind}
    if screenshot.target is not None:
        fields["target_app"] = screenshot.target.process_name
    if screenshot.ui is not None:
        fields["ui_status"] = screenshot.ui.status
        fields["ui_node_count"] = screenshot.ui.node_count
        fields["ui_truncated"] = screenshot.ui.truncated
    return fields


def _macos_permissions() -> dict[str, bool]:
    """Best-effort TCC status. Never raises; absence means unknown."""
    try:
        from labguide.platforms.macos import permissions as macos_permissions

        return {
            "screen_recording": bool(macos_permissions.screen_capture_granted()),
            "accessibility": bool(macos_permissions.accessibility_granted()),
        }
    except Exception:
        return {}


def main() -> int:
    """Stdio entry point: python -m labguide.service"""
    import io

    reader = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    writer = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    service = SidecarService(reader=reader, writer=writer)
    # The reader daemon stays blocked on stdin across shutdown; interpreter
    # finalization with a locked buffered reader crashes, so the real stdio
    # service exits hard after the shutdown response is flushed.
    service._hard_exit = True
    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
