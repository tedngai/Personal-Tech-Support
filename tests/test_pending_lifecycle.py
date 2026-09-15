from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from labguide.app import LabGuideApp
from labguide.models import CapturedScreenshot, ScreenContext


def make_screenshot() -> CapturedScreenshot:
    return CapturedScreenshot(
        image_base64="QUJD",
        context=ScreenContext("windows", 100, 100, "2026-09-15T00:00:00+00:00"),
        byte_count=3,
    )


def make_app(temp_dir: str) -> LabGuideApp:
    config_path = Path(temp_dir) / "labguide.toml"
    config_path.write_text("[session]\nlog_path = \"\"\n", encoding="utf-8")
    return LabGuideApp(config_path)


class PendingCaptureLifecycleTests(unittest.TestCase):
    def test_clear_only_matching_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = make_app(temp_dir)
            submitted = make_screenshot()
            newer = make_screenshot()
            app.pending_capture = submitted

            # A different (newer) capture must never be cleared by the old send.
            app.pending_capture = newer
            self.assertFalse(app._maybe_clear_pending(submitted))
            self.assertIs(app.pending_capture, newer)

            # The matching capture clears.
            self.assertTrue(app._maybe_clear_pending(newer))
            self.assertIsNone(app.pending_capture)

    def test_clear_with_no_pending_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = make_app(temp_dir)
            self.assertFalse(app._maybe_clear_pending(make_screenshot()))

    def test_history_counts_turns_not_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = make_app(temp_dir)
            app.config.session.max_history_turns = 2
            from labguide.models import Message

            app.history = [
                Message("user", "u1"),
                Message("assistant", "a1"),
                Message("user", "u2"),
                Message("assistant", "a2"),
                Message("user", "u3"),
                Message("assistant", "a3"),
            ]
            recent = app._recent_history()
            self.assertEqual(len(recent), 4)
            self.assertEqual(recent[0].content, "u2")


if __name__ == "__main__":
    unittest.main()
