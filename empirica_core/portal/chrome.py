"""Streamlit page chrome — the Empirica look, applied to every client portal.

``configure_page`` runs first; ``inject_brand_css`` applies the Empirica design
system (fonts, clay/cream/ink palette, hidden Streamlit UI); ``render_brand`` and
``render_footer`` place the Empirica lockup + the client's logo.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from empirica_core.portal import theme


def configure_page(title: str, *, icon: Optional[str] = None,
                   layout: str = "wide", sidebar: str = "expanded") -> None:
    import streamlit as st
    st.set_page_config(page_title=title, page_icon=icon, layout=layout,
                       initial_sidebar_state=sidebar)


def data_uri(path) -> Optional[str]:
    """Base64 ``data:`` URI for an svg/png asset, or None if missing."""
    p = Path(path)
    if not p.exists():
        return None
    mime = "image/svg+xml" if p.suffix.lower() == ".svg" else f"image/{p.suffix.lower().lstrip('.')}"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def hide_streamlit_chrome() -> None:
    import streamlit as st
    st.markdown(
        """<style>
        #MainMenu{visibility:hidden;} footer{visibility:hidden;}
        [data-testid="stToolbar"]{visibility:hidden;}
        [data-testid="stDecoration"]{display:none;}
        [data-testid="stStatusWidget"]{display:none;}
        </style>""",
        unsafe_allow_html=True,
    )


def inject_brand_css(accent_color: str = theme.CLAY, *, hide_chrome: bool = True) -> None:
    """Apply the Empirica design system. ``accent_color`` is the client accent
    used for small per-client touches; Empirica clay drives interactive states."""
    import streamlit as st
    if hide_chrome:
        hide_streamlit_chrome()

    t = theme
    st.markdown(
        f"""
        <style>
        @import url('{t.GOOGLE_FONTS}');

        :root {{ --clay:{t.CLAY}; --ink:{t.INK}; --ink-soft:{t.INK_SOFT};
                 --paper:{t.PAPER}; --cream:{t.CREAM}; --line:{t.LINE};
                 --accent:{accent_color}; }}

        .stApp {{ background:{t.PAPER}; color:{t.INK};
                  font-family:{t.FONT_DISPLAY}; }}
        [data-testid="stHeader"] {{ background:transparent; }}
        .block-container {{ padding-top:2.4rem; }}
        [data-testid="stSidebar"] {{ background:{t.CREAM};
                  border-right:1px solid {t.LINE}; }}

        h1,h2,h3,h4,h5 {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
                  color:{t.INK}; letter-spacing:-0.01em; }}
        h1 {{ font-weight:700; }}
        .stApp, p, li, label, .stMarkdown {{ color:{t.INK}; }}
        a {{ color:{t.CLAY}; text-decoration:none; }}
        a:hover {{ text-decoration:underline; }}

        /* mono for captions / small labels */
        [data-testid="stCaptionContainer"], .stCaption,
        [data-testid="stMetricLabel"] {{
            font-family:{t.FONT_MONO}; letter-spacing:.02em;
            text-transform:uppercase; font-size:.68rem; color:{t.INK_SOFT}; }}

        /* KPI cards */
        div[data-testid="stMetric"] {{
            background:{t.PAPER}; padding:14px 16px; border-radius:10px;
            border:1px solid {t.LINE}; box-shadow:0 1px 0 rgba(33,29,22,.03); }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
            font-family:{t.FONT_DISPLAY}; font-weight:700; color:{t.INK}; }}

        /* primary buttons -> Empirica clay */
        .stButton>button[kind="primary"], .stDownloadButton>button {{
            background:{t.CLAY}; border:1px solid {t.CLAY}; color:{t.PAPER}; }}
        .stButton>button[kind="primary"]:hover {{ background:{t.SIENNA};
            border-color:{t.SIENNA}; }}
        .stButton>button {{ border-radius:8px; }}

        /* sidebar nav radio -> pill list */
        [data-testid="stSidebar"] [role="radiogroup"] label {{
            padding:6px 10px; border-radius:7px; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
            background:rgba(181,98,63,.08); }}

        /* tabs + accents */
        .stTabs [aria-selected="true"] {{ color:{t.CLAY}; }}
        [data-testid="stSidebar"] hr {{ border-color:{t.LINE}; }}

        /* thin client-accent rule under the brand block */
        .emp-accent {{ height:3px; background:{accent_color}; border-radius:2px;
            margin:2px 0 10px; }}
        .emp-footer {{ font-family:{t.FONT_MONO}; font-size:.62rem;
            color:{t.INK_SOFT}; text-transform:uppercase; letter-spacing:.04em;
            display:flex; align-items:center; gap:6px; margin-top:4px; }}
        .emp-client-name {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
            font-size:1.05rem; color:{t.INK}; }}

        /* legacy page classes (Alma/CNS), restyled to Empirica */
        .main-header {{ font-family:{t.FONT_DISPLAY}; font-weight:700;
            font-size:1.9rem; color:{t.INK}; margin-bottom:.15rem; }}
        .sub-header {{ color:{t.INK_SOFT}; font-size:1rem; margin-bottom:1.1rem; }}
        .metric-card {{ background:{t.PAPER}; border:1px solid {t.LINE};
            border-left:4px solid var(--accent); border-radius:10px;
            padding:1rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand(container, *, client_logo=None, client_name: str = "",
                 accent_color: str = theme.CLAY, logo_bg: Optional[str] = None) -> None:
    """Empirica lockup (transparent mark + wordmark) + the client's logo.

    ``logo_bg`` places the client logo on a colored plate — use it for logos
    designed for dark backgrounds (e.g. gold/cream marks) so they don't wash out.
    """
    t = theme
    mark = data_uri(t.INTERVAL_MARK)          # transparent SVG [ · ]
    logo = data_uri(client_logo) if client_logo else None

    html = "<div style='padding:6px 0 2px;'>"
    # Empirica lockup — transparent mark + text wordmark (no image background)
    if mark:
        html += (
            "<div style='display:flex;align-items:center;gap:7px;margin-bottom:14px;'>"
            f"<img src='{mark}' style='height:22px;'/>"
            f"<span style='font-family:{t.FONT_DISPLAY};font-weight:600;font-size:1rem;"
            f"color:{t.INK};letter-spacing:.01em;'>empirica</span></div>"
        )
    # Client logo
    if logo:
        if logo_bg:
            html += (f"<div style='background:{logo_bg};border-radius:8px;padding:9px 12px;"
                     f"display:inline-block;margin-bottom:7px;'>"
                     f"<img src='{logo}' style='max-height:32px;max-width:158px;display:block;'/></div>")
        else:
            html += (f"<img src='{logo}' style='max-height:40px;max-width:180px;"
                     f"display:block;margin-bottom:7px;'/>")
    elif client_name:
        html += f"<div class='emp-client-name'>{client_name}</div>"
    html += "<div class='emp-accent'></div></div>"
    container.markdown(html, unsafe_allow_html=True)


def render_footer(container) -> None:
    mark = data_uri(theme.INTERVAL_MARK)
    img = f"<img src='{mark}' style='height:12px;'/>" if mark else ""
    container.markdown(
        f"<div class='emp-footer'>{img}Prepared by Empirica Analytics</div>",
        unsafe_allow_html=True,
    )


__all__ = ["configure_page", "data_uri", "hide_streamlit_chrome",
           "inject_brand_css", "render_brand", "render_footer"]
