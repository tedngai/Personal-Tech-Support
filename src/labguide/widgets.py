"""Chat transcript and prompt widgets.

Styling is expressed entirely through the role CSS classes defined in
``labguide.tcss``; these widgets never embed colors or markup themselves.
"""

from __future__ import annotations

from typing import Callable

from textual import events
from textual.widgets import Markdown, Static, TextArea

NEWLINE_KEYS = frozenset({"shift+enter", "alt+enter", "meta+enter", "ctrl+j"})


class TextMessage(Static):
    """Plain-text transcript line for one role (user, capture, system, error)."""

    def __init__(self, role: str, content: str) -> None:
        super().__init__(content, markup=False, classes=f"msg {role}-msg")


class MarkdownMessage(Markdown):
    """Assistant answer rendered as markdown."""

    def __init__(self, role: str, content: str) -> None:
        super().__init__(content, classes=f"msg {role}-msg")


class PromptInput(TextArea):
    """Multiline composer: Enter submits, Shift/Alt+Enter or Ctrl+J inserts a newline."""

    def __init__(self, on_submit: Callable[[str], None], **kwargs) -> None:
        self._on_submit = on_submit
        super().__init__(
            "",
            soft_wrap=True,
            show_line_numbers=False,
            **kwargs,
        )
        self.show_line_number_gutter = False
        self.show_minimap = False

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            if self.text.strip():
                self._on_submit(self.text)
            return
        if event.key in NEWLINE_KEYS:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)
