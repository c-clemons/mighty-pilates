"""
New Studio Planner — model startup costs, TI, sales ramp, and OpEx for new studios.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from dashboard.data_store import DataStore
from dashboard.constants import (
    DEVELOPMENT_STUDIOS, PIPELINE_STUDIOS, STUDIO_TIERS, STUDIO_TYPES,
    month_key, month_display,
)


def show():
    ds = DataStore.get()
    st.header("New Studio Planner")

    templates = ds.merged.get("new_studio_templates", {})
    if not templates:
        st.warning("No studio templates found in baseline. Check baseline.json.")
        return

    # Current new studio configs from overrides
    new_studios = ds.merged.get("new_studios", {})
    forecast_months = ds.get_forecast_months()

    # --- Studio Setup ---
    st.subheader("Configure New Studio")

    available_studios = {**DEVELOPMENT_STUDIOS, **PIPELINE_STUDIOS}
    # Also allow custom
    studio_options = list(available_studios.keys()) + ["Custom"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        studio_code = st.selectbox("Studio", studio_options,
                                    format_func=lambda x: f"{x} - {available_studios.get(x, 'Custom')}")
    with col2:
        tier = st.selectbox("Tier", STUDIO_TIERS)
    with col3:
        studio_type = st.selectbox("Type", STUDIO_TYPES)
    with col4:
        open_year = st.selectbox("Open Year", [2026, 2027, 2028])
        open_month = st.selectbox("Open Month", list(range(1, 13)), index=5)

    if studio_code == "Custom":
        custom_name = st.text_input("Studio Name", "New Studio")
    else:
        custom_name = available_studios.get(studio_code, studio_code)

    open_date = month_key(open_year, open_month)
    template_key = f"{tier} {studio_type}"

    if template_key not in templates:
        st.error(f"Template '{template_key}' not found.")
        return

    template = templates[template_key]

    # Check if this studio already exists in config
    existing = new_studios.get(studio_code, {})
    enabled = existing.get("enabled", False)

    include = st.toggle(
        f"Include {custom_name} in forecast",
        value=enabled,
        key=f"toggle_{studio_code}",
    )

    st.divider()

    # --- Apply Template ---
    # Convert relative month offsets to absolute months
    sales_ramp = _apply_template(template["sales_ramp"], open_date)
    opex_ramps = {}
    for cat, ramp in template["opex_ramp"].items():
        opex_ramps[cat] = _apply_template(ramp, open_date)

    # --- Sales Ramp ---
    st.subheader("Sales Ramp")

    # Show as a chart + editable table
    ramp_months = sorted(sales_ramp.keys())
    display_months = ramp_months[:18]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[month_display(m) for m in display_months],
        y=[sales_ramp.get(m, 0) for m in display_months],
        marker_color="#2ecc71", name="Sales",
    ))

    # Add cumulative OpEx line
    total_opex = {}
    for m in display_months:
        total_opex[m] = sum(opex_ramps.get(cat, {}).get(m, 0) for cat in opex_ramps if cat not in ("ti", "startup"))
    fig.add_trace(go.Scatter(
        x=[month_display(m) for m in display_months],
        y=[total_opex[m] for m in display_months],
        mode="lines+markers", name="Monthly OpEx",
        line=dict(color="#e74c3c", width=2),
    ))

    fig.update_layout(
        height=350, margin=dict(t=10, b=30),
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", y=1.1),
        barmode="group",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Editable ramp values
    with st.expander("Edit Sales Ramp", expanded=False):
        cols_per_row = 6
        edited_sales = {}
        for row_start in range(0, len(display_months), cols_per_row):
            row_months = display_months[row_start:row_start + cols_per_row]
            cols = st.columns(len(row_months))
            for i, m in enumerate(row_months):
                with cols[i]:
                    v = st.number_input(
                        month_display(m), value=int(sales_ramp.get(m, 0)),
                        step=5000, min_value=0, key=f"ns_sales_{studio_code}_{m}",
                    )
                    edited_sales[m] = float(v)

    # --- Cost Summary ---
    st.subheader("Cost Summary")

    # TI + Startup
    ti_total = sum(opex_ramps.get("ti", {}).values())
    startup_total = sum(opex_ramps.get("startup", {}).values())
    yr1_opex = sum(total_opex.get(m, 0) for m in display_months[:12])
    yr1_sales = sum(sales_ramp.get(m, 0) for m in display_months[:12])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("TI Costs", f"${ti_total:,.0f}")
    with col2:
        st.metric("Startup Costs", f"${startup_total:,.0f}")
    with col3:
        st.metric("Year 1 Sales", f"${yr1_sales:,.0f}")
    with col4:
        st.metric("Year 1 OpEx", f"${yr1_opex:,.0f}")

    # OpEx breakdown table
    opex_display = {}
    operating_cats = [c for c in opex_ramps if c not in ("ti", "startup")]
    for cat in operating_cats:
        monthly_avg = np.mean([opex_ramps[cat].get(m, 0) for m in display_months[:12] if opex_ramps[cat].get(m, 0) > 0])
        opex_display[cat] = monthly_avg if not np.isnan(monthly_avg) else 0

    with st.expander("Monthly OpEx Breakdown"):
        for cat, avg in sorted(opex_display.items(), key=lambda x: -x[1]):
            if avg > 0:
                st.text(f"  {cat:<25} ${avg:>10,.0f}/mo")
        st.text(f"  {'TOTAL':<25} ${sum(opex_display.values()):>10,.0f}/mo")

    # --- Cash Needs Timeline ---
    st.subheader("Cash Needs Timeline")

    cash_needs = {}
    for m in ramp_months[:18]:
        ti = opex_ramps.get("ti", {}).get(m, 0)
        startup = opex_ramps.get("startup", {}).get(m, 0)
        opex = total_opex.get(m, 0)
        sales = sales_ramp.get(m, 0)
        cash_needs[m] = -(ti + startup + opex) + sales

    fig2 = go.Figure()
    cum_cash = 0
    cum_values = []
    for m in display_months:
        cum_cash += cash_needs.get(m, 0)
        cum_values.append(cum_cash)

    fig2.add_trace(go.Bar(
        x=[month_display(m) for m in display_months],
        y=[cash_needs.get(m, 0) for m in display_months],
        marker_color=["#2ecc71" if cash_needs.get(m, 0) >= 0 else "#e74c3c" for m in display_months],
        name="Monthly Net",
    ))
    fig2.add_trace(go.Scatter(
        x=[month_display(m) for m in display_months],
        y=cum_values,
        mode="lines+markers", name="Cumulative",
        line=dict(color="#2c3e50", width=2),
    ))
    fig2.update_layout(
        height=350, margin=dict(t=10, b=30),
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig2, use_container_width=True)

    breakeven_month = None
    cum = 0
    for m in ramp_months:
        cum += cash_needs.get(m, 0)
        if cum > 0 and breakeven_month is None:
            breakeven_month = m
            break

    total_investment = ti_total + startup_total
    if breakeven_month:
        st.success(f"Cumulative cash-positive by **{month_display(breakeven_month)}** | Total pre-open investment: **${total_investment:,.0f}**")
    else:
        st.warning(f"Studio does not reach cumulative cash-positive within 18 months | Total pre-open investment: **${total_investment:,.0f}**")

    st.divider()

    # --- Save ---
    if st.button("Save Studio Configuration", type="primary"):
        studio_config = {
            "name": custom_name,
            "code": studio_code,
            "tier": tier,
            "type": studio_type,
            "template_key": template_key,
            "open_date": open_date,
            "enabled": include,
            "sales_ramp": edited_sales if "edited_sales" in dir() and edited_sales else sales_ramp,
            "opex_ramps": opex_ramps,
        }

        if "new_studios" not in ds.overrides:
            ds.overrides["new_studios"] = {}
        ds.overrides["new_studios"][studio_code] = studio_config

        # If enabled, add to sales forecast and opex assumptions
        if include:
            if "sales_forecast" not in ds.overrides:
                ds.overrides["sales_forecast"] = {}
            ds.overrides["sales_forecast"][studio_code] = studio_config["sales_ramp"]

            if "opex_assumptions" not in ds.overrides:
                ds.overrides["opex_assumptions"] = {}
            ds.overrides["opex_assumptions"][studio_code] = {}
            for cat, ramp in opex_ramps.items():
                if cat not in ("ti", "startup"):
                    ds.overrides["opex_assumptions"][studio_code][cat] = ramp

            # Add TI + startup as capex
            if "capex" not in ds.overrides:
                ds.overrides["capex"] = {}
            capex_by_month = {}
            for m in ramp_months:
                ti = opex_ramps.get("ti", {}).get(m, 0)
                startup = opex_ramps.get("startup", {}).get(m, 0)
                if ti + startup > 0:
                    capex_by_month[m] = ti + startup
            ds.overrides["capex"][studio_code] = capex_by_month

        ds.merged = ds._deep_merge(ds.baseline, ds.overrides)
        ds.save_overrides()
        st.success(f"{'Enabled' if include else 'Saved (disabled)'}: {custom_name} opening {month_display(open_date)}")
        st.rerun()


def _apply_template(ramp: dict, open_date: str) -> dict:
    """Convert relative month offsets to absolute month keys."""
    oy, om = map(int, open_date.split("-"))
    result = {}
    for offset_str, value in ramp.items():
        offset = int(float(offset_str))
        # Month 0 = open_date, -1 = one month before, 1 = one month after
        if offset <= 0:
            # Pre-open: offset from open_date
            abs_m = om + offset
            abs_y = oy
        else:
            # Post-open: month 1 = open_date, month 2 = one after, etc.
            abs_m = om + (offset - 1)
            abs_y = oy

        while abs_m > 12:
            abs_m -= 12
            abs_y += 1
        while abs_m < 1:
            abs_m += 12
            abs_y -= 1

        result[month_key(abs_y, abs_m)] = value

    return result
