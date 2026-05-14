from __future__ import annotations

from typing import Any
from time import perf_counter

import httpx

from labguide.config import BackendConfig
from labguide.models import AnalyzeResult, CapturedScreenshot, HealthResult, Message


class BackendError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config

    async def health_check(self) -> HealthResult:
        url = f"{self._config.base_url.rstrip('/')}{self._config.models_path}"
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return HealthResult(reachable=False, detail=str(exc))

        payload = response.json() if response.content else {}
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
    ) -> AnalyzeResult:
        url = f"{self._config.base_url.rstrip('/')}{self._config.chat_path}"
        payload = {
            "model": self._config.model,
            "messages": _build_messages(
                system_prompt=self._config.system_prompt,
                latest_message=message,
                screenshot=screenshot,
                history=history,
            ),
        }
        if self._config.max_tokens is not None:
            payload["max_tokens"] = self._config.max_tokens
        payload["temperature"] = self._config.temperature

        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BackendError(_extract_error_message(exc.response)) from exc
        except httpx.HTTPError as exc:
            raise BackendError(str(exc)) from exc

        payload = response.json()
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
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Backend returned HTTP {response.status_code}."

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
    return f"Backend returned HTTP {response.status_code}."


def _build_messages(
    system_prompt: str,
    latest_message: str,
    screenshot: CapturedScreenshot | None,
    history: list[Message],
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
                        "text": _build_user_prompt(latest_message, screenshot),
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


def _build_user_prompt(message: str, screenshot: CapturedScreenshot) -> str:
    context = screenshot.context
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
