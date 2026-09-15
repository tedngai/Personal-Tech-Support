from __future__ import annotations

import gzip
import json
from typing import Any
from time import perf_counter

import httpx

from labguide.config import BackendConfig
from labguide.models import AnalyzeResult, CapturedScreenshot, HealthResult, Message
from labguide.ui_outline import render_ui_outline


class BackendError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config

    async def health_check(self) -> HealthResult:
        url = f"{self._config.base_url.rstrip('/')}{self._config.models_path}"
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                status, reason, raw = await _send(
                    client, "GET", url, self._headers(), None, self._config.max_response_bytes
                )
        except httpx.HTTPError as exc:
            return HealthResult(reachable=False, detail=str(exc))
        except BackendError as exc:
            return HealthResult(reachable=False, detail=str(exc))

        if status >= 400:
            return HealthResult(
                reachable=False,
                detail=_extract_error_message(status, reason, _decode_body(raw)),
            )
        try:
            payload = json.loads(_decode_body(raw)) if raw else {}
        except ValueError:
            payload = {}

        model_ids = {
            item.get("id")
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        }
        detail = None
        if model_ids and self._config.model not in model_ids:
            detail = f"Configured model '{self._config.model}' was not listed by /models."
        return HealthResult(
            reachable=True,
            service="openai-compatible",
            model=self._config.model,
            detail=detail,
        )

    async def analyze(
        self,
        message: str,
        screenshot: CapturedScreenshot | None,
        history: list[Message],
        ui_max_text_chars: int = 10000,
    ) -> AnalyzeResult:
        url = f"{self._config.base_url.rstrip('/')}{self._config.chat_path}"
        payload = {
            "model": self._config.model,
            "messages": _build_messages(
                system_prompt=self._config.system_prompt,
                latest_message=message,
                screenshot=screenshot,
                history=history,
                ui_max_text_chars=ui_max_text_chars,
            ),
        }
        if self._config.max_tokens is not None:
            payload["max_tokens"] = self._config.max_tokens
        payload["temperature"] = self._config.temperature

        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                status, reason, raw = await _send(
                    client, "POST", url, self._headers(), payload, self._config.max_response_bytes
                )
        except httpx.HTTPError as exc:
            raise BackendError(str(exc)) from exc

        if status >= 400:
            raise BackendError(_extract_error_message(status, reason, _decode_body(raw)))
        try:
            payload = json.loads(_decode_body(raw))
        except ValueError:
            raise BackendError(f"Backend returned HTTP {status} with unreadable JSON.") from None

        answer = _extract_answer(payload)
        if not answer:
            raise BackendError("Backend response did not include assistant message content.")

        elapsed_ms = int((perf_counter() - started) * 1000)
        return AnalyzeResult(
            answer=answer,
            model=payload.get("model"),
            latency_ms=elapsed_ms,
            confidence=None,
            request_id=payload.get("id"),
        )

    def _headers(self) -> dict[str, str]:
        # Some gateways mislabel Content-Encoding; asking for identity keeps
        # responses readable, and _decode_body sniffs gzip as a fallback.
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None,
    max_response_bytes: int = 8_000_000,
) -> tuple[int, str, bytes]:
    """Send one request and return (status, reason phrase, raw body).

    Reads the raw stream so a mislabeled Content-Encoding can never crash
    httpx's automatic decoder. The body is bounded by max_response_bytes.
    """
    async with client.stream(method, url, json=json_payload, headers=headers) as response:
        chunks: list[bytes] = []
        total = 0
        async for part in response.aiter_raw():
            total += len(part)
            if max_response_bytes > 0 and total > max_response_bytes:
                raise BackendError(
                    f"Backend response exceeded the {max_response_bytes}-byte limit."
                )
            chunks.append(part)
        return response.status_code, response.reason_phrase, b"".join(chunks)


def _decode_body(raw: bytes) -> str:
    """Decode a response body by content sniffing, not by header trust."""
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw).decode("utf-8", errors="replace")
        except OSError:
            pass
    return raw.decode("utf-8", errors="replace")


def _extract_error_message(status_code: int, reason: str, body_text: str) -> str:
    fallback = f"Backend returned HTTP {status_code} {reason}.".strip()
    try:
        payload = json.loads(body_text)
    except ValueError:
        return fallback

    detail = payload.get("detail")
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        error_type = error.get("type")
        if message and error_type:
            return f"{error_type}: {message}"
        if message:
            return str(message)
    if detail and error:
        return f"{error}: {detail}"
    if detail:
        return str(detail)
    if error:
        return str(error)
    return fallback


def _build_messages(
    system_prompt: str,
    latest_message: str,
    screenshot: CapturedScreenshot | None,
    history: list[Message],
    ui_max_text_chars: int = 10000,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})

    for entry in history:
        messages.append(entry.to_dict())

    if screenshot is None:
        messages.append({"role": "user", "content": latest_message})
    else:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _build_user_prompt(latest_message, screenshot, ui_max_text_chars),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot.image_base64}"
                        },
                    },
                ],
            }
        )
    return messages


def _build_user_prompt(
    message: str, screenshot: CapturedScreenshot, ui_max_text_chars: int = 10000
) -> str:
    context = screenshot.context
    if screenshot.target is not None and screenshot.ui is not None:
        # Enriched window capture: one compact accessibility outline plus the
        # image. Canonical UI JSON is never embedded alongside the outline.
        outline = render_ui_outline(screenshot.ui, screenshot.target, ui_max_text_chars)
        return "\n".join(
            [
                outline,
                "",
                "The attached screenshot shows this captured window.",
                f"Captured at: {context.timestamp}",
                "",
                "User request:",
                message,
            ]
        )
    return "\n".join(
        [
            "The attached screenshot shows the user's current screen.",
            f"Operating system: {context.os_name}",
            f"Screen resolution: {context.screen_width}x{context.screen_height}",
            f"Captured at: {context.timestamp}",
            "User request:",
            message,
        ]
    )


def _extract_answer(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    combined = "\n".join(part.strip() for part in parts if part.strip())
    return combined or None
