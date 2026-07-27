from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass(slots=True)
class SessionLogEntry:
    """Operational metadata only.

    Never put screenshots, base64 images, UI text, field values, document
    text, window titles, or canonical UI JSON in this entry.
    """

    message: str
    success: bool
    latency_ms: int | None
    backend_url: str
    model: str | None = None
    confidence: float | None = None
    error: str | None = None
    capture_kind: str | None = None
    target_app: str | None = None
    ui_status: str | None = None
    ui_node_count: int | None = None
    ui_truncated: bool | None = None


class SessionLogger:
    def __init__(self, log_path: str | None) -> None:
        self._path = Path(log_path) if log_path else None

    def write(self, entry: SessionLogEntry) -> None:
        if self._path is None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **asdict(entry),
        }
        with self._path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload) + "\n")
