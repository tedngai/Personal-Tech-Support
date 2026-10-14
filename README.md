# Pratt Lab Guide — your lab computer's fix-it buddy 🛠️

> Stuck on a weird error right before your deadline? Don't copy-paste the error code into Google for the 10th time — just *show* LabGuide what's on your screen and ask.

LabGuide is a small desktop + terminal app that helps you troubleshoot lab computers. You capture the broken window (or your whole screen), type "why won't this print??" and get back short, step-by-step help from an AI vision model. It runs on Windows and macOS, works with the Pratt AI backend, and never sends anything until *you* hit send.

**Perfect for:** students in Pratt labs, TAs on help-desk duty, and anyone tired of "have you tried turning it off and on again?"

---

## ✨ What it actually does

- **📸 Show, don't tell** — Click *Capture window…*, pick the broken app from a thumbnail grid, and LabGuide grabs that window *even if it's buried under other windows*. No more cropping screenshots.
- **🔍 Reads the fine print for you** — It pulls the real text from buttons, error codes, and dialogs (not just pixels), so you get exact answers.
- **💬 Just chat** — Type your question, hit Enter, get a markdown answer. Your history stays in the app while it's open.
- **🔒 You stay in control** — Capturing saves it locally. Nothing is sent until you explicitly hit Send. Passwords are always redacted.

> Prefer the terminal? Same brain, Textual TUI version included (`python -m labGuide`).

---

## 🚀 Get it in 2 minutes

### Option A: Desktop app (recommended)

1. **Install** `LabGuide_0.1.0_x64_en-US.msi` (double-click → *More info → Run anyway* if Windows warns — it's unsigned for now).

2. **Add your config** — pick one:

   ```powershell
   # For everyone on this computer (needs admin, once):
   New-Item -ItemType Directory -Force C:\ProgramData\LabGuide
   Copy-Item labguide.toml C:\ProgramData\LabGuide\labguide.toml

   # Or just for you (no admin):
   New-Item -ItemType Directory -Force $env:APPDATA\LabGuide
   Copy-Item labguide.toml $env:APPDATA\LabGuide\labguide.toml
   ```

   > Don't have a `labguide.toml` yet? `Copy-Item labguide.example.toml labguide.toml` and edit it.

3. **Open LabGuide** from the Start Menu and you're in. It should say `online · model pratt-agent` at the top.

For devs:
```powershell
cd desktop
npm run tauri dev
```

### Option B: Terminal version

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # macOS
pip install -e .
labguide          # or: python -m labguide
```

---

## 🎮 How to use it (30 seconds)

| What you do | What happens |
|---|---|
| **1. Break something** | Photoshop crashes. Printer says `0x6100004a`. You know the drill. |
| **2. Capture** | Click **Capture window…** → pick the broken app → see the thumbnail appear. Or press **Ctrl+Shift+Space** while the broken app is in front. |
| **3. Ask** | Type "why is this happening and how do I fix it?" → **Enter**. The pending screenshot is attached automatically. |
| **4. Fix & repeat** | Follow the steps. `Discard` the screenshot if you don't need it, or just keep chatting. |

**Desktop controls:**

- `Enter` to send, `Shift+Enter` for a new line
- `Capture window…` = pick a window (minimized ones are hidden on purpose)
- `Capture screen` = whole display
- `Ctrl+Shift+Space` = global hotkey (works even when LabGuide is in the background)
- Tray icon → click to bring LabGuide back

**TUI controls:** `Ctrl+S` captures the window *below* the terminal, same hotkey works, `Ctrl+Shift+D` discards, `Ctrl+L` clears.

That's it. No account, no cloud sync.

---

## ⚙️ Configuration — where do I put stuff?

You edit one file: `labguide.toml`. Copy the example and fill in your backend:

```powershell
Copy-Item labguide.example.toml labguide.toml
# then open labguide.toml in Notepad/VS Code
```

**Where LabGuide looks (first file that exists wins, machine-wide wins per-setting):**

1. `LABGUIDE_CONFIG` env var — if you set it, that's the file
2. **Machine-wide:** `C:\ProgramData\LabGuide\labguide.toml` (Windows) or `/Library/Application Support/LabGuide/labguide.toml` (macOS) — *this wins for every user on that machine*
3. **Your stuff:** `labguide.toml` next to where you run it, or `%APPDATA%\LabGuide\labguide.toml`
4. Built-in defaults

Put your API key in the file (`api_key = "..."`) or as `LABGUIDE_API_KEY` env var. Never commit it.

<details>
<summary><b>Full example config (click to expand)</b></summary>

```toml
[backend]
base_url = "https://your-backend.example/v1"
model = "pratt-agent"
api_key = ""
timeout_seconds = 30.0

[capture]
jpeg_quality = 80
ui_enabled = false          # true = also grab accessibility text (labels, errors)
ui_timeout_seconds = 8.0
global_hotkey = "ctrl+shift+space"

[session]
max_history_turns = 6
log_path = "logs/labguide-session.jsonl"
```

See `labguide.example.toml` for all options with comments.
</details>

Need richer captures? Set `ui_enabled = true` in your toml. It grabs the exact dialog text + button states, still as text — not a guess from pixels.

---

## 🧠 How it works (the 10-second version)

1. You hit capture → LabGuide freezes that window's identity and grabs its pixels (with `PrintWindow` so covered windows still work).
2. In the background it asks Windows/macOS "what text is in this window?" via accessibility APIs — totally read-only, in a separate process so a frozen app can't freeze LabGuide.
3. When you hit Send, it sends *one* compact message: screenshot + a tiny text outline of the UI (marked as untrusted data so the AI can't be tricked by text *inside* your screenshot).

<details>
<summary><b>Nerdy details for the curious</b></summary>

- Frontend: Tauri 2 + React (desktop) + Textual TUI fallback
- Backend: any OpenAI-compatible `/v1/chat/completions` + `/v1/models` health check
- Image handling: JPEG bounded by dimension & byte size before sending; responses capped at 8 MB
- Accessibility: Windows UIA / macOS AXUIElement, isolated child process + hard timeout, password fields redacted
- Platform adapters live in `src/labguide/platforms/` — OS calls never leak into the app
- Session log is local JSONL with *only* metadata (no prompts, screenshots, or window titles)

</details>

---

## 🗂️ Project structure (for contributors)

```text
src/labguide/        # Python core: capture, backend client, config, sidecar
  service/           # JSON-RPC sidecar (what the desktop app talks to)
  platforms/         # windows/ + macos/ adapters
tests/               # pure unit tests — no display needed
desktop/             # Tauri + React app (tray, picker, sidecar supervision)
scripts/             # sidecar build + fixture generation
docs/                # architecture & execution plans
PROGRESS.xml         # machine-readable status (start here if you're picking up work)
```

---

## 🧪 For developers

```bash
# Python tests (no display needed)
python -m unittest discover -s tests

# Frontend tests
cd desktop && npm test

# Desktop dev
cd desktop && npm run tauri dev

# TUI probes
python -m labguide.ui_probe --help
python -m labguide.platforms.macos.ax_probe --help
```

> **Status & next steps live in `PROGRESS.xml` and `docs/Desktop-App-Migration-Plan.md`.** Phase 2 (desktop app shell) is done and verified live; next is the Windows acceptance matrix, signing the MSI, and fleet/MDM rollout.

---

## 🆘 Something broke?

**Red banner "Capture service unavailable"?** `labguide-sidecar.exe` needs to sit next to `LabGuide.exe` — the installer does this. Try running it directly:

```powershell
'{"id":1,"method":"hello"}' | & "C:\Program Files\LabGuide\labguide-sidecar.exe"
```

If that prints JSON, the service is fine — restart LabGuide.

**"Backend unreachable"?** Check `base_url` in your toml and that the backend is up. Health check is `GET /v1/models`.

**Hotkey does nothing?** Another app owns `ctrl+shift+space` — change `global_hotkey` in your toml, or grant **Accessibility** permission on macOS (System Settings → Privacy & Security).

**Slow first capture?** The accessibility probe starts a helper process on first use (~1-2s). Subsequent captures are instant.

**macOS permission woes?** Screen Recording (for screenshots) + Accessibility (for hotkey & text) are per-terminal-app. Grant them to your Terminal, then restart it.

Still stuck? Open an issue or ping a TA with your `labguide.toml` (with the key redacted!) and the error text.

---

## 📄 License

MIT — see `LICENSE`.

*Built for Pratt labs, by Pratt labs. PRs welcome — especially from students who've actually had to fix the lab printer at 11pm.*
