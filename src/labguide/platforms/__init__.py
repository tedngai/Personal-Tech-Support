"""Platform adapter selection.

Only the adapter for the current operating system is imported, so macOS-only
(PyObjC) and Windows-only (uiautomation) dependencies never load elsewhere.
"""

from __future__ import annotations

import sys

from labguide.platforms.contracts import (
    PlatformAdapter,
    PlatformCapabilities,
    UnsupportedAdapter,
)

__all__ = ["get_adapter", "PlatformAdapter", "PlatformCapabilities", "UnsupportedAdapter"]


def get_adapter(platform_name: str | None = None) -> PlatformAdapter:
    """Return the adapter for platform_name (defaults to sys.platform)."""
    name = platform_name if platform_name is not None else sys.platform
    if name == "win32":
        from labguide.platforms.windows.adapter import WindowsAdapter

        return WindowsAdapter()
    if name == "darwin":
        from labguide.platforms.macos.adapter import MacOSAdapter

        return MacOSAdapter()
    return UnsupportedAdapter()
