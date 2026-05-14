from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from labguide.capture import capture_primary_display
from labguide.client import BackendClient, BackendError
from labguide.config import AppConfig, load_config
from labguide.models import AnalyzeResult, HealthResult, Message
from labguide.session_log import SessionLogEntry, SessionLogger


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

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="scroll"):
            yield Vertical(id="conversation")
        with Horizontal(id="bar"):
            yield Static(">", id="prompt-prefix")
            yield Input(placeholder="Describe your issue...", id="prompt")
        yield Static("Ctrl+S capture+send | Ctrl+C quit", id="hint")

    async def on_mount(self) -> None:
        self._append_banner()
        self._append_message("system", "Pratt Lab Guide · local VLM troubleshooting console")
        self._append_message("system", f"Model: {self.config.backend.model}")
        self._append_message("system", "Enter: Type Your Question  and  Ctrl+S: capture screen  ·  Ctrl+C: quit")
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
        screenshot = None
        try:
            if capture:
                screenshot = await asyncio.to_thread(
                    capture_primary_display,
                    self.config.capture.jpeg_quality,
                )
                self._append_message(
                    "capture",
                    f"Screen captured ({screenshot.context.screen_width}x{screenshot.context.screen_height}, {screenshot.byte_count/1024:.0f}KB)",
                )

            result = await self.backend.analyze(
                message=prompt,
                screenshot=screenshot,
                history=self._recent_history(),
            )
        except BackendError as exc:
            self._append_message("error", str(exc))
            self.session_logger.write(
                SessionLogEntry(
                    message=prompt,
                    success=False,
                    latency_ms=None,
                    backend_url=self.config.backend.base_url,
                    error=str(exc),
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
                )
            )
        else:
            self._handle_success(prompt, result)
            self.session_logger.write(
                SessionLogEntry(
                    message=prompt,
                    success=True,
                    latency_ms=result.latency_ms,
                    backend_url=self.config.backend.base_url,
                    model=result.model,
                    confidence=result.confidence,
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


def run() -> None:
    LabGuideApp().run()
