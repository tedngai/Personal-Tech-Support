from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from labguide.app import LabGuideApp, _capture_log_fields, _format_capture_summary
from labguide.models import (
    UI_STATUS_COMPLETE,
    UI_STATUS_TIMED_OUT,
    CapturedScreenshot,
    ScreenContext,
    TargetWindow,
    UIElement,
    UISnapshot,
)


def make_screenshot(target=None, ui=None) -> CapturedScreenshot:
    return CapturedScreenshot(
        image_base64="QUJD",
        context=ScreenContext("windows", 1200, 800, "2026-07-26T00:00:00+00:00"),
        byte_count=86016,
        target=target,
        ui=ui,
    )


def make_target() -> TargetWindow:
    return TargetWindow(1, 2, "notepad.exe", "Untitled - Notepad", 0, 0, 1200, 800)


class CaptureSummaryTests(unittest.TestCase):
    def test_full_capture_summary(self) -> None:
        ui = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[UIElement(depth=1, control_type="Edit", text="x")],
            node_count=5,
        )
        summary = _format_capture_summary(make_screenshot(make_target(), ui))
        self.assertIn("notepad.exe", summary)
        self.assertIn("Untitled - Notepad", summary)
        self.assertIn("1200x800", summary)
        self.assertIn("1 UI elements", summary)
        self.assertNotIn("x\"", summary)

    def test_timed_out_summary_says_screenshot_only(self) -> None:
        ui = UISnapshot(status=UI_STATUS_TIMED_OUT)
        summary = _format_capture_summary(make_screenshot(make_target(), ui))
        self.assertIn("timed_out", summary)
        self.assertIn("screenshot only", summary)

    def test_truncated_summary(self) -> None:
        ui = UISnapshot(status=UI_STATUS_COMPLETE, node_count=3, truncated=True)
        summary = _format_capture_summary(make_screenshot(make_target(), ui))
        self.assertIn("truncated", summary)


class CaptureLogFieldTests(unittest.TestCase):
    def test_no_capture(self) -> None:
        self.assertEqual(_capture_log_fields(None, False), {"capture_kind": "none"})

    def test_pending_capture_fields_carry_no_content(self) -> None:
        ui = UISnapshot(status=UI_STATUS_COMPLETE, node_count=7, truncated=False)
        fields = _capture_log_fields(make_screenshot(make_target(), ui), True)
        self.assertEqual(fields["capture_kind"], "pending")
        self.assertEqual(fields["target_app"], "notepad.exe")
        self.assertEqual(fields["ui_status"], "complete")
        self.assertEqual(fields["ui_node_count"], 7)
        self.assertFalse(fields["ui_truncated"])
        # No title, no text, no image data.
        self.assertNotIn("Untitled", str(fields))
        self.assertNotIn("QUJD", str(fields))

    def test_primary_capture_fields(self) -> None:
        fields = _capture_log_fields(make_screenshot(), False)
        self.assertEqual(fields["capture_kind"], "primary")
        self.assertNotIn("ui_status", fields)

    def test_window_capture_fields(self) -> None:
        fields = _capture_log_fields(make_screenshot(make_target()), False)
        self.assertEqual(fields["capture_kind"], "window")
        self.assertEqual(fields["target_app"], "notepad.exe")


@unittest.skipUnless(sys.platform == "win32", "TUI smoke test requires Windows console support")
class AppSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_mounts_with_ui_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "labguide.toml"
            config_path.write_text("[session]\nlog_path = \"\"\n", encoding="utf-8")
            app = LabGuideApp(config_path)
            async with app.run_test():
                self.assertIsNone(app._hotkey_listener)
                self.assertFalse(app.config.capture.ui_enabled)
                self.assertIsNone(app.pending_capture)

    async def test_app_mounts_and_starts_hotkey_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "labguide.toml"
            config_path.write_text(
                "[capture]\nui_enabled = true\nglobal_hotkey = \"ctrl+shift+f24\"\n"
                "[session]\nlog_path = \"\"\n",
                encoding="utf-8",
            )
            app = LabGuideApp(config_path)
            async with app.run_test():
                self.assertTrue(app.config.capture.ui_enabled)
                self.assertIsNotNone(app._hotkey_listener)
            # Listener is cleaned up on unmount.
            self.assertIsNone(app._hotkey_listener)


if __name__ == "__main__":
    unittest.main()
