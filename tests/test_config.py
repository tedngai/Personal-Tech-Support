from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from labguide.config import load_config


EXAMPLE_TOML = """
[capture]
jpeg_quality = 70
ui_enabled = true
ui_timeout_seconds = 2.5
ui_max_nodes = 123
ui_max_depth = 7
ui_max_text_chars = 4321
ui_include_offscreen = true
global_hotkey = "ctrl+alt+k"
"""


class CaptureConfigTests(unittest.TestCase):
    def test_defaults_keep_feature_disabled(self) -> None:
        config = load_config(Path("does-not-exist.toml"))
        capture = config.capture
        self.assertFalse(capture.ui_enabled)
        self.assertEqual(capture.ui_timeout_seconds, 3.0)
        self.assertEqual(capture.ui_max_nodes, 500)
        self.assertEqual(capture.ui_max_depth, 20)
        self.assertEqual(capture.ui_max_text_chars, 10000)
        self.assertFalse(capture.ui_include_offscreen)
        self.assertEqual(capture.global_hotkey, "ctrl+shift+space")
        self.assertEqual(capture.jpeg_quality, 80)

    def test_reads_capture_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "labguide.toml"
            path.write_text(EXAMPLE_TOML, encoding="utf-8")
            config = load_config(path)
        capture = config.capture
        self.assertEqual(capture.jpeg_quality, 70)
        self.assertTrue(capture.ui_enabled)
        self.assertEqual(capture.ui_timeout_seconds, 2.5)
        self.assertEqual(capture.ui_max_nodes, 123)
        self.assertEqual(capture.ui_max_depth, 7)
        self.assertEqual(capture.ui_max_text_chars, 4321)
        self.assertTrue(capture.ui_include_offscreen)
        self.assertEqual(capture.global_hotkey, "ctrl+alt+k")

    def test_example_file_parses(self) -> None:
        example = Path(__file__).resolve().parent.parent / "labguide.example.toml"
        config = load_config(example)
        self.assertFalse(config.capture.ui_enabled)
        self.assertEqual(config.capture.global_hotkey, "ctrl+shift+space")


if __name__ == "__main__":
    unittest.main()
