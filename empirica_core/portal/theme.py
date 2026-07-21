"""Empirica Analytics brand system (dark) for the client portals.

Matches the empirica-analytics.com site: ink background, cream/bone text, clay
accents, Schibsted Grotesk + JetBrains Mono, the Interval mark ``[ · ]``. Each
portal layers on a client accent + logo.
"""
from __future__ import annotations

from pathlib import Path

# --- Empirica dark palette (from the marketing site) ------------------------
INK = "#211d16"        # app background
PANEL = "#2a2620"      # cards / sidebar / raised surfaces
BONE = "#faf6ef"       # headings
CREAM = "#e6ddcc"      # body text
MUTED = "#b3a998"      # secondary text
LABEL = "#9a8f79"      # mono labels
CLAY = "#b5623f"       # primary accent
CLAY_SOFT = "#cd7f57"  # accent on dark (links, active, mono labels)
RED = "#bf4f45"
SIENNA = "#8f4a2b"
LINE = "rgba(255,255,255,0.10)"      # hairline borders
LINE_SOFT = "rgba(255,255,255,0.07)"

# Back-compat aliases (older kit code)
PAPER = INK
EMPIRICA_PRIMARY = CLAY
EMPIRICA_ACCENT = CLAY
EMPIRICA_INK = CREAM
EMPIRICA_MUTED = MUTED
EMPIRICA_SURFACE = PANEL
EMPIRICA_BORDER = LINE

# Chart series palette — the site's node-network colors (warm, muted, dark-safe)
SERIES_PALETTE = [
    "#cd7f57", "#9eb078", "#608c86", "#c6a86e",
    "#968096", "#809260", "#c46e48", "#789892", "#bc9e66",
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
INTERVAL_MARK = ASSETS / "interval-clay.svg"      # transparent [ · ] (works on dark)
FAVICON = ASSETS / "favicon.png"

# --- Known client accents ---------------------------------------------------
CLIENT_THEMES: dict[str, dict] = {}


def _config_toml(primary: str) -> str:
    return f"""[theme]
base = "dark"
primaryColor = "{primary}"
backgroundColor = "{INK}"
secondaryBackgroundColor = "{PANEL}"
textColor = "{CREAM}"
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
    """Contents of a client ``.streamlit/config.toml`` (Empirica dark base)."""
    return _config_toml(primary_color)


__all__ = [
    "INK", "PANEL", "BONE", "CREAM", "MUTED", "LABEL", "CLAY", "CLAY_SOFT",
    "RED", "SIENNA", "LINE", "LINE_SOFT", "PAPER",
    "EMPIRICA_PRIMARY", "EMPIRICA_ACCENT", "EMPIRICA_INK", "EMPIRICA_MUTED",
    "EMPIRICA_SURFACE", "EMPIRICA_BORDER", "SERIES_PALETTE",
    "FONT_DISPLAY", "FONT_MONO", "GOOGLE_FONTS",
    "ASSETS", "INTERVAL_MARK", "FAVICON", "CLIENT_THEMES", "render_config_toml",
]
