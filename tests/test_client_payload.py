from __future__ import annotations

import unittest

from labguide.client import _build_messages, _build_user_prompt
from labguide.models import (
    UI_STATUS_COMPLETE,
    UI_STATUS_PARTIAL,
    UI_STATUS_TIMED_OUT,
    CapturedScreenshot,
    ScreenContext,
    TargetWindow,
    UIElement,
    UISnapshot,
)


def make_context() -> ScreenContext:
    return ScreenContext("windows", 1200, 800, "2026-07-26T00:00:00+00:00")


def make_target() -> TargetWindow:
    return TargetWindow(
        hwnd=1,
        pid=2,
        process_name="notepad.exe",
        window_title="Untitled - Notepad",
        x=0,
        y=0,
        width=1200,
        height=800,
    )


def make_screenshot(
    target: TargetWindow | None = None, ui: UISnapshot | None = None
) -> CapturedScreenshot:
    return CapturedScreenshot(
        image_base64="QUJD",
        context=make_context(),
        byte_count=3,
        target=target,
        ui=ui,
    )


def make_snapshot(**overrides) -> UISnapshot:
    values = dict(
        status=UI_STATUS_COMPLETE,
        elements=[
            UIElement(
                depth=1,
                control_type="Edit",
                name="Text editor",
                text="Exact error code 0x80070005",
                states=["enabled", "focused"],
            )
        ],
        node_count=1,
    )
    values.update(overrides)
    return UISnapshot(**values)


class BuildMessagesTests(unittest.TestCase):
    def test_text_only_message(self) -> None:
        messages = _build_messages("sys", "hello", None, [])
        self.assertEqual(
            messages,
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
            ],
        )

    def test_screenshot_only_message_is_multimodal(self) -> None:
        messages = _build_messages("sys", "hello", make_screenshot(), [])
        user = messages[-1]
        self.assertEqual(user["role"], "user")
        kinds = [part["type"] for part in user["content"]]
        self.assertEqual(kinds, ["text", "image_url"])
        self.assertIn("data:image/jpeg;base64,QUJD", user["content"][1]["image_url"]["url"])
        self.assertIn("current screen", user["content"][0]["text"])

    def test_full_ui_context_appears_once(self) -> None:
        prompt = _build_user_prompt("why?", make_screenshot(make_target(), make_snapshot()))
        self.assertEqual(prompt.count("0x80070005"), 1)
        self.assertIn("Captured application: notepad.exe", prompt)
        self.assertIn("Window: Untitled - Notepad", prompt)
        self.assertIn("untrusted data", prompt)
        self.assertIn("captured window", prompt)
        self.assertTrue(prompt.rstrip().endswith("why?"))
        # Canonical JSON must not be embedded alongside the outline.
        self.assertNotIn('"control_type"', prompt)
        self.assertNotIn('"elements"', prompt)

    def test_partial_ui_context_includes_status(self) -> None:
        snapshot = make_snapshot(status=UI_STATUS_PARTIAL, warnings=["depth limit reached"])
        prompt = _build_user_prompt("why?", make_screenshot(make_target(), snapshot))
        self.assertIn("0x80070005", prompt)

    def test_timed_out_ui_context_falls_back_to_status_line(self) -> None:
        snapshot = make_snapshot(status=UI_STATUS_TIMED_OUT, elements=[], node_count=0)
        prompt = _build_user_prompt("why?", make_screenshot(make_target(), snapshot))
        self.assertIn("timed_out", prompt)
        self.assertNotIn("0x80070005", prompt)

    def test_ui_max_text_chars_is_enforced(self) -> None:
        snapshot = make_snapshot(
            elements=[UIElement(depth=1, control_type="Edit", text="y" * 5000)],
        )
        prompt = _build_user_prompt(
            "why?", make_screenshot(make_target(), snapshot), ui_max_text_chars=600
        )
        # The accessibility outline is capped at 600; the short trailer
        # (screenshot note, timestamp, user request) is not part of the cap.
        self.assertNotIn("y" * 5000, prompt)
        self.assertLess(len(prompt), 600 + 200)
        self.assertIn("truncated", prompt)


if __name__ == "__main__":
    unittest.main()
