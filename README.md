# Pratt Lab Guide

Pratt Lab Guide is a lightweight Textual-based terminal UI for software troubleshooting on lab machines. It lets a user describe a problem, optionally capture the current screen, send the prompt and screenshot to an OpenAI-compatible vision backend, and get short troubleshooting guidance back in the terminal.

The current app is intentionally small and Windows-first. It is meant for internal testing, TA workflows, and validating the screenshot-plus-prompt support loop before investing in a desktop UI.

## Features

- Textual TUI with a conversation transcript and prompt input
- Optional screenshot capture on send with `Ctrl+S`
- Short multi-turn in-memory history
- OpenAI-compatible `/v1/chat/completions` backend integration
- Backend health check against `/v1/models` on startup
- Local JSONL session logging for latency and failures
- Configurable backend URL, model, timeouts, prompt, and capture quality

## Requirements

- Python 3.10+
- A local or network-accessible OpenAI-compatible backend
- A model that can accept image input when using screenshot capture
- Windows is the primary target for the current implementation

## Installation

### 1. Create and activate a virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install the project

```powershell
pip install -e .
```

## Configuration

The app reads configuration from `labguide.toml` by default. You can point it at a different file with the `LABGUIDE_CONFIG` environment variable.

This repository intentionally does not commit real credentials. Start from the example file:

```powershell
Copy-Item labguide.example.toml labguide.toml
```

You can either put an API key in the config file locally, or set it through `LABGUIDE_API_KEY`.

Example:

```toml
[backend]
base_url = "https://your-backend.example/v1"
chat_path = "/chat/completions"
models_path = "/models"
model = "your-vision-model"
api_key = ""
timeout_seconds = 30.0
temperature = 0.2
max_tokens = 500
system_prompt = "You are LabGuide, a concise troubleshooting assistant for software issues on lab computers. Use the screenshot and the user's message to explain what you see and provide short, numbered next steps."

[capture]
jpeg_quality = 80

[session]
max_history_turns = 6
log_path = "logs/labguide-session.jsonl"
```

## Running The App

After installation:

```powershell
labguide
```

Or:

```powershell
python -m labguide
```

## Controls

- `Enter`: send the typed message without a screenshot
- `Ctrl+S`: capture the primary display and send the message with the screenshot
- `Ctrl+C`: quit the app

## How It Works

1. The app starts and checks backend availability through `/v1/models`.
2. The user types a problem description.
3. On `Ctrl+S`, the app captures the primary display, compresses it to JPEG, and base64-encodes it.
4. The client sends the request to an OpenAI-compatible chat completions endpoint.
5. The response is rendered back into the transcript.
6. A JSONL log entry is optionally written locally with success, latency, and error metadata.

When no screenshot is attached, the user message is sent as plain text. When a screenshot is attached, the client sends a multimodal user message containing both text context and a `data:image/jpeg;base64,...` image URL payload.

## Backend Contract

The client expects an OpenAI-compatible backend.

### Health check

- `GET /v1/models`

### Chat request

- `POST /v1/chat/completions`

The client depends primarily on:

- `choices[0].message.content`

Additional fields like `id` and `model` are used only as informational metadata.

## Project Structure

```text
src/labguide/
  app.py            Textual UI and interaction flow
  client.py         Backend request and response handling
  capture.py        Primary display screenshot capture
  config.py         TOML and environment-based configuration loading
  models.py         Small dataclasses for request/session state
  session_log.py    Local JSONL session logging
docs/
  Backend-API-Spec.md
  Frontend-MVP-Tasks.md
labguide.example.toml
```

## Development Notes

- The repo ignores local secrets and runtime artifacts such as `.env`, `labguide.toml`, `.venv`, logs, and generated caches.
- `LabGuide-PRD.md` is kept out of version control for this repo snapshot.
- The title screen banner is currently hand-authored block text in `src/labguide/app.py`.

## Troubleshooting

### Backend unreachable on startup

- Verify `base_url`, `models_path`, and `chat_path`
- Confirm the backend is running and reachable from the current machine
- Check whether the configured model is listed by `/v1/models`

### Screenshot send fails

- Confirm the backend model supports image input
- Reduce `jpeg_quality` if payload size is a problem
- Try sending text-only first with `Enter`

### Authentication issues

- Set `backend.api_key` locally in `labguide.toml`, or use `LABGUIDE_API_KEY`
- Do not commit real keys into the repository

## License

MIT. See `LICENSE`.
