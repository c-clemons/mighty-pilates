"""Streamlit page chrome — the Empirica dark look, on every client portal.

``configure_page`` runs first (sets the Empirica favicon); ``inject_brand_css``
applies the dark design system (ink bg, cream/bone text, clay accents, hidden
Streamlit UI) and forces every Plotly chart onto the dark theme; ``render_brand``
/ ``render_footer`` place the Empirica lockup + the client's logo.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from empirica_core.portal import theme


def configure_page(title: str, *, icon: Optional[str] = None,
                   layout: str = "wide", sidebar: str = "expanded") -> None:
    import streamlit as st
    page_icon = icon
    if page_icon is None and theme.FAVICON.exists():
        page_icon = str(theme.FAVICON)
    st.set_page_config(page_title=title, page_icon=page_icon, layout=layout,
                       initial_sidebar_state=sidebar)


def data_uri(path) -> Optional[str]:
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


def apply_plotly_theme() -> None:
    """Register + default an Empirica dark Plotly template."""
    try:
        import plotly.io as pio
        import plotly.graph_objects as go
    except Exception:
        return
    t = theme
    axis = dict(gridcolor=t.LINE_SOFT, zerolinecolor=t.LINE, linecolor=t.LINE,
                tickcolor=t.LINE, tickfont=dict(color=t.MUTED),
                title_font=dict(color=t.MUTED))
    tmpl = go.layout.Template()
    tmpl.layout.colorway = list(t.SERIES_PALETTE)
    tmpl.layout.font = dict(family="Schibsted Grotesk, system-ui, sans-serif",
                            color=t.CREAM, size=13)
    tmpl.layout.paper_bgcolor = "rgba(0,0,0,0)"
    tmpl.layout.plot_bgcolor = "rgba(0,0,0,0)"
    tmpl.layout.xaxis = axis
    tmpl.layout.yaxis = axis
    tmpl.layout.legend = dict(font=dict(color=t.CREAM))
    tmpl.layout.title = dict(font=dict(color=t.BONE))
    pio.templates["empirica"] = tmpl
    pio.templates.default = "empirica"
    try:
        import plotly.express as px
        px.defaults.color_discrete_sequence = list(t.SERIES_PALETTE)
        px.defaults.template = "empirica"
    except Exception:
        pass


def _patch_plotly_chart() -> None:
    """Wrap ``st.plotly_chart`` so EVERY figure gets the Empirica dark treatment,
    regardless of what the page set (transparent bg, cream font, dark grid). Page
    series colors are preserved."""
    import streamlit as st
    if getattr(st, "_empirica_plotly_patched", False):
        return
    _orig = st.plotly_chart
    t = theme

    def _styled(fig, *args, **kwargs):
        try:
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Schibsted Grotesk, system-ui, sans-serif",
                          color=t.CREAM),
                legend=dict(font=dict(color=t.CREAM)),
            )
            fig.update_xaxes(gridcolor=t.LINE_SOFT, zerolinecolor=t.LINE,
                             linecolor=t.LINE, tickfont=dict(color=t.MUTED))
            fig.update_yaxes(gridcolor=t.LINE_SOFT, zerolinecolor=t.LINE,
                             linecolor=t.LINE, tickfont=dict(color=t.MUTED))
        except Exception:
            pass
        return _orig(fig, *args, **kwargs)

    st.plotly_chart = _styled
    st._empirica_plotly_patched = True


def inject_brand_css(accent_color: str = theme.CLAY, *, hide_chrome: bool = True) -> None:
    """Apply the Empirica dark design system + dark charts."""
    import streamlit as st
    if hide_chrome:
        hide_streamlit_chrome()
    apply_plotly_theme()
    _patch_plotly_chart()

    t = theme
    st.markdown(
        f"""
        <style>
        @import url('{t.GOOGLE_FONTS}');
        :root {{ --ink:{t.INK}; --panel:{t.PANEL}; --bone:{t.BONE};
                 --cream:{t.CREAM}; --muted:{t.MUTED}; --clay:{t.CLAY};
                 --clay-soft:{t.CLAY_SOFT}; --line:{t.LINE}; --accent:{accent_color}; }}

        .stApp {{ background:{t.INK}; color:{t.CREAM}; font-family:{t.FONT_DISPLAY}; }}
        [data-testid="stHeader"] {{ background:transparent; }}
        .block-container {{ padding-top:2.4rem; }}
        [data-testid="stSidebar"] {{ background:{t.PANEL};
            border-right:1px solid {t.LINE}; }}
        [data-testid="stSidebar"] * {{ color:{t.CREAM}; }}

        h1,h2,h3,h4,h5 {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
            color:{t.BONE}; letter-spacing:-0.015em; }}
        h1 {{ font-weight:700; }}
        p, li, label, .stMarkdown, .stApp {{ color:{t.CREAM}; }}
        a {{ color:{t.CLAY_SOFT}; text-decoration:none; }}
        a:hover {{ text-decoration:underline; }}
        hr, [data-testid="stSidebar"] hr {{ border-color:{t.LINE}; }}

        /* mono labels / captions */
        [data-testid="stCaptionContainer"], .stCaption,
        [data-testid="stMetricLabel"] {{
            font-family:{t.FONT_MONO}; letter-spacing:.03em; text-transform:uppercase;
            font-size:.66rem; color:{t.LABEL}; }}

        /* KPI cards */
        div[data-testid="stMetric"] {{
            background:{t.PANEL}; padding:15px 17px; border-radius:10px;
            border:1px solid {t.LINE}; }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
            font-family:{t.FONT_DISPLAY}; font-weight:700; color:{t.BONE};
            font-size:1.7rem; line-height:1.15; }}
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {{ color:{t.MUTED}; }}

        /* buttons */
        .stButton>button[kind="primary"], .stDownloadButton>button {{
            background:{t.CLAY}; border:1px solid {t.CLAY}; color:{t.BONE};
            font-weight:600; }}
        .stButton>button[kind="primary"]:hover {{ background:{t.SIENNA};
            border-color:{t.SIENNA}; }}
        .stButton>button {{ border-radius:8px; background:{t.PANEL};
            color:{t.CREAM}; border:1px solid {t.LINE}; }}

        /* inputs */
        input, textarea, [data-baseweb="input"], [data-baseweb="select"]>div {{
            background:{t.PANEL} !important; color:{t.CREAM} !important;
            border-color:{t.LINE} !important; }}

        /* sidebar nav radio -> pills */
        [data-testid="stSidebar"] [role="radiogroup"] label {{
            padding:6px 10px; border-radius:7px; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
            background:rgba(205,127,87,.12); }}

        .stTabs [aria-selected="true"] {{ color:{t.CLAY_SOFT}; }}

        /* client-accent rule + brand bits */
        .emp-accent {{ height:3px; background:{accent_color}; border-radius:2px;
            margin:2px 0 10px; opacity:.9; }}
        .emp-footer {{ font-family:{t.FONT_MONO}; font-size:.6rem; color:{t.LABEL};
            text-transform:uppercase; letter-spacing:.05em; display:flex;
            align-items:center; gap:6px; margin-top:4px; }}
        .emp-client-name {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
            font-size:1.05rem; color:{t.BONE}; }}

        /* legacy page classes, dark-restyled */
        .main-header {{ font-family:{t.FONT_DISPLAY}; font-weight:700;
            font-size:1.9rem; color:{t.BONE}; margin-bottom:.15rem; }}
        .sub-header {{ color:{t.MUTED}; font-size:1rem; margin-bottom:1.1rem; }}
        .metric-card {{ background:{t.PANEL}; border:1px solid {t.LINE};
            border-left:4px solid var(--accent); border-radius:10px; padding:1rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand(container, *, client_logo=None, client_name: str = "",
                 accent_color: str = theme.CLAY, logo_bg: Optional[str] = None) -> None:
    """Empirica lockup (transparent mark + wordmark) + the client's logo."""
    t = theme
    mark = data_uri(t.INTERVAL_MARK)
    logo = data_uri(client_logo) if client_logo else None

    html = "<div style='padding:6px 0 2px;'>"
    if mark:
        html += (
            "<div style='display:flex;align-items:center;gap:7px;margin-bottom:14px;'>"
            f"<img src='{mark}' style='height:22px;'/>"
            f"<span style='font-family:{t.FONT_DISPLAY};font-weight:600;font-size:1rem;"
            f"color:{t.BONE};letter-spacing:.01em;'>empirica</span></div>"
        )
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


__all__ = ["configure_page", "data_uri", "hide_streamlit_chrome", "apply_plotly_theme",
           "inject_brand_css", "render_brand", "render_footer"]
