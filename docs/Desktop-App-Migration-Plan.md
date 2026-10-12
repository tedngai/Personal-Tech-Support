# Desktop App Migration Plan (Textual TUI → Tauri 2)

## Status

- State: Proposed; not started. No code changes yet.
- Driver: Fleet deployment to campus-managed computers (Windows + macOS)
  requires a packaged, signed, auto-updating desktop application. A terminal
  UI cannot carry signing, MDM, TCC pre-provisioning, or end-user
  distribution.
- Target: Tauri 2 + React/TypeScript shell with a PyInstaller-packaged Python
  sidecar owning all capture and backend logic.
- Reference architecture: `block/buzz` desktop app (Tauri 2 + React + Tailwind,
  native core, features under `desktop/src/features/`). LabGuide substitutes
  a Python sidecar for its Rust core because the capture pipeline
  (PyObjC/ScreenCaptureKit, UIA, mss, pynput) is working, partially
  hardware-validated Python code.
- Last reviewed: 2026-10-05

## Objective

Ship LabGuide as a professional cross-platform desktop app deployable to a
fleet of campus-managed Windows and macOS machines, preserving every privacy
and architecture invariant of the TUI, without rewriting the validated
capture pipeline.

## Fixed Decisions

- UI shell: Tauri 2 + React + TypeScript + Vite + Tailwind. Rust stays
  template-level glue (window, tray, updater, sidecar supervision); no
  product logic in Rust.
- Capture/backend logic: the existing `src/labguide` package, packaged with
  PyInstaller as a sidecar executable. No Rust rewrite of capture code.
- Global hotkey stays in the sidecar. The hotkey handler must freeze the
  foreground window and capture pixels immediately; an IPC hop before
  capture would risk foreground changes. The sidecar owns hotkey → capture
  and notifies the UI after.
- The sidecar owns the backend request. Image/response size limits are
  enforced there, before request construction, exactly as today.
- IPC: JSON-RPC over the sidecar's stdio. Every call bounded by timeout.
  The sidecar is supervised by the shell: heartbeat, respawn with backoff,
  readable degraded states in the UI.
- The IPC surface is the read-only enforcement point: the sidecar exposes
  capture, permission, and send methods only. No click/type/focus/invoke
  methods exist to call.
- Backend contract stays OpenAI-compatible `/v1/chat/completions` and
  `/v1/models`. No server-side LabGuide service in this phase.
- Stable application identity from v1: fixed bundle ID, consistently signed
  shell and sidecar on both OSes, so TCC grants and enterprise trust
  survive updates.
- Configuration layering: MDM-managed read-only profile → user `labguide.toml`
  → built-in defaults. Never run elevated; never request `UIAccess`.
- The Textual TUI remains functional and supported until the desktop app
  passes its acceptance matrices; both coexist during migration. The pure
  modules (`capture`, `client`, `config`, `models`, `ui_outline`,
  `platforms/*`) are shared, not forked.

## Relationship to the Current Initiative

The macOS adapter validation (Cross-Platform-Execution-Plan.md) continues.
Row-by-row disposition when the desktop app lands:

- Adapter-level rows (identity, capture, AX probe, redaction, permissions,
  timeouts, stale window) carry over unchanged — they test `platforms/*`,
  which the sidecar reuses as-is.
- TUI-dependent rows (interactive TUI flow, real-keypress hotkey) re-target
  the desktop app instead of the TUI. Do not invest in polishing the TUI
  hotkey path beyond what is needed to finish adapter validation.
- Retina and secondary-display rows are hardware-bound and unchanged.
- The AX-server-wedge finding (avoid hard-killing AX-served processes)
  applies doubly to the desktop app: the shell must shut the sidecar down
  gracefully, never SIGKILL it while an AX transaction is open.

## Target Architecture

```
desktop/                     # Tauri 2 app (new top-level directory)
  src/                       # React + TypeScript + Tailwind
    features/
      transcript/            # role-coded message list (from widgets.py)
      composer/              # multiline input, explicit submit
      pending-capture/       # pending attachment state machine
      permissions/           # permission preflight surfacing
      settings/              # config display; MDM profile shown read-only
  src-tauri/                 # shell glue: sidecar spawn/supervise, updater,
                             # tray, single-instance, deep state serialization
src/labguide/                # existing package; new additions only:
  service/                   #   JSON-RPC stdio service entry point
  ipc.py                     #   request/response envelopes, error taxonomy
sidecar-dist/                # PyInstaller build output (not committed)
```

### IPC contract (sketch)

Requests (UI → sidecar), all with timeouts:

- `hello` → capabilities, adapter name, config summary (no secrets)
- `permissions.status` → per-permission granted/unavailable
- `capture.start` → hotkey-capture equivalent; returns pending-attachment
  metadata (id, window identity, image size, ui-context status). Image and
  UI context bytes are pulled by handle, not pushed through logs.
- `attachment.get` → attachment payload for display
- `submit` → enqueue backend request with prompt + attachment id; the only
  path that sends data
- `conversation.reset`, `discard`, `shutdown`

Events (sidecar → UI), unrequested:

- `hotkey.pressed`, `capture.completed`, `capture.failed`
- `submit.succeeded`, `submit.failed` (stage + category only)
- `sidecar.degraded` (e.g. hotkey unavailable → screenshot-only path)

Error taxonomy mirrors existing stage/category errors; exceptions never
include captured content.

### Invariants carried forward (binding on the React UI)

- A hotkey capture creates a local pending attachment; only explicit submit
  sends data.
- A new pending attachment replaces the old one only after capture succeeds;
  retained after backend errors; cleared after successful send.
- Captured UI text and screenshots are untrusted observed data: rendered as
  quoted/plain content, never interpreted, never echoed into logs. Backend
  answers render as markdown; captured content never does.
- Redaction (password/secure controls) happens in the sidecar before
  serialization, exactly as today; the UI never receives secret values
  because they never exist outside the sidecar.
- No literal colors in components; theme tokens only (Tailwind theme
  variables, mirroring the `$`-token rule from `labguide.tcss`).
- Session log remains non-content operational metadata.

## Delivery Milestones

### Phase 0: Prerequisites and decision gates

- [ ] Finish macOS adapter validation rows that are not TUI-dependent
      (see relationship section); record outcomes in the existing matrix.
- [ ] Confirm fleet requirements with campus IT: MDM system (Intune/JAMF or
      equivalent), update channel expectations, proxy/virus-scan constraints
      for the sidecar binary.
- [ ] Acquire code-signing assets: Windows Authenticode certificate (OV or
      EV; EV avoids SmartScreen reputation lag), Apple Developer ID + notary
      tooling.
- [ ] Fix the application identity: bundle ID, sidecar executable name,
      update-channel URL layout. These are unchangeable after first fleet
      release (TCC keys on them).

### Phase 1: Sidecar extraction (no UI change)

- [ ] `labguide.service`: long-running JSON-RPC stdio service wrapping the
      existing capture pipeline, client, and config; TUI code path untouched.
- [ ] Every IPC call bounded by timeout; errors mapped to the
      stage/category taxonomy.
- [ ] Hotkey adapters register inside the service; events emitted over the
      same channel.
- [ ] Contract tests for the IPC envelope (pure, cross-platform, no OS APIs).
- [ ] Graceful-shutdown contract: sidecar drains AX transactions before exit
      (AX-wedge finding); shell-initiated shutdown is a request, not a kill.
- [ ] A `--stdin-swap` test harness mode so the service can be exercised
      from unit tests on any OS.

### Phase 2: Tauri shell

- [ ] Tauri 2 project scaffold; sidecar spawn via tauri-plugin-shell;
      supervised restart with backoff; UI shows a readable degraded banner
      while the sidecar is down (screenshot-only/text-only rules preserved
      at the UI layer).
- [ ] Single-instance enforcement; tray icon with show/quit.
- [ ] Typed TS client generated or hand-mirrored from the IPC contract, with
      a drift test (contract test shared by both sides).
- [ ] React components: transcript (role-coded), composer, pending-capture
      state machine (replace-only-after-success, retain-on-error,
      clear-on-send), permission surfacing.
- [ ] Theme tokens in Tailwind config; no literal colors in components.

### Phase 3: Packaging and identity

- [ ] PyInstaller onefile spec per OS; sidecar versioned and signed with the
      same identity across releases.
- [ ] Windows: MSI via Tauri bundler, Authenticode-signed shell + sidecar.
- [ ] macOS: signed + notarized app bundle; sidecar inside the bundle
      signed with the same team ID.
- [ ] Tauri updater wired to a static update manifest (start with static
      hosting; no update server to run).
- [ ] First-run experience: permission preflights surfaced before first
      capture; readable guidance when a permission is missing.

### Phase 4: Fleet operability

- [ ] Config layering implemented: MDM profile path (platform-appropriate)
      → user TOML → defaults; MDM layer displayed as managed/read-only.
- [ ] Sample MDM profiles: macOS TCC pre-approval payload (Screen Recording,
      Accessibility) and Windows policy notes for campus IT.
- [ ] Validation on a managed machine image: antivirus/proxy behavior with
      the sidecar, non-elevated install, AppLocker/ Gatekeeper paths.
- [ ] Update-path verification: signed update installs cleanly on both OSes
      without re-prompting TCC permissions (the stable-identity payoff).

### Phase 5: Acceptance

- [ ] Windows: full regression matrix from
      `UI-Context-Capture-Execution-Plan.md` re-run against the desktop app.
- [ ] macOS: matrix rows re-run; TUI-dependent rows closed out here.
- [ ] New rows: sidecar crash mid-capture (bounded, readable, respawned),
      sidecar slow (timeouts visible, UI never wedged), app quit during AX
      probe (graceful, no wedge), update installed while capture pending.
- [ ] Pure unit suite still passes unchanged (models, formatting,
      truncation, redaction, adapter selection).
- [ ] README, example config, and troubleshooting updated for the desktop
      app; `AGENTS.md` code map updated for `desktop/` and `service/`.

## Risks and Mitigations

- **PyObjC + PyInstaller on macOS**: hidden imports and framework
  weak-linking are the classic failure mode. Mitigate with a Phase 1 smoke
  build early, not after the UI exists.
- **TCC identity churn**: any relink/resign that changes the designated
  requirement re-prompts every fleet machine. Mitigate by treating signing
  identity as fixed infrastructure (Phase 0) and testing an update cycle
  before fleet rollout (Phase 4).
- **Two IPC surfaces to keep honest** (Tauri commands + sidecar JSON-RPC):
  mitigate with one shared contract definition and drift tests.
- **Team bandwidth**: Rust exposure is limited to scaffold glue, but a small
  team still needs the toolchain (Rust, Node, pnpm) pinned; use Hermit-style
  pinning as Buzz does.
- **Scope creep toward management plane**: no telemetry aggregation, remote
  config push, or new server in this phase. File-based config and the
  existing OpenAI-compatible backend only. Revisit with evidence and a
  privacy review.

## Rollback Strategy

- The TUI remains in the repo and functional throughout; pure modules are
  shared, so no divergence. Desktop app phases can pause without breaking
  `python -m labguide`.
- Fleet rollout is staged: pilot machines first; the TUI stays the fallback
  install path until Phase 5 acceptance passes.
- If the desktop app is blocked in the field, TCC grants keyed to the stable
  identity remain valid for later releases; nothing is lost by pausing.

## Deferred Work

- Central management plane (telemetry, remote config, health reporting) —
  requires an explicit privacy review and a user/data requirement.
- OCR fallback, multiple attachments, computer-use actions — unchanged
  non-goals.
- Linux adapters and Linux packaging — deferred unchanged.
- Auto-update delta/differential packaging — start with full-package
  updates; optimize if fleet bandwidth demands it.
