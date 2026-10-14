# Personal Tech Support

> An AI-powered desktop assistant for instant, context-aware technical support — show it what you see, and get clear next steps.

Personal Tech Support streamlines troubleshooting for everyday software issues. Capture any application window, add a brief description, and receive concise, actionable guidance from your configured vision-language model. Built for Windows and macOS, it runs locally, integrates with any OpenAI-compatible backend, and ensures no data is transmitted until you explicitly send it.

Designed for individual productivity and enterprise support workflows where accuracy, privacy, and deployment at scale matter.

---

## Key Capabilities

- **Context-Aware Window Capture** — Select any window from a visual thumbnail grid. The application captures the target window directly, even when it is obscured by other windows, eliminating manual cropping.
- **Accurate Text Extraction** — Retrieves exact labels, error codes, field values, and control states via native accessibility APIs (Windows UI Automation / macOS AX), rather than relying on OCR.
- **Conversational Assistance** — Chat-based interface with multi-turn history and markdown-formatted responses. Pending captures are managed explicitly and attached automatically on send.
- **Privacy by Design** — All captures remain local until submission. Password fields are automatically redacted, and no prompts, screenshots, or window content are written to logs.
- **Enterprise Ready** — Layered configuration, machine-wide deployment support, system tray integration, and single-instance enforcement for managed environments.
- **Flexible Deployment** — Available as a Tauri-based desktop application (recommended) with a Textual-based terminal interface included for development and lightweight use.

---

## System Requirements

- Python 3.10+
- Windows 11 or macOS 14+
- Network access to an OpenAI-compatible backend
- A vision-capable model for screenshot-assisted troubleshooting
- **macOS additional setup:** Screen Recording permission (screenshots) and Accessibility permission (global hotkey and text extraction) granted to the host application

---

## Installation

### Desktop Application (Recommended)

1. Install `LabGuide_0.1.0_x64_en-US.msi`.

2. Provision the configuration file. Choose one:

   ```powershell
   # Machine-wide — applies to all users on the device (requires administrator):
   New-Item -ItemType Directory -Force C:\ProgramData\LabGuide
   Copy-Item labguide.toml C:\ProgramData\LabGuide\labguide.toml

   # Per-user — no administrator privileges required:
   New-Item -ItemType Directory -Force $env:APPDATA\LabGuide
   Copy-Item labguide.toml $env:APPDATA\LabGuide\labguide.toml
   ```

   If you do not have a configuration file, create one from the example:
   ```powershell
   Copy-Item labguide.example.toml labguide.toml
   ```

3. Launch **LabGuide** from the Start Menu. The header should display `online`.

For development:

```powershell
cd desktop
npm run tauri dev
```

### Terminal Interface

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # macOS
pip install -e .
labguide          # or: python -m labguide
```

---

## Usage

1. **Capture** — Click **Capture window…** and select the target application, or press **Ctrl+Shift+Space** while the affected application is in the foreground. Use **Capture screen** for a full-display capture when needed.

2. **Describe** — Enter a concise description of the issue. The pending capture thumbnail will appear above the composer and will be attached automatically.

3. **Send and Resolve** — Press **Enter** to submit. Responses are returned as structured, actionable steps. Use **Discard** to remove the pending capture or **Clear conversation** to reset history.

**Desktop Controls**

| Action | Shortcut / Control |
|---|---|
| Send message | `Enter` |
| New line | `Shift+Enter` |
| Capture window | `Capture window…` button |
| Capture screen | `Capture screen` button |
| Global capture | `Ctrl+Shift+Space` (configurable) |
| Discard pending capture | `Discard` button |
| Clear conversation | `Clear conversation` button |
| Restore window | Tray icon click |

**Terminal Controls**

`Enter` to send, `Shift+Enter` / `Alt+Enter` / `Ctrl+J` for new line, `Ctrl+S` to capture the window below the terminal, `Ctrl+Shift+Space` for global capture, `Ctrl+Shift+D` to discard, `Ctrl+L` to clear, `Ctrl+C` to exit.

Pending captures are replaced upon successful capture, retained on send failure, and cleared only after a successful submission where no newer capture has been created.

---

## Configuration

All settings are managed through `labguide.toml`. An API key may be provided in the file or via the `LABGUIDE_API_KEY` environment variable. The repository does not commit credentials.

**Configuration resolution order (first existing file wins; machine-wide settings take precedence per key):**

1. Path specified by `LABGUIDE_CONFIG` environment variable
2. Machine-wide: `C:\ProgramData\LabGuide\labguide.toml` (Windows) / `/Library/Application Support/LabGuide/labguide.toml` (macOS)
3. User/local: `labguide.toml` in the current directory, adjacent to the executable, or `%APPDATA%\LabGuide\labguide.toml`
4. Built-in defaults

<details>
<summary><strong>Example configuration</strong></summary>

```toml
[backend]
base_url = "https://your-backend.example/v1"
model = "your-vision-model"
api_key = ""
timeout_seconds = 30.0

[capture]
jpeg_quality = 80
ui_enabled = false          # true to include accessibility text
ui_timeout_seconds = 8.0
global_hotkey = "ctrl+shift+space"

[session]
max_history_turns = 6
log_path = "logs/labguide-session.jsonl"
```

Refer to `labguide.example.toml` for the complete annotated example.

</details>

Enable enriched captures by setting `ui_enabled = true` to include structured accessibility text (labels, values, control states) alongside the screenshot. This data is provided as text — no inference from pixels — and remains subject to password redaction.

---

## How It Works

1. **Capture** — The application identifies the target window and acquires its pixel data using native windowing APIs. Window-level capture remains accurate even when the target is obscured.
2. **Context Extraction** — A separate, time-bounded process retrieves accessibility information via platform APIs (UI Automation on Windows, AXUIElement on macOS). The operation is read-only and isolated to ensure the main application remains responsive.
3. **Submission** — Upon explicit user action, a single compact request containing the screenshot and a text projection of the UI is sent to the configured OpenAI-compatible endpoint. When no screenshot is attached, a text-only prompt is used.
4. **Response and Logging** — The response is rendered in the transcript. A local JSONL log records operational metadata only — latency, success status, and error categories.

<details>
<summary><strong>Technical details</strong></summary>

- Frontend: Tauri 2 + React (desktop) with Textual TUI fallback
- Backend: OpenAI-compatible `/v1/chat/completions` and `/v1/models` (health check)
- Image handling: JPEG encoding with configurable dimension and byte limits; response bodies capped at 8 MB
- Platform layer: Isolated accessibility adapters in `src/labguide/platforms/` with lazy imports for OS-specific dependencies
- Session logging: Local JSONL, metadata only

</details>

---

## Project Structure

```text
src/labguide/        # Core Python package: capture, backend client, configuration, sidecar
  service/           # JSON-RPC sidecar service
  platforms/         # windows/ and macos/ adapters
tests/               # Unit tests (no display required)
desktop/             # Tauri + React desktop application
scripts/             # Sidecar build and fixture generation
docs/                # Architecture and execution plans
PROGRESS.xml         # Machine-readable project status
```

---

## Development

```bash
# Python unit tests
python -m unittest discover -s tests

# Frontend tests
cd desktop && npm test

# Desktop development
cd desktop && npm run tauri dev

# Platform probes
python -m labguide.ui_probe --help
python -m labguide.platforms.macos.ax_probe --help
```

Current status and next steps are tracked in `PROGRESS.xml` and `docs/Desktop-App-Migration-Plan.md`.

---

## Troubleshooting

**Desktop app displays "Capture service unavailable"**

Ensure `labguide-sidecar.exe` is located alongside `LabGuide.exe` (handled automatically by the installer). To diagnose:

```powershell
'{"id":1,"method":"hello"}' | & "C:\Program Files\LabGuide\labguide-sidecar.exe"
```

A healthy service returns a JSON response; startup errors are written to stderr.

**Backend unreachable**

Verify `base_url`, `models_path`, and `chat_path` in your configuration. Confirm the backend is reachable and that the configured model is listed via `GET /v1/models`.

**Screenshot transmission failures**

Confirm the model supports image input. Reduce `jpeg_quality` if payload size is constrained. Test with a text-only message first. The client requests identity encoding and handles mislabeled gzip responses automatically.

**Authentication failures**

Set `backend.api_key` in `labguide.toml` or export `LABGUIDE_API_KEY`. Do not commit credentials.

**Capture issues (`ui_enabled = true`)**

- *Hotkey unavailable:* Another application has registered the chord. Update `global_hotkey` in your configuration. On macOS, verify Accessibility permission for the host application.
- *Capture ignored:* The global hotkey must be triggered while the target application is in the foreground.
- *UI text unavailable (timed_out / unsupported / inaccessible):* The screenshot is still transmitted. Elevated applications cannot be inspected from a non-elevated context; certain Electron, browser, and GPU-rendered applications expose limited accessibility trees.
- *Slow initial capture:* The accessibility helper initializes on first use. Subsequent captures are immediate. Adjust `ui_timeout_seconds` if needed.

**macOS Permissions**

- **Screen Recording** (System Settings → Privacy & Security → Screen Recording) — Required for captures. Grant to the terminal or application running LabGuide and restart it.
- **Accessibility** — Required for the global hotkey and accessibility text extraction. Screenshot-only capture remains functional without it.

---

## License

MIT — see `LICENSE`.
