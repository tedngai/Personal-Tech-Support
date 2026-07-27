from __future__ import annotations

import unittest

from labguide.global_hotkey import parse_hotkey


class ParseHotkeyTests(unittest.TestCase):
    def test_default_chord(self) -> None:
        modifiers, vk = parse_hotkey("ctrl+shift+space")
        self.assertEqual(modifiers, 0x0002 | 0x0004)
        self.assertEqual(vk, 0x20)

    def test_case_and_whitespace_insensitive(self) -> None:
        modifiers, vk = parse_hotkey(" Ctrl + ALT + k ")
        self.assertEqual(modifiers, 0x0002 | 0x0001)
        self.assertEqual(vk, ord("K"))

    def test_function_key(self) -> None:
        modifiers, vk = parse_hotkey("shift+f9")
        self.assertEqual(modifiers, 0x0004)
        self.assertEqual(vk, 0x70 + 8)

    def test_control_alias(self) -> None:
        modifiers, _ = parse_hotkey("control+q")
        self.assertEqual(modifiers, 0x0002)

    def test_rejects_multiple_keys(self) -> None:
        with self.assertRaises(ValueError):
            parse_hotkey("ctrl+a+b")

    def test_rejects_missing_key(self) -> None:
        with self.assertRaises(ValueError):
            parse_hotkey("ctrl+shift")

    def test_rejects_unknown_key(self) -> None:
        with self.assertRaises(ValueError):
            parse_hotkey("ctrl+boguskey")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            parse_hotkey("")


if __name__ == "__main__":
    unittest.main()
