from __future__ import annotations

import unittest

from labguide.win32_window import WindowCandidate, select_window_below


class SelectWindowBelowTests(unittest.TestCase):
    def test_prefers_first_visible_titled_non_terminal(self) -> None:
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="LabGuide terminal", is_terminal=True),
            WindowCandidate(hwnd=11, visible=True, title="Untitled - Notepad", is_terminal=False),
            WindowCandidate(hwnd=12, visible=True, title="Other app", is_terminal=False),
        ]
        self.assertEqual(select_window_below(candidates), 11)

    def test_skips_invisible_windows(self) -> None:
        candidates = [
            WindowCandidate(hwnd=10, visible=False, title="Hidden", is_terminal=False),
            WindowCandidate(hwnd=11, visible=True, title="Shown", is_terminal=False),
        ]
        self.assertEqual(select_window_below(candidates), 11)

    def test_skips_all_terminals(self) -> None:
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="Windows Terminal", is_terminal=True),
            WindowCandidate(hwnd=11, visible=True, title="conhost", is_terminal=True),
        ]
        self.assertIsNone(select_window_below(candidates))

    def test_falls_back_to_untitled_visible_window(self) -> None:
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="", is_terminal=False),
            WindowCandidate(hwnd=11, visible=True, title="", is_terminal=False),
        ]
        self.assertEqual(select_window_below(candidates), 10)

    def test_empty_candidates(self) -> None:
        self.assertIsNone(select_window_below([]))


if __name__ == "__main__":
    unittest.main()
