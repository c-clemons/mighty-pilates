"""Streamlit page chrome: page config, brand CSS, and hiding the Streamlit UI.

The "professionalize" layer. ``configure_page`` must run before any other
Streamlit call; ``inject_brand_css`` restyles metric cards and (by default)
hides the hamburger menu / footer / toolbar so a client portal doesn't look
like a dev tool.
"""
from __future__ import annotations

from typing import Optional

from empirica_core.portal import theme


def configure_page(
    title: str,
    *,
    icon: Optional[str] = None,
    layout: str = "wide",
    sidebar: str = "expanded",
) -> None:
    """Call ``st.set_page_config`` — must be the first Streamlit call."""
    import streamlit as st

    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout=layout,
        initial_sidebar_state=sidebar,
    )


def hide_streamlit_chrome() -> None:
    """Hide the hamburger menu, footer, and top toolbar (Deploy button)."""
    import streamlit as st

    st.markdown(
        """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;}
        [data-testid="stDecoration"] {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_brand_css(
    primary_color: str = theme.EMPIRICA_PRIMARY,
    *,
    hide_chrome: bool = True,
) -> None:
    """Inject the shared metric-card / header styling and brand accents.

    Set ``hide_chrome=False`` to keep Streamlit's menu/footer visible (useful
    in local dev).
    """
    import streamlit as st

    if hide_chrome:
        hide_streamlit_chrome()

    st.markdown(
        f"""
        <style>
        .main-header {{font-size: 1.8rem; font-weight: 700; margin-bottom: 0.3rem;}}
        .sub-header {{font-size: 1rem; color: {theme.EMPIRICA_MUTED}; margin-bottom: 1.5rem;}}
        div[data-testid="stMetric"] {{
            background-color: {theme.EMPIRICA_SURFACE};
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid {theme.EMPIRICA_BORDER};
        }}
        div[data-testid="stMetric"] label {{ color: {theme.EMPIRICA_MUTED}; }}
        a {{ color: {primary_color}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


__all__ = ["configure_page", "hide_streamlit_chrome", "inject_brand_css"]
