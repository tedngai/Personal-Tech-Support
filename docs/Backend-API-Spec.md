# LabGuide MVP OpenAI-Compatible API Specification

## Purpose

This document defines the direct API contract used by the LabGuide TUI after the frontend refactor to standard OpenAI-compatible endpoints.

The frontend now talks directly to an OpenAI-style multimodal API instead of a custom `/analyze` wrapper.

## Design Decisions

- Use OpenAI-compatible `chat/completions` because it is broadly supported by `vllm` and similar local servers
- Use `models` as a lightweight startup reachability check
- Keep LabGuide-specific logic in the client prompt formatting, not in a custom backend envelope

## Base URL

Configured locally by the TUI client.

Example:

```text
http://127.0.0.1:8000/v1
```

## Authentication

- If an API key is configured, the client sends:

```text
Authorization: Bearer <api-key>
```

- If no API key is configured, the client sends no `Authorization` header.

This supports both locked-down OpenAI-style services and unsecured local development servers.

## Endpoints

### `GET /v1/models`

Used by the TUI on startup to verify that the backend is reachable.

### Example response

```json
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2.5-VL-7B-Instruct",
      "object": "model",
      "owned_by": "vllm"
    }
  ]
}
```

### Frontend behavior

- Any `2xx` response means the backend is reachable.
- If the configured model is not listed, the TUI should warn but remain usable.

### `POST /v1/chat/completions`

Used for screenshot-plus-text troubleshooting requests.

## Request Schema

```json
{
  "model": "Qwen/Qwen2.5-VL-7B-Instruct",
  "messages": [
    {
      "role": "system",
      "content": "You are LabGuide, a concise troubleshooting assistant for software issues on lab computers. Use the screenshot and the user's message to explain what you see and provide short, numbered next steps."
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "The attached screenshot shows the user's current screen.\nOperating system: windows\nScreen resolution: 1920x1080\nCaptured at: 2026-05-13T14:05:00+00:00\nUser request:\nThe printer says it is offline."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,<base64-jpeg>"
          }
        }
      ]
    }
  ],
  "temperature": 0.2,
  "max_tokens": 500
}
```

## Field Definitions

### `model`
- Type: string
- Required: yes
- Meaning: model identifier exposed by the OpenAI-compatible server

### `messages`
- Type: array
- Required: yes
- Meaning: standard chat message list

### `messages[*].role`
- Type: string
- Allowed values used by LabGuide: `system`, `user`, `assistant`

### `messages[*].content`
- Type: string or array
- LabGuide uses:
  - plain string content for historical text-only messages
  - multimodal array content for the latest user request

### Latest user message structure

LabGuide sends the newest user turn as multimodal content:

- one `text` item containing:
  - operating system
  - screen resolution
  - capture timestamp
  - latest user request
- one `image_url` item containing a base64 data URL for the JPEG screenshot

### `temperature`
- Type: number
- Required: no

### `max_tokens`
- Type: integer
- Required: no

## Success Response Schema

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1715600000,
  "model": "Qwen/Qwen2.5-VL-7B-Instruct",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "I can see the printer status window. Try these steps: 1. Open Services. 2. Restart Print Spooler. 3. Recheck the printer status."
      },
      "finish_reason": "stop"
    }
  ]
}
```

## Required Success Data

The LabGuide client requires only:

- `choices[0].message.content`

The client also reads these fields when present:

- `id`
- `model`

## Error Response Schema

OpenAI-style services commonly return errors like:

```json
{
  "error": {
    "message": "The model `Qwen/Qwen2.5-VL-7B-Instruct` does not exist.",
    "type": "invalid_request_error"
  }
}
```

The client should surface `error.message` when available.

## Recommended Status Codes

- `200 OK`: request succeeded
- `400 Bad Request`: malformed request body
- `401 Unauthorized`: invalid or missing API key
- `404 Not Found`: wrong endpoint or model path
- `413 Payload Too Large`: screenshot too large
- `422 Unprocessable Entity`: structurally valid request with invalid field contents
- `500 Internal Server Error`: backend inference failure
- `503 Service Unavailable`: backend overloaded or unavailable

## Client Mapping Rules

LabGuide transforms its local state into standard OpenAI-compatible messages as follows:

- configured system prompt becomes the first `system` message
- prior conversation turns become plain text `user` and `assistant` messages
- the newest user turn becomes a multimodal `user` message with text plus image

## Compatibility Notes

This format is intended to work with:

- local `vllm` OpenAI-compatible servers
- OpenAI-style self-hosted gateways
- other providers exposing compatible `chat/completions` multimodal behavior

Some servers may differ slightly in image support details. The client currently assumes `image_url` with a `data:image/jpeg;base64,...` URL.
