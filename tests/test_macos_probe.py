from __future__ import annotations

import unittest

from labguide.platforms.macos.ax_probe import is_secure_role, normalize_role
from labguide.platforms.macos.hotkey import parse_chord


class RoleMappingTests(unittest.TestCase):
    def test_common_roles_map_to_windows_vocabulary(self) -> None:
        self.assertEqual(normalize_role("AXTextField"), "Edit")
        self.assertEqual(normalize_role("AXTextArea"), "Edit")
        self.assertEqual(normalize_role("AXButton"), "Button")
        self.assertEqual(normalize_role("AXCheckBox"), "CheckBox")
        self.assertEqual(normalize_role("AXStaticText"), "Text")
        self.assertEqual(normalize_role("AXWindow"), "Window")

    def test_unknown_ax_role_is_shortened(self) -> None:
        self.assertEqual(normalize_role("AXCustomWidget"), "CustomWidget")

    def test_missing_role_is_unknown(self) -> None:
        self.assertEqual(normalize_role(None), "Unknown")
        self.assertEqual(normalize_role(""), "Unknown")


class SecureRoleTests(unittest.TestCase):
    def test_secure_text_field_detected(self) -> None:
        self.assertTrue(is_secure_role("AXTextField", "AXSecureTextField"))
        self.assertTrue(is_secure_role("AXSecureTextField", None))

    def test_normal_fields_are_not_secure(self) -> None:
        self.assertFalse(is_secure_role("AXTextField", None))
        self.assertFalse(is_secure_role("AXButton", None))
        self.assertFalse(is_secure_role(None, None))


class ChordParsingTests(unittest.TestCase):
    def test_default_chord(self) -> None:
        self.assertEqual(parse_chord("ctrl+shift+space"), "<ctrl>+<shift>+<space>")

    def test_case_and_whitespace_insensitive(self) -> None:
        self.assertEqual(parse_chord(" Ctrl + Shift + K "), "<ctrl>+<shift>+k")

    def test_function_key(self) -> None:
        self.assertEqual(parse_chord("ctrl+f5"), "<ctrl>+<f5>")

    def test_cmd_alias(self) -> None:
        self.assertEqual(parse_chord("cmd+shift+p"), "<cmd>+<shift>+p")

    def test_rejects_multiple_keys(self) -> None:
        with self.assertRaises(ValueError):
            parse_chord("ctrl+a+b")

    def test_rejects_missing_key(self) -> None:
        with self.assertRaises(ValueError):
            parse_chord("ctrl+shift")

    def test_rejects_unknown_key(self) -> None:
        with self.assertRaises(ValueError):
            parse_chord("ctrl+definitelynotakey")


if __name__ == "__main__":
    unittest.main()
