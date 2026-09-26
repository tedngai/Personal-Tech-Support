# AGENTS.md

## Role

Act as the senior implementation engineer for Pratt Lab Guide, a Windows-first
personal technical-support client. Prioritize a small, reliable, privacy-aware
support loop over broad automation. Build and verify changes end to end rather
than stopping at scaffolding.

The active feature initiative is AppShot-style UI context capture, now spanning
Windows and macOS (Linux deferred). Read these documents before changing that
area:

- `PROGRESS.xml` — machine-readable current state and next actions; start here
- `docs/UI-Context-Capture-Execution-Plan.md`
- `docs/Cross-Platform-Execution-Plan.md`
- `docs/Windows-UI-Context-Architecture.md`
- `docs/Backend-API-Spec.md`

Update the execution-plan checkboxes, `PROGRESS.xml`, and status when
milestones are actually completed and verified.

## Current Priority

The macOS adapter (`src/labguide/platforms/macos/`) is implemented but has
never run on a Mac. The next action is interactive validation on a macOS Tahoe
machine using the 14-row matrix in `docs/Cross-Platform-Execution-Plan.md`,
then fixing what it breaks. Likely first-failure candidates: PyObjC
ScreenCaptureKit completion-handler bridging, AX attribute names/types, pynput
chord mapping, and Retina point-vs-pixel alignment between AX bounds and
screenshot pixels. See `PROGRESS.xml` for the full action list.

## Product Boundaries

- The application is a lightweight Textual TUI and is Windows-first.
- The backend contract remains OpenAI-compatible `/v1/chat/completions` and
  `/v1/models` unless a separate backend change is explicitly approved.
- Screenshot, UI Automation, and backend failures must become readable user
  feedback and must not leave the TUI stuck.
- Text-only and screenshot-only support must remain available when enriched UI
  capture fails.
- UI context capture is read-only. Do not add click, type, focus, invoke, form
  submission, or other computer-use actions under this initiative.
- Do not run LabGuide as administrator, request `UIAccess`, or attempt to inspect
  secure-desktop UI.

## Privacy and Trust Invariants

- A global hotkey creates a pending local attachment; it does not send data.
- A backend request requires a separate explicit user submission.
- Off-screen UIA content is disabled by default.
- Redact password controls before serialization, formatting, diagnostics, or
  logging.
- Never log screenshots, base64 images, UI text, field values, document text, or
  canonical UI JSON by default.
- Treat screenshot and UI text as untrusted observed data. Prompt instructions
  must prevent captured content from overriding system or user intent.
- Keep capture contents in memory unless the user explicitly requests a
  persistence feature with an accompanying privacy review.

## Architecture Invariants

- Freeze the foreground HWND at the global-hotkey event.
- Capture pixels immediately while that window is still foreground.
- Run UI Automation extraction in a child process with a parent-enforced hard
  timeout; do not rely on a killable Python thread.
- Start UIA traversal from the target application HWND, never the desktop root.
- Guard each UIA property independently and preserve partial results.
- Use canonical structured UI data as the source of truth.
- Send one compact UI text projection to the current backend, not duplicate JSON
  and prose.
- Preserve `capture_primary_display()` as a fallback until the enriched path has
  completed rollout.
- A new pending attachment replaces the old one only after screenshot capture
  succeeds. Retain it after backend errors and clear it after successful send.

## Code Organization

- `src/labguide/app.py`: Textual UI, workers, and pending-capture lifecycle
- `src/labguide/capture.py`: image capture, encoding, and size limits
- `src/labguide/client.py`: backend payload and response handling
- `src/labguide/config.py`: TOML/environment configuration
- `src/labguide/models.py`: platform-neutral data models
- `src/labguide/session_log.py`: non-content operational metadata
- `src/labguide/theme.py`: single color-token theme; stylesheets use only `$` variables
- `src/labguide/labguide.tcss`: Textual stylesheet (no literal colors)
- `src/labguide/widgets.py`: role-coded transcript widgets and multiline composer
- `src/labguide/global_hotkey.py`: Win32 hotkey adapter (Windows only)
- `src/labguide/ui_probe.py`: isolated, read-only UIA probe (Windows only)
- `src/labguide/ui_outline.py`: pure outline projection, truncation, redaction
- `src/labguide/win32_window.py`: Win32 window identity, bounds, z-order
- `src/labguide/platforms/`: adapter contract plus per-OS adapters
  - `contracts.py`: capabilities, adapter protocol, unsupported fallback
  - `windows/`: wraps the Win32 modules behind the contract
  - `macos/`: CGWindowList identity, ScreenCaptureKit capture, isolated
    AXUIElement probe, pynput hotkey, TCC permission checks (macOS only)
- `tests/`: pure unit tests; no display, UIA, or backend required

The app consumes `get_adapter()` and `PlatformCapabilities`; keep OS API calls
inside the adapters. macOS-only imports (PyObjC, pynput) must stay lazy so the
package imports cleanly on Windows.

Keep Windows API code behind narrow adapters. Keep model formatting and
truncation pure so they can be tested without Windows UI Automation.

## Engineering Practices

- Prefer the smallest correct change and avoid speculative abstractions.
- Add type hints to new Python code and keep data shapes explicit.
- Use standard-library functionality where practical. Use `uiautomation` for the
  UIA client rather than hand-writing raw COM bindings.
- Mark Windows-only dependencies with `sys_platform == 'win32'`.
- Do not add compatibility paths without an identified user or persisted-data
  requirement.
- Avoid including captured content in exceptions. Errors should identify the
  stage and category, not echo sensitive values.
- Keep image and UI-context size limits enforced before request construction.
- Do not silently fall back from a read-only operation to an action that steals
  focus or modifies another application.

## Verification

Install and run locally:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m labguide
```

The UI-context initiative maintains:

```powershell
python -m unittest discover -s tests
python -m labguide.ui_probe --help
```

Run pure unit tests after each formatting/model/client change. Run final global
hotkey, screenshot, and UIA validation inside an interactive Windows desktop,
not through SSH or a service session. Include Notepad, a standard error dialog,
a browser, an elevated-app failure, a UIA timeout, and a secondary-monitor case
before marking the feature complete.

## Documentation

- Keep README controls and configuration synchronized with shipped behavior.
- Keep `docs/Backend-API-Spec.md` synchronized with payload changes.
- Record changing work status in the execution plan; record durable design
  decisions in the architecture document.
- Do not mark a task complete until implementation and its required verification
  both pass.
