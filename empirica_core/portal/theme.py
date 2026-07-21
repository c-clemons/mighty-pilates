"""Empirica Analytics brand system (light) for the client portals.

A warm, clean light system — off-white page, white cards, ink text, clay accent,
Schibsted Grotesk + JetBrains Mono, the Interval mark ``[ · ]`` — layered with a
per-client accent + logo. Tuned to read like the Themis portal: white cards on a
warm page, hairline borders, soft shadows, uppercase eyebrow labels.
"""
from __future__ import annotations

from pathlib import Path

# --- Empirica light palette --------------------------------------------------
PAPER = "#f6f4ef"      # app background (warm off-white)
WHITE = "#ffffff"      # cards / sidebar / raised surfaces
CREAM = "#efe9dd"      # soft secondary panel
INK = "#241f19"        # headings (near-black, warm)
INK_SOFT = "#5f564a"   # body text
MUTED = "#8c8272"      # secondary text
LABEL = "#9a907e"      # mono eyebrow labels
CLAY = "#b5623f"       # primary accent
CLAY_SOFT = "#bd6f49"  # hover / secondary accent
RED = "#bf4f45"
SIENNA = "#8f4a2b"
LINE = "#e8e2d6"       # hairline borders
LINE_SOFT = "#f0ebe1"
ACTIVE = "rgba(181,98,63,0.10)"   # active nav pill tint
SHADOW = "0 1px 2px rgba(36,31,25,0.04), 0 4px 16px rgba(36,31,25,0.05)"

# Back-compat aliases (older kit code)
BONE = INK             # headings alias (was bone on dark)
EMPIRICA_PRIMARY = CLAY
EMPIRICA_ACCENT = CLAY
EMPIRICA_INK = INK
EMPIRICA_MUTED = MUTED
EMPIRICA_SURFACE = WHITE
EMPIRICA_BORDER = LINE

# Chart series palette — the site's node-network colors (warm, muted, light-safe)
SERIES_PALETTE = [
    "#b5623f", "#7f8f5a", "#4f7d76", "#c09a4e",
    "#7d6a86", "#6b8250", "#a8542f", "#5f827c", "#a8894f",
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
INTERVAL_MARK = ASSETS / "interval-clay.svg"      # [ · ] on light
FAVICON = ASSETS / "favicon.png"

# --- Known client accents ---------------------------------------------------
CLIENT_THEMES: dict[str, dict] = {}


def _config_toml(primary: str) -> str:
    return f"""[theme]
base = "light"
primaryColor = "{primary}"
backgroundColor = "{PAPER}"
secondaryBackgroundColor = "{WHITE}"
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
    """Contents of a client ``.streamlit/config.toml`` (Empirica light base)."""
    return _config_toml(primary_color)


__all__ = [
    "PAPER", "WHITE", "CREAM", "INK", "INK_SOFT", "MUTED", "LABEL",
    "CLAY", "CLAY_SOFT", "RED", "SIENNA", "LINE", "LINE_SOFT", "ACTIVE",
    "SHADOW", "BONE",
    "EMPIRICA_PRIMARY", "EMPIRICA_ACCENT", "EMPIRICA_INK", "EMPIRICA_MUTED",
    "EMPIRICA_SURFACE", "EMPIRICA_BORDER", "SERIES_PALETTE",
    "FONT_DISPLAY", "FONT_MONO", "GOOGLE_FONTS",
    "ASSETS", "INTERVAL_MARK", "FAVICON", "CLIENT_THEMES", "render_config_toml",
]
