"""Generate golden IPC fixtures from the Python sidecar's contract tests.

Run from the repo root after any IPC contract change:

    .venv/Scripts/python scripts/generate_ipc_fixtures.py

The fixtures (desktop/src/ipc/fixtures/*.json) are the shared contract the
TypeScript client is tested against in vitest, keeping both sides honest
without CI needing to run Python. Fixture names describe the scenario; the
contents are real service responses, produced by the same fakes the Python
contract tests use.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_service import FakeAdapter, FakeBackend, make_service  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "desktop" / "src" / "ipc" / "fixtures"


def generate() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # hello + permissions: a fresh service with the fake adapter.
    adapter = FakeAdapter()
    service, _ = make_service(adapter)
    fixtures: dict[str, dict] = {}

    def call(name: str, request_id, method: str, params: dict | None = None) -> dict:
        line = json.dumps({"id": request_id, "method": method, "params": params or {}})
        service.post_line(line)
        service.pump(timeout=2.0)
        for payload in _output(service):
            if payload.get("id") == request_id:
                fixtures[name] = payload
                return payload
        raise RuntimeError(f"no response for {method}")

    call("hello", 1, "hello")
    call("health-check", 2, "health.check")
    call("permissions-status", 3, "permissions.status")
    call("attachment-get-empty", 4, "attachment.get")
    call("unknown-method", 5, "nope")

    # capture + attachment: fresh service with a gated probe so fixtures are
    # deterministic — capture-start shows ui "pending", then "complete".
    adapter = FakeAdapter()
    adapter.probe_gate = threading.Event()
    service, _ = make_service(adapter)
    call("capture-start", 5, "capture.start")
    adapter.probe_gate.set()
    time.sleep(0.5)
    call("attachment-get", 6, "attachment.get")

    # window-identity failure on a fresh capture attempt.
    adapter2 = FakeAdapter()
    adapter2.freeze_error = WindowIdentityErrorShim
    service, _ = make_service(adapter2)
    call("window-identity-error", 8, "capture.start")

    # backend failure on submit.
    backend = FakeBackend()
    backend.error = BackendErrorShim("backend returned HTTP 502")
    service, _ = make_service(FakeAdapter(), backend)
    call("backend-error", 9, "submit", {"prompt": "hello"})

    for name, payload in fixtures.items():
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def _output(service) -> list[dict]:
    raw = service._writer.getvalue()  # noqa: SLF001 - fixture harness
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


# Import after sys.path setup; these are the contract-test exception types.
from labguide.models import WindowIdentityError  # noqa: E402

WindowIdentityErrorShim = WindowIdentityError("closed")

from labguide.client import BackendError  # noqa: E402

BackendErrorShim = BackendError


if __name__ == "__main__":
    generate()
