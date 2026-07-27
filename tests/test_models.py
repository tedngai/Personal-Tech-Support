from __future__ import annotations

import json
import unittest

from labguide.models import (
    UI_STATUS_COMPLETE,
    CapturedScreenshot,
    ScreenContext,
    TargetWindow,
    UIElement,
    UISnapshot,
)


def make_target() -> TargetWindow:
    return TargetWindow(
        hwnd=12345,
        pid=6789,
        process_name="notepad.exe",
        window_title="Untitled - Notepad",
        x=100,
        y=80,
        width=1200,
        height=800,
    )


class ModelSerializationTests(unittest.TestCase):
    def test_snapshot_round_trip_without_image_data(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(
                    depth=1,
                    control_type="Edit",
                    name="Text editor",
                    text="Example document text",
                    states=["enabled", "focused"],
                    x=8,
                    y=70,
                    width=1180,
                    height=700,
                )
            ],
            node_count=1,
            truncated=True,
            warnings=["depth limit reached"],
        )
        payload = json.dumps(snapshot.to_dict())
        self.assertNotIn("image_base64", payload)

        restored = UISnapshot.from_dict(json.loads(payload))
        self.assertEqual(restored.status, UI_STATUS_COMPLETE)
        self.assertEqual(len(restored.elements), 1)
        element = restored.elements[0]
        self.assertEqual(element.control_type, "Edit")
        self.assertEqual(element.text, "Example document text")
        self.assertEqual(element.x, 8)
        self.assertTrue(restored.truncated)
        self.assertEqual(restored.warnings, ["depth limit reached"])

    def test_from_dict_tolerates_missing_and_bad_fields(self) -> None:
        restored = UISnapshot.from_dict({"status": "partial", "elements": [{"depth": 0}, "junk"]})
        self.assertEqual(restored.status, "partial")
        self.assertEqual(len(restored.elements), 1)
        self.assertEqual(restored.elements[0].control_type, "Unknown")
        self.assertEqual(restored.node_count, 1)

    def test_screenshot_ui_serialization_excludes_image(self) -> None:
        screenshot = CapturedScreenshot(
            image_base64="QUJD",
            context=ScreenContext("windows", 1200, 800, "2026-07-26T00:00:00+00:00"),
            byte_count=3,
            target=make_target(),
            ui=UISnapshot(status=UI_STATUS_COMPLETE, node_count=0),
        )
        ui_payload = json.dumps(screenshot.ui.to_dict())
        self.assertNotIn(screenshot.image_base64, ui_payload)
        self.assertNotIn("image", ui_payload)


if __name__ == "__main__":
    unittest.main()
