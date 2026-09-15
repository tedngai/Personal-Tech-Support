from __future__ import annotations

import unittest

from labguide.platforms import get_adapter
from labguide.platforms.contracts import UnsupportedAdapter
from labguide.models import WindowIdentityError


class AdapterSelectionTests(unittest.TestCase):
    def test_windows_adapter_selected(self) -> None:
        adapter = get_adapter("win32")
        self.assertEqual(adapter.name, "windows")
        capabilities = adapter.capabilities()
        self.assertTrue(capabilities.window_capture)
        self.assertTrue(capabilities.accessibility)
        self.assertTrue(capabilities.global_hotkey)

    def test_macos_adapter_selected(self) -> None:
        adapter = get_adapter("darwin")
        self.assertEqual(adapter.name, "macos")
        capabilities = adapter.capabilities()
        self.assertTrue(capabilities.window_capture)
        self.assertTrue(capabilities.accessibility)
        self.assertTrue(capabilities.global_hotkey)

    def test_unsupported_platform_degrades(self) -> None:
        adapter = get_adapter("linux")
        self.assertIsInstance(adapter, UnsupportedAdapter)
        capabilities = adapter.capabilities()
        self.assertTrue(capabilities.screenshot)
        self.assertFalse(capabilities.window_capture)
        self.assertFalse(capabilities.accessibility)
        self.assertFalse(capabilities.global_hotkey)

    def test_unsupported_adapter_bounded_failures(self) -> None:
        from labguide.config import CaptureConfig
        from labguide.models import UI_STATUS_UNSUPPORTED

        adapter = UnsupportedAdapter()
        self.assertEqual(adapter.get_foreground_target(), 0)
        self.assertEqual(adapter.get_window_below(123), 0)
        with self.assertRaises(WindowIdentityError):
            adapter.freeze_target(123)
        snapshot = adapter.probe_accessibility(None, CaptureConfig())  # type: ignore[arg-type]
        self.assertEqual(snapshot.status, UI_STATUS_UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
