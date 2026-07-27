from __future__ import annotations

import unittest

from labguide.models import (
    UI_STATUS_COMPLETE,
    UI_STATUS_TIMED_OUT,
    UI_STATUS_UNSUPPORTED,
    TargetWindow,
    UIElement,
    UISnapshot,
)
from labguide.ui_outline import (
    REDACTED_PASSWORD_MARKER,
    TRUNCATION_MARKER,
    redact_password_elements,
    render_ui_outline,
)


def make_target() -> TargetWindow:
    return TargetWindow(
        hwnd=1,
        pid=2,
        process_name="notepad.exe",
        window_title="Untitled - Notepad",
        x=0,
        y=0,
        width=800,
        height=600,
    )


class RedactionTests(unittest.TestCase):
    def test_password_element_is_redacted_before_formatting(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(
                    depth=1,
                    control_type="Edit",
                    name="Password",
                    value="hunter2",
                    text="hunter2",
                    is_password=True,
                )
            ],
            node_count=1,
        )
        redact_password_elements(snapshot)
        element = snapshot.elements[0]
        self.assertIsNone(element.name)
        self.assertIsNone(element.value)
        self.assertIsNone(element.text)

        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertNotIn("hunter2", outline)
        self.assertIn(REDACTED_PASSWORD_MARKER, outline)


class OutlineRenderingTests(unittest.TestCase):
    def test_renders_header_states_and_indented_text(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(
                    depth=1,
                    control_type="Edit",
                    name="Text editor",
                    text="Example document text",
                    states=["enabled", "focused"],
                )
            ],
            node_count=1,
        )
        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertIn("Captured application: notepad.exe", outline)
        self.assertIn("Window: Untitled - Notepad", outline)
        self.assertIn("untrusted data", outline)
        # 'enabled' is noise; 'focused' is kept.
        self.assertIn("[Edit, focused] Text editor", outline)
        self.assertIn("    Example document text", outline)

    def test_empty_snapshot_reports_status(self) -> None:
        outline = render_ui_outline(
            UISnapshot(status=UI_STATUS_UNSUPPORTED), make_target(), 10000
        )
        self.assertIn("unsupported", outline)

    def test_timed_out_snapshot_reports_status(self) -> None:
        outline = render_ui_outline(
            UISnapshot(status=UI_STATUS_TIMED_OUT), make_target(), 10000
        )
        self.assertIn("timed_out", outline)

    def test_duplicate_adjacent_text_collapses(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(depth=1, control_type="Text", name="Same label"),
                UIElement(depth=1, control_type="Text", name="Same label"),
            ],
            node_count=2,
        )
        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertEqual(outline.count("Same label"), 1)

    def test_value_and_text_deduplicated_against_name(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(
                    depth=1,
                    control_type="Edit",
                    name="File name:",
                    value="report.txt",
                    text="report.txt",
                )
            ],
            node_count=1,
        )
        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertEqual(outline.count("report.txt"), 1)

    def test_layout_only_nodes_are_skipped(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(depth=0, control_type="Pane"),
                UIElement(depth=1, control_type="Button", name="OK"),
            ],
            node_count=2,
        )
        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertNotIn("[Pane]", outline)
        self.assertIn("[Button] OK", outline)


class TruncationTests(unittest.TestCase):
    def test_total_character_cap(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[
                UIElement(depth=1, control_type="Edit", text="x" * 5000),
            ],
            node_count=1,
        )
        outline = render_ui_outline(snapshot, make_target(), 500)
        self.assertLessEqual(len(outline), 500)
        self.assertTrue(outline.rstrip().endswith(TRUNCATION_MARKER))

    def test_snapshot_truncation_flag_appends_marker(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[UIElement(depth=1, control_type="Button", name="OK")],
            node_count=1,
            truncated=True,
        )
        outline = render_ui_outline(snapshot, make_target(), 10000)
        self.assertIn(TRUNCATION_MARKER, outline)

    def test_zero_cap_returns_empty(self) -> None:
        snapshot = UISnapshot(
            status=UI_STATUS_COMPLETE,
            elements=[UIElement(depth=1, control_type="Button", name="OK")],
            node_count=1,
        )
        self.assertEqual(render_ui_outline(snapshot, make_target(), 0), "")


if __name__ == "__main__":
    unittest.main()
