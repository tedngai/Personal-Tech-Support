from __future__ import annotations

import unittest

from labguide.capture import clamp_region_to_virtual_screen


VIRTUAL = {"virtual_left": -1920, "virtual_top": 0, "virtual_width": 3840, "virtual_height": 1080}


class ClampRegionTests(unittest.TestCase):
    def clamp(self, x, y, w, h):
        return clamp_region_to_virtual_screen(x, y, w, h, **VIRTUAL)

    def test_region_fully_inside_primary(self) -> None:
        self.assertEqual(self.clamp(100, 100, 800, 600), (100, 100, 800, 600))

    def test_region_on_secondary_monitor_negative_coordinates(self) -> None:
        self.assertEqual(self.clamp(-1800, 50, 500, 400), (-1800, 50, 500, 400))

    def test_region_spanning_monitors_is_kept(self) -> None:
        self.assertEqual(self.clamp(-100, 0, 400, 300), (-100, 0, 400, 300))

    def test_partially_off_left_edge_is_clamped(self) -> None:
        self.assertEqual(self.clamp(-2000, 100, 200, 300), (-1920, 100, 120, 300))

    def test_partially_off_bottom_is_clamped(self) -> None:
        self.assertEqual(self.clamp(0, 1000, 640, 480), (0, 1000, 640, 80))

    def test_fully_offscreen_returns_none(self) -> None:
        self.assertIsNone(self.clamp(5000, 0, 500, 500))
        self.assertIsNone(self.clamp(0, 5000, 500, 500))
        self.assertIsNone(self.clamp(-5000, 0, 500, 500))

    def test_zero_area_returns_none(self) -> None:
        self.assertIsNone(self.clamp(0, 0, 0, 100))
        self.assertIsNone(self.clamp(0, 0, 100, 0))


if __name__ == "__main__":
    unittest.main()
