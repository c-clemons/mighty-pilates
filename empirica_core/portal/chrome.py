"""Streamlit page chrome — the Empirica light look, on every client portal.

``configure_page`` runs first (sets the Empirica favicon); ``inject_brand_css``
applies the light design system (warm off-white page, white cards, ink text,
clay accents, hidden Streamlit UI) and normalizes every Plotly chart to the light
theme; ``render_brand`` / ``render_topbar`` / ``page_header`` / ``render_footer``
place the Empirica lockup, the client's logo, the user chip, and section headers.
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
    """Register + default an Empirica light Plotly template."""
    try:
        import plotly.io as pio
        import plotly.graph_objects as go
    except Exception:
        return
    t = theme
    axis = dict(gridcolor=t.LINE, zerolinecolor=t.LINE, linecolor=t.LINE,
                tickcolor=t.LINE, tickfont=dict(color=t.MUTED),
                title_font=dict(color=t.MUTED))
    tmpl = go.layout.Template()
    tmpl.layout.colorway = list(t.SERIES_PALETTE)
    tmpl.layout.font = dict(family="Schibsted Grotesk, system-ui, sans-serif",
                            color=t.INK_SOFT, size=13)
    tmpl.layout.paper_bgcolor = "rgba(0,0,0,0)"
    tmpl.layout.plot_bgcolor = "rgba(0,0,0,0)"
    tmpl.layout.xaxis = axis
    tmpl.layout.yaxis = axis
    tmpl.layout.legend = dict(font=dict(color=t.INK_SOFT))
    tmpl.layout.title = dict(font=dict(color=t.INK))
    pio.templates["empirica"] = tmpl
    pio.templates.default = "empirica"
    try:
        import plotly.express as px
        px.defaults.color_discrete_sequence = list(t.SERIES_PALETTE)
        px.defaults.template = "empirica"
    except Exception:
        pass


def _patch_plotly_chart() -> None:
    """Wrap ``st.plotly_chart`` so EVERY figure gets the Empirica light treatment
    (transparent bg so it sits on the white card, ink font, warm gridlines).
    Page series colors are preserved."""
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
                          color=t.INK_SOFT),
                legend=dict(font=dict(color=t.INK_SOFT)),
            )
            fig.update_xaxes(gridcolor=t.LINE, zerolinecolor=t.LINE,
                             linecolor=t.LINE, tickfont=dict(color=t.MUTED))
            fig.update_yaxes(gridcolor=t.LINE, zerolinecolor=t.LINE,
                             linecolor=t.LINE, tickfont=dict(color=t.MUTED))
        except Exception:
            pass
        return _orig(fig, *args, **kwargs)

    st.plotly_chart = _styled
    st._empirica_plotly_patched = True


def inject_brand_css(accent_color: str = theme.CLAY, *, hide_chrome: bool = True) -> None:
    """Apply the Empirica light design system + normalize charts."""
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
        :root {{ --paper:{t.PAPER}; --white:{t.WHITE}; --cream:{t.CREAM};
                 --ink:{t.INK}; --ink-soft:{t.INK_SOFT}; --muted:{t.MUTED};
                 --clay:{t.CLAY}; --line:{t.LINE}; --accent:{accent_color}; }}

        .stApp {{ background:{t.PAPER}; color:{t.INK_SOFT}; font-family:{t.FONT_DISPLAY}; }}
        [data-testid="stHeader"] {{ background:transparent; }}
        .block-container {{ padding-top:1.8rem; max-width:1400px; }}
        [data-testid="stSidebar"] {{ background:{t.WHITE};
            border-right:1px solid {t.LINE}; }}

        h1,h2,h3,h4,h5 {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
            color:{t.INK}; letter-spacing:-0.015em; }}
        h1 {{ font-weight:700; }}
        p, li, label, .stMarkdown {{ color:{t.INK_SOFT}; }}
        a {{ color:{t.CLAY}; text-decoration:none; }}
        a:hover {{ text-decoration:underline; }}
        hr {{ border-color:{t.LINE}; }}

        /* mono eyebrow labels / captions */
        [data-testid="stCaptionContainer"], .stCaption,
        [data-testid="stMetricLabel"] {{
            font-family:{t.FONT_MONO}; letter-spacing:.04em; text-transform:uppercase;
            font-size:.66rem; color:{t.LABEL}; }}

        /* KPI cards */
        div[data-testid="stMetric"] {{
            background:{t.WHITE}; padding:16px 18px; border-radius:12px;
            border:1px solid {t.LINE}; box-shadow:{t.SHADOW}; }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
            font-family:{t.FONT_DISPLAY}; font-weight:700; color:{t.INK};
            font-size:1.6rem; line-height:1.15; white-space:normal;
            overflow-wrap:anywhere; }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] > div {{
            white-space:normal; overflow:visible; text-overflow:clip; }}
        div[data-testid="stMetric"] [data-testid="stMetricLabel"] {{
            white-space:normal; overflow:visible; }}
        div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {{
            white-space:normal; overflow:visible; text-overflow:clip;
            line-height:1.25; }}
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {{ color:{t.MUTED}; }}

        /* bordered containers + expanders -> white cards */
        [data-testid="stExpander"],
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background:{t.WHITE}; border:1px solid {t.LINE} !important;
            border-radius:12px; box-shadow:{t.SHADOW}; }}

        /* buttons */
        .stButton>button[kind="primary"], .stDownloadButton>button {{
            background:{t.CLAY}; border:1px solid {t.CLAY}; color:{t.WHITE};
            font-weight:600; border-radius:8px; }}
        .stButton>button[kind="primary"]:hover {{ background:{t.SIENNA};
            border-color:{t.SIENNA}; }}
        .stButton>button {{ border-radius:8px; background:{t.WHITE};
            color:{t.INK}; border:1px solid {t.LINE}; }}
        .stButton>button:hover {{ border-color:{t.CLAY}; color:{t.CLAY}; }}

        /* inputs */
        input, textarea, [data-baseweb="input"], [data-baseweb="select"]>div {{
            background:{t.WHITE} !important; color:{t.INK} !important;
            border-color:{t.LINE} !important; }}

        /* sidebar nav radio -> pills w/ active state */
        [data-testid="stSidebar"] [role="radiogroup"] {{ gap:2px; }}
        [data-testid="stSidebar"] [role="radiogroup"] label {{
            padding:7px 11px; border-radius:8px; margin:0; transition:background .12s; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
            background:{t.LINE_SOFT}; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
            background:{t.ACTIVE}; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
            color:{t.CLAY}; font-weight:600; }}
        /* hide the actual radio dots (label text is the nav) */
        [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display:none; }}

        /* tables / dataframes */
        [data-testid="stDataFrame"] {{ border:1px solid {t.LINE}; border-radius:10px; }}
        thead tr th {{ font-family:{t.FONT_MONO}; text-transform:uppercase;
            letter-spacing:.03em; font-size:.68rem; color:{t.MUTED}; }}
        .stTabs [aria-selected="true"] {{ color:{t.CLAY}; }}

        /* --- brand bits --- */
        .emp-accent {{ height:3px; width:100%; background:{accent_color};
            border-radius:2px; margin:2px 0 10px; opacity:.9; }}
        .emp-client-name {{ font-family:{t.FONT_DISPLAY}; font-weight:600;
            font-size:1.05rem; color:{t.INK}; }}
        .emp-footer {{ font-family:{t.FONT_MONO}; font-size:.6rem; color:{t.LABEL};
            text-transform:uppercase; letter-spacing:.05em; display:flex;
            align-items:center; gap:6px; margin-top:4px; }}

        /* top bar (product context left, user chip right) */
        .emp-topbar {{ display:flex; align-items:center; justify-content:space-between;
            padding-bottom:14px; margin-bottom:20px; border-bottom:1px solid {t.LINE}; }}
        .emp-topbar-l {{ font-family:{t.FONT_MONO}; text-transform:uppercase;
            letter-spacing:.05em; font-size:.66rem; color:{t.LABEL}; }}
        .emp-user {{ display:flex; align-items:center; gap:9px; }}
        .emp-user-email {{ font-size:.82rem; color:{t.INK_SOFT}; }}
        .emp-avatar {{ width:30px; height:30px; border-radius:50%; background:{t.CLAY};
            color:{t.WHITE}; font-weight:600; font-size:.8rem; display:flex;
            align-items:center; justify-content:center; }}

        /* page header (eyebrow + title + subtitle) */
        .emp-eyebrow {{ font-family:{t.FONT_MONO}; text-transform:uppercase;
            letter-spacing:.07em; font-size:.68rem; color:{accent_color};
            font-weight:500; margin-bottom:6px; }}
        .emp-title {{ font-family:{t.FONT_DISPLAY}; font-weight:700; font-size:1.9rem;
            color:{t.INK}; letter-spacing:-0.02em; margin:0 0 4px; line-height:1.1; }}
        .emp-subtitle {{ color:{t.MUTED}; font-size:1rem; margin-bottom:1.1rem; }}
        .emp-hero-title {{ font-family:{t.FONT_DISPLAY}; font-weight:700; font-size:2.1rem;
            color:{t.INK}; letter-spacing:-0.02em; line-height:1.08; margin:2px 0 6px; }}

        /* KPI strip (custom cards w/ sparkline) */
        .emp-kpi-row {{ display:grid;
            grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
            gap:14px; margin:4px 0 10px; }}
        .emp-kpi {{ background:{t.WHITE}; border:1px solid {t.LINE}; border-radius:12px;
            padding:15px 17px; box-shadow:{t.SHADOW}; display:flex; flex-direction:column; }}
        .emp-kpi-label {{ font-family:{t.FONT_MONO}; text-transform:uppercase;
            letter-spacing:.04em; font-size:.63rem; color:{t.LABEL}; margin-bottom:7px; }}
        .emp-kpi-value {{ font-family:{t.FONT_DISPLAY}; font-weight:700; font-size:1.7rem;
            color:{t.INK}; line-height:1.1; }}
        .emp-kpi-delta {{ font-size:.72rem; margin-top:4px; color:{t.MUTED}; }}
        .emp-kpi-delta.up {{ color:#5f7d4f; }} .emp-kpi-delta.down {{ color:{t.RED}; }}
        .emp-kpi-cap {{ font-size:.67rem; color:{t.MUTED}; margin-top:3px; }}
        .emp-kpi-spark {{ margin-top:11px; }}

        /* legacy page classes, light */
        .main-header {{ font-family:{t.FONT_DISPLAY}; font-weight:700;
            font-size:1.9rem; color:{t.INK}; margin-bottom:.15rem; }}
        .sub-header {{ color:{t.MUTED}; font-size:1rem; margin-bottom:1.1rem; }}
        .metric-card {{ background:{t.WHITE}; border:1px solid {t.LINE};
            border-left:4px solid var(--accent); border-radius:12px; padding:1rem;
            box-shadow:{t.SHADOW}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand(container, *, client_logo=None, client_name: str = "",
                 accent_color: str = theme.CLAY, logo_bg: Optional[str] = None) -> None:
    """Empirica lockup (clay mark + ink wordmark) + the client's logo."""
    t = theme
    mark = data_uri(t.INTERVAL_MARK)
    logo = data_uri(client_logo) if client_logo else None

    html = "<div style='padding:6px 0 2px;'>"
    if mark:
        html += (
            "<div style='display:flex;align-items:center;gap:7px;margin-bottom:14px;'>"
            f"<img src='{mark}' style='height:22px;'/>"
            f"<span style='font-family:{t.FONT_DISPLAY};font-weight:600;font-size:1rem;"
            f"color:{t.INK};letter-spacing:.01em;'>empirica</span></div>"
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


def render_topbar(container, *, email: str = "", context: str = "",
                  role: Optional[str] = None) -> None:
    """Themis-style top row: product context on the left, user chip on the right."""
    initial = (email[:1] or "•").upper()
    who = email
    if role:
        who = f"{email} · {role}"
    left = f"<div class='emp-topbar-l'>{context}</div>" if context else "<div></div>"
    container.markdown(
        f"<div class='emp-topbar'>{left}"
        f"<div class='emp-user'><span class='emp-user-email'>{who}</span>"
        f"<div class='emp-avatar'>{initial}</div></div></div>",
        unsafe_allow_html=True,
    )


def page_header(container, title: str, *, eyebrow: str = "", subtitle: str = "") -> None:
    """Themis-style section header: uppercase eyebrow, big title, muted subtitle."""
    html = ""
    if eyebrow:
        html += f"<div class='emp-eyebrow'>{eyebrow}</div>"
    html += f"<div class='emp-title'>{title}</div>"
    if subtitle:
        html += f"<div class='emp-subtitle'>{subtitle}</div>"
    container.markdown(html, unsafe_allow_html=True)


def render_footer(container) -> None:
    mark = data_uri(theme.INTERVAL_MARK)
    img = f"<img src='{mark}' style='height:12px;'/>" if mark else ""
    container.markdown(
        f"<div class='emp-footer'>{img}Prepared by Empirica Analytics</div>",
        unsafe_allow_html=True,
    )


def sparkline_svg(values, *, color: Optional[str] = None,
                  width: int = 132, height: int = 30, fill: bool = True) -> str:
    """Inline SVG sparkline from a numeric series (empty string if <2 points)."""
    t = theme
    color = color or t.CLAY
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = [(i / (n - 1) * width, height - ((v - lo) / rng) * (height - 5) - 2.5)
           for i, v in enumerate(vals)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    fill_svg = ""
    if fill:
        fd = d + f" L{width:.1f},{height:.1f} L0,{height:.1f} Z"
        fill_svg = f"<path d='{fd}' fill='{color}' opacity='0.10'/>"
    lx, ly = pts[-1]
    return (f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
            f"preserveAspectRatio='none' style='display:block;'>{fill_svg}"
            f"<path d='{d}' fill='none' stroke='{color}' stroke-width='1.7' "
            f"stroke-linecap='round' stroke-linejoin='round'/>"
            f"<circle cx='{lx:.1f}' cy='{ly:.1f}' r='2.3' fill='{color}'/></svg>")


def kpi_strip(container, items, *, accent: Optional[str] = None) -> None:
    """Themis-style KPI cards with optional sparklines.

    items: list of dicts with keys:
        label (str), value (str), caption (str, optional),
        delta (str, optional), delta_dir ("up"/"down"/None, optional),
        spark (list[float], optional), spark_color (str, optional).
    """
    t = theme
    accent = accent or t.CLAY
    cards = ""
    for it in items:
        spark = ""
        if it.get("spark"):
            spark = ("<div class='emp-kpi-spark'>"
                     + sparkline_svg(it["spark"], color=it.get("spark_color", accent))
                     + "</div>")
        cap = f"<div class='emp-kpi-cap'>{it['caption']}</div>" if it.get("caption") else ""
        delta = ""
        if it.get("delta"):
            cls = f" {it['delta_dir']}" if it.get("delta_dir") in ("up", "down") else ""
            delta = f"<div class='emp-kpi-delta{cls}'>{it['delta']}</div>"
        cards += (
            "<div class='emp-kpi'>"
            f"<div class='emp-kpi-label'>{it['label']}</div>"
            f"<div class='emp-kpi-value'>{it['value']}</div>"
            f"{delta}{cap}{spark}</div>"
        )
    container.markdown(f"<div class='emp-kpi-row'>{cards}</div>", unsafe_allow_html=True)


def render_hero(*, eyebrow: str = "", title: str = "", subtitle: str = "",
                fig=None, fig_height: int = 240) -> None:
    """Themis-style hero band: white card with eyebrow + big title + subtitle,
    and an optional Plotly figure on the right."""
    import streamlit as st
    with st.container(border=True):
        cols = st.columns([1, 1.25]) if fig is not None else None
        target = cols[0] if cols else st
        html = ""
        if eyebrow:
            html += f"<div class='emp-eyebrow'>{eyebrow}</div>"
        html += f"<div class='emp-hero-title'>{title}</div>"
        if subtitle:
            html += f"<div class='emp-subtitle'>{subtitle}</div>"
        target.markdown(html, unsafe_allow_html=True)
        if fig is not None:
            try:
                fig.update_layout(height=fig_height,
                                  margin=dict(t=8, b=8, l=0, r=0), showlegend=False)
            except Exception:
                pass
            cols[1].plotly_chart(fig, use_container_width=True,
                                 config={"displayModeBar": False})


__all__ = ["configure_page", "data_uri", "hide_streamlit_chrome", "apply_plotly_theme",
           "inject_brand_css", "render_brand", "render_topbar", "page_header",
           "render_footer", "sparkline_svg", "kpi_strip", "render_hero"]
