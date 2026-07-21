"""
Studio Assumptions page — per-studio sales and payroll forecast editor.
Shows prior month actual + trailing 3-month average as context for each input.
"""

import streamlit as st
import pandas as pd
import numpy as np

from dashboard.data_store import DataStore
from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS, OVERHEAD,
    OPEX_CATEGORIES, month_display, parse_accountant_month,
)
from dashboard.financial_calcs import (
    get_actuals_cash_sales_by_studio,
    get_actuals_opex_breakdown,
)


def show():
    ds = DataStore.get()

    last_actuals = ds.get_last_actuals_month()
    last_key = ds.get_last_actuals_month_key()
    st.caption(f"Actuals through **{last_actuals}** | Edit forecast values below")

    # Seed from actuals button
    col_seed1, col_seed2 = st.columns([1, 4])
    with col_seed1:
        if st.button("Seed Forecast from Actuals", type="primary"):
            n_opex, n_sales = ds.seed_forecast_from_actuals()
            st.success(f"Seeded {n_opex} studios (OpEx) + {n_sales} studios (Sales) from trailing 3-month average")
            st.rerun()
    with col_seed2:
        st.caption("Sets all forecast months to the trailing 3-month actuals average. You can edit individual values after.")

    # Get actuals for context
    actuals_months = ds.get_actuals_months()
    studio_pls = ds.get_actuals_studio_pls()
    actuals_pl = ds.get_actuals_pl()

    # Per-studio actuals cash sales
    actuals_sales = get_actuals_cash_sales_by_studio(studio_pls, actuals_months)

    # Per-studio actuals opex (from studio P&Ls)
    studio_opex_actuals = _get_studio_opex_actuals(studio_pls, actuals_months)

    # Current forecasts from data store
    sales_forecast = ds.get_sales_forecast()
    opex_assumptions = ds.get_opex_assumptions()
    staff_detail = ds.merged.get("staff_detail", {})
    forecast_months = ds.get_forecast_months()

    # Studio selector
    all_studios = list(ACTIVE_STUDIOS.items()) + list(DEVELOPMENT_STUDIOS.items()) + list(OVERHEAD.items())
    studio_options = [f"{code} - {name}" for code, name in all_studios]
    selected = st.selectbox("Select Studio", studio_options)
    studio_code = selected.split(" - ")[0]
    studio_name = selected.split(" - ")[1]

    st.divider()

    # Compute context metrics
    prior_month = actuals_months[-1] if actuals_months else None
    trailing_3 = actuals_months[-3:] if len(actuals_months) >= 3 else actuals_months

    tab_sales, tab_payroll, tab_opex = st.tabs(["Sales Forecast", "Payroll / Staff Costs", "Other OpEx"])

    # =====================================================================
    # TAB 1: SALES FORECAST
    # =====================================================================
    with tab_sales:
        st.subheader(f"Cash Sales Forecast — {studio_name}")

        # Context metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            prior_val = _get_studio_actual_sales(actuals_sales, studio_code, prior_month)
            st.metric("Prior Month Actual", f"${prior_val:,.0f}",
                       delta=month_display(prior_month) if prior_month else "N/A",
                       delta_color="off")
        with col2:
            avg_3 = np.mean([_get_studio_actual_sales(actuals_sales, studio_code, m) for m in trailing_3]) if trailing_3 else 0
            st.metric("Trailing 3-Month Avg", f"${avg_3:,.0f}")
        with col3:
            avg_6 = np.mean([_get_studio_actual_sales(actuals_sales, studio_code, m) for m in actuals_months[-6:]]) if len(actuals_months) >= 6 else avg_3
            st.metric("Trailing 6-Month Avg", f"${avg_6:,.0f}")

        st.caption("Edit monthly sales forecast below. Values are total cash sales (sessions + breakage + retail, net of refunds & discounts).")

        # Editable forecast — show 12 months at a time
        visible_months = forecast_months[:12]
        cols_per_row = 6

        changed = False
        new_values = {}

        for row_start in range(0, len(visible_months), cols_per_row):
            row_months = visible_months[row_start:row_start + cols_per_row]
            cols = st.columns(len(row_months))
            for i, m in enumerate(row_months):
                with cols[i]:
                    current = sales_forecast.loc[studio_code, m] if studio_code in sales_forecast.index and m in sales_forecast.columns else 0
                    new_val = st.number_input(
                        month_display(m),
                        value=int(current),
                        step=1000,
                        min_value=0,
                        key=f"sales_{studio_code}_{m}",
                    )
                    new_values[m] = float(new_val)
                    if abs(new_val - current) > 0.01:
                        changed = True

        if changed and st.button("Save Sales Forecast", type="primary", key="save_sales"):
            if "sales_forecast" not in ds.overrides:
                ds.overrides["sales_forecast"] = {}
            if studio_code not in ds.overrides["sales_forecast"]:
                ds.overrides["sales_forecast"][studio_code] = {}
            for m, val in new_values.items():
                ds.overrides["sales_forecast"][studio_code][m] = val
            ds.merged = ds._deep_merge(ds.baseline, ds.overrides)
            ds.save_overrides()
            st.success(f"Sales forecast saved for {studio_name}.")
            st.rerun()

    # =====================================================================
    # TAB 2: PAYROLL / STAFF COSTS
    # =====================================================================
    with tab_payroll:
        st.subheader(f"Staff Costs — {studio_name}")

        # Context: actuals payroll
        studio_payroll_actuals = studio_opex_actuals.get(studio_code, {}).get("staff", {})

        col1, col2, col3 = st.columns(3)
        with col1:
            prior_payroll = studio_payroll_actuals.get(prior_month, 0) if prior_month else 0
            st.metric("Prior Month Actual", f"${prior_payroll:,.0f}",
                       delta=month_display(prior_month) if prior_month else "N/A",
                       delta_color="off")
        with col2:
            avg_3_payroll = np.mean([studio_payroll_actuals.get(m, 0) for m in trailing_3]) if trailing_3 else 0
            st.metric("Trailing 3-Month Avg", f"${avg_3_payroll:,.0f}")
        with col3:
            # Current forecast from G&A assumptions
            current_staff = _get_opex_value(opex_assumptions, studio_code, "staff", forecast_months[0])
            st.metric("Current Forecast", f"${current_staff:,.0f}",
                       delta=f"{'vs ' + month_display(prior_month) + ': '}{_pct_diff(current_staff, prior_payroll)}" if prior_payroll else None,
                       delta_color="off")

        # Staff detail breakdown (from G&A Assumptions tab)
        detail = staff_detail.get(studio_code, {})
        if detail:
            st.caption("Line-item breakdown from the Excel model (monthly amounts):")
            detail_items = sorted(detail.items(), key=lambda x: -x[1])
            for item_name, val in detail_items:
                if val > 0:
                    st.text(f"  {item_name:<55} ${val:>10,.2f}")
            st.text(f"  {'TOTAL':<55} ${sum(v for v in detail.values()):>10,.2f}")

        st.divider()
        st.caption("Adjust the total staff cost forecast per month:")

        # Editable total staff cost
        visible_months = forecast_months[:12]
        staff_changed = False
        new_staff = {}

        for row_start in range(0, len(visible_months), 6):
            row_months = visible_months[row_start:row_start + 6]
            cols = st.columns(len(row_months))
            for i, m in enumerate(row_months):
                with cols[i]:
                    current = _get_opex_value(opex_assumptions, studio_code, "staff", m)
                    new_val = st.number_input(
                        month_display(m),
                        value=int(current),
                        step=500,
                        min_value=0,
                        key=f"staff_{studio_code}_{m}",
                    )
                    new_staff[m] = float(new_val)
                    if abs(new_val - current) > 0.01:
                        staff_changed = True

        if staff_changed and st.button("Save Staff Costs", type="primary", key="save_staff"):
            if "opex_assumptions" not in ds.overrides:
                ds.overrides["opex_assumptions"] = {}
            if studio_code not in ds.overrides["opex_assumptions"]:
                ds.overrides["opex_assumptions"][studio_code] = {}
            if "staff" not in ds.overrides["opex_assumptions"][studio_code]:
                ds.overrides["opex_assumptions"][studio_code]["staff"] = {}
            for m, val in new_staff.items():
                ds.overrides["opex_assumptions"][studio_code]["staff"][m] = val
            ds.merged = ds._deep_merge(ds.baseline, ds.overrides)
            ds.save_overrides()
            st.success(f"Staff costs saved for {studio_name}.")
            st.rerun()

    # =====================================================================
    # TAB 3: OTHER OPEX
    # =====================================================================
    with tab_opex:
        st.subheader(f"Other Operating Expenses — {studio_name}")

        # Show all opex categories with actuals context
        opex_cats = [
            ("property", "Property Costs"),
            ("utilities", "Utilities"),
            ("maintenance", "Facility & Equipment Maintenance"),
            ("marketing", "Marketing & Promotion"),
            ("admin", "Administrative & G&A"),
            ("professional_fees", "Professional Fees"),
            ("travel", "Travel & Meals"),
            ("finance", "Merchant Fees / Finance"),
            ("startup", "Studio Start Up Costs"),
        ]

        opex_changed = False
        new_opex = {}

        for cat_key, cat_label in opex_cats:
            cat_actuals = studio_opex_actuals.get(studio_code, {}).get(cat_key, {})
            prior_cat = cat_actuals.get(prior_month, 0) if prior_month else 0
            avg_3_cat = np.mean([cat_actuals.get(m, 0) for m in trailing_3]) if trailing_3 else 0
            current_forecast = _get_opex_value(opex_assumptions, studio_code, cat_key, forecast_months[0])

            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            with col1:
                st.markdown(f"**{cat_label}**")
            with col2:
                st.caption(f"Prior: ${prior_cat:,.0f}")
            with col3:
                st.caption(f"3mo avg: ${avg_3_cat:,.0f}")
            with col4:
                new_val = st.number_input(
                    "Monthly forecast",
                    value=int(current_forecast),
                    step=100,
                    min_value=0,
                    key=f"opex_{studio_code}_{cat_key}",
                    label_visibility="collapsed",
                )
                if abs(new_val - current_forecast) > 0.01:
                    opex_changed = True
                new_opex[cat_key] = float(new_val)

        # Total
        total_forecast = sum(new_opex.values())
        total_prior = sum(studio_opex_actuals.get(studio_code, {}).get(k, {}).get(prior_month, 0) for k, _ in opex_cats) if prior_month else 0
        st.divider()
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        with col1:
            st.markdown(f"**TOTAL OpEx (excl. staff)**")
        with col2:
            st.caption(f"Prior: ${total_prior:,.0f}")
        with col4:
            st.markdown(f"**${total_forecast:,.0f}**")

        if opex_changed and st.button("Save OpEx", type="primary", key="save_opex"):
            if "opex_assumptions" not in ds.overrides:
                ds.overrides["opex_assumptions"] = {}
            if studio_code not in ds.overrides["opex_assumptions"]:
                ds.overrides["opex_assumptions"][studio_code] = {}
            for cat_key, val in new_opex.items():
                if val > 0:
                    # Apply to all forecast months
                    ds.overrides["opex_assumptions"][studio_code][cat_key] = {
                        m: val for m in forecast_months
                    }
            ds.merged = ds._deep_merge(ds.baseline, ds.overrides)
            ds.save_overrides()
            st.success(f"OpEx saved for {studio_name}.")
            st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_studio_actual_sales(actuals_sales: pd.DataFrame, code: str, month: str) -> float:
    if actuals_sales.empty or code not in actuals_sales.index or month not in actuals_sales.columns:
        return 0.0
    return float(actuals_sales.loc[code, month])


def _get_opex_value(opex_assumptions: dict, studio: str, category: str, month: str) -> float:
    return float(opex_assumptions.get(studio, {}).get(category, {}).get(month, 0))


def _pct_diff(forecast: float, actual: float) -> str:
    if actual == 0:
        return ""
    diff = (forecast - actual) / actual * 100
    return f"{diff:+.0f}%"


def _get_studio_opex_actuals(studio_pls: dict, months: list) -> dict:
    """
    Extract per-studio opex by category from studio P&Ls.
    Returns {studio_code: {opex_category: {month: value}}}.
    """
    from dashboard.constants import PL_TO_OPEX_CATEGORY

    label_to_pl = {
        "Total 700000 Property Costs": "property_costs",
        "Total for 700000 Property Costs": "property_costs",
        "Total 602000 Payroll": "payroll",
        "Total for 602000 Payroll": "payroll",
        "Total 616000 Utilities": "utilities",
        "Total for 616000 Utilities": "utilities",
        "Total 601000 Sales & Marketing": "marketing",
        "Total for 601000 Sales & Marketing": "marketing",
        "Total 604000 Professional Fees": "professional_fees",
        "Total for 604000 Professional Fees": "professional_fees",
        "506000 Merchant Account Fees": "finance_merchant",
        "Total Cost of goods sold": "finance_cogs",
        "Total for Cost of goods sold": "finance_cogs",
    }

    # Map pl_key -> opex_category
    pl_to_cat = {
        "property_costs": "property",
        "payroll": "staff",
        "utilities": "utilities",
        "marketing": "marketing",
        "professional_fees": "professional_fees",
        "finance_merchant": "finance",
        "finance_cogs": "finance",
    }

    result = {}
    for code, studio_data in studio_pls.items():
        sp = studio_data["data"]
        if sp.empty:
            continue
        result[code] = {}

        for label, pl_key in label_to_pl.items():
            cat = pl_to_cat.get(pl_key)
            if not cat:
                continue
            if cat not in result[code]:
                result[code][cat] = {}

            if label in sp.index:
                for col in sp.columns:
                    mk = parse_accountant_month(col)
                    if mk and mk in months:
                        val = sp.loc[label, col]
                        if pd.notna(val):
                            result[code][cat][mk] = result[code][cat].get(mk, 0) + abs(float(val))

    return result
