from __future__ import annotations

import unittest

from labguide.platforms.macos.window import _is_candidate


def window(layer: int | None) -> dict:
    info: dict = {"kCGWindowNumber": 1}
    if layer is not None:
        info["kCGWindowLayer"] = layer
    return info


class MacosWindowLayerTests(unittest.TestCase):
    def test_normal_application_window_is_candidate(self) -> None:
        self.assertTrue(_is_candidate(window(0)))

    def test_modal_dialog_panel_is_candidate(self) -> None:
        # Error dialogs and save panels live at layer 8 on macOS.
        self.assertTrue(_is_candidate(window(8)))

    def test_menu_bar_is_not_candidate(self) -> None:
        self.assertFalse(_is_candidate(window(24)))

    def test_status_items_are_not_candidates(self) -> None:
        self.assertFalse(_is_candidate(window(25)))

    def test_missing_layer_is_not_candidate(self) -> None:
        self.assertFalse(_is_candidate(window(None)))


if __name__ == "__main__":
    unittest.main()
