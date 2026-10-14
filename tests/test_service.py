"""Sidecar service contract tests.

Pure and cross-platform: a scripted fake adapter and fake backend drive an
in-memory transport, so no display, UIA, AX, or backend is required.
"""

from __future__ import annotations

import io
import json
import threading
import time
import unittest
from datetime import datetime, timezone

from labguide.capture import CaptureError
from labguide.client import BackendError
from labguide.config import AppConfig, BackendConfig, CaptureConfig, SessionConfig
from labguide.models import (
    AnalyzeResult,
    CapturedScreenshot,
    Message,
    ScreenContext,
    TargetWindow,
    UISnapshot,
    WindowIdentityError,
)
from labguide.platforms.contracts import PlatformCapabilities
from labguide.service.server import SidecarService


def make_screenshot(capture_id: str | None = None) -> CapturedScreenshot:
    shot = CapturedScreenshot(
        image_base64="aGVsbG8=",  # "hello"
        context=ScreenContext(os_name="test", screen_width=800, screen_height=600, timestamp="t"),
        byte_count=6,
        target=TargetWindow(
            hwnd=42,
            pid=7,
            process_name="Notepad",
            window_title="Untitled",
            x=0,
            y=0,
            width=800,
            height=600,
        ),
        ui=None,  # accessibility extraction merges in via the probe
    )
    if capture_id is not None:
        shot.capture_id = capture_id
    return shot


class FakeAdapter:
    name = "test"

    def __init__(self) -> None:
        self.capabilities_value = PlatformCapabilities(
            screenshot=True, window_capture=True, accessibility=True, global_hotkey=True
        )
        self.foreground = 42
        self.own_terminal_targets: set[int] = set()
        self.below: int = 42
        self.freeze_error: WindowIdentityError | None = None
        self.capture_error: CaptureError | None = None
        self.hotkey_error: HotkeyError | None = None
        self.probe_gate: threading.Event | None = None
        self.probe_error: Exception | None = None
        self.registered_callback = None
        self.stopped = False

    def capabilities(self) -> PlatformCapabilities:
        return self.capabilities_value

    def ensure_ready(self) -> None:
        return None

    def start_hotkey_listener(self, chord, callback):
        from labguide.global_hotkey import HotkeyError

        if self.hotkey_error is not None:
            raise HotkeyError(str(self.hotkey_error))
        self.registered_callback = callback

        class Listener:
            def stop(inner_self) -> None:
                self.stopped = True

        return Listener()

    def get_foreground_target(self) -> int:
        return self.foreground

    def is_own_terminal(self, target: int) -> bool:
        return target in self.own_terminal_targets

    def get_window_below(self, target: int) -> int:
        return self.below

    def list_capture_targets(self):
        from labguide.platforms.contracts import WindowChoice

        return [
            WindowChoice(hwnd=99, title="Firefox", process_name="firefox.exe"),
            WindowChoice(hwnd=42, title="Untitled - Notepad", process_name="Notepad.exe"),
        ]

    def freeze_target(self, target: int) -> TargetWindow:
        if self.freeze_error is not None:
            raise self.freeze_error
        return TargetWindow(hwnd=target, pid=7, process_name="Notepad", window_title="Untitled", x=0, y=0, width=800, height=600)

    def capture_target(self, target, config) -> CapturedScreenshot:
        if self.capture_error is not None:
            raise self.capture_error
        return make_screenshot()

    def probe_accessibility(self, target, config) -> UISnapshot:
        if self.probe_gate is not None:
            self.probe_gate.wait(timeout=10)
        if self.probe_error is not None:
            raise self.probe_error
        return UISnapshot(status="complete")



class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: BackendError | None = None
        self.reachable = True
        self.health_detail: str | None = None

    async def health_check(self):
        from labguide.models import HealthResult

        return HealthResult(
            reachable=self.reachable,
            service="openai-compatible",
            model="fake-model",
            detail=self.health_detail,
        )

    async def analyze(self, message, screenshot, history, ui_max_text_chars=10000):
        self.calls.append(
            {"message": message, "screenshot": screenshot, "history": list(history)}
        )
        if self.error is not None:
            raise self.error
        return AnalyzeResult(answer="try restarting", model="fake-model", latency_ms=5)


def make_service(adapter: FakeAdapter, backend: FakeBackend | None = None, logger=None) -> tuple[SidecarService, io.StringIO]:
    reader = io.StringIO()
    writer = io.StringIO()
    config = AppConfig(
        backend=BackendConfig(timeout_seconds=5.0),
        capture=CaptureConfig(),
        session=SessionConfig(log_path=None),
    )
    service = SidecarService(
        reader=reader,
        writer=writer,
        config=config,
        adapter=adapter,
        backend=backend or FakeBackend(),
        logger=logger,
    )
    return service, writer


def call(service: SidecarService, request_id, method, params=None, timeout=5.0) -> dict:
    """Post one request line and pump until its response appears."""
    line = json.dumps({"id": request_id, "method": method, "params": params or {}})
    service.post_line(line)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        service.pump(timeout=0.05)
        output = output_lines(service)
        for payload in output:
            if payload.get("id") == request_id and ("result" in payload or "error" in payload):
                return payload
    raise AssertionError(f"no response for request {request_id}")


def output_lines(service: SidecarService) -> list[dict]:
    raw = service._writer.getvalue()  # type: ignore[attr-defined]
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


class HelloTests(unittest.TestCase):
    def test_hello_reports_capabilities_and_config_without_secrets(self) -> None:
        adapter = FakeAdapter()
        service, _ = make_service(adapter)
        response = call(service, 1, "hello")
        result = response["result"]
        self.assertEqual(result["service"], "labguide-sidecar")
        self.assertEqual(result["adapter"], "test")
        self.assertTrue(result["capabilities"]["window_capture"])
        self.assertEqual(result["config"]["model"], BackendConfig().model)
        self.assertNotIn("api_key", json.dumps(result))

    def test_unknown_method_is_method_not_found(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 2, "nope")
        self.assertEqual(response["error"]["code"], -32601)

    def test_malformed_line_gets_parse_error(self) -> None:
        service, _ = make_service(FakeAdapter())
        service.post_line("{bad json")
        service.pump(timeout=1.0)
        payloads = output_lines(service)
        self.assertEqual(payloads[0]["error"]["code"], -32700)
        self.assertIsNone(payloads[0]["id"])


class CaptureTests(unittest.TestCase):
    def test_capture_start_is_immediate_while_probe_merges_in_background(self) -> None:
        adapter = FakeAdapter()
        adapter.probe_gate = threading.Event()  # probe blocked until released
        service, _ = make_service(adapter)
        response = call(service, 1, "capture.start")
        self.assertTrue(response["result"]["pending"])
        capture = response["result"]["capture"]
        self.assertEqual(capture["target"]["process_name"], "Notepad")
        self.assertEqual(capture["ui"]["status"], "pending")
        # Metadata only: no image bytes ride in responses or events.
        self.assertNotIn("image_base64", json.dumps(response))
        # Release the probe: it merges into the same capture and emits
        # attachment.updated for the UI to refresh.
        adapter.probe_gate.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not _has_event(service, "attachment.updated"):
            time.sleep(0.02)
        self.assertTrue(_has_event(service, "attachment.updated"))
        after = call(service, 2, "attachment.get")
        self.assertEqual(after["result"]["attachment"]["ui"]["status"], "complete")

    def test_attachment_get_returns_image_exactly_once_requested(self) -> None:
        service, _ = make_service(FakeAdapter())
        call(service, 1, "capture.start")
        response = call(service, 2, "attachment.get")
        self.assertTrue(response["result"]["pending"])
        self.assertEqual(response["result"]["attachment"]["image_base64"], "aGVsbG8=")

    def test_attachment_get_without_pending(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "attachment.get")
        self.assertEqual(response["result"], {"pending": False, "attachment": None})

    def test_own_terminal_target_is_rejected_without_losing_pending(self) -> None:
        adapter = FakeAdapter()
        adapter.own_terminal_targets = {42}
        service, _ = make_service(adapter)
        call(service, 1, "capture.start", {"mode": "display"})  # pending from display
        response = call(service, 2, "capture.start")
        self.assertEqual(response["error"]["data"]["category"], "own_terminal")
        still_there = call(service, 3, "attachment.get")
        self.assertTrue(still_there["result"]["pending"])

    def test_window_identity_failure_keeps_previous_pending(self) -> None:
        adapter = FakeAdapter()
        service, _ = make_service(adapter)
        call(service, 1, "capture.start")
        first = call(service, 2, "attachment.get")
        adapter.freeze_error = WindowIdentityError("closed")
        response = call(service, 3, "capture.start")
        self.assertEqual(response["error"]["code"], -32002)
        self.assertEqual(response["error"]["data"]["category"], "closed")
        still_there = call(service, 4, "attachment.get")
        self.assertEqual(
            still_there["result"]["attachment"]["capture_id"],
            first["result"]["attachment"]["capture_id"],
        )

    def test_capture_failure_maps_to_capture_failed(self) -> None:
        adapter = FakeAdapter()
        adapter.capture_error = CaptureError("window capture failed")
        service, _ = make_service(adapter)
        response = call(service, 1, "capture.start")
        self.assertEqual(response["error"]["code"], -32000)

    def test_below_mode_falls_back_to_display_when_no_window(self) -> None:
        adapter = FakeAdapter()
        adapter.below = 0
        service, _ = make_service(adapter)
        response = call(service, 1, "capture.start", {"mode": "below"})
        self.assertTrue(response["result"]["pending"])
        self.assertIsNone(response["result"]["capture"]["target"])

    def test_probe_failure_degrades_to_screenshot_only(self) -> None:
        adapter = FakeAdapter()
        adapter.probe_error = RuntimeError("uia provider died")
        service, _ = make_service(adapter)
        call(service, 1, "capture.start")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not _has_event(service, "attachment.updated"):
            time.sleep(0.02)
        after = call(service, 2, "attachment.get")
        self.assertEqual(after["result"]["attachment"]["ui"]["status"], "failed")

    def test_submit_waits_for_inflight_probe_and_sends_ui_text(self) -> None:
        adapter = FakeAdapter()
        adapter.probe_gate = threading.Event()
        backend = FakeBackend()
        service, _ = make_service(adapter, backend)
        call(service, 1, "capture.start")
        # The probe finishes while the submit is in flight.
        threading.Timer(0.3, adapter.probe_gate.set).start()
        response = call(service, 2, "submit", {"prompt": "what is this"}, timeout=10)
        self.assertEqual(response["result"]["answer"], "try restarting")
        sent = backend.calls[0]["screenshot"]
        self.assertEqual(sent.ui.status, "complete")


class SubmitTests(unittest.TestCase):
    def test_text_only_submit(self) -> None:
        backend = FakeBackend()
        service, _ = make_service(FakeAdapter(), backend)
        response = call(service, 1, "submit", {"prompt": "why is wifi slow"})
        self.assertEqual(response["result"]["answer"], "try restarting")
        self.assertEqual(backend.calls[0]["screenshot"], None)

    def test_submit_uses_pending_and_clears_only_the_sent_capture(self) -> None:
        backend = FakeBackend()
        adapter = FakeAdapter()
        service, _ = make_service(adapter, backend)
        captured = call(service, 1, "capture.start")["result"]["capture"]
        response = call(service, 2, "submit", {"prompt": "what is this error"})
        # The pending attachment was attached and cleared after success.
        self.assertEqual(response["result"]["used_capture_id"], captured["capture_id"])
        after = call(service, 3, "attachment.get")
        self.assertFalse(after["result"]["pending"])
        # History retained for follow-up turns.
        self.assertEqual(len(backend.calls[0]["history"]), 0)
        call(service, 4, "submit", {"prompt": "and now"})
        self.assertEqual(
            [m.role for m in backend.calls[1]["history"]], ["user", "assistant"]
        )

    def test_newer_pending_survives_a_send_of_older_capture(self) -> None:
        adapter = FakeAdapter()
        service, _ = make_service(adapter)
        call(service, 1, "capture.start")  # capture A
        first = call(service, 2, "attachment.get")
        call(service, 3, "capture.start")  # capture B replaces A
        second = call(service, 4, "attachment.get")
        self.assertNotEqual(
            first["result"]["attachment"]["capture_id"],
            second["result"]["attachment"]["capture_id"],
        )
        call(service, 5, "submit", {"prompt": "send pending"})
        after = call(service, 6, "attachment.get")
        # The submitted (latest) capture is the one cleared; nothing older.
        self.assertFalse(after["result"]["pending"])

    def test_backend_error_retains_pending(self) -> None:
        backend = FakeBackend()
        backend.error = BackendError("http 500")
        service, _ = make_service(FakeAdapter(), backend)
        call(service, 1, "capture.start")
        response = call(service, 2, "submit", {"prompt": "hello"})
        self.assertEqual(response["error"]["code"], -32004)
        after = call(service, 3, "attachment.get")
        self.assertTrue(after["result"]["pending"])

    def test_empty_prompt_is_invalid_params(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "submit", {"prompt": "   "})
        self.assertEqual(response["error"]["code"], -32602)

    def test_submit_with_capture_uses_below_then_display(self) -> None:
        adapter = FakeAdapter()
        adapter.below = 0
        service, _ = make_service(adapter)
        response = call(service, 1, "submit", {"prompt": "look", "with_capture": True})
        self.assertEqual(response["result"]["answer"], "try restarting")
        after = call(service, 2, "attachment.get")
        # with_capture bypasses pending: none existed, none stored.
        self.assertFalse(after["result"]["pending"])


class ConversationAndLifecycleTests(unittest.TestCase):
    def test_conversation_reset_clears_history(self) -> None:
        backend = FakeBackend()
        service, _ = make_service(FakeAdapter(), backend)
        call(service, 1, "submit", {"prompt": "one"})
        response = call(service, 2, "conversation.reset")
        self.assertTrue(response["result"]["cleared"])
        call(service, 3, "submit", {"prompt": "two"})
        self.assertEqual(len(backend.calls[1]["history"]), 0)

    def test_discard_reports_whether_something_was_discarded(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "discard")
        self.assertFalse(response["result"]["discarded"])
        call(service, 2, "capture.start")
        response = call(service, 3, "discard")
        self.assertTrue(response["result"]["discarded"])

    def test_shutdown_stops_loop_and_stops_hotkey(self) -> None:
        adapter = FakeAdapter()
        service, _ = make_service(adapter)
        adapter.registered_callback = lambda t: None  # pretend registration
        response = call(service, 1, "shutdown")
        self.assertTrue(response["result"]["stopping"])
        self.assertFalse(service._running)


class HotkeyEventTests(unittest.TestCase):
    def test_hotkey_trigger_emits_pressed_then_completed(self) -> None:
        service, _ = make_service(FakeAdapter())
        trigger_time = datetime.now(timezone.utc).isoformat()
        service.post_hotkey(
            type("T", (), {"hwnd": 42, "triggered_at": trigger_time})()
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _has_event(service, "capture.completed"):
            service.pump(timeout=0.05)
        events = output_lines(service)
        names = [
            p["event"]
            for p in events
            if "event" in p and p["event"] != "attachment.updated"
        ]
        self.assertEqual(names, ["hotkey.pressed", "capture.completed"])
        completed = next(p for p in events if p.get("event") == "capture.completed")
        self.assertEqual(completed["data"]["capture"]["target"]["process_name"], "Notepad")

    def test_hotkey_own_terminal_emits_ignored(self) -> None:
        adapter = FakeAdapter()
        adapter.own_terminal_targets = {42}
        service, _ = make_service(adapter)
        service.post_hotkey(type("T", (), {"hwnd": 42, "triggered_at": "t"})())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _has_event(service, "capture.ignored"):
            service.pump(timeout=0.05)
        events = [p for p in output_lines(service) if "event" in p]
        self.assertEqual(events[0]["event"], "capture.ignored")

    def test_hotkey_capture_failure_emits_failed_event_with_category(self) -> None:
        adapter = FakeAdapter()
        adapter.freeze_error = WindowIdentityError("closed")
        service, _ = make_service(adapter)
        service.post_hotkey(type("T", (), {"hwnd": 42, "triggered_at": "t"})())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _has_event(service, "capture.failed"):
            service.pump(timeout=0.05)
        events = [p for p in output_lines(service) if "event" in p]
        self.assertEqual(events[0]["event"], "hotkey.pressed")
        self.assertEqual(events[1]["event"], "capture.failed")
        self.assertEqual(events[1]["data"]["category"], "closed")
        self.assertNotIn("42", events[1]["data"]["message"])


def _has_event(service: SidecarService, name: str) -> bool:
    return any(
        p.get("event") == name for p in output_lines(service)
    )



class WindowPickerTests(unittest.TestCase):
    def test_windows_list_returns_choices(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "windows.list")
        windows = response["result"]["windows"]
        self.assertEqual(windows[0]["id"], 99)
        self.assertEqual(windows[0]["title"], "Firefox")
        self.assertEqual(windows[0]["process_name"], "firefox.exe")
        self.assertEqual(windows[1]["id"], 42)

    def test_capture_window_mode_captures_chosen_hwnd(self) -> None:
        adapter = FakeAdapter()
        service, _ = make_service(adapter)
        response = call(service, 1, "capture.start", {"mode": "window", "hwnd": 99})
        self.assertTrue(response["result"]["pending"])
        # The fake adapter always reports Notepad; what matters is the
        # request path succeeds and stores a pending attachment.
        after = call(service, 2, "attachment.get")
        self.assertTrue(after["result"]["pending"])

    def test_capture_window_mode_requires_hwnd(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "capture.start", {"mode": "window"})
        self.assertEqual(response["error"]["code"], -32602)

    def test_capture_window_mode_rejects_own_window(self) -> None:
        adapter = FakeAdapter()
        adapter.own_terminal_targets = {99}
        service, _ = make_service(adapter)
        response = call(service, 1, "capture.start", {"mode": "window", "hwnd": 99})
        self.assertEqual(response["error"]["data"]["category"], "own_terminal")

    def test_capture_window_mode_rejects_bool_hwnd(self) -> None:
        # bool is a subclass of int; True must not pass as hwnd 1.
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "capture.start", {"mode": "window", "hwnd": True})
        self.assertEqual(response["error"]["code"], -32602)


class HealthCheckTests(unittest.TestCase):
    def test_health_check_reports_reachable_backend(self) -> None:
        service, _ = make_service(FakeAdapter())
        response = call(service, 1, "health.check")
        self.assertTrue(response["result"]["reachable"])
        self.assertEqual(response["result"]["model"], "fake-model")

    def test_health_check_reports_unreachable_backend(self) -> None:
        backend = FakeBackend()
        backend.reachable = False
        backend.health_detail = "connection refused"
        service, _ = make_service(FakeAdapter(), backend)
        response = call(service, 1, "health.check")
        self.assertFalse(response["result"]["reachable"])
        self.assertEqual(response["result"]["detail"], "connection refused")


class RecordingLogger:
    def __init__(self) -> None:
        self.entries: list = []

    def write(self, entry) -> None:
        self.entries.append(entry)


class SessionLogComplianceTests(unittest.TestCase):
    def test_failed_submit_logs_stage_category_not_verbatim_text(self) -> None:
        backend = FakeBackend()
        backend.error = BackendError("http 502: model 'x' rejected prompt 'hi'")
        logger = RecordingLogger()
        service, _ = make_service(FakeAdapter(), backend, logger=logger)
        call(service, 1, "capture.start")
        response = call(service, 2, "submit", {"prompt": "hi"})
        self.assertEqual(response["error"]["code"], -32004)
        self.assertEqual(len(logger.entries), 1)
        entry = logger.entries[0]
        self.assertFalse(entry.success)
        self.assertEqual(entry.error, "backend")
        # Verbatim backend text must never reach the log.
        self.assertNotIn("prompt 'hi'", str(entry))

    def test_successful_submit_logs_operational_metadata_only(self) -> None:
        logger = RecordingLogger()
        service, _ = make_service(FakeAdapter(), FakeBackend(), logger=logger)
        call(service, 1, "capture.start")
        call(service, 2, "submit", {"prompt": "hi"})
        self.assertEqual(len(logger.entries), 1)
        entry = logger.entries[0]
        self.assertTrue(entry.success)
        self.assertEqual(entry.capture_kind, "pending")
        self.assertNotIn("hi", str(entry))


if __name__ == "__main__":
    unittest.main()
