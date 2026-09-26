from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

from labguide.app import LabGuideApp, _status_line
from labguide.models import CapturedScreenshot, ScreenContext, TargetWindow
from labguide.theme import THEME_NAME, labguide_theme
from labguide.widgets import MarkdownMessage, TextMessage

TCSS_PATH = Path(__file__).resolve().parent.parent / "src" / "labguide" / "labguide.tcss"

# Variables Textual generates from Theme base colors, plus our custom keys.
_BASE_TOKENS = {
    "primary",
    "secondary",
    "accent",
    "success",
    "warning",
    "error",
    "foreground",
    "background",
    "surface",
    "panel",
    "boost",
}


def make_shot(target: TargetWindow | None) -> CapturedScreenshot:
    return CapturedScreenshot(
        image_base64="SECRET-IMAGE-DATA",
        context=ScreenContext("windows", 800, 600, "2026-09-20T00:00:00+00:00"),
        byte_count=3,
        target=target,
    )


class ThemeTokenTests(unittest.TestCase):
    def test_tcss_contains_no_literal_colors(self) -> None:
        css = TCSS_PATH.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
        self.assertIsNone(re.search(r"\b(?:rgb|hsl)\(", css))

    def test_tcss_only_uses_defined_tokens(self) -> None:
        theme = labguide_theme()
        allowed = set(_BASE_TOKENS) | set(theme.variables)
        css = TCSS_PATH.read_text(encoding="utf-8")
        used = set(re.findall(r"\$([a-zA-Z0-9_-]+)", css))
        self.assertEqual(used - allowed, set())

    def test_theme_name_and_dark(self) -> None:
        theme = labguide_theme()
        self.assertEqual(theme.name, THEME_NAME)
        self.assertTrue(theme.dark)

    def test_role_tokens_defined(self) -> None:
        variables = labguide_theme().variables
        for role in ("user", "assistant", "capture", "system", "error"):
            key = f"bar-{role}" if role != "error" else "bar-error"
            self.assertIn(key, variables)


class StatusLineTests(unittest.TestCase):
    def test_backend_states(self) -> None:
        self.assertIn("checking", _status_line("m", None, False, None))
        self.assertIn("online", _status_line("m", True, False, None))
        self.assertIn("offline", _status_line("m", False, False, None))

    def test_model_always_shown(self) -> None:
        self.assertIn("model: vision-7b", _status_line("vision-7b", True, False, None))

    def test_thinking_only_while_in_flight(self) -> None:
        self.assertIn("thinking", _status_line("m", True, True, None))
        self.assertNotIn("thinking", _status_line("m", True, False, None))

    def test_pending_shows_process_name_not_title_or_image(self) -> None:
        target = TargetWindow(1, 2, "notepad.exe", "Secret Doc Title", 0, 0, 10, 10)
        line = _status_line("m", True, False, make_shot(target))
        self.assertIn("notepad.exe", line)
        self.assertNotIn("Secret Doc Title", line)
        self.assertNotIn("SECRET-IMAGE-DATA", line)

    def test_pending_display_capture_says_screen(self) -> None:
        self.assertIn("screen", _status_line("m", True, False, make_shot(None)))


class WidgetTests(unittest.TestCase):
    def test_text_message_role_classes(self) -> None:
        widget = TextMessage("capture", "Captured x")
        self.assertIn("msg", widget.classes)
        self.assertIn("capture-msg", widget.classes)

    def test_markdown_message_role_classes(self) -> None:
        widget = MarkdownMessage("assistant", "hello")
        self.assertIn("msg", widget.classes)
        self.assertIn("assistant-msg", widget.classes)

    def test_text_message_renders_brackets_literally(self) -> None:
        widget = TextMessage("user", "[bold]hi[/bold]")
        self.assertEqual(str(widget.renderable), "[bold]hi[/bold]")


@unittest.skipUnless(sys.platform == "win32", "TUI smoke test requires Windows console support")
class ThemeApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_applies_theme_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "labguide.toml"
            config_path.write_text("[session]\nlog_path = \"\"\n", encoding="utf-8")
            app = LabGuideApp(config_path)
            async with app.run_test():
                self.assertEqual(app.theme, THEME_NAME)
                self.assertEqual(len(app.query("#status-bar")), 1)
                self.assertEqual(len(app.query("PromptInput")), 1)
                self.assertEqual(len(app.query("Footer")), 1)


if __name__ == "__main__":
    unittest.main()
