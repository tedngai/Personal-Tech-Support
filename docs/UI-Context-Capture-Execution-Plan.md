# Windows UI Context Capture Execution Plan

## Status

- State: Implemented; pending interactive acceptance and privacy review
- Target: Windows-first LabGuide MVP
- Scope: Read-only screenshot and Windows UI Automation context capture
- Last reviewed: 2026-07-26

## Objective

Add an AppShot-style capture path to LabGuide that combines a screenshot of the
foreground application window with structured text exposed through Windows UI
Automation (UIA). The user will capture context with a global hotkey while the
problematic application is still foreground, return to LabGuide, enter a
question, and send both forms of context to the existing OpenAI-compatible
backend.

This work must preserve the current screenshot-only path as a fallback. UIA
errors, unsupported applications, and timeouts must never prevent the user from
submitting the screenshot.

## Success Criteria

1. A global hotkey captures the foreground application without moving focus to
   LabGuide.
2. The screenshot and UIA tree describe the same foreground window and capture
   event.
3. Notepad text, standard dialog labels, button names, field values, and useful
   control state reach the backend as text without OCR.
4. Password controls are always redacted and off-screen content is excluded by
   default.
5. A hung or inaccessible UIA provider times out without hanging LabGuide.
6. The pending capture is retained when a backend request fails and cleared only
   after a successful request or explicit replacement.
7. The existing text-only and screenshot-only request paths remain usable.
8. No screenshot or captured UI text is written to the session log by default.

## Fixed Decisions

- Use a configurable Win32 global hotkey, initially `Ctrl+Shift+Space`.
- Capture first and ask the question second. A global capture creates one pending
  attachment; it does not automatically contact the backend.
- Capture the foreground window rather than the primary display for the new
  path. Keep the current primary-display capture as a fallback.
- `Ctrl+S` targets the window below LabGuide's terminal in z-order (the app
  the user was just in) when the enriched path is enabled, and falls back to
  the primary display when no such window exists or the enriched path is
  disabled. (Amended 2026-07-26 per user feedback; originally `Ctrl+S` always
  captured the primary display.)
- Use the Python `uiautomation` package rather than implementing raw COM bindings.
- Run UIA extraction in a child process with a hard timeout.
- Keep canonical UI context as structured Python data/JSON, but send only one
  compact text projection to the current chat-completions backend.
- Treat screenshot and UI text as untrusted observations, never as instructions.
- Do not request elevation, `UIAccess`, or access to the secure desktop.
- Do not add clicking, typing, form submission, or other computer-use actions.

See `docs/Windows-UI-Context-Architecture.md` for the durable design and data
contracts behind these decisions.

## Delivery Milestones

### Milestone 1: Models, Configuration, and Pure Formatting

Tasks:

- [x] Add UI snapshot and element dataclasses to `src/labguide/models.py`.
- [x] Extend the captured screenshot model with optional target-window and UI
      context.
- [x] Add Windows UI capture settings to `CaptureConfig` and
      `labguide.example.toml`.
- [x] Implement compact outline rendering from canonical UI element data.
- [x] Implement deterministic character and node truncation.
- [x] Add password-field redaction before data enters the canonical snapshot.
- [x] Add unit tests for rendering, truncation, redaction, and empty snapshots.

Initial settings:

```toml
[capture]
jpeg_quality = 80
ui_enabled = false
ui_timeout_seconds = 3.0
ui_max_nodes = 500
ui_max_depth = 20
ui_max_text_chars = 10000
ui_include_offscreen = false
global_hotkey = "ctrl+shift+space"
```

Exit criteria:

- Pure formatting tests run on non-Windows development environments.
- A UI snapshot can be serialized without including image data.
- Redaction and truncation happen before prompt construction or logging.

### Milestone 2: Isolated Windows UIA Probe

Tasks:

- [x] Add the Windows-only `uiautomation` dependency with a platform marker.
- [x] Add `src/labguide/ui_probe.py` with a machine-readable CLI contract.
- [x] Resolve the UIA root from a supplied foreground HWND, not the desktop root.
- [x] Traverse UIA Control View with depth and node limits.
- [x] Read fields independently so one failing property does not discard the
      entire snapshot.
- [x] Extract `TextPattern`, `ValuePattern`, `Name`, and
      `LegacyIAccessible` text in that order where supported.
- [x] Collect useful role, state, help text, automation ID, class, and bounds.
- [x] Exclude off-screen controls unless explicitly configured.
- [x] Return structured status for success, partial success, unsupported, and
      failure.
- [x] Add a parent-side subprocess wrapper that enforces the timeout and kills a
      stuck probe.

Exit criteria:

- The probe extracts known text from Notepad and standard Windows dialogs.
- An inaccessible or closed window produces a bounded, readable failure.
- A deliberately stalled probe cannot block the TUI beyond the configured
  timeout.

### Milestone 3: Foreground Window Screenshot Capture

Tasks:

- [x] Add Win32 helpers to identify the foreground HWND, PID, process name, and
      title at the instant of capture.
- [x] Obtain physical window bounds through DWM, with a UIA/Win32 fallback.
- [x] Capture the bounded foreground window with `mss` while it is still visible.
- [x] Support negative coordinates and windows on secondary monitors.
- [x] Normalize element bounds relative to the captured window.
- [x] Handle closed, minimized, zero-size, and off-screen windows explicitly.
- [x] Preserve `capture_primary_display()` as the screenshot-only fallback.

Exit criteria:

- Screenshot dimensions and reported window bounds agree. (Validated live:
  JPEG dimensions equal DWM extended frame bounds.)
- A window on each attached monitor can be captured. (This machine has one
  monitor; negative-coordinate and multi-monitor clamping is unit-tested.
  Re-verify on multi-monitor hardware.)
- Mixed-DPI behavior is documented and tested on available hardware. (The app
  and probe request Per-Monitor-V2 awareness so Win32, mss, and UIA share
  physical pixels; single-DPI hardware here.)

### Milestone 4: Global Hotkey and Pending Capture Lifecycle

Tasks:

- [x] Add `src/labguide/global_hotkey.py` using Win32 `RegisterHotKey` and a
      dedicated message-loop thread.
- [x] Register and unregister the hotkey with the Textual application lifecycle.
- [x] Reject captures when the foreground target is LabGuide's own terminal
      window.
- [x] Freeze target identity at the hotkey event, then capture the screenshot and
      UIA snapshot asynchronously.
- [x] Store exactly one pending capture in `LabGuideApp`.
- [x] Replace an existing pending capture only after the new screenshot succeeds.
- [x] Show target title, image dimensions, UI node count, timeout/truncation, and
      fallback status in the transcript.
- [x] Retain the pending capture after backend errors; clear it after successful
      send.
- [x] Report hotkey collisions and allow configuration of another chord.

Exit criteria:

- The target application remains foreground throughout capture.
- Capturing does not automatically send data.
- A user can capture, return to LabGuide, type a question, and submit the pending
  attachment. (Headless TUI smoke tests cover mount, hotkey registration, and
  cleanup; the interactive capture-to-send walkthrough remains a manual
  acceptance step.)

### Milestone 5: Backend Prompt and RAG Context Integration

Tasks:

- [x] Extend `_build_user_prompt()` in `src/labguide/client.py` with target-window
      metadata and the compact UI outline.
- [x] Delimit captured UI content and explicitly mark it as untrusted data.
- [x] Update the default system prompt to prefer UIA text for exact labels and
      values while using the image for layout and visual state.
- [x] Avoid sending both JSON and outline representations in the same prompt.
- [x] Keep the request compatible with standard OpenAI-style
      `/v1/chat/completions` servers.
- [x] Document how a future RAG backend can consume canonical JSON through a
      separate metadata contract without changing the capture layer.
- [x] Add payload-construction tests for text-only, screenshot-only, full UI
      context, partial UI context, and truncated UI context.

Exit criteria:

- Existing backend implementations accept the enriched request.
- Exact UI text is visible in the generated prompt once and only once.
- The system and user messages make the trust boundary explicit.

### Milestone 6: Privacy, Observability, and Rollout

Tasks:

- [x] Add non-content session metadata: target application, UI capture status,
      node count, truncation, and capture latency.
- [x] Confirm that screenshots, UI values, document text, and canonical JSON are
      not written to JSONL logs.
- [x] Add user-facing documentation describing what UIA can capture beyond the
      visible screenshot.
- [x] Add troubleshooting guidance for unsupported, elevated, Electron, browser,
      and GPU-rendered applications.
- [ ] Complete the Windows application test matrix below.
- [ ] Review privacy behavior with the organization before changing
      `ui_enabled` from false in shipped configuration.
- [x] Update this document's status and checkboxes as work completes.

Exit criteria:

- Privacy and support documentation matches actual behavior.
- Failures remain screenshot-only rather than request-blocking.
- The feature is enabled only after acceptance and privacy review.

## Validation Matrix

Live-verified rows are marked (verified 2026-07-26). All other rows remain
manual acceptance steps in an interactive desktop session.

| Scenario | Expected result |
| --- | --- |
| Notepad with known text | Text appears through Text/Value pattern (verified via WinForms Edit: exact value extracted; Notepad uses the same patterns) |
| Windows Settings | Labels, controls, and current states are present |
| File Explorer | Window, navigation, and selected-item context are present |
| Standard error dialog | Error text and button labels are present (verified: MsgBox body text and OK button extracted) |
| Edge or Chrome page | Best-effort accessibility text; screenshot always present |
| Electron application | Best-effort tree with documented sparse-tree fallback |
| Password field | Value is redacted before serialization (unit-tested: name, value, and text are cleared and replaced with a marker) |
| Elevated application | Bounded partial/failure result; screenshot still usable |
| Hung UIA provider | Probe is killed at timeout; LabGuide remains responsive (verified: 0.5s timeout kills the child process) |
| Window on secondary monitor | Correct window pixels and relative bounds (clamp unit-tested with negative coordinates; no second monitor on this machine) |
| Mixed-DPI monitors | Screenshot and UI element geometry remain aligned (Per-Monitor-V2 awareness requested by app and probe; single-DPI hardware here) |
| Target closes during capture | Partial/fallback capture with readable status (verified: closed HWND returns a bounded "closed" failure and the old pending capture is kept) |
| Backend request fails | Pending capture is retained for retry |
| Hotkey already registered | Startup warning and configurable recovery (verified: second registration of the same chord fails with a readable error) |

## Verification Commands

```powershell
python -m unittest discover -s tests
python -m labguide.ui_probe --help
python -m labguide
```

Manual UIA and hotkey tests must run inside the logged-in interactive Windows
desktop session. SSH, Windows services, and non-interactive scheduled tasks are
not valid substitutes for final GUI validation.

## Rollback Strategy

- Keep UI context behind `capture.ui_enabled` throughout implementation.
- If hotkey registration or UIA initialization fails, disable only the enriched
  capture path for that session.
- Preserve text-only submission and `capture_primary_display()` so support work
  can continue while UIA-specific defects are investigated.
- Avoid persisted schema migrations; the pending capture remains in memory.

## Deferred Work

- macOS Accessibility support
- Linux AT-SPI support
- Multiple pending screenshots per question
- OCR fallback for inaccessible custom controls
- Computer-use actions such as click, type, or form submission
- Capturing elevated or secure-desktop UI
- A custom backend field for canonical UI JSON
