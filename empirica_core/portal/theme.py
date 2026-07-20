"""Empirica Analytics brand system for the client portals.

The portals read as *Empirica software* (warm clay/cream/ink palette, Schibsted
Grotesk + JetBrains Mono, the Interval mark ``[ · ]``) with a per-client accent
and logo layered on top.
"""
from __future__ import annotations

from pathlib import Path

# --- Empirica palette (from the brand kit) ----------------------------------
CLAY = "#b5623f"      # primary accent
RED = "#bf4f45"
SIENNA = "#8f4a2b"
INK = "#211d16"       # body text / headings
INK_SOFT = "#5c5346"  # secondary text
PAPER = "#faf9f5"     # app background
CREAM = "#e9e0ce"     # panels / cards
LINE = "#e4dccb"      # hairline borders

# Back-compat aliases (older kit code referenced these names)
EMPIRICA_PRIMARY = CLAY
EMPIRICA_ACCENT = CLAY
EMPIRICA_INK = INK
EMPIRICA_MUTED = INK_SOFT
EMPIRICA_SURFACE = CREAM
EMPIRICA_BORDER = LINE

# Categorical chart palette — warm, brand-anchored, good adjacent contrast.
SERIES_PALETTE = [
    CLAY, "#8f4a2b", "#c99a3f", "#6b7f6a",
    RED, "#4f6d7a", "#a8894f", "#8a5a44",
]

# --- Type -------------------------------------------------------------------
FONT_DISPLAY = "'Schibsted Grotesk', system-ui, sans-serif"
FONT_MONO = "'JetBrains Mono', ui-monospace, monospace"
GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Schibsted+Grotesk:wght@400;500;600;700&"
    "family=JetBrains+Mono:wght@400;500&display=swap"
)

# --- Assets (bundled in the kit, vendored into every app) -------------------
ASSETS = Path(__file__).parent / "assets"
INTERVAL_MARK = ASSETS / "interval-clay.svg"
INTERVAL_MARK_BONE = ASSETS / "interval-bone.svg"
LOCKUP_LIGHT = ASSETS / "lockup-clay-light.png"

# --- Known client accents ---------------------------------------------------
CLIENT_THEMES: dict[str, dict] = {}


def _config_toml(primary: str) -> str:
    return f"""[theme]
primaryColor = "{primary}"
backgroundColor = "{PAPER}"
secondaryBackgroundColor = "{CREAM}"
textColor = "{INK}"
font = "sans serif"

[server]
headless = true
enableCORS = false
enableXsrfProtection = false

[client]
showSidebarNavigation = false
toolbarMode = "minimal"
"""


def render_config_toml(primary_color: str = CLAY) -> str:
    """Contents of a client ``.streamlit/config.toml`` (client accent + Empirica base)."""
    return _config_toml(primary_color)


__all__ = [
    "CLAY", "RED", "SIENNA", "INK", "INK_SOFT", "PAPER", "CREAM", "LINE",
    "EMPIRICA_PRIMARY", "EMPIRICA_ACCENT", "EMPIRICA_INK", "EMPIRICA_MUTED",
    "EMPIRICA_SURFACE", "EMPIRICA_BORDER", "SERIES_PALETTE",
    "FONT_DISPLAY", "FONT_MONO", "GOOGLE_FONTS",
    "ASSETS", "INTERVAL_MARK", "INTERVAL_MARK_BONE", "LOCKUP_LIGHT",
    "CLIENT_THEMES", "render_config_toml",
]
