"""
Actuals page — pull real-time data from Snowflake, view variance, import accountant package.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

from dashboard.data_store import DataStore
from dashboard.constants import (
    ACTIVE_STUDIOS, month_display, month_key, parse_accountant_month,
)
from dashboard.financial_calcs import get_actuals_cash_sales_by_studio


def show():
    ds = DataStore.get()
    st.header("Actuals & Variance")

    last_actuals = ds.get_last_actuals_month()
    last_key = ds.get_last_actuals_month_key()

    tab_mtd, tab_variance, tab_import = st.tabs([
        "Current Month (Snowflake)", "Forecast vs Actuals", "Import Financials"
    ])

    # =====================================================================
    # TAB 1: Current Month from Snowflake
    # =====================================================================
    with tab_mtd:
        st.subheader("Month-to-Date Revenue (Live from Snowflake)")

        if st.button("Pull Latest Data", type="primary"):
            with st.spinner("Querying Snowflake..."):
                try:
                    from dashboard.snowflake_actuals import pull_current_month_summary
                    summary = pull_current_month_summary()
                    st.session_state["snowflake_mtd"] = summary
                except Exception as e:
                    st.error(f"Snowflake query failed: {e}")
                    return

        summary = st.session_state.get("snowflake_mtd")
        if summary:
            today = datetime.now()
            days_elapsed = summary.get("days_elapsed", today.day)
            month_str = month_display(summary["month"])

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                total_rev = summary["total_earned"] + summary["total_classpass"]
                st.metric(f"{month_str} Revenue (MTD)", f"${total_rev:,.0f}")
            with col2:
                st.metric("ClassPass", f"${summary['total_classpass']:,.0f}")
            with col3:
                daily_run_rate = total_rev / days_elapsed if days_elapsed > 0 else 0
                st.metric("Daily Run Rate", f"${daily_run_rate:,.0f}")
            with col4:
                import calendar
                days_in_month = calendar.monthrange(today.year, today.month)[1]
                projected = daily_run_rate * days_in_month
                st.metric("Projected Full Month", f"${projected:,.0f}")

            st.caption(f"As of {summary['as_of']} ({days_elapsed} days)")

            # Per-studio breakdown
            st.subheader("By Studio")
            studio_data = []
            for studio, vals in sorted(summary.get("studios", {}).items()):
                earned = vals.get("earned", 0)
                breakage = vals.get("breakage", 0)
                retail = vals.get("retail", 0)
                classpass = vals.get("classpass", 0)
                total = earned + breakage + retail + classpass
                studio_data.append({
                    "Studio": studio,
                    "Earned": earned,
                    "Breakage": breakage,
                    "Retail": retail,
                    "ClassPass": classpass,
                    "Total": total,
                })

            if studio_data:
                sdf = pd.DataFrame(studio_data).set_index("Studio")
                st.dataframe(
                    sdf.style.format("${:,.0f}"),
                    use_container_width=True,
                )

                # Bar chart
                fig = go.Figure()
                studios = sdf.index.tolist()
                fig.add_trace(go.Bar(x=studios, y=sdf["Earned"], name="Earned", marker_color="#2ecc71"))
                fig.add_trace(go.Bar(x=studios, y=sdf["ClassPass"], name="ClassPass", marker_color="#3498db"))
                fig.add_trace(go.Bar(x=studios, y=sdf["Breakage"], name="Breakage", marker_color="#f39c12"))
                fig.update_layout(
                    barmode="stack", height=350, margin=dict(t=10, b=30),
                    yaxis_tickformat="$,.0f",
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Click 'Pull Latest Data' to fetch current-month revenue from Snowflake.")

    # =====================================================================
    # TAB 2: Forecast vs Actuals Variance
    # =====================================================================
    with tab_variance:
        st.subheader("Forecast vs Actuals Variance")

        actuals_months = ds.get_actuals_months()
        studio_pls = ds.get_actuals_studio_pls()
        sales_forecast = ds.get_sales_forecast()

        # Get actuals by studio
        actuals_grid = get_actuals_cash_sales_by_studio(studio_pls, actuals_months)

        # Compare forecast vs actuals for closed months
        # Only show months where we have both forecast and actuals
        forecast_cols = list(sales_forecast.columns) if not sales_forecast.empty else []
        common_months = sorted(set(actuals_months) & set(forecast_cols))

        if not common_months:
            st.info("No overlapping months between forecast and actuals. Forecast starts after last actuals month.")
        else:
            st.caption(f"Comparing {len(common_months)} months where forecast overlaps with actuals")

            # Build variance table
            studios = list(ACTIVE_STUDIOS.keys())
            variance_data = []
            for code in studios:
                name = ACTIVE_STUDIOS[code]
                for m in common_months[-6:]:  # last 6 common months
                    actual = actuals_grid.loc[code, m] if code in actuals_grid.index and m in actuals_grid.columns else 0
                    forecast = sales_forecast.loc[code, m] if code in sales_forecast.index and m in sales_forecast.columns else 0
                    variance = actual - forecast
                    pct = (variance / forecast * 100) if forecast != 0 else 0
                    variance_data.append({
                        "Studio": name, "Month": month_display(m),
                        "Actual": actual, "Forecast": forecast,
                        "Variance": variance, "Var %": pct,
                    })

            if variance_data:
                vdf = pd.DataFrame(variance_data)
                # Pivot for display
                for metric in ["Actual", "Forecast", "Variance"]:
                    pivot = vdf.pivot(index="Studio", columns="Month", values=metric)
                    st.markdown(f"**{metric}**")
                    fmt = "${:,.0f}" if metric != "Var %" else "{:.1f}%"
                    st.dataframe(pivot.style.format("${:,.0f}"), use_container_width=True)

                # Variance heatmap
                var_pivot = vdf.pivot(index="Studio", columns="Month", values="Var %")
                fig = go.Figure(data=go.Heatmap(
                    z=var_pivot.values,
                    x=var_pivot.columns.tolist(),
                    y=var_pivot.index.tolist(),
                    colorscale=[[0, "#e74c3c"], [0.5, "#ffffff"], [1, "#2ecc71"]],
                    zmid=0,
                    text=[[f"{v:.0f}%" for v in row] for row in var_pivot.values],
                    texttemplate="%{text}",
                    hovertemplate="Studio: %{y}<br>Month: %{x}<br>Variance: %{text}<extra></extra>",
                ))
                fig.update_layout(
                    title="Variance % Heatmap (Green = Over Forecast)",
                    height=400, margin=dict(t=40, b=30),
                )
                st.plotly_chart(fig, use_container_width=True)

    # =====================================================================
    # TAB 3: Import Financials
    # =====================================================================
    with tab_import:
        st.subheader("Import Accountant Financial Package")
        st.caption(f"Current actuals through: **{last_actuals}**")

        uploaded = st.file_uploader(
            "Upload the accountant's Excel file",
            type=["xlsx"],
            key="actuals_upload",
        )

        if uploaded:
            import tempfile
            from pipeline.accountant_import import import_financials, print_summary

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name

            if st.button("Import", type="primary"):
                with st.spinner("Importing..."):
                    try:
                        result = import_financials(tmp_path)
                        meta = result["metadata"]
                        st.success(f"Imported through {meta['last_actuals_month']}")
                        st.json(meta)

                        # Reload data store
                        ds.reload()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")

        # Show what's currently loaded
        st.divider()
        st.subheader("Currently Loaded Data")

        col1, col2, col3 = st.columns(3)
        with col1:
            pl = ds.get_actuals_pl()
            st.metric("P&L Rows", len(pl) if not pl.empty else 0)
        with col2:
            bs = ds.get_actuals_bs()
            st.metric("BS Rows", len(bs) if not bs.empty else 0)
        with col3:
            st.metric("Studio P&Ls", len(ds.get_actuals_studio_pls()))

        st.caption(f"Months: {ds.get_actuals_months()[0] if ds.get_actuals_months() else 'N/A'} through {last_key}")
