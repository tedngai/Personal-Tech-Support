from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from labguide.capture import CaptureError, capture_primary_display, capture_window_region
from labguide.client import BackendClient, BackendError
from labguide.config import AppConfig, load_config
from labguide.global_hotkey import CaptureTrigger, GlobalHotkeyListener, HotkeyError
from labguide.models import (
    UI_STATUS_COMPLETE,
    UI_STATUS_PARTIAL,
    AnalyzeResult,
    CapturedScreenshot,
    HealthResult,
    Message,
)
from labguide.session_log import SessionLogEntry, SessionLogger
from labguide.ui_probe import run_ui_probe
from labguide.win32_window import (
    WindowIdentityError,
    ensure_dpi_awareness,
    freeze_target_window,
    get_foreground_hwnd,
    get_window_below,
    is_own_terminal,
)


BANNER = "\n".join(
    (
        "██████  ██████   █████   ██████ ██████",
        "██   ██ ██   ██ ██   ██    ██     ██  ",
        "██▄▄▄█  ██▄▄▄█▌ ██▄▄▄██    ██     ██  ",
        "██▀▀▀▀  ██▀▀██  ██▀▀▀██    ██     ██  ",
        "██      ██   ██ ██   ██    ██     ██  ",
        "",
        "██      █████  ██████    ██████  ██   ██ ██ █████▌  █████",
        "██     ██   ██ ██   ██   ██      ██   ██ ██ ██   ██ ██   ",
        "██     ██▄▄▄██ ██████▌   ██  ███ ██   ██ ██ ██   ██ █████",
        "██     ██▀▀▀██ ██   ██   ██   ██ ██   ██ ██ ██   ██ ██   ",
        "█████  ██   ██ ██████▌   ██████▌ ███████ ██ ██████▌ █████",
    )
)

_WINDOW_IDENTITY_MESSAGES = {
    "closed": "the target window closed before capture",
    "minimized": "the target window is minimized",
    "zero_size": "the target window has no visible area",
    "unavailable": "the target window is no longer available",
}


class LabGuideApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: #0d0d0d;
        color: #d4d4d4;
    }

    #scroll {
        height: 1fr;
        padding: 1 2 0 2;
    }

    #conversation {
        height: auto;
    }

    .msg {
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
    }

    .user-msg {
        color: #e8e8e8;
    }

    .assistant-msg {
        color: #c4c4c4;
    }

    .capture-msg {
        color: #505050;
    }

    .error-msg {
        color: #f44747;
    }

    .system-msg {
        color: #666;
    }

    .banner-msg {
        width: auto;
        color: #d28d6d;
        padding: 1 0 2 0;
        margin-bottom: 0;
    }

    .banner-wrap {
        width: 1fr;
        height: auto;
    }

    #bar {
        height: auto;
        border-top: solid #222;
        padding: 0 2;
    }

    #prompt-prefix {
        width: auto;
        color: #555;
        padding: 1 1 1 0;
    }

    #prompt {
        width: 1fr;
        height: 3;
        background: #1a1a1a;
        color: #f0f0f0;
        border: solid #333;
        padding: 0 1;
        margin: 0;
    }

    #prompt:focus {
        border: solid #5a5a5a;
        background: #222;
        color: #fff;
    }

    #hint {
        color: #404040;
        padding: 0 2;
        border-top: solid #181818;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "send_prompt", "Send with screenshot"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    TITLE = "Pratt Lab Guide"

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self.config: AppConfig = load_config(config_path)
        self.backend = BackendClient(self.config.backend)
        self.session_logger = SessionLogger(self.config.session.log_path)
        self.history: list[Message] = []
        self.request_in_flight = False
        self.pending_capture: CapturedScreenshot | None = None
        self._hotkey_listener: GlobalHotkeyListener | None = None

    @property
    def _ui_capture_active(self) -> bool:
        return self.config.capture.ui_enabled and sys.platform == "win32"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="scroll"):
            yield Vertical(id="conversation")
        with Horizontal(id="bar"):
            yield Static(">", id="prompt-prefix")
            yield Input(placeholder="Describe your issue...", id="prompt")
        yield Static(self._hint_text(), id="hint")

    def _hint_text(self) -> str:
        if self._ui_capture_active:
            hotkey = self.config.capture.global_hotkey
            return f"Enter send (+pending) | Ctrl+S capture window+send | {hotkey} capture in app | Ctrl+C quit"
        return "Ctrl+S capture+send | Ctrl+C quit"

    async def on_mount(self) -> None:
        self._append_banner()
        self._append_message("system", "Pratt Lab Guide · local VLM troubleshooting console")
        self._append_message("system", f"Model: {self.config.backend.model}")
        self._append_message("system", "Enter: Type Your Question  and  Ctrl+S: capture window below  ·  Ctrl+C: quit")

        if self._ui_capture_active:
            self._start_hotkey_listener()
        self._append_message("system", "")

        try:
            health = await self.backend.health_check()
        except Exception:
            health = HealthResult(reachable=False, detail="Could not reach backend.")

        if not health.reachable:
            self._append_message("error", health.detail or "Backend unreachable.")
        else:
            self._append_message("system", "Backend online.")

        self.query_one("#prompt", Input).focus()

    def on_unmount(self) -> None:
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
            self._hotkey_listener = None

    # ------------------------------------------------------------------
    # Global hotkey capture
    # ------------------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        hotkey = self.config.capture.global_hotkey
        try:
            listener = GlobalHotkeyListener(hotkey, self._on_hotkey_from_thread)
            listener.start()
        except (HotkeyError, ValueError) as exc:
            self._append_message(
                "error",
                f"Global capture hotkey unavailable ({exc}). Window capture disabled; Ctrl+S still works.",
            )
            return
        self._hotkey_listener = listener
        self._append_message(
            "system", f"Global capture ready: press {hotkey} while the problem app is in front."
        )

    def _on_hotkey_from_thread(self, trigger: CaptureTrigger) -> None:
        try:
            self.call_from_thread(self._handle_capture_trigger, trigger)
        except Exception:
            # App is shutting down; drop the trigger.
            pass

    def _handle_capture_trigger(self, trigger: CaptureTrigger) -> None:
        if not trigger.hwnd:
            return
        if is_own_terminal(trigger.hwnd):
            self._append_message(
                "system",
                "Capture ignored: the terminal is in front. Press the hotkey while the problem app is in front.",
            )
            return
        self._capture_foreground(trigger)

    @work(exclusive=True, group="capture")
    async def _capture_foreground(self, trigger: CaptureTrigger) -> None:
        try:
            screenshot = await asyncio.to_thread(self._do_window_capture, trigger)
        except WindowIdentityError as exc:
            detail = _WINDOW_IDENTITY_MESSAGES.get(exc.reason, "the target window is unavailable")
            self._append_message("error", f"Capture failed: {detail}. Previous capture kept.")
            return
        except CaptureError as exc:
            self._append_message("error", f"Capture failed: {exc}. Previous capture kept.")
            return
        except Exception:
            self._append_message("error", "Capture failed unexpectedly. Previous capture kept.")
            return

        # Replace the pending attachment only after the screenshot succeeds.
        self.pending_capture = screenshot
        self._append_message("capture", _format_capture_summary(screenshot))

    def _do_window_capture(self, trigger: CaptureTrigger) -> CapturedScreenshot:
        return self._capture_hwnd(trigger.hwnd)

    def _capture_hwnd(self, hwnd: int) -> CapturedScreenshot:
        """Freeze identity, grab pixels, then probe UIA. Runs off the UI thread.

        Pixels come first because they are time-sensitive; UIA can be slow.
        """
        capture_config = self.config.capture
        target = freeze_target_window(hwnd)
        screenshot = capture_window_region(
            target.x, target.y, target.width, target.height, capture_config.jpeg_quality
        )
        ui_snapshot = run_ui_probe(
            hwnd,
            timeout_seconds=capture_config.ui_timeout_seconds,
            max_nodes=capture_config.ui_max_nodes,
            max_depth=capture_config.ui_max_depth,
            include_offscreen=capture_config.ui_include_offscreen,
        )
        screenshot.target = target
        screenshot.ui = ui_snapshot
        return screenshot

    def _capture_for_ctrl_s(self) -> CapturedScreenshot:
        """Ctrl+S target: the window below the terminal, else the primary display.

        When the terminal is foreground, the window below it in z-order is
        usually the app the user just came from. Runs off the UI thread.
        """
        if self._ui_capture_active:
            below = get_window_below(get_foreground_hwnd())
            if below:
                try:
                    return self._capture_hwnd(below)
                except (WindowIdentityError, CaptureError):
                    pass  # Fall through to the primary-display fallback.
        return capture_primary_display(self.config.capture.jpeg_quality)

    # ------------------------------------------------------------------
    # Prompt submission
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_prompt(event.value, capture=False)

    def action_send_prompt(self) -> None:
        prompt = self.query_one("#prompt", Input).value
        self._submit_prompt(prompt, capture=True)

    def _submit_prompt(self, prompt: str, *, capture: bool) -> None:
        clean_prompt = prompt.strip()
        if not clean_prompt or self.request_in_flight:
            return

        input_widget = self.query_one("#prompt", Input)
        input_widget.value = ""
        self._append_message("user", clean_prompt)
        self.request_in_flight = True
        input_widget.disabled = True
        self._send_request(clean_prompt, capture=capture)

    @work(exclusive=True)
    async def _send_request(self, prompt: str, *, capture: bool) -> None:
        screenshot: CapturedScreenshot | None = None
        used_pending_capture = False
        try:
            if capture:
                # Ctrl+S: window below the terminal when possible, else display.
                screenshot = await asyncio.to_thread(self._capture_for_ctrl_s)
                if screenshot.target is not None:
                    self._append_message("capture", _format_capture_summary(screenshot))
                else:
                    self._append_message(
                        "capture",
                        f"Screen captured ({screenshot.context.screen_width}x{screenshot.context.screen_height}, {screenshot.byte_count/1024:.0f}KB)",
                    )
            elif self.pending_capture is not None:
                screenshot = self.pending_capture
                used_pending_capture = True

            result = await self.backend.analyze(
                message=prompt,
                screenshot=screenshot,
                history=self._recent_history(),
                ui_max_text_chars=self.config.capture.ui_max_text_chars,
            )
        except BackendError as exc:
            # The pending capture is retained for retry after backend errors.
            self._append_message("error", str(exc))
            self.session_logger.write(
                SessionLogEntry(
                    message=prompt,
                    success=False,
                    latency_ms=None,
                    backend_url=self.config.backend.base_url,
                    error=str(exc),
                    **_capture_log_fields(screenshot, used_pending_capture),
                )
            )
        except Exception as exc:
            self._append_message("error", f"Unexpected error: {exc}")
            self.session_logger.write(
                SessionLogEntry(
                    message=prompt,
                    success=False,
                    latency_ms=None,
                    backend_url=self.config.backend.base_url,
                    error=str(exc),
                    **_capture_log_fields(screenshot, used_pending_capture),
                )
            )
        else:
            self._handle_success(prompt, result)
            if used_pending_capture:
                # Cleared only after a successful send.
                self.pending_capture = None
            self.session_logger.write(
                SessionLogEntry(
                    message=prompt,
                    success=True,
                    latency_ms=result.latency_ms,
                    backend_url=self.config.backend.base_url,
                    model=result.model,
                    confidence=result.confidence,
                    **_capture_log_fields(screenshot, used_pending_capture),
                )
            )
        finally:
            self.request_in_flight = False
            input_widget = self.query_one("#prompt", Input)
            input_widget.disabled = False
            input_widget.focus()

    def _recent_history(self) -> list[Message]:
        return self.history[-self.config.session.max_history_turns :]

    def _handle_success(self, prompt: str, result: AnalyzeResult) -> None:
        self._append_message("assistant", result.answer)
        self.history.append(Message(role="user", content=prompt))
        self.history.append(Message(role="assistant", content=result.answer))

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    def _append_banner(self) -> None:
        conversation = self.query_one("#conversation", Vertical)
        conversation.mount(
            Center(
                Static(
                    BANNER,
                    classes="banner-msg",
                    markup=False,
                ),
                classes="msg banner-wrap",
            )
        )

    def _append_message(self, role: str, content: str) -> None:
        conversation = self.query_one("#conversation", Vertical)

        role_colors = {
            "user": "#e8e8e8",
            "assistant": "#c4c4c4",
            "capture": "#505050",
            "error": "#f44747",
            "system": "#666",
        }
        role_prefixes = {
            "user": "> ",
            "assistant": "",
            "capture": "  ",
            "error": "! ",
            "system": "",
        }
        color = role_colors.get(role, "#c4c4c4")
        prefix = role_prefixes.get(role, "")

        conversation.mount(
            Static(
                f"[{color}]{prefix}{content}[/{color}]",
                classes=f"msg {role}-msg",
                markup=True,
            )
        )
        self.call_after_refresh(self._scroll_end)

    def _scroll_end(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_end(animate=False)


def _format_capture_summary(screenshot: CapturedScreenshot) -> str:
    """Capture metadata for the transcript. Never includes captured content."""
    target = screenshot.target
    if target is None:
        return f"Captured ({screenshot.context.screen_width}x{screenshot.context.screen_height}, {screenshot.byte_count/1024:.0f}KB)"

    parts = [
        f"Captured {target.process_name} \"{target.window_title}\"",
        f"{screenshot.context.screen_width}x{screenshot.context.screen_height}",
        f"{screenshot.byte_count/1024:.0f}KB",
    ]

    ui = screenshot.ui
    if ui is None:
        parts.append("screenshot only")
    elif ui.status in (UI_STATUS_COMPLETE, UI_STATUS_PARTIAL):
        element_note = f"{len(ui.elements)} UI elements"
        if ui.truncated:
            element_note += ", truncated"
        if ui.status == UI_STATUS_PARTIAL:
            element_note += ", partial"
        parts.append(element_note)
    else:
        parts.append(f"UI text {ui.status} (screenshot only)")
    return f"{parts[0]} ({', '.join(parts[1:])})"


def _capture_log_fields(
    screenshot: CapturedScreenshot | None,
    used_pending: bool,
) -> dict:
    """Non-content capture metadata for the session log."""
    if screenshot is None:
        return {"capture_kind": "none"}
    if used_pending:
        kind = "pending"
    elif screenshot.target is not None:
        kind = "window"
    else:
        kind = "primary"
    fields: dict = {"capture_kind": kind}
    if screenshot.target is not None:
        fields["target_app"] = screenshot.target.process_name
    if screenshot.ui is not None:
        fields["ui_status"] = screenshot.ui.status
        fields["ui_node_count"] = screenshot.ui.node_count
        fields["ui_truncated"] = screenshot.ui.truncated
    return fields


def run() -> None:
    ensure_dpi_awareness()
    LabGuideApp().run()
