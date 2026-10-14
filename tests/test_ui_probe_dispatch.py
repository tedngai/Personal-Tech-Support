from __future__ import annotations

import sys
import unittest
from unittest import mock

from labguide.ui_probe import _probe_command


class ProbeCommandTests(unittest.TestCase):
    def test_interpreter_form_uses_module_flag(self) -> None:
        command = _probe_command(42, max_nodes=5, max_depth=3, include_offscreen=False)
        self.assertEqual(command[1:3], ["-m", "labguide.ui_probe"])
        self.assertEqual(command[3:5], ["--hwnd", "42"])
        self.assertNotIn("--include-offscreen", command)

    def test_frozen_form_dispatches_through_entry_point(self) -> None:
        # A PyInstaller bundle ignores `-m`; the sidecar entry re-dispatches
        # --ui-probe to the probe CLI instead of spawning a nested service.
        with mock.patch.object(sys, "frozen", True, create=True):
            command = _probe_command(42, max_nodes=5, max_depth=3, include_offscreen=True)
        self.assertEqual(command[1], "--ui-probe")
        self.assertNotIn("-m", command)
        self.assertIn("--include-offscreen", command)


if __name__ == "__main__":
    unittest.main()