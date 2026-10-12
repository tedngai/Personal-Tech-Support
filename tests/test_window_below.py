from __future__ import annotations

import sys
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


class ShellDesktopExclusionTests(unittest.TestCase):
    def test_shell_desktop_window_is_never_selected(self) -> None:
        # Desktop app foreground: below it in z-order sits Progman, then a
        # real app. The desktop must not become the capture target.
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="Program Manager", is_terminal=False, is_shell_desktop=True),
            WindowCandidate(hwnd=11, visible=True, title="Firefox", is_terminal=False, is_shell_desktop=False),
        ]
        self.assertEqual(select_window_below(candidates), 11)

    def test_shell_desktop_fallback_wins_over_untitled_only_when_alone(self) -> None:
        # Only the shell remains: no usable target at all (the service then
        # falls back to a primary-display capture with target=None).
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="Program Manager", is_terminal=False, is_shell_desktop=True),
        ]
        self.assertIsNone(select_window_below(candidates))

    def test_titled_shell_is_skipped_in_favor_of_untitled_app(self) -> None:
        candidates = [
            WindowCandidate(hwnd=10, visible=True, title="Program Manager", is_terminal=False, is_shell_desktop=True),
            WindowCandidate(hwnd=11, visible=True, title="", is_terminal=False, is_shell_desktop=False),
        ]
        self.assertEqual(select_window_below(candidates), 11)


class OwnShellPidTests(unittest.TestCase):
    def test_own_shell_pid_env_marks_window_as_own(self) -> None:
        import os
        from unittest import mock

        from labguide import win32_window

        if sys.platform != "win32":
            self.skipTest("pid check requires Win32 APIs")
        with mock.patch.dict(os.environ, {"LABGUIDE_OWN_PID": "424242"}):
            with (
                mock.patch.object(win32_window, "get_window_pid", return_value=424242),
                mock.patch.object(win32_window, "get_window_class_name", return_value="MozillaWindowClass"),
                mock.patch.object(win32_window, "get_console_hwnd", return_value=0),
            ):
                # The desktop shell's window belongs to another process, but
                # the shell announced its pid at spawn time.
                self.assertTrue(win32_window.is_own_terminal(hwnd=1))

    def test_unrelated_pid_is_not_own(self) -> None:
        import os
        from unittest import mock

        from labguide import win32_window

        if sys.platform != "win32":
            self.skipTest("pid check requires Win32 APIs")
        with mock.patch.dict(os.environ, {"LABGUIDE_OWN_PID": "424242"}):
            with (
                mock.patch.object(win32_window, "get_window_pid", return_value=111111),
                mock.patch.object(win32_window, "get_window_class_name", return_value="MozillaWindowClass"),
                mock.patch.object(win32_window, "get_console_hwnd", return_value=0),
            ):
                self.assertFalse(win32_window.is_own_terminal(hwnd=1))
