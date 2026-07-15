"""Reusable Streamlit widgets for Empirica dashboards.

KPI rows, styled tables, and a thin Plotly line-chart wrapper that applies the
brand series palette. Build the visual vocabulary once here so every client
dashboard reads as one system.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from empirica_core.formatting import fmt_currency, fmt_pct
from empirica_core.portal import theme


def kpi_row(metrics: Sequence[dict]) -> None:
    """Render a row of ``st.metric`` cards.

    Each item: ``{"label": str, "value": str|number, "delta": optional,
    "help": optional}``. Format currency/percent with ``fmt_currency`` /
    ``fmt_pct`` before passing, or pass a pre-formatted string.
    """
    import streamlit as st

    if not metrics:
        return
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        col.metric(
            label=m["label"],
            value=m["value"],
            delta=m.get("delta"),
            help=m.get("help"),
        )


def currency_kpis(items: Sequence[tuple], decimals: int = 0) -> None:
    """Convenience: render currency KPIs from ``[(label, number), ...]``."""
    kpi_row([
        {"label": label, "value": fmt_currency(value, decimals)}
        for label, value in items
    ])


def styled_table(df: Any, *, currency_cols: Optional[Sequence[str]] = None,
                 pct_cols: Optional[Sequence[str]] = None,
                 use_container_width: bool = True) -> None:
    """Display a DataFrame with currency/percent formatting applied.

    Formats in place on a copy; leaves the original untouched.
    """
    import streamlit as st

    show = df.copy()
    for c in (currency_cols or []):
        if c in show.columns:
            show[c] = show[c].map(lambda v: fmt_currency(v))
    for c in (pct_cols or []):
        if c in show.columns:
            show[c] = show[c].map(lambda v: fmt_pct(v))
    st.dataframe(show, use_container_width=use_container_width)


def line_chart(df: Any, *, x: str, y: Sequence[str], title: str = "",
               height: int = 360):
    """Thin Plotly line chart with the brand series palette. Returns the fig."""
    import plotly.graph_objects as go

    fig = go.Figure()
    for i, col in enumerate(y):
        fig.add_trace(go.Scatter(
            x=df[x], y=df[col], mode="lines", name=col,
            line=dict(color=theme.SERIES_PALETTE[i % len(theme.SERIES_PALETTE)], width=2),
        ))
    fig.update_layout(
        title=title or None,
        height=height,
        margin=dict(l=10, r=10, t=40 if title else 10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        font=dict(color=theme.EMPIRICA_INK),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=theme.EMPIRICA_BORDER)
    return fig


__all__ = ["kpi_row", "currency_kpis", "styled_table", "line_chart"]
