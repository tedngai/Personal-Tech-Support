from __future__ import annotations

import base64
import unittest
from io import BytesIO

from PIL import Image

from labguide.capture import encode_image


def make_image(width: int = 400, height: int = 300) -> Image.Image:
    return Image.new("RGB", (width, height), (128, 64, 200))


def decode(capture) -> Image.Image:
    raw = base64.b64decode(capture.image_base64)
    return Image.open(BytesIO(raw))


class EncodeImageTests(unittest.TestCase):
    def test_unbounded_round_trip(self) -> None:
        capture = encode_image(make_image(), 80)
        self.assertEqual(capture.context.screen_width, 400)
        self.assertEqual(capture.context.screen_height, 300)
        self.assertEqual(capture.byte_count, len(base64.b64decode(capture.image_base64)))
        self.assertGreater(capture.capture_id, "")

    def test_max_dimension_downscales_and_updates_context(self) -> None:
        capture = encode_image(make_image(4000, 2000), 80, max_dimension=1000)
        self.assertEqual(capture.context.screen_width, 1000)
        self.assertEqual(capture.context.screen_height, 500)
        image = decode(capture)
        self.assertEqual(image.size, (1000, 500))

    def test_max_dimension_disabled_when_zero(self) -> None:
        capture = encode_image(make_image(4000, 2000), 80, max_dimension=0)
        self.assertEqual(capture.context.screen_width, 4000)

    def test_max_bytes_steps_quality_down(self) -> None:
        # A noisy image compresses poorly, so a small byte cap forces the
        # quality floor path.
        import random

        random.seed(7)
        noisy = Image.frombytes(
            "RGB", (512, 512), bytes(random.getrandbits(8) for _ in range(512 * 512 * 3))
        )
        capture = encode_image(noisy, 95, max_bytes=20_000)
        self.assertLessEqual(capture.byte_count, 20_000)

    def test_capture_ids_are_unique(self) -> None:
        first = encode_image(make_image(), 80)
        second = encode_image(make_image(), 80)
        self.assertNotEqual(first.capture_id, second.capture_id)


if __name__ == "__main__":
    unittest.main()
