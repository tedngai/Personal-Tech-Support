from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path("labguide.toml")


@dataclass(slots=True)
class BackendConfig:
    base_url: str = "http://127.0.0.1:8000/v1"
    chat_path: str = "/chat/completions"
    models_path: str = "/models"
    model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    api_key: str | None = None
    timeout_seconds: float = 30.0
    temperature: float = 0.2
    max_tokens: int | None = 500
    system_prompt: str = (
        "You are LabGuide, a concise troubleshooting assistant for software issues on lab computers. "
        "Use the screenshot and the user's message to explain what you see and provide short, numbered next steps."
    )


@dataclass(slots=True)
class CaptureConfig:
    jpeg_quality: int = 80


@dataclass(slots=True)
class SessionConfig:
    max_history_turns: int = 6
    log_path: str | None = "logs/labguide-session.jsonl"


@dataclass(slots=True)
class AppConfig:
    backend: BackendConfig
    capture: CaptureConfig
    session: SessionConfig


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or Path(os.environ.get("LABGUIDE_CONFIG", DEFAULT_CONFIG_PATH))
    raw = _read_toml(path) if path.exists() else {}
    backend_defaults = BackendConfig()
    capture_defaults = CaptureConfig()
    session_defaults = SessionConfig()

    backend = raw.get("backend", {})
    capture = raw.get("capture", {})
    session = raw.get("session", {})

    return AppConfig(
        backend=BackendConfig(
            base_url=backend.get("base_url", backend_defaults.base_url),
            chat_path=backend.get("chat_path", backend_defaults.chat_path),
            models_path=backend.get("models_path", backend_defaults.models_path),
            model=backend.get("model", backend_defaults.model),
            api_key=_read_api_key(backend),
            timeout_seconds=float(backend.get("timeout_seconds", backend_defaults.timeout_seconds)),
            temperature=float(backend.get("temperature", backend_defaults.temperature)),
            max_tokens=_read_max_tokens(backend),
            system_prompt=backend.get("system_prompt", backend_defaults.system_prompt),
        ),
        capture=CaptureConfig(
            jpeg_quality=int(capture.get("jpeg_quality", capture_defaults.jpeg_quality))
        ),
        session=SessionConfig(
            max_history_turns=int(session.get("max_history_turns", session_defaults.max_history_turns)),
            log_path=session.get("log_path", session_defaults.log_path),
        ),
    )


def _read_toml(path: Path) -> dict:
    with path.open("rb") as file_handle:
        return tomllib.load(file_handle)


def _read_api_key(backend: dict) -> str | None:
    configured = backend.get("api_key")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()

    environment_value = os.environ.get("LABGUIDE_API_KEY")
    return environment_value.strip() if environment_value else None


def _read_max_tokens(backend: dict) -> int | None:
    value = backend.get("max_tokens", BackendConfig().max_tokens)
    if value in (None, ""):
        return None
    return int(value)
