from __future__ import annotations

import json
import unittest

from labguide.capture import CaptureError
from labguide.client import BackendError
from labguide.global_hotkey import HotkeyError
from labguide.ipc import (
    BACKEND_FAILED,
    CAPTURE_FAILED,
    HOTKEY_UNAVAILABLE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    WINDOW_UNAVAILABLE,
    Event,
    IpcError,
    Request,
    error_from_exception,
    error_response,
    event_message,
    parse_message,
    result_response,
)
from labguide.models import WindowIdentityError


class ParseMessageTests(unittest.TestCase):
    def test_valid_request(self) -> None:
        line = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "hello", "params": {}})
        parsed = parse_message(line)
        self.assertIsInstance(parsed, Request)
        self.assertEqual(parsed.id, 7)  # type: ignore[union-attr]
        self.assertEqual(parsed.method, "hello")  # type: ignore[union-attr]

    def test_string_request_id(self) -> None:
        line = json.dumps({"id": "abc", "method": "discard"})
        parsed = parse_message(line)
        self.assertIsInstance(parsed, Request)
        self.assertEqual(parsed.id, "abc")  # type: ignore[union-attr]

    def test_blank_line_returns_none(self) -> None:
        self.assertIsNone(parse_message("   \n"))

    def test_event_message(self) -> None:
        line = json.dumps({"event": "hotkey.pressed", "data": {"a": 1}})
        parsed = parse_message(line)
        self.assertIsInstance(parsed, Event)
        self.assertEqual(parsed.name, "hotkey.pressed")  # type: ignore[union-attr]

    def test_malformed_json_raises_parse_error(self) -> None:
        with self.assertRaises(IpcError) as ctx:
            parse_message("{not json")
        self.assertEqual(ctx.exception.code, PARSE_ERROR)

    def test_non_object_raises_invalid_request(self) -> None:
        with self.assertRaises(IpcError) as ctx:
            parse_message("[1, 2]")
        self.assertEqual(ctx.exception.code, INVALID_REQUEST)

    def test_missing_method_and_event_raises_invalid_request(self) -> None:
        with self.assertRaises(IpcError) as ctx:
            parse_message(json.dumps({"id": 1}))
        self.assertEqual(ctx.exception.code, INVALID_REQUEST)

    def test_bad_id_raises_invalid_request(self) -> None:
        with self.assertRaises(IpcError) as ctx:
            parse_message(json.dumps({"id": True, "method": "hello"}))
        self.assertEqual(ctx.exception.code, INVALID_REQUEST)

    def test_non_object_params_raises_invalid_params(self) -> None:
        with self.assertRaises(IpcError) as ctx:
            parse_message(json.dumps({"id": 1, "method": "submit", "params": [1]}))
        self.assertEqual(ctx.exception.code, INVALID_PARAMS)


class ResponseBuilderTests(unittest.TestCase):
    def test_result_response_shape(self) -> None:
        payload = json.loads(result_response(3, {"ok": True}))
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 3)
        self.assertEqual(payload["result"], {"ok": True})
        self.assertNotIn("error", payload)

    def test_error_response_includes_stage_and_category(self) -> None:
        payload = json.loads(
            error_response(1, CAPTURE_FAILED, "capture failed", stage="capture")
        )
        error = payload["error"]
        self.assertEqual(error["code"], CAPTURE_FAILED)
        self.assertEqual(error["data"]["stage"], "capture")
        self.assertNotIn("category", error["data"])

    def test_error_response_without_data_omits_data(self) -> None:
        payload = json.loads(error_response(1, INTERNAL_ERROR, "boom"))
        self.assertNotIn("data", payload["error"])

    def test_event_message_shape(self) -> None:
        payload = json.loads(event_message("capture.completed", {"capture_id": "x"}))
        self.assertEqual(payload["event"], "capture.completed")
        self.assertEqual(payload["data"], {"capture_id": "x"})
        self.assertNotIn("id", payload)


class ExceptionMappingTests(unittest.TestCase):
    def test_window_identity_error_maps_with_reason_category(self) -> None:
        payload = json.loads(
            error_from_exception(1, WindowIdentityError("closed"))
        )
        self.assertEqual(payload["error"]["code"], WINDOW_UNAVAILABLE)
        self.assertEqual(payload["error"]["data"]["stage"], "window-identity")
        self.assertEqual(payload["error"]["data"]["category"], "closed")

    def test_capture_error_maps_to_capture_failed(self) -> None:
        payload = json.loads(error_from_exception(1, CaptureError("window capture failed")))
        self.assertEqual(payload["error"]["code"], CAPTURE_FAILED)
        self.assertEqual(payload["error"]["data"]["stage"], "capture")

    def test_hotkey_error_maps_to_hotkey_unavailable(self) -> None:
        payload = json.loads(error_from_exception(1, HotkeyError("no hotkey")))
        self.assertEqual(payload["error"]["code"], HOTKEY_UNAVAILABLE)

    def test_backend_error_maps_to_backend_failed(self) -> None:
        payload = json.loads(error_from_exception(1, BackendError("http 500")))
        self.assertEqual(payload["error"]["code"], BACKEND_FAILED)

    def test_unexpected_error_maps_to_internal(self) -> None:
        payload = json.loads(error_from_exception(1, ValueError("x")))
        self.assertEqual(payload["error"]["code"], INTERNAL_ERROR)

    def test_ipc_error_passes_through(self) -> None:
        payload = json.loads(
            error_from_exception(
                1, IpcError(METHOD_NOT_FOUND, "unknown method", stage="dispatch")
            )
        )
        self.assertEqual(payload["error"]["code"], METHOD_NOT_FOUND)
        self.assertEqual(payload["error"]["data"]["stage"], "dispatch")


if __name__ == "__main__":
    unittest.main()
