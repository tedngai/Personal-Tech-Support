"""Color token definitions for the LabGuide TUI.

All literal colors live here as a single Textual theme. Stylesheets and
widgets must reference only the generated ``$...`` CSS variables so the
palette can be swapped or extended in one place.
"""

from __future__ import annotations

from textual.theme import Theme

THEME_NAME = "labguide-dark"


def labguide_theme() -> Theme:
    """The default dark theme: near-black surface, terracotta brand accent."""
    return Theme(
        name=THEME_NAME,
        primary="#d28d6d",
        secondary="#5c9cf5",
        accent="#9d7cd8",
        success="#7fd88f",
        warning="#e5c07b",
        error="#f44747",
        foreground="#d4d4d4",
        background="#0d0d0d",
        surface="#161616",
        panel="#1f1f1f",
        dark=True,
        variables={
            # Transcript text colors per role.
            "msg-user": "#e8e8e8",
            "msg-assistant": "#d4d4d4",
            "msg-capture": "#7a7a7a",
            "msg-system": "#8a8a8a",
            # Left border bars per role (claudechic-style content coding).
            "bar-user": "#cc7700",
            "bar-assistant": "#334455",
            "bar-capture": "#2e2e2e",
            "bar-system": "#232323",
            "bar-error": "#7a2d2d",
            # Chrome.
            "muted": "#8a8a8a",
            "faint": "#4d4d4d",
            "rule": "#1d1d1d",
            "prompt-background": "#141414",
            "prompt-border": "#333333",
            "prompt-border-focus": "#5a5a5a",
        },
    )
