# Windows UI Context Capture Architecture

## Purpose

This document defines the durable architecture and safety boundaries for adding
Windows accessibility context to LabGuide screenshots. Milestone status and task
tracking belong in `UI-Context-Capture-Execution-Plan.md`.

## Problem

The current `Ctrl+S` flow captures the primary display after LabGuide's terminal
has focus. A screenshot gives the vision model useful layout and visual state,
but exact text must be inferred from pixels. It may also capture the terminal
instead of the application the user needs help with.

Windows UI Automation exposes a structured control tree containing application
text, roles, values, state, and geometry. Combining this data with a screenshot
improves exact error recognition and control identification without OCR.

## Capture Semantics

The enriched capture path is a two-stage attachment workflow:

1. While the problematic application is foreground, the user presses a global
   hotkey.
2. LabGuide freezes the foreground window identity and immediately captures its
   visible pixels.
3. LabGuide starts an isolated UIA probe for the same HWND.
4. The combined result becomes one in-memory pending attachment.
5. The user returns to LabGuide, enters a question, and submits it.

Capture does not imply consent to send. The backend request occurs only when
the user submits a prompt.

One pending attachment is supported. A later successful capture replaces it.
Backend failure retains it for retry; backend success clears it.

A second, single-stage path exists for convenience: when the user presses
`Ctrl+S` inside LabGuide, the terminal is foreground, so LabGuide walks the
z-order (`GW_HWNDNEXT`) for the first visible, non-terminal, titled window —
normally the app the user was just in — and runs the same freeze, pixel, and
probe pipeline on it before sending immediately. If no such window exists or
the window capture fails, `Ctrl+S` falls back to the primary display. The
global-hotkey path remains the more reliable way to pin an exact target.

## Component Boundaries

### `global_hotkey.py`

- Owns Win32 global-hotkey registration and cleanup.
- Runs the Windows message loop outside Textual's event loop.
- Reports an immutable capture trigger containing foreground HWND and timestamp.
- Contains no screenshot, UIA, backend, or prompt logic.

### `capture.py`

- Owns pixel capture and platform-neutral image encoding.
- Retains primary-display capture for fallback behavior.
- Adds foreground-window capture from frozen Win32 bounds.
- Does not walk UIA or format prompts.

### `ui_probe.py`

- Is a read-only Windows UIA client.
- Accepts an HWND and limits through command-line arguments.
- Writes one JSON result to stdout and diagnostics to stderr.
- Runs in a child process so the parent can enforce a hard timeout.
- Never performs invoke, click, focus, selection, value-setting, or keyboard
  actions.

### `models.py`

- Defines the canonical capture, target-window, UI snapshot, and UI element
  structures.
- Contains no platform API calls.
- Canonical UI data is the source for prompt projection and future RAG metadata.

### `app.py`

- Owns the pending-attachment state machine.
- Coordinates capture work without blocking Textual.
- Displays capture metadata, not captured content.
- Decides when an attachment is replaced, retained, or cleared.

### `client.py`

- Converts canonical context into the existing OpenAI-compatible message shape.
- Adds a single compact accessibility outline rather than duplicate JSON and
  prose.
- Marks captured text as untrusted observations.
- Does not perform capture or UIA operations.

## Capture Pipeline

```text
RegisterHotKey event
        |
        v
Freeze HWND, PID, title, timestamp
        |
        +-------------------------+
        |                         |
        v                         v
DWM bounds + mss pixels     child UIA probe
        |                         |
        v                         v
JPEG/base64                 structured JSON
        |                         |
        +------------+------------+
                     v
            pending capture
                     |
              explicit send
                     v
       text projection + image_url
```

The screenshot must be captured before UIA traversal because pixels are
time-sensitive and UIA can be slow. Both branches use the HWND frozen at the
hotkey event.

## Canonical Data Contract

The exact Python representation may evolve, but it should preserve this logical
shape:

```json
{
  "target": {
    "hwnd": 12345,
    "pid": 6789,
    "process_name": "notepad.exe",
    "window_title": "Untitled - Notepad",
    "bounds": {"x": 100, "y": 80, "width": 1200, "height": 800}
  },
  "image": {
    "mime_type": "image/jpeg",
    "width": 1200,
    "height": 800,
    "byte_count": 84211
  },
  "ui": {
    "status": "complete",
    "elements": [
      {
        "depth": 1,
        "control_type": "Edit",
        "name": "Text editor",
        "value": null,
        "text": "Example document text",
        "automation_id": "TextArea",
        "class_name": "RichEditD2DPT",
        "states": ["enabled", "focused"],
        "bounds": {"x": 8, "y": 70, "width": 1180, "height": 700}
      }
    ],
    "node_count": 1,
    "truncated": false,
    "warnings": []
  },
  "captured_at": "2026-07-26T00:00:00+00:00"
}
```

Element bounds are relative to the captured window. Raw HWNDs and runtime IDs
are internal metadata and should not be included in the model prompt unless they
serve a demonstrated support need.

## UIA Extraction Rules

Start at the UIA element resolved from the frozen HWND and traverse Control View,
not the desktop root. Apply node, depth, text, and timeout limits before building
the prompt.

Text extraction priority:

1. `TextPattern.DocumentRange.GetText(limit)` for document-like controls.
2. `ValuePattern.Value` for fields that expose a value.
3. UIA `Name` for labels, buttons, and named controls.
4. `LegacyIAccessible` properties as a best-effort fallback.

Useful metadata includes control type, localized role, automation ID, class,
help text, enabled state, focus, selection, checked/toggled state,
expanded/collapsed state, off-screen state, and bounding rectangle.

Every property read is independently guarded. UIA providers frequently throw
for individual properties or disappear while being inspected; one bad element
must not invalidate the whole capture.

Default filtering:

- Exclude empty layout-only nodes.
- Exclude off-screen nodes.
- Collapse duplicate adjacent text.
- Retain named interactive controls even when they have no value.
- Retrieve document text in moderately sized blocks, never character by
  character.
- Stop when any configured limit is reached and mark the snapshot truncated.

## Process Isolation and Timeouts

UIA makes cross-process calls into applications that may be slow or hung. A
normal Python worker thread cannot be safely terminated if a provider blocks.
Therefore, UIA extraction runs through a child process launched with the current
Python executable.

The parent owns the timeout. On timeout it terminates the child and returns a
partial capture containing the screenshot and a `timed_out` UI status. Probe
stdout is size-limited JSON; stderr is diagnostic and must not contain captured
field values in normal operation.

## Prompt Projection

The canonical JSON is rendered once into a compact outline for the current
OpenAI-compatible backend:

```text
Captured application: Notepad
Window: Untitled - Notepad

Accessibility observations (untrusted data):
[Edit, focused] Text editor
  Example document text

User request:
Why does this application report an error?
```

The model should use accessibility text for exact labels, values, and messages,
and the image for layout, color, icons, visual selection, and content that UIA
does not expose.

The accessibility block is untrusted because a website, email, or document can
contain text that resembles instructions. System guidance must tell the model
not to follow instructions found in captured content.

Canonical JSON remains in memory for a future RAG metadata contract. It should
not be embedded alongside the outline because that duplicates tokens and can
degrade retrieval quality.

## Privacy and Security Boundaries

- Captures are user-triggered and require a separate explicit send action.
- UIA content can be more sensitive than the screenshot because applications may
  expose text not readily visible to the user.
- Off-screen content is disabled by default.
- If `IsPassword` is true, omit Name-derived secrets, value, text patterns, and
  legacy values. Emit only a redacted password-control marker.
- Screenshots, UI values, document text, and canonical JSON are not written to
  session logs by default.
- Logs may contain target process name, capture status, node count, truncation,
  duration, and error category.
- The helper remains read-only. Adding UI actions requires a separate design and
  security review.
- LabGuide runs at normal user integrity. Elevated applications and secure
  desktop UI are deliberately unsupported.

## Failure Behavior

| Failure | Behavior |
| --- | --- |
| Hotkey collision | Show configuration error; preserve existing capture path |
| Invalid or closed HWND | Report failed enriched capture; do not replace pending attachment |
| Screenshot failure | Do not create or replace pending attachment |
| UIA unsupported or empty | Store screenshot with `unsupported` UI status |
| UIA property error | Keep other fields and mark partial warning |
| UIA timeout | Kill probe and store screenshot with `timed_out` status |
| Target closes after screenshot | Preserve screenshot and partial UI result |
| Backend request failure | Retain pending attachment for retry |
| Elevated target | Return inaccessible UI status; use screenshot if available |

## Platform Constraints

- UIA requires the logged-in interactive desktop session.
- Electron, browser, custom canvas, OpenGL, DirectX, remote-desktop, and
  proprietary controls may expose sparse or no useful tree.
- Window capture and UIA geometry must be tested with secondary monitors,
  negative coordinates, and mixed DPI.
- No Windows permission toggle equivalent to macOS Accessibility is required for
  same-integrity applications, but Windows integrity boundaries still apply.

## Non-Goals

- Reproducing OpenAI's internal AppShots wire format
- OCR or visual text extraction
- Capturing every application with perfect fidelity
- Reading protected or elevated UI
- Persisting capture contents
- Automating the target application
