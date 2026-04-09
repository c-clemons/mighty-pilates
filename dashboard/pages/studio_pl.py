"""
Studio P&L page — per-studio forecast vs actuals with variance.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from dashboard.data_store import DataStore
from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS, OVERHEAD, OPEX_CATEGORIES,
    month_display, parse_accountant_month,
)
from dashboard.financial_calcs import (
    get_actuals_cash_sales_by_studio,
    calculate_studio_contribution,
)


def show():
    ds = DataStore.get()
    st.header("Studio P&L")

    last_key = ds.get_last_actuals_month_key()
    actuals_months = ds.get_actuals_months()
    forecast_months = ds.get_forecast_months()
    studio_pls = ds.get_actuals_studio_pls()

    # Studio selector
    all_studios = list(ACTIVE_STUDIOS.items()) + list(DEVELOPMENT_STUDIOS.items()) + list(OVERHEAD.items())
    studio_options = [f"{code} - {name}" for code, name in all_studios]
    selected = st.selectbox("Select Studio", studio_options)
    studio_code = selected.split(" - ")[0]
    studio_name = selected.split(" - ")[1]

    st.divider()

    # --- Actuals P&L ---
    if studio_code in studio_pls:
        sp = studio_pls[studio_code]["data"]

        # Show recent months
        col1, col2 = st.columns(2)
        with col1:
            show_months = st.slider("Actuals months to show", 3, 14, 6, key="pl_actuals_months")
        with col2:
            show_forecast = st.slider("Forecast months to show", 3, 12, 6, key="pl_forecast_months")

        # Get recent actuals months
        recent_actuals = actuals_months[-show_months:]

        # Build actuals side
        actuals_display = _build_actuals_pl(sp, recent_actuals)

        # Build forecast side (studio contribution)
        sales_forecast = ds.get_sales_forecast()
        opex_assumptions = ds.get_opex_assumptions()
        forecast_display = _build_forecast_pl(
            sales_forecast, opex_assumptions, studio_code, forecast_months[:show_forecast]
        )

        # --- Revenue Trend Chart ---
        st.subheader(f"{studio_name} — Revenue Trend")

        all_months_display = recent_actuals + forecast_months[:show_forecast]
        rev_actuals = []
        for m in recent_actuals:
            rev_actuals.append(actuals_display.get("Total Income", {}).get(m, 0))

        rev_forecast = []
        for m in forecast_months[:show_forecast]:
            rev_forecast.append(forecast_display.get("Revenue", {}).get(m, 0))

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=[month_display(m) for m in recent_actuals],
            y=rev_actuals, name="Actuals", marker_color="#2c3e50",
        ))
        fig.add_trace(go.Bar(
            x=[month_display(m) for m in forecast_months[:show_forecast]],
            y=rev_forecast, name="Forecast", marker_color="#3498db", opacity=0.7,
        ))
        fig.update_layout(
            height=300, margin=dict(t=10, b=30),
            yaxis_tickformat="$,.0f",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Actuals Table ---
        st.subheader("Actuals (from Accountant)")

        # Key P&L rows to display
        key_rows = [
            "Total Income", "Gross Profit",
            "Total Expenses", "Net Operating Income", "Net Income",
        ]
        # Also show revenue detail
        revenue_rows = [l for l in sp.index if any(x in str(l) for x in ["401", "403", "404", "406", "407"])]
        expense_rows = [l for l in sp.index if any(x in str(l) for x in ["Total 601", "Total 602", "Total for 602",
                                                                          "Total 700", "Total for 700",
                                                                          "Total 616", "Total for 616",
                                                                          "Total 604", "Total for 604"])]

        display_rows = list(dict.fromkeys(revenue_rows + ["Total Income", "Gross Profit"] + expense_rows +
                                          ["Total Expenses", "Net Operating Income", "Net Income"]))

        # Filter to rows that exist
        display_rows = [r for r in display_rows if r in sp.index]

        visible_cols = [c for c in sp.columns if parse_accountant_month(c) in recent_actuals]
        if display_rows and visible_cols:
            table = sp.loc[display_rows, visible_cols].copy()
            table.columns = [month_display(parse_accountant_month(c)) for c in visible_cols]

            # Style
            def _style(row):
                styles = []
                is_total = any(x in str(row.name) for x in ["Total", "Gross Profit", "Net"])
                for val in row:
                    s = ""
                    if is_total:
                        s += "font-weight: bold; "
                    if isinstance(val, (int, float)) and val < 0:
                        s += "color: #e74c3c; "
                    styles.append(s)
                return styles

            st.dataframe(
                table.style.apply(_style, axis=1).format("${:,.0f}"),
                use_container_width=True, height=500,
            )

        # --- Forecast Contribution ---
        st.subheader("Forecast (Studio Contribution)")

        contrib = calculate_studio_contribution(sales_forecast, opex_assumptions, studio_code)
        if not contrib.empty:
            visible_forecast = [m for m in contrib.columns if m in forecast_months[:show_forecast]]
            if visible_forecast:
                fc_display = contrib[visible_forecast].copy()
                fc_display.columns = [month_display(m) for m in visible_forecast]

                def _style_fc(row):
                    styles = []
                    is_total = any(x in str(row.name) for x in ["Revenue", "Total Costs", "Contribution"])
                    for val in row:
                        s = ""
                        if is_total:
                            s += "font-weight: bold; "
                        if isinstance(val, (int, float)) and val < 0:
                            s += "color: #e74c3c; "
                        styles.append(s)
                    return styles

                st.dataframe(
                    fc_display.style.apply(_style_fc, axis=1).format("${:,.0f}"),
                    use_container_width=True,
                )
        else:
            st.info("No forecast data for this studio. Add sales forecast and OpEx assumptions first.")

    else:
        st.info(f"No actuals data available for {studio_name}. This studio may be in development.")

        # Still show forecast if available
        sales_forecast = ds.get_sales_forecast()
        opex_assumptions = ds.get_opex_assumptions()
        contrib = calculate_studio_contribution(sales_forecast, opex_assumptions, studio_code)
        if not contrib.empty:
            st.subheader("Forecast")
            visible = [m for m in contrib.columns if m in forecast_months[:12]]
            if visible:
                fc_display = contrib[visible].copy()
                fc_display.columns = [month_display(m) for m in visible]
                st.dataframe(fc_display.style.format("${:,.0f}"), use_container_width=True)


def _build_actuals_pl(sp: pd.DataFrame, months: list) -> dict:
    """Extract key P&L items from studio actuals."""
    result = {}
    for label in sp.index:
        label_str = str(label)
        row = {}
        for col in sp.columns:
            mk = parse_accountant_month(col)
            if mk and mk in months:
                val = sp.loc[label, col]
                row[mk] = float(val) if pd.notna(val) else 0
        if row:
            result[label_str] = row
    return result


def _build_forecast_pl(
    sales_forecast: pd.DataFrame,
    opex_assumptions: dict,
    studio_code: str,
    months: list,
) -> dict:
    """Build simple forecast P&L for a studio."""
    result = {"Revenue": {}, "Costs": {}, "Contribution": {}}
    for m in months:
        rev = sales_forecast.loc[studio_code, m] if studio_code in sales_forecast.index and m in sales_forecast.columns else 0
        cost = sum(
            float(opex_assumptions.get(studio_code, {}).get(cat, {}).get(m, 0))
            for cat in OPEX_CATEGORIES
        )
        result["Revenue"][m] = float(rev)
        result["Costs"][m] = cost
        result["Contribution"][m] = float(rev) - cost
    return result
