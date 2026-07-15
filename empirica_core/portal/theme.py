"""Empirica brand tokens + per-client Streamlit theming.

The ``.streamlit/config.toml`` in each client repo is the source of truth for
that client's ``primaryColor``. Use :func:`render_config_toml` to generate a
consistent config, and :data:`CLIENT_THEMES` as the registry of known clients.
"""
from __future__ import annotations

# --- Empirica brand palette -------------------------------------------------
# Neutral, professional defaults. A client override only needs to change the
# primary/accent; everything else stays consistent across the practice.
EMPIRICA_PRIMARY = "#1B2A4A"   # deep navy — Empirica house color
EMPIRICA_ACCENT = "#3498DB"    # supporting blue for chart series / links
EMPIRICA_INK = "#262730"       # body text
EMPIRICA_MUTED = "#6b7280"     # captions / secondary text
EMPIRICA_SURFACE = "#f8f9fa"   # KPI card / panel background
EMPIRICA_BORDER = "#e9ecef"    # hairline borders

# Categorical series palette for charts (swap per the `dataviz` skill if a
# client needs brand-matched series). Ordered for good adjacent contrast.
SERIES_PALETTE = [
    "#1B2A4A", "#3498DB", "#16A34A", "#D97706",
    "#9333EA", "#DC2626", "#0891B2", "#65A30D",
]

# --- Client theme registry --------------------------------------------------
# Optional {slug: {"name": display_name, "primary": config.toml primaryColor}}.
# Kept empty here so the shared kit carries no client identifiers; each client
# repo passes its own primary_color to run_app / config.toml. Populate a local
# copy if you want a central lookup.
CLIENT_THEMES: dict[str, dict] = {}

_CONFIG_TOML = """[theme]
primaryColor = "{primary}"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
font = "sans serif"

[server]
headless = true
enableCORS = false
enableXsrfProtection = false

[client]
showSidebarNavigation = false
toolbarMode = "minimal"
"""


def render_config_toml(primary_color: str = EMPIRICA_PRIMARY) -> str:
    """Return the contents of a client ``.streamlit/config.toml``."""
    return _CONFIG_TOML.format(primary=primary_color)


__all__ = [
    "EMPIRICA_PRIMARY", "EMPIRICA_ACCENT", "EMPIRICA_INK", "EMPIRICA_MUTED",
    "EMPIRICA_SURFACE", "EMPIRICA_BORDER", "SERIES_PALETTE",
    "CLIENT_THEMES", "render_config_toml",
]
