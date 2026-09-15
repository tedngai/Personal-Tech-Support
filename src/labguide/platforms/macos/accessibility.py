"""Parent-side runner for the macOS AX probe child process.

Mirrors run_ui_probe: a hung accessibility provider can block a thread
forever, so extraction runs in a child process with a parent-enforced hard
timeout.
"""

from __future__ import annotations

import json
import subprocess
import sys

from labguide.models import (
    UI_STATUS_FAILED,
    UI_STATUS_TIMED_OUT,
    UI_STATUS_UNSUPPORTED,
    TargetWindow,
    UISnapshot,
)
from labguide.ui_outline import redact_password_elements

_MAX_STDOUT_BYTES = 4 * 1024 * 1024


def run_ax_probe(
    target: TargetWindow,
    *,
    timeout_seconds: float,
    max_nodes: int,
    max_depth: int,
    include_offscreen: bool,
) -> UISnapshot:
    """Run the AX probe in a child process with a hard timeout."""
    if sys.platform != "darwin":
        return UISnapshot(status=UI_STATUS_UNSUPPORTED, warnings=["AX probe requires macOS"])

    command = [
        sys.executable,
        "-m",
        "labguide.platforms.macos.ax_probe",
        "--pid",
        str(target.pid),
        "--max-nodes",
        str(max_nodes),
        "--max-depth",
        str(max_depth),
    ]
    if target.window_title:
        command.extend(["--window-title", target.window_title])
    if include_offscreen:
        command.append("--include-offscreen")

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return UISnapshot(status=UI_STATUS_FAILED, warnings=[f"could not start probe: {exc}"])

    try:
        stdout, stderr = process.communicate(timeout=max(0.5, timeout_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=1.0)
        except Exception:
            pass
        return UISnapshot(
            status=UI_STATUS_TIMED_OUT,
            warnings=[f"AX probe exceeded {timeout_seconds:.1f}s and was terminated"],
        )

    if len(stdout) > _MAX_STDOUT_BYTES:
        return UISnapshot(status=UI_STATUS_FAILED, warnings=["AX probe output exceeded size limit"])

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        diagnostic = stderr.decode("utf-8", errors="replace").strip()[:300]
        warning = "AX probe returned unreadable output"
        if diagnostic:
            warning = f"{warning}: {diagnostic}"
        return UISnapshot(status=UI_STATUS_FAILED, warnings=[warning])

    if not isinstance(payload, dict):
        return UISnapshot(status=UI_STATUS_FAILED, warnings=["AX probe returned unexpected output"])

    return redact_password_elements(UISnapshot.from_dict(payload))
