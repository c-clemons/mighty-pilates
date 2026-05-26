"""
Cash Flow Forecast page — the #1 priority page.
Displays consolidated cash flow statement with KPIs, chart, and detail table.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from dashboard.data_store import DataStore
from dashboard.constants import (
    month_display, parse_accountant_month,
    CF_OPERATIONS_INFLOW, CF_OPERATIONS_OUTFLOW,
)
from dashboard.financial_calcs import (
    build_monthly_cash_sales,
    build_cash_flow_forecast,
    calculate_studio_contribution,
)


def show():
    ds = DataStore.get()
    st.header("Cash Flow Forecast")

    last_actuals = ds.get_last_actuals_month()
    last_key = ds.get_last_actuals_month_key()

    # View selector
    from dashboard.constants import ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS, OVERHEAD
    all_studios = list(ACTIVE_STUDIOS.items()) + list(DEVELOPMENT_STUDIOS.items())
    view_options = ["Consolidated"] + [f"{code} - {name}" for code, name in all_studios]
    selected_view = st.selectbox("View", view_options, key="cf_view")

    if selected_view != "Consolidated":
        _show_studio_cash_flow(ds, selected_view, last_actuals, last_key)
        return

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
        capex_by_month=ds.get_capex_by_month(),
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
    """Two charts: ending cash balance + monthly cash flow bars."""
    months = list(cf_df.columns)
    display_months = [month_display(m) for m in months]

    # Chart 1: Ending Cash Balance
    st.subheader("Cash Balance")
    ending = cf_df.loc["Ending Cash"]
    fig_cash = go.Figure()
    colors = ["#2c3e50" if m <= last_key else "#3498db" for m in months]
    fig_cash.add_trace(go.Bar(
        x=display_months, y=ending, name="Ending Cash",
        marker_color=colors,
    ))
    if last_key in months:
        div_idx = months.index(last_key) + 0.5
        fig_cash.add_vline(x=div_idx, line_dash="dash", line_color="gray",
                           annotation_text="Forecast", annotation_position="top right")
    fig_cash.update_layout(
        height=300, margin=dict(t=10, b=30),
        yaxis_tickformat="$,.0f",
    )
    st.plotly_chart(fig_cash, use_container_width=True)

    # Chart 2: Monthly Cash Flow Components
    st.subheader("Monthly Cash Flow")
    fig = go.Figure()

    # Inflows
    inflows = cf_df.loc["Total Cash Sales"]
    fig.add_trace(go.Bar(
        x=display_months, y=inflows, name="Cash Sales",
        marker_color="#2ecc71", opacity=0.8,
    ))

    # Outflows
    outflows = cf_df.loc["Total Operating Expenses"]
    fig.add_trace(go.Bar(
        x=display_months, y=[-v for v in outflows], name="Operating Expenses",
        marker_color="#e74c3c", opacity=0.8,
    ))

    # Investing
    investing = cf_df.loc["Net Cash from Investing"]
    inv_vals = [v if v < 0 else 0 for v in investing]
    if any(v != 0 for v in inv_vals):
        fig.add_trace(go.Bar(
            x=display_months, y=inv_vals, name="Investing",
            marker_color="#e67e22", opacity=0.7,
        ))

    # Financing
    financing = cf_df.loc["Net Cash from Financing"]
    fin_vals = [v if v < 0 else 0 for v in financing]
    if any(v != 0 for v in fin_vals):
        fig.add_trace(go.Bar(
            x=display_months, y=fin_vals, name="Financing",
            marker_color="#9b59b6", opacity=0.7,
        ))

    if last_key in months:
        div_idx = months.index(last_key) + 0.5
        fig.add_vline(x=div_idx, line_dash="dash", line_color="gray",
                       annotation_text="Forecast", annotation_position="top right")

    fig.update_layout(
        barmode="relative",
        height=350, margin=dict(t=10, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
        yaxis_tickformat="$,.0f",
    )
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

    # Hide individual revenue line items — only show "Total Cash Sales"
    revenue_detail_rows = [label for _, label in CF_OPERATIONS_INFLOW]
    display = display.drop(
        [r for r in revenue_detail_rows if r in display.index], errors="ignore"
    )

    # Highlight rows
    summary_rows = [
        "Total Cash Sales", "Total Operating Expenses",
        "Net Cash from Operations", "Net Cash from Investing",
        "Net Cash from Financing", "Net Change in Cash",
        "Beginning Cash", "Ending Cash",
    ]

    actuals_display = set(month_display(m) for m in actuals_months)

    def _style_row(row):
        styles = []
        name = row.name
        for i, val in enumerate(row):
            s = ""
            col = display.columns[i] if i < len(display.columns) else ""
            is_act = col in actuals_display
            if name in summary_rows:
                s += "font-weight: bold; "
                s += "background-color: #e8eaed; " if is_act else "background-color: #e3edf7; "
            elif not is_act and col:
                s += "background-color: #f5f9ff; "
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    styled = display.style.apply(_style_row, axis=1).format("${:,.0f}")
    st.dataframe(styled, use_container_width=True, height=700)

    # Download
    csv = cf_df.to_csv()
    st.download_button("Download Full CSV", csv, "mighty_cash_flow.csv", "text/csv")


def _show_studio_cash_flow(ds, selected_view: str, last_actuals: str, last_key: str):
    """Show studio-level P&L with actuals + forecast."""
    studio_code = selected_view.split(" - ")[0]
    studio_name = selected_view.split(" - ")[1]

    st.subheader(f"{studio_name} — P&L")

    studio_pls = ds.get_actuals_studio_pls()
    actuals_months = ds.get_actuals_months()
    forecast_months = ds.get_forecast_months()

    col1, col2 = st.columns(2)
    with col1:
        n_actuals = st.slider("Actuals months", 3, 12, 6, key="scf_actuals")
    with col2:
        n_forecast = st.slider("Forecast months", 3, 12, 6, key="scf_forecast")

    recent_actuals = actuals_months[-n_actuals:]
    show_forecast = forecast_months[:n_forecast]

    # Actuals from studio P&L
    if studio_code in studio_pls:
        sp = studio_pls[studio_code]["data"]

        # Revenue rows
        revenue_rows = [l for l in sp.index if any(x in str(l) for x in
                        ["401", "403", "404", "406", "407"]) and "Total" not in str(l)]
        summary_rows = [l for l in sp.index if any(x in str(l) for x in
                        ["Total Income", "Total Expenses", "Gross Profit",
                         "Net Operating Income", "Net Income",
                         "Total 401", "Total 403", "Total for 401", "Total for 403",
                         "Total Cost of Goods Sold", "Total for Cost of Goods Sold",
                         "Total 601", "Total 602", "Total 604", "Total 616", "Total 700",
                         "Total for 601", "Total for 602", "Total for 604", "Total for 616", "Total for 700"])]
        all_rows = list(dict.fromkeys(revenue_rows + summary_rows))
        all_rows = [r for r in sp.index if r in all_rows]  # preserve original order

        visible_cols = [c for c in sp.columns if parse_accountant_month(c) in recent_actuals]
        if all_rows and visible_cols:
            table = sp.loc[all_rows, visible_cols].copy()
            table.columns = [month_display(parse_accountant_month(c)) for c in visible_cols]

            # Add forecast columns from studio contribution
            sales_forecast = ds.get_sales_forecast()
            opex_assumptions = ds.get_opex_assumptions()
            contrib = calculate_studio_contribution(sales_forecast, opex_assumptions, studio_code)
            if not contrib.empty:
                for m in show_forecast:
                    if m in contrib.columns:
                        col_name = month_display(m)
                        table[col_name] = 0.0
                        # Map contribution rows to P&L rows
                        if "Revenue" in contrib.index:
                            for r in table.index:
                                if "Total Income" in str(r):
                                    table.loc[r, col_name] = contrib.loc["Revenue", m]
                        if "Total Costs" in contrib.index:
                            for r in table.index:
                                if "Total Expenses" in str(r):
                                    table.loc[r, col_name] = contrib.loc["Total Costs", m]
                        if "Contribution" in contrib.index:
                            for r in table.index:
                                if "Net Operating Income" in str(r) or "Net Income" in str(r):
                                    table.loc[r, col_name] = contrib.loc["Contribution", m]

            def _style(row):
                styles = []
                is_bold = any(x in str(row.name) for x in ["Total", "Gross Profit", "Net"])
                for val in row:
                    s = "font-weight: bold; " if is_bold else ""
                    if isinstance(val, (int, float)) and val < 0:
                        s += "color: #e74c3c; "
                    styles.append(s)
                return styles

            st.dataframe(
                table.style.apply(_style, axis=1).format("${:,.0f}"),
                use_container_width=True, height=600,
            )

            # Revenue chart
            st.subheader(f"{studio_name} — Revenue Trend")
            rev_vals = []
            rev_labels = []
            rev_colors = []
            for c in table.columns:
                for r in table.index:
                    if "Total Income" in str(r):
                        rev_vals.append(table.loc[r, c])
                        rev_labels.append(c)
                        rev_colors.append("#2c3e50" if len(rev_labels) <= n_actuals else "#3498db")
                        break

            fig = go.Figure()
            fig.add_trace(go.Bar(x=rev_labels, y=rev_vals, marker_color=rev_colors))
            fig.update_layout(height=300, margin=dict(t=10, b=30), yaxis_tickformat="$,.0f")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No actuals data for {studio_name}.")
