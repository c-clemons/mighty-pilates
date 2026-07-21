"""
Scenarios page — save, load, and compare named forecast scenarios.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import copy

from dashboard.data_store import DataStore
from dashboard.constants import month_display, ACTIVE_STUDIOS
from dashboard.financial_calcs import (
    build_monthly_cash_sales,
    build_cash_flow_forecast,
)


def show():
    ds = DataStore.get()

    tab_manage, tab_compare = st.tabs(["Manage Scenarios", "Compare Scenarios"])

    # =====================================================================
    # TAB 1: Manage
    # =====================================================================
    with tab_manage:
        st.subheader("Save Current Forecast as Scenario")

        col1, col2 = st.columns([3, 1])
        with col1:
            name = st.text_input("Scenario Name", placeholder="e.g., Base Case Q2 2026")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Save Scenario", type="primary") and name:
                clean_name = name.strip().replace(" ", "_").lower()
                ds.save_scenario(clean_name)
                st.success(f"Saved: {name}")
                st.rerun()

        st.divider()
        st.subheader("Saved Scenarios")

        scenarios = ds.list_scenarios()
        if not scenarios:
            st.info("No scenarios saved yet. Make changes to the forecast and save a scenario above.")
        else:
            for sc in scenarios:
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.markdown(f"**{sc['name']}**")
                with col2:
                    st.caption(f"Saved: {sc['saved_at'][:16]}")
                with col3:
                    if st.button("Load", key=f"load_{sc['name']}"):
                        ds.load_scenario(sc["name"])
                        st.success(f"Loaded: {sc['name']}")
                        st.rerun()
                    if st.button("Delete", key=f"del_{sc['name']}"):
                        ds.delete_scenario(sc["name"])
                        st.rerun()

    # =====================================================================
    # TAB 2: Compare
    # =====================================================================
    with tab_compare:
        st.subheader("Compare Scenarios")

        scenarios = ds.list_scenarios()
        if len(scenarios) < 1:
            st.info("Save at least one scenario to compare against the current forecast.")
            return

        scenario_names = [sc["name"] for sc in scenarios]
        selected = st.multiselect(
            "Select scenarios to compare (current forecast always included)",
            scenario_names,
            default=scenario_names[:2] if len(scenario_names) >= 2 else scenario_names,
        )

        if not selected:
            return

        # Build cash flow for current forecast
        results = {}
        results["Current"] = _build_cf(ds)

        # Build cash flow for each selected scenario
        for sc_name in selected:
            sc_ds = _load_scenario_ds(ds, sc_name)
            if sc_ds:
                results[sc_name] = _build_cf(sc_ds)

        forecast_months = ds.get_forecast_months()[:18]

        # --- Ending Cash Comparison ---
        st.subheader("Ending Cash Balance")
        fig = go.Figure()
        colors = ["#2c3e50", "#e74c3c", "#2ecc71", "#3498db", "#f39c12"]
        for i, (name, cf) in enumerate(results.items()):
            vals = [cf.loc["Ending Cash", m] for m in forecast_months if m in cf.columns]
            months = [month_display(m) for m in forecast_months if m in cf.columns]
            fig.add_trace(go.Scatter(
                x=months, y=vals,
                mode="lines+markers", name=name,
                line=dict(color=colors[i % len(colors)], width=2 if i == 0 else 1.5),
            ))

        fig.update_layout(
            height=400, margin=dict(t=10, b=30),
            yaxis_tickformat="$,.0f",
            legend=dict(orientation="h", y=1.1),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Key Metrics Comparison Table ---
        st.subheader("Key Metrics (12-Month Forward)")

        metrics_data = []
        for name, cf in results.items():
            fm12 = forecast_months[:12]
            fm_in_cf = [m for m in fm12 if m in cf.columns]
            total_rev = sum(cf.loc["Total Cash Sales", m] for m in fm_in_cf)
            total_opex = sum(cf.loc["Total Operating Expenses", m] for m in fm_in_cf)
            net_ops = sum(cf.loc["Net Cash from Operations", m] for m in fm_in_cf)
            end_cash = cf.loc["Ending Cash", fm_in_cf[-1]] if fm_in_cf else 0
            min_cash = min(cf.loc["Ending Cash", m] for m in fm_in_cf) if fm_in_cf else 0

            metrics_data.append({
                "Scenario": name,
                "12-Mo Revenue": total_rev,
                "12-Mo OpEx": total_opex,
                "12-Mo Net Cash from Ops": net_ops,
                "Ending Cash (12 mo)": end_cash,
                "Lowest Cash Point": min_cash,
            })

        mdf = pd.DataFrame(metrics_data).set_index("Scenario")
        st.dataframe(mdf.style.format("${:,.0f}"), use_container_width=True)

        # --- Monthly Net Cash Comparison ---
        st.subheader("Monthly Net Cash from Operations")
        fig2 = go.Figure()
        for i, (name, cf) in enumerate(results.items()):
            vals = [cf.loc["Net Cash from Operations", m] for m in forecast_months if m in cf.columns]
            months = [month_display(m) for m in forecast_months if m in cf.columns]
            fig2.add_trace(go.Bar(
                x=months, y=vals, name=name,
                marker_color=colors[i % len(colors)], opacity=0.7,
            ))
        fig2.update_layout(
            barmode="group", height=350, margin=dict(t=10, b=30),
            yaxis_tickformat="$,.0f",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig2, use_container_width=True)


def _build_cf(ds: DataStore) -> pd.DataFrame:
    """Build cash flow from a DataStore instance."""
    cash_sales = build_monthly_cash_sales(
        ds.get_sales_forecast(), ds.get_actuals_pl(),
        ds.get_actuals_studio_pls(), ds.get_last_actuals_month(),
    )
    return build_cash_flow_forecast(
        cash_sales=cash_sales,
        opex_assumptions=ds.get_opex_assumptions(),
        loans=ds.get_loans(),
        actuals_pl=ds.get_actuals_pl(),
        actuals_scf=ds.get_actuals_scf(),
        actuals_bs=ds.get_actuals_bs(),
        last_actuals_month=ds.get_last_actuals_month(),
    )


def _load_scenario_ds(base_ds: DataStore, scenario_name: str):
    """Create a temporary DataStore-like object with scenario overrides."""
    scenario_path = base_ds._instance._load_json(
        DataStore._instance.baseline.__class__.__mro__[0]  # hacky
    ) if False else None

    # Simpler approach: load scenario JSON and merge with baseline
    from pathlib import Path
    scenario_file = Path(__file__).parent.parent / "data" / "scenarios" / f"{scenario_name}.json"
    if not scenario_file.exists():
        return None

    import json
    with open(scenario_file) as f:
        sc_overrides = json.load(f)

    # Create a lightweight DS copy
    sc_ds = DataStore.__new__(DataStore)
    sc_ds.baseline = base_ds.baseline
    sc_ds.overrides = sc_overrides
    sc_ds.merged = DataStore._deep_merge(base_ds.baseline, sc_overrides)
    sc_ds.actuals = base_ds.actuals
    sc_ds._loaded = True
    return sc_ds
