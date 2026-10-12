from __future__ import annotations

import unittest

from PIL import Image

from labguide.capture import is_blank_image


class BlankImageTests(unittest.TestCase):
    def test_solid_black_is_blank(self) -> None:
        self.assertTrue(is_blank_image(Image.new("RGB", (80, 60), (0, 0, 0))))

    def test_solid_white_is_blank(self) -> None:
        self.assertTrue(is_blank_image(Image.new("RGB", (80, 60), (255, 255, 255))))

    def test_varied_window_is_not_blank(self) -> None:
        image = Image.new("RGB", (80, 60), (240, 240, 240))
        for x in range(10, 70, 8):
            for y in range(8, 50, 6):
                image.putpixel((x, y), (20, 80, 160))
        self.assertFalse(is_blank_image(image))


if __name__ == "__main__":
    unittest.main()
