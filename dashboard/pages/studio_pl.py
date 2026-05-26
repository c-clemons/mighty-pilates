"""
P&L page — consolidated and per-studio with actuals + forecast.
Uses historical ratios to forecast breakage, refunds, discounts.
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
    calculate_studio_contribution,
)

# Header rows — these are section labels, not data
HEADER_ROWS = {
    "Income", "401000 Sessions", "403000 Breakage Revenue",
    "Cost of Goods Sold", "Cost of goods sold", "Expenses",
    "601000 Sales & Marketing", "602000 Payroll", "604000 Professional Fees",
    "616000 Utilities", "700000 Property Costs", "Other Expenses",
}

# Summary P&L structure for the compact view
SUMMARY_ROWS = [
    ("Total for 401000 Sessions", "Session Revenue"),
    ("Total for 403000 Breakage Revenue", "Breakage Revenue"),
    ("404000 Retail Sales", "Retail Sales"),
    ("406000 Refunds", "Refunds"),
    ("407000 Discounts", "Discounts"),
    ("Total for Income", "Total Revenue"),
    ("Total for Cost of Goods Sold", "COGS & Merchant Fees"),
    ("Gross Profit", "Gross Profit"),
    ("Total for 601000 Sales & Marketing", "Marketing"),
    ("Total for 602000 Payroll", "Payroll"),
    ("603000 Software & Web Services", "Software"),
    ("Total for 604000 Professional Fees", "Professional Fees"),
    ("Total for 616000 Utilities", "Utilities"),
    ("Total for 700000 Property Costs", "Property Costs"),
    ("Total for Expenses", "Total Operating Expenses"),
    ("Net Operating Income", "Net Operating Income"),
    ("810000 Depreciation", "Depreciation"),
    ("901000 Interest Expense/(Income)", "Interest Expense"),
    ("902000 Taxes Paid", "Taxes Paid"),
    ("903000 Property taxes", "Property Taxes"),
    ("Total for Other Expenses", "Total Other Expenses"),
    ("Net Income", "Net Income"),
]

# Studio variants of the same labels
STUDIO_LABEL_VARIANTS = {
    "Total for 401000 Sessions": ["Total 401000 Sessions", "Total for 401000 Sessions"],
    "Total for 403000 Breakage Revenue": ["Total 403000 Breakage Revenue", "Total for 403000 Breakage Revenue"],
    "Total for Income": ["Total Income", "Total for Income"],
    "Total for Cost of Goods Sold": ["Total Cost of Goods Sold", "Total for Cost of Goods Sold"],
    "Total for 601000 Sales & Marketing": ["Total 601000 Sales & Marketing", "Total for 601000 Sales & Marketing"],
    "Total for 602000 Payroll": ["Total 602000 Payroll", "Total for 602000 Payroll"],
    "Total for 604000 Professional Fees": ["Total 604000 Professional Fees", "Total for 604000 Professional Fees"],
    "Total for 616000 Utilities": ["Total 616000 Utilities", "Total for 616000 Utilities"],
    "Total for 700000 Property Costs": ["Total 700000 Property Costs", "Total for 700000 Property Costs"],
    "Total for Expenses": ["Total Expenses", "Total for Expenses"],
    "Total for Other Expenses": ["Total Other Expenses", "Total for Other Expenses"],
}

BOLD_ROWS = {"Total Revenue", "Gross Profit", "Total Operating Expenses",
             "Net Operating Income", "Total Other Expenses", "Net Income"}


def _find_value(pl_df, label_key, col):
    """Find a value trying multiple label variants."""
    variants = STUDIO_LABEL_VARIANTS.get(label_key, [label_key])
    for v in variants:
        if v in pl_df.index:
            val = pl_df.loc[v, col]
            if pd.notna(val):
                return float(val)
    if label_key in pl_df.index:
        val = pl_df.loc[label_key, col]
        if pd.notna(val):
            return float(val)
    return 0.0


def _compute_ratios(pl_df, actuals_months):
    """Compute historical ratios from actuals for forecasting."""
    totals = {"sessions": 0, "breakage": 0, "retail": 0,
              "refunds": 0, "discounts": 0, "total_income": 0}
    below_line = {"depreciation": 0, "interest": 0, "taxes": 0, "prop_taxes": 0}

    n = 0
    for col in pl_df.columns:
        mk = parse_accountant_month(col)
        if mk and mk in actuals_months:
            n += 1
            totals["sessions"] += _find_value(pl_df, "Total for 401000 Sessions", col)
            totals["breakage"] += _find_value(pl_df, "Total for 403000 Breakage Revenue", col)
            totals["retail"] += _find_value(pl_df, "404000 Retail Sales", col)
            totals["refunds"] += _find_value(pl_df, "406000 Refunds", col)
            totals["discounts"] += _find_value(pl_df, "407000 Discounts", col)
            totals["total_income"] += _find_value(pl_df, "Total for Income", col)
            below_line["depreciation"] += abs(_find_value(pl_df, "810000 Depreciation", col))
            below_line["interest"] += abs(_find_value(pl_df, "901000 Interest Expense/(Income)", col))
            below_line["taxes"] += abs(_find_value(pl_df, "902000 Taxes Paid", col))
            below_line["prop_taxes"] += abs(_find_value(pl_df, "903000 Property taxes", col))

    if n == 0:
        return {}, {}

    sessions = totals["sessions"]
    ratios = {
        "breakage_pct": totals["breakage"] / sessions if sessions else 0,
        "retail_avg": totals["retail"] / n,
        "refund_pct": totals["refunds"] / totals["total_income"] if totals["total_income"] else 0,
        "discount_pct": totals["discounts"] / totals["total_income"] if totals["total_income"] else 0,
    }
    below_avg = {k: v / n for k, v in below_line.items()}
    return ratios, below_avg


def _build_revenue_forecast(ds, fc_months, is_consolidated, studio_code):
    """
    Convolve actual + forecasted sales with rev rec curves to project
    earned revenue and breakage per month.
    """
    curves = ds.get_rev_rec_curves()
    actual_sales = ds.get_monthly_sales()
    sales_forecast = ds.get_sales_forecast()

    earned_curve = {int(k): v / 100 for k, v in curves.get("earned", {}).items()}
    breakage_curve = {int(k): v / 100 for k, v in curves.get("breakage", {}).items()}
    refund_pct = curves.get("refund_pct", -1.8) / 100
    discount_pct = curves.get("discount_pct", -7.2) / 100

    # Build complete sales timeline (actuals + forecast)
    all_sales = dict(actual_sales)  # {month_key: amount}
    for m in fc_months:
        if m not in all_sales:
            if is_consolidated:
                all_sales[m] = sales_forecast[m].sum() if m in sales_forecast.columns else 0
            else:
                if studio_code in sales_forecast.index and m in sales_forecast.columns:
                    all_sales[m] = float(sales_forecast.loc[studio_code, m])
                else:
                    all_sales[m] = 0

    # For each forecast month, convolve: sum across all prior sale months
    result = {}
    for m in fc_months:
        y, mo = map(int, m.split("-"))
        earned = 0
        breakage = 0
        for lag, pct in earned_curve.items():
            # Which sale month feeds into this earned month at this lag?
            sale_mo = mo - lag
            sale_y = y
            while sale_mo < 1:
                sale_mo += 12
                sale_y -= 1
            from dashboard.constants import month_key
            sale_mk = month_key(sale_y, sale_mo)
            sales_val = all_sales.get(sale_mk, 0)
            earned += sales_val * pct

        for lag, pct in breakage_curve.items():
            sale_mo = mo - lag
            sale_y = y
            while sale_mo < 1:
                sale_mo += 12
                sale_y -= 1
            from dashboard.constants import month_key
            sale_mk = month_key(sale_y, sale_mo)
            sales_val = all_sales.get(sale_mk, 0)
            breakage += sales_val * pct

        gross = earned + breakage
        refunds = gross * refund_pct
        discounts = gross * discount_pct
        retail = _compute_ratios.__defaults__  # placeholder

        result[m] = {
            "sessions": earned,
            "breakage": breakage,
            "retail": 0,  # filled from trailing avg below
            "refunds": refunds,
            "discounts": discounts,
            "total": gross + refunds + discounts,
        }

    return result


def show():
    ds = DataStore.get()
    st.header("P&L")

    last_key = ds.get_last_actuals_month_key()
    actuals_months = ds.get_actuals_months()
    forecast_months = ds.get_forecast_months()
    studio_pls = ds.get_actuals_studio_pls()

    all_studios = list(ACTIVE_STUDIOS.items()) + list(DEVELOPMENT_STUDIOS.items()) + list(OVERHEAD.items())
    studio_options = ["Consolidated"] + [f"{code} - {name}" for code, name in all_studios]
    selected = st.selectbox("Select Studio", studio_options)

    col1, col2, col3 = st.columns(3)
    with col1:
        n_actuals = st.slider("Actuals months", 3, 14, min(6, len(actuals_months)), key="pl_nact")
    with col2:
        n_forecast = st.slider("Forecast months", 0, 12, 6, key="pl_nfc")
    with col3:
        detail_mode = st.toggle("Show detail rows", value=False, key="pl_detail")

    recent_actuals = actuals_months[-n_actuals:]
    fc_months = forecast_months[:n_forecast]

    is_consolidated = (selected == "Consolidated")
    pl_df = ds.get_actuals_pl() if is_consolidated else None
    studio_code = None
    studio_name = "All Studios"

    if not is_consolidated:
        studio_code = selected.split(" - ")[0]
        studio_name = selected.split(" - ")[1]
        if studio_code in studio_pls:
            pl_df = studio_pls[studio_code]["data"]

    if pl_df is None or pl_df.empty:
        st.info(f"No actuals data for {studio_name}.")
        return

    # Build revenue forecast from curves
    rev_forecast = _build_revenue_forecast(ds, fc_months, is_consolidated, studio_code)
    # Add retail trailing average
    ratios, below_avg = _compute_ratios(pl_df, recent_actuals[-3:])
    for m in rev_forecast:
        rev_forecast[m]["retail"] = ratios.get("retail_avg", 0)
        rev_forecast[m]["total"] += ratios.get("retail_avg", 0)

    # Revenue chart
    st.subheader("Revenue Trend")
    _render_revenue_chart_v2(pl_df, recent_actuals, fc_months, rev_forecast)

    # Build the P&L table
    st.subheader("P&L" if is_consolidated else f"{studio_name} P&L")

    opex_assumptions = ds.get_opex_assumptions()
    sales_forecast = ds.get_sales_forecast()

    if detail_mode:
        _render_detail_table(pl_df, recent_actuals, fc_months, ratios, below_avg,
                             opex_assumptions, sales_forecast, is_consolidated, studio_code,
                             rev_forecast=rev_forecast)
    else:
        _render_summary_table(pl_df, recent_actuals, fc_months, ratios, below_avg,
                              opex_assumptions, sales_forecast, is_consolidated, studio_code,
                              rev_forecast=rev_forecast)


def _get_forecast_revenue(sales_forecast, month, is_consolidated, studio_code):
    """Get total session revenue for a forecast month."""
    if is_consolidated:
        return sales_forecast[month].sum() if month in sales_forecast.columns else 0
    else:
        if studio_code in sales_forecast.index and month in sales_forecast.columns:
            return float(sales_forecast.loc[studio_code, month])
        return 0


def _get_forecast_opex(opex_assumptions, category, month, is_consolidated, studio_code):
    """Get opex for a forecast month."""
    if is_consolidated:
        total = 0
        for studio_data in opex_assumptions.values():
            if isinstance(studio_data, dict) and category in studio_data:
                val = studio_data[category].get(month, 0)
                if isinstance(val, (int, float)):
                    total += val
        return total
    else:
        return float(opex_assumptions.get(studio_code, {}).get(category, {}).get(month, 0))


def _build_forecast_row(label_key, month, ratios, below_avg, opex_assumptions,
                        sales_forecast, is_consolidated, studio_code, rev_forecast=None):
    """Compute a single forecast value for a P&L row."""
    rf = rev_forecast.get(month, {}) if rev_forecast else {}

    # Revenue rows — use curve-based forecast
    if "401000 Sessions" in label_key and "Total" in label_key:
        return rf.get("sessions", 0)
    if "403000 Breakage" in label_key and "Total" in label_key:
        return rf.get("breakage", 0)
    if label_key == "404000 Retail Sales":
        return rf.get("retail", 0)
    if label_key == "406000 Refunds":
        return rf.get("refunds", 0)
    if label_key == "407000 Discounts":
        return rf.get("discounts", 0)

    # Total revenue
    if "Total for Income" in label_key or "Total Income" in label_key:
        return rf.get("total", 0)

    # COGS
    if "Cost of Goods Sold" in label_key and "Total" in label_key:
        return _get_forecast_opex(opex_assumptions, "finance", month, is_consolidated, studio_code)

    # Gross Profit
    if label_key == "Gross Profit":
        total_rev = rf.get("total", 0)
        cogs = _get_forecast_opex(opex_assumptions, "finance", month, is_consolidated, studio_code)
        return total_rev - cogs

    # Expense categories
    expense_map = {
        "601000 Sales & Marketing": "marketing",
        "602000 Payroll": "staff",
        "604000 Professional Fees": "professional_fees",
        "616000 Utilities": "utilities",
        "700000 Property Costs": "property",
        "603000 Software": "admin",
    }
    for pattern, cat in expense_map.items():
        if pattern in label_key:
            return _get_forecast_opex(opex_assumptions, cat, month, is_consolidated, studio_code)

    # Total expenses
    if "Total for Expenses" in label_key or "Total Expenses" in label_key:
        return sum(
            _get_forecast_opex(opex_assumptions, cat, month, is_consolidated, studio_code)
            for cat in OPEX_CATEGORIES if cat != "taxes"
        )

    # NOI
    if label_key == "Net Operating Income":
        total_rev = _build_forecast_row("Total for Income", month, ratios, below_avg,
                                        opex_assumptions, sales_forecast, is_consolidated, studio_code,
                                        rev_forecast=rev_forecast)
        cogs = _get_forecast_opex(opex_assumptions, "finance", month, is_consolidated, studio_code)
        total_opex = sum(
            _get_forecast_opex(opex_assumptions, cat, month, is_consolidated, studio_code)
            for cat in OPEX_CATEGORIES if cat != "taxes"
        )
        return total_rev - cogs - total_opex

    # Below the line
    if label_key == "810000 Depreciation":
        return below_avg.get("depreciation", 0)
    if "901000 Interest" in label_key:
        return below_avg.get("interest", 0)
    if label_key == "902000 Taxes Paid":
        return below_avg.get("taxes", 0)
    if label_key == "903000 Property taxes":
        return below_avg.get("prop_taxes", 0)
    if "Total for Other Expenses" in label_key or "Total Other Expenses" in label_key:
        return sum(below_avg.values())

    # Net Income
    if label_key == "Net Income":
        noi = _build_forecast_row("Net Operating Income", month, ratios, below_avg,
                                  opex_assumptions, sales_forecast, is_consolidated, studio_code,
                                  rev_forecast=rev_forecast)
        other = sum(below_avg.values())
        return noi - other

    return 0


def _render_summary_table(pl_df, actuals_months, fc_months, ratios, below_avg,
                          opex_assumptions, sales_forecast, is_consolidated, studio_code,
                          rev_forecast=None):
    """Render compact summary P&L with named rows."""
    rows = {}
    for label_key, display_name in SUMMARY_ROWS:
        row = {}
        # Actuals
        for col in pl_df.columns:
            mk = parse_accountant_month(col)
            if mk and mk in actuals_months:
                row[month_display(mk)] = _find_value(pl_df, label_key, col)
        # Forecast
        for m in fc_months:
            row[month_display(m)] = _build_forecast_row(
                label_key, m, ratios, below_avg,
                opex_assumptions, sales_forecast, is_consolidated, studio_code,
                rev_forecast=rev_forecast,
            )
        rows[display_name] = row

    df = pd.DataFrame(rows).T
    df.index.name = "Line Item"

    def _style(row):
        styles = []
        is_bold = row.name in BOLD_ROWS
        for val in row:
            s = "font-weight: bold; " if is_bold else ""
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    st.dataframe(
        df.style.apply(_style, axis=1).format("${:,.0f}"),
        use_container_width=True, height=650,
    )


def _render_detail_table(pl_df, actuals_months, fc_months, ratios, below_avg,
                         opex_assumptions, sales_forecast, is_consolidated, studio_code,
                         rev_forecast=None):
    """Render full detail P&L with all account rows."""
    visible_cols = [c for c in pl_df.columns if parse_accountant_month(c) in actuals_months]
    table = pl_df[visible_cols].copy()
    table.columns = [month_display(parse_accountant_month(c)) for c in visible_cols]

    # Add forecast — map each actual row to a forecast value
    for m in fc_months:
        col_name = month_display(m)
        table[col_name] = 0.0
        for label in table.index:
            ls = str(label).strip()
            if ls in HEADER_ROWS:
                table.loc[label, col_name] = np.nan
                continue
            # Try to map to a summary row for forecast
            matched = False
            for label_key, _ in SUMMARY_ROWS:
                variants = STUDIO_LABEL_VARIANTS.get(label_key, [label_key])
                if ls in variants or ls == label_key:
                    table.loc[label, col_name] = _build_forecast_row(
                        label_key, m, ratios, below_avg,
                        opex_assumptions, sales_forecast, is_consolidated, studio_code,
                        rev_forecast=rev_forecast,
                    )
                    matched = True
                    break
            if not matched:
                table.loc[label, col_name] = np.nan

    # Blank out header rows in actuals too
    for label in table.index:
        if str(label).strip() in HEADER_ROWS:
            table.loc[label] = np.nan

    def _style(row):
        styles = []
        label = str(row.name).strip()
        is_header = label in HEADER_ROWS
        is_total = any(x in label for x in ["Total", "Gross Profit", "Net"])
        for val in row:
            s = ""
            if is_header:
                s += "color: #999; font-style: italic; "
            elif is_total:
                s += "font-weight: bold; "
            if isinstance(val, (int, float)) and not pd.isna(val) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    def _fmt(val):
        if pd.isna(val):
            return ""
        return f"${val:,.0f}"

    st.dataframe(
        table.style.apply(_style, axis=1).format(_fmt),
        use_container_width=True, height=700,
    )


def _render_revenue_chart_v2(pl_df, actuals_months, fc_months, rev_forecast):
    """Revenue bar chart with actuals + curve-based forecast."""
    fig = go.Figure()

    # Actuals
    act_labels, act_vals = [], []
    for mk in actuals_months:
        for col in pl_df.columns:
            if parse_accountant_month(col) == mk:
                val = _find_value(pl_df, "Total for Income", col)
                act_vals.append(abs(val))
                act_labels.append(month_display(mk))
                break

    fig.add_trace(go.Bar(x=act_labels, y=act_vals, name="Actuals", marker_color="#2c3e50"))

    # Forecast from curves
    if fc_months and rev_forecast:
        fc_labels = [month_display(m) for m in fc_months]
        fc_vals = [rev_forecast[m]["total"] for m in fc_months]
        fig.add_trace(go.Bar(x=fc_labels, y=fc_vals, name="Forecast",
                             marker_color="#3498db", opacity=0.7))

    fig.update_layout(height=300, margin=dict(t=10, b=30),
                      yaxis_tickformat="$,.0f",
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)
