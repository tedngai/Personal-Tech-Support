from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Message:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class ScreenContext:
    os_name: str
    screen_width: int
    screen_height: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os_name,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class CapturedScreenshot:
    image_base64: str
    context: ScreenContext
    byte_count: int


@dataclass(slots=True)
class AnalyzeResult:
    answer: str
    model: str | None = None
    latency_ms: int | None = None
    confidence: float | None = None
    request_id: str | None = None


@dataclass(slots=True)
class HealthResult:
    reachable: bool
    service: str | None = None
    model: str | None = None
    detail: str | None = None
