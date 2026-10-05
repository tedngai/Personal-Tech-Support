# Cross-Platform Execution Plan (Windows + macOS)

## Status

- State: Phases 1–5 implemented; macOS adapter pending interactive validation
- Target: LabGuide TUI on Windows 11 and macOS 14+ (validated target: macOS Tahoe)
- Scope: Read-only screenshot and accessibility context capture; Linux deferred
- Last reviewed: 2026-09-15

## Objective

Preserve the Windows support loop (capture problem app → pending attachment →
explicit send) on macOS with feature parity where the platform allows it,
through a narrow platform-adapter layer. Linux is explicitly out of scope for
this phase.

## Fixed Decisions

- Stay with Python and the existing Textual TUI; no desktop GUI rewrite.
- Platform differences live behind `labguide.platforms` adapters; the app
  consumes capabilities, not OS APIs.
- macOS window pixels come from ScreenCaptureKit (actual window contents,
  not a desktop crop). The Windows path keeps desktop-region capture for now;
  Windows Graphics Capture is a future improvement.
- macOS accessibility text comes from an isolated AXUIElement child-process
  probe with the same JSON contract, timeout, and redaction rules as the
  Windows UIA probe.
- macOS global hotkey uses pynput (CGEvent tap); it requires Accessibility
  permission. Screenshot-only capture must keep working without it.
- macOS baseline is 14+ (SCScreenshotManager). Labs run macOS Tahoe.
- Python-based installation is sufficient; no packaged installer in this phase.
- Linux gets an `UnsupportedAdapter` (text-only + primary screenshot) rather
  than partial support.

## Delivery Milestones

### Phase 1: Attachment lifecycle hardening

- [x] Unique capture IDs; a successful send clears only the attachment it
      submitted, never a newer pending capture.
- [x] Unexpected accessibility-probe failure degrades to screenshot-only
      instead of losing captured pixels.
- [x] `Ctrl+Shift+D` discards the pending capture; `Ctrl+L` clears the
      conversation.
- [x] Failed sends restore the prompt when the input is still empty.
- [x] Session-log write failures are nonfatal.

### Phase 2: Shared contracts, limits, and privacy

- [x] `PlatformCapabilities` and `PlatformAdapter` contracts; native handles
      stay inside adapters.
- [x] Image dimension and encoded-byte limits enforced before request
      construction (quality floor, then downscale).
- [x] Backend response bodies bounded (`max_response_bytes`).
- [x] Default session log drops user prompts; operational metadata only.
- [x] UIA probe treats an unreadable IsPassword property as sensitive
      (redact) instead of extracting text.
- [x] History limit counts user/assistant turns; retained history is bounded.

### Phase 3: Windows adapter extraction

- [x] `platforms/windows/adapter.py` wraps win32_window, global_hotkey, and
      ui_probe behind the contract with no behavior change.
- [ ] Windows Graphics Capture for true window contents (overlapping windows
      can still appear in the desktop-region crop). Future work.

### Phase 4: macOS adapter

- [x] CGWindowList foreground identity, z-order "window below", bounds,
      terminal detection (`platforms/macos/window.py`).
- [x] ScreenCaptureKit window capture with bounded async waits and Retina
      scale handling (`platforms/macos/screenshot.py`).
- [x] Isolated AXUIElement probe with role normalization, secure-field
      redaction, node/depth/text limits (`platforms/macos/ax_probe.py`) and
      parent runner with hard timeout (`platforms/macos/accessibility.py`).
- [x] pynput global hotkey with chord parsing (`platforms/macos/hotkey.py`).
- [x] TCC permission checks (`platforms/macos/permissions.py`).
- [ ] Interactive validation on a Tahoe machine (matrix below).

### Phase 5: TUI unification

- [x] App consumes `get_adapter()` and capabilities instead of `sys.platform`
      checks.
- [x] Unsupported platforms degrade to text-only + primary screenshot.

### Phase 6: Packaging, docs, acceptance

- [x] pyproject macOS dependencies behind `sys_platform == 'darwin'`.
- [x] README, example config, and troubleshooting updated.
- [ ] Interactive Windows regression pass (existing matrix in
      `UI-Context-Capture-Execution-Plan.md`).
- [ ] Interactive macOS acceptance pass (matrix below).

## macOS Validation Matrix

All rows are manual acceptance steps in an interactive desktop session on a
Tahoe machine.

| Scenario | Expected result |
| --- | --- |
| TextEdit with known text | Exact text appears through the AX probe |
| Standard error dialog | Dialog text and button labels are present |
| Safari page | Best-effort AX text; screenshot always present |
| Electron application | Best-effort tree with sparse-tree fallback |
| Password field (secure text) | Redacted marker only; no value or text |
| Screen Recording denied | Readable permission error; no capture |
| Accessibility denied | Screenshot works; hotkey/UI text report unavailable |
| Permission revoked mid-session | Next capture reports the permission loss cleanly |
| Hung AX provider | Probe killed at timeout; TUI stays responsive |
| Retina display | JPEG pixel size matches window scale; AX bounds align |
| Secondary display | Correct window pixels and relative bounds |
| Target closes during capture | Bounded failure; previous pending capture kept |
| Backend request fails | Pending capture retained; prompt restored |
| Hotkey while terminal focused | Capture ignored with readable message |

### Validation status — 2026-10-05, macOS 26.6.2 (Tahoe, Mac mini M1, 1x display)

Driven from the Hermes app as permission host. Machine-run rows were
exercised through headless adapter calls and the isolated probe CLI.

| Scenario | Outcome |
| --- | --- |
| TextEdit with known text | PASS — complete snapshot, all known strings found |
| Standard error dialog | GAP FOUND — modal dialogs sit at CGS layer 8; `get_foreground_window_id()` / `get_window_below()` accept layer 0 only, so the identity stage cannot target them. AX readability of the dialog itself left inconclusive (AX wedge, below) |
| Safari page | PASS — partial at the 500-node cap, rich tree (73 Text, 25 Hyperlink) |
| Electron application | PASS — Hermes window: partial, 348 nodes, bounded truncation |
| Password field (secure text) | PASS — NSSecureTextField yields only a `pw=True` marker; value never read; plain field content intact |
| Screen Recording denied | PASS — preflight false, readable CaptureError (observed before grant) |
| Accessibility denied | PASS — preflight false observed; probe inaccessibility path unit-tested |
| Hung AX provider | PASS — probe child hard-killed at 0.50 s, `timed_out` status, parent responsive |
| Retina display | N/A here — 1x display (point/pixel scale verified = 1.0; 2x path implemented via `pointPixelScale`, needs Retina hardware) |
| Secondary display | N/A — single display |
| Target closes during capture | PASS — stale window id fails bounded (0.08 s) with readable error |
| Backend request fails | Pending — needs interactive TUI against a backend |
| Hotkey while terminal focused | Pending real keypress — synthetic CGEvents are ignored by pynput 1.8.2 `GlobalHotKeys` (`if not injected:`), by design; raw event tap reception verified working |

Additional findings:

- **Capture fix (code change, this session):** PyObjC 11.1 bindings lag
  macOS 26 — SCScreenshotConfiguration lost `+configuration` and its
  pixelFormat accessors while the framework still walks them by selector.
  `screenshot.py` now layers a runtime accessor shim plus a
  CGWindowListCreateImage fallback; verified exact window pixels (673x439).
- **AX server wedge (environment, not code):** twice this session the AX
  server began returning self-referential degenerate windows (role
  AXApplication as AXMainWindow, attribute errors -25205/-25202) to every
  Hermes-hosted process, and System Events queries hung. Both episodes
  followed a Python process dying abruptly while its AX tree had just been
  served (SIGABRT inside an AX XPC transaction; later a SIGTERM after a
  probe). A Hermes relaunch cleared it the first time; identical probe
  results returned immediately. Avoid hard-killing AX-served processes from
  this process tree; prefer graceful app quits.

## Verification Commands

Any platform:

```bash
python -m unittest discover -s tests
python -m labguide.ui_probe --help                     # Windows UIA probe
python -m labguide.platforms.macos.ax_probe --help     # macOS AX probe
python -m labguide
```

macOS first-run setup (Tahoe):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
# Grant Screen Recording and Accessibility to the terminal app, restart it,
# then set ui_enabled = true in labguide.toml.
python -m labguide.platforms.macos.ax_probe --pid <pid>   # probe smoke test
python -m labguide
```

macOS-only code paths (ScreenCaptureKit, AXUIElement, pynput) cannot be
exercised on Windows; pure helpers (role mapping, chord parsing, adapter
selection, image limits) are unit-tested cross-platform.

## Rollback Strategy

- macOS code only loads on darwin; Windows behavior is unchanged behind the
  same modules as before.
- `capture.ui_enabled = false` disables enriched capture on both platforms.
- The `UnsupportedAdapter` keeps Linux/unknown platforms at text-only +
  primary screenshot instead of failing obscurely.

## Deferred Work

- Linux (X11/Wayland) adapters.
- Windows Graphics Capture for true window contents.
- Packaged/signed app with its own TCC identity.
- OCR fallback, multiple attachments, computer-use actions (unchanged
  non-goals).
