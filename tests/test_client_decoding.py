from __future__ import annotations

import gzip
import unittest

from labguide.client import _decode_body, _extract_error_message


class DecodeBodyTests(unittest.TestCase):
    def test_plain_json_passes_through(self) -> None:
        self.assertEqual(_decode_body(b'{"ok": true}'), '{"ok": true}')

    def test_gzip_body_is_decompressed(self) -> None:
        raw = gzip.compress(b'{"ok": true}')
        self.assertEqual(_decode_body(raw), '{"ok": true}')

    def test_mislabeled_plain_body_survives(self) -> None:
        # The observed gateway bug: content-encoding says gzip but the body
        # is identity JSON. Sniffing by magic bytes handles it.
        raw = b'{"id": "chatcmpl-1"}'
        self.assertEqual(_decode_body(raw), '{"id": "chatcmpl-1"}')

    def test_invalid_utf8_is_replaced_not_raised(self) -> None:
        self.assertIn("�", _decode_body(b"\xff\xfe"))


class ExtractErrorMessageTests(unittest.TestCase):
    def test_openai_error_shape(self) -> None:
        body = '{"error": {"message": "bad model", "type": "invalid_request_error"}}'
        self.assertEqual(
            _extract_error_message(400, "Bad Request", body),
            "invalid_request_error: bad model",
        )

    def test_detail_shape(self) -> None:
        self.assertEqual(_extract_error_message(401, "Unauthorized", '{"detail": "nope"}'), "nope")

    def test_non_json_body_falls_back_to_status(self) -> None:
        self.assertEqual(
            _extract_error_message(502, "Bad Gateway", "<html>oops</html>"),
            "Backend returned HTTP 502 Bad Gateway.",
        )


if __name__ == "__main__":
    unittest.main()
