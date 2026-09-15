"""macOS permission checks (TCC).

Screen Recording and Accessibility are separate permissions. Neither blocks
import; checks run at capture time so failures become readable statuses.
"""

from __future__ import annotations


def screen_capture_granted() -> bool:
    try:
        from Quartz import CGPreflightScreenCaptureAccess
    except ImportError:
        return False
    try:
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return False


def request_screen_capture() -> bool:
    """Trigger the system prompt. First grant may require an app relaunch."""
    try:
        from Quartz import CGRequestScreenCaptureAccess
    except ImportError:
        return False
    try:
        return bool(CGRequestScreenCaptureAccess())
    except Exception:
        return False


def accessibility_granted() -> bool:
    try:
        from ApplicationServices import AXIsProcessTrusted
    except ImportError:
        return False
    try:
        return bool(AXIsProcessTrusted())
    except Exception:
        return False
