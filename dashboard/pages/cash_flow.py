"""
Cash Flow Forecast page — the #1 priority page.
Displays consolidated cash flow statement with KPIs, chart, and detail table.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.data_store import DataStore
from dashboard.constants import (
    month_display, parse_accountant_month,
    CF_OPERATIONS_INFLOW, CF_OPERATIONS_OUTFLOW,
)
from dashboard.financial_calcs import (
    build_monthly_cash_sales,
    build_cash_flow_forecast,
)


def show():
    ds = DataStore.get()
    st.header("Cash Flow Forecast")

    last_actuals = ds.get_last_actuals_month()
    last_key = ds.get_last_actuals_month_key()

    # Sensitivity controls
    with st.expander("Sensitivity Adjustments", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            revenue_adj = st.slider(
                "Revenue adjustment %", -20, 20, 0, 1,
                format="%+d%%", key="rev_adj"
            ) / 100.0
        with col2:
            opex_adj = st.slider(
                "OpEx adjustment %", -20, 20, 0, 1,
                format="%+d%%", key="opex_adj"
            ) / 100.0

    # Build cash flow
    cash_sales = build_monthly_cash_sales(
        ds.get_sales_forecast(),
        ds.get_actuals_pl(),
        ds.get_actuals_studio_pls(),
        last_actuals,
    )

    cf_df = build_cash_flow_forecast(
        cash_sales=cash_sales,
        opex_assumptions=ds.get_opex_assumptions(),
        loans=ds.get_loans(),
        actuals_pl=ds.get_actuals_pl(),
        actuals_scf=ds.get_actuals_scf(),
        actuals_bs=ds.get_actuals_bs(),
        last_actuals_month=last_actuals,
        revenue_adj=revenue_adj,
        opex_adj=opex_adj,
    )

    # --- KPI Cards ---
    _render_kpis(cf_df, last_key)

    # --- Chart ---
    _render_chart(cf_df, last_key)

    # --- Detail Table ---
    _render_table(cf_df, last_key)


def _render_kpis(cf_df: pd.DataFrame, last_key: str):
    """Display 4 KPI cards at the top."""
    months = list(cf_df.columns)
    forecast_months = [m for m in months if m > last_key]

    col1, col2, col3, col4 = st.columns(4)

    # Current ending cash (last actuals month or latest)
    ending_cash = cf_df.loc["Ending Cash", last_key] if last_key in cf_df.columns else 0
    with col1:
        st.metric("Current Cash Position", f"${ending_cash:,.0f}")

    # Trailing 3-month avg net cash from operations
    recent = [m for m in months if m <= last_key][-3:]
    if recent:
        avg_ops = np.mean([cf_df.loc["Net Cash from Operations", m] for m in recent])
    else:
        avg_ops = 0
    with col2:
        st.metric("Avg Monthly Net Cash (3mo)", f"${avg_ops:,.0f}")

    # 12-month forward cumulative net change
    forward_12 = forecast_months[:12]
    if forward_12:
        cum_12 = sum(cf_df.loc["Net Change in Cash", m] for m in forward_12)
    else:
        cum_12 = 0
    with col3:
        st.metric("12-Month Net Cash Flow", f"${cum_12:,.0f}",
                   delta=f"{'surplus' if cum_12 > 0 else 'deficit'}")

    # Lowest cash point in forecast
    if forecast_months:
        min_cash = min(cf_df.loc["Ending Cash", m] for m in forecast_months)
        min_month = min(forecast_months, key=lambda m: cf_df.loc["Ending Cash", m])
        min_display = month_display(min_month)
    else:
        min_cash = ending_cash
        min_display = "N/A"
    with col4:
        color = "normal" if min_cash > 0 else "inverse"
        st.metric("Lowest Cash Point", f"${min_cash:,.0f}",
                   delta=min_display, delta_color="off")


def _render_chart(cf_df: pd.DataFrame, last_key: str):
    """Stacked bar chart of cash flows + ending cash line."""
    months = list(cf_df.columns)
    display_months = [month_display(m) for m in months]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Inflows (positive bars)
    inflows = cf_df.loc["Total Cash Sales"]
    fig.add_trace(
        go.Bar(x=display_months, y=inflows, name="Cash Sales",
               marker_color="#2ecc71", opacity=0.8),
        secondary_y=False,
    )

    # Outflows (negative bars)
    outflows = cf_df.loc["Total Operating Expenses"]
    fig.add_trace(
        go.Bar(x=display_months, y=[-v for v in outflows], name="Operating Expenses",
               marker_color="#e74c3c", opacity=0.8),
        secondary_y=False,
    )

    # Investing (negative bars)
    investing = cf_df.loc["Net Cash from Investing"]
    inv_vals = [v if v < 0 else 0 for v in investing]
    if any(v != 0 for v in inv_vals):
        fig.add_trace(
            go.Bar(x=display_months, y=inv_vals, name="Investing",
                   marker_color="#e67e22", opacity=0.7),
            secondary_y=False,
        )

    # Ending cash line
    ending = cf_df.loc["Ending Cash"]
    fig.add_trace(
        go.Scatter(x=display_months, y=ending, name="Ending Cash",
                   line=dict(color="#2c3e50", width=3),
                   mode="lines+markers", marker=dict(size=5)),
        secondary_y=True,
    )

    # Actuals/forecast divider
    if last_key in months:
        div_idx = months.index(last_key) + 0.5
        fig.add_vline(x=div_idx, line_dash="dash", line_color="gray",
                       annotation_text="Forecast", annotation_position="top right")

    fig.update_layout(
        barmode="relative",
        height=450,
        margin=dict(t=30, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Monthly Cash Flow", secondary_y=False, tickformat="$,.0f")
    fig.update_yaxes(title_text="Ending Cash", secondary_y=True, tickformat="$,.0f")

    st.plotly_chart(fig, use_container_width=True)


def _render_table(cf_df: pd.DataFrame, last_key: str):
    """Display the cash flow detail table with formatting."""
    st.subheader("Cash Flow Detail")

    # Controls
    col1, col2 = st.columns(2)
    with col1:
        show_actuals = st.checkbox("Show actuals months", value=True, key="cf_show_actuals")
    with col2:
        months_to_show = st.slider("Forecast months", 6, 24, 12, key="cf_months")

    months = list(cf_df.columns)
    actuals_months = [m for m in months if m <= last_key]
    forecast_months = [m for m in months if m > last_key]

    visible = []
    if show_actuals:
        visible += actuals_months[-6:]
    visible += forecast_months[:months_to_show]

    display = cf_df[visible].copy()
    display.columns = [month_display(m) for m in visible]

    # Highlight rows
    summary_rows = [
        "Total Cash Sales", "Total Operating Expenses",
        "Net Cash from Operations", "Net Cash from Investing",
        "Net Cash from Financing", "Net Change in Cash",
        "Beginning Cash", "Ending Cash",
    ]

    def _style_row(row):
        styles = []
        name = row.name
        for val in row:
            s = ""
            if name in summary_rows:
                s += "font-weight: bold; "
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    styled = display.style.apply(_style_row, axis=1).format("${:,.0f}")
    st.dataframe(styled, use_container_width=True, height=700)

    # Download
    csv = cf_df.to_csv()
    st.download_button("Download Full CSV", csv, "mighty_cash_flow.csv", "text/csv")
