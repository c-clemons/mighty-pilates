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

    For consolidated: uses monthly_sales (consolidated, has 2025+ history).
    For per-studio: uses sales_forecast[studio] for 2026+ months, allocates
    consolidated 2025 history to studio by its Jan-Apr 2026 share.
    """
    curves = ds.get_rev_rec_curves()
    actual_sales = ds.get_monthly_sales()  # consolidated
    sales_forecast = ds.get_sales_forecast()  # per-studio × month

    earned_curve = {int(k): v / 100 for k, v in curves.get("earned", {}).items()}
    breakage_curve = {int(k): v / 100 for k, v in curves.get("breakage", {}).items()}
    refund_pct = curves.get("refund_pct", -1.8) / 100
    discount_pct = curves.get("discount_pct", -7.2) / 100

    if is_consolidated:
        # Use consolidated monthly_sales for all months (has 2025 history).
        # Add forecast months from sales_forecast TOTAL if not in monthly_sales.
        all_sales = dict(actual_sales)
        for m in fc_months:
            if m not in all_sales:
                all_sales[m] = sales_forecast[m].sum() if m in sales_forecast.columns else 0
    else:
        # Per-studio: use studio's own sales for 2026+; allocate 2025 by share.
        all_sales = {}

        # 2026+ months from per-studio sales_forecast (includes both actuals
        # and forecast months for the studio)
        if studio_code in sales_forecast.index:
            for m in sales_forecast.columns:
                all_sales[m] = float(sales_forecast.loc[studio_code, m])

        # Studio share = avg Jan-Apr 2026 share of consolidated
        q_months = ["2026-01", "2026-02", "2026-03", "2026-04"]
        studio_q = 0
        consol_q = 0
        for qm in q_months:
            if qm in sales_forecast.columns:
                if studio_code in sales_forecast.index:
                    studio_q += float(sales_forecast.loc[studio_code, qm])
                consol_q += float(sales_forecast[qm].sum())
        share = (studio_q / consol_q) if consol_q else 0

        # Allocate 2025 history from consolidated monthly_sales by share
        for m, val in actual_sales.items():
            if m.startswith("2025") and m not in all_sales:
                all_sales[m] = float(val) * share

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
        n_forecast = st.slider("Forecast months", 0, 24, 12, key="pl_nfc")
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
    forecast_ratios = ds.get_forecast_ratios()
    forecast_ratios["_interest_schedule"] = ds.get_interest_schedule()

    if detail_mode:
        _render_detail_table(pl_df, recent_actuals, fc_months, ratios, below_avg,
                             opex_assumptions, sales_forecast, is_consolidated, studio_code,
                             rev_forecast=rev_forecast, forecast_ratios=forecast_ratios)
    else:
        _render_summary_table(pl_df, recent_actuals, fc_months, ratios, below_avg,
                              opex_assumptions, sales_forecast, is_consolidated, studio_code,
                              rev_forecast=rev_forecast, forecast_ratios=forecast_ratios)

    # === Adjusted EBITDA Reconciliation (consolidated only) ===
    if is_consolidated:
        _render_adjusted_ebitda(ds, pl_df, recent_actuals, fc_months,
                                  ratios, below_avg, opex_assumptions, sales_forecast,
                                  rev_forecast, forecast_ratios)

    # === Annual totals summary ===
    # Pass FULL forecast_months (not sliced fc_months) so annual totals include
    # all 12 months of each year regardless of display slider.
    full_rev_forecast = _build_revenue_forecast(ds, forecast_months, is_consolidated, studio_code)
    for m in full_rev_forecast:
        full_rev_forecast[m]["retail"] = ratios.get("retail_avg", 0)
        full_rev_forecast[m]["total"] += ratios.get("retail_avg", 0)
    _render_annual_totals(pl_df, actuals_months, forecast_months, ratios, below_avg,
                          opex_assumptions, sales_forecast, is_consolidated, studio_code,
                          full_rev_forecast, forecast_ratios, ds=ds)


def _render_adjusted_ebitda(ds, pl_df, actuals_months, fc_months, ratios, below_avg,
                              opex_assumptions, sales_forecast, rev_forecast, forecast_ratios):
    """Show Adjusted EBITDA = Net Operating Income + One-Time Add-Backs."""
    ebitda_data = ds.actuals.get("adjusted_ebitda_addbacks", {})
    if not ebitda_data:
        return

    st.subheader("Adjusted EBITDA Reconciliation")

    addback_cats = ebitda_data.get("categories", [])
    addback_total = ebitda_data.get("total", 0)

    all_months = actuals_months + fc_months

    # Build rows: NOI ref + addbacks + Total addbacks + Adjusted EBITDA
    rows = {}

    # NOI for each month
    noi_row = {}
    for col in pl_df.columns:
        mk = parse_accountant_month(col)
        if mk and mk in actuals_months:
            noi_row[month_display(mk)] = _find_value(pl_df, "Net Operating Income", col)
    for m in fc_months:
        noi_row[month_display(m)] = _build_forecast_row(
            "Net Operating Income", m, ratios, below_avg, opex_assumptions,
            sales_forecast, True, None,
            rev_forecast=rev_forecast, forecast_ratios=forecast_ratios,
        )
    rows["Net Operating Income"] = noi_row

    # Add-back rows: use exact monthly distribution per category (one-time costs
    # hit in the month they occurred, not amortized evenly).
    addback_rows = {}
    for cat in addback_cats:
        cat_row = {}
        monthly = cat.get("monthly", {})
        for m in all_months:
            cat_row[month_display(m)] = float(monthly.get(m, 0))
        addback_rows[f"  {cat['name']}"] = cat_row

    # Total add-backs
    total_row = {}
    for m in all_months:
        mlabel = month_display(m)
        total_row[mlabel] = sum(addback_rows[k].get(mlabel, 0) for k in addback_rows)

    # Adjusted EBITDA
    adj_ebitda_row = {}
    for m in all_months:
        mlabel = month_display(m)
        adj_ebitda_row[mlabel] = noi_row.get(mlabel, 0) + total_row.get(mlabel, 0)

    # Combine
    rows.update(addback_rows)
    rows["Total Add Backs"] = total_row
    rows["Adjusted EBITDA"] = adj_ebitda_row

    df = pd.DataFrame(rows).T
    df.index.name = "Line Item"

    def _style(row):
        styles = []
        is_bold = row.name in ("Net Operating Income", "Total Add Backs", "Adjusted EBITDA")
        is_highlight = row.name == "Adjusted EBITDA"
        for val in row:
            s = "font-weight: bold; " if is_bold else ""
            if is_highlight:
                s += "background-color: #D5EAD0; "
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    st.dataframe(
        df.style.apply(_style, axis=1).format("${:,.0f}"),
        use_container_width=True, height=300,
    )

    st.caption(f"Add-backs total over actuals period: ${addback_total:,.2f}. "
               "One-time costs are removed to show recurring operating profitability.")


def _render_annual_totals(pl_df, actuals_months, fc_months, ratios, below_avg,
                            opex_assumptions, sales_forecast, is_consolidated, studio_code,
                            rev_forecast, forecast_ratios, ds=None):
    """Show annual summaries grouping months by calendar year."""
    st.subheader("Annual Totals")

    # Group months into years
    all_months = actuals_months + fc_months
    years = {}
    for m in all_months:
        y = m[:4]
        years.setdefault(y, []).append(m)

    # Key rows to summarize
    key_lines = [
        ("Total Revenue", ["Total Income", "Total for Income"]),
        ("Gross Profit", ["Gross Profit"]),
        ("Total Operating Expenses", ["Total Expenses", "Total for Expenses"]),
        ("Net Operating Income", ["Net Operating Income"]),
        ("Net Income", ["Net Income"]),
    ]

    rows = {}
    noi_by_year = {}  # save for Adjusted EBITDA calc
    for display, labels in key_lines:
        row = {}
        for year, months in sorted(years.items()):
            year_total = 0
            for m in months:
                if m in actuals_months:
                    for col in pl_df.columns:
                        mk = parse_accountant_month(col)
                        if mk == m:
                            for lbl in labels:
                                v = _find_value(pl_df, lbl, col)
                                if v:
                                    year_total += v
                                    break
                            break
                else:
                    v = _build_forecast_row(
                        labels[0], m, ratios, below_avg, opex_assumptions,
                        sales_forecast, is_consolidated, studio_code,
                        rev_forecast=rev_forecast, forecast_ratios=forecast_ratios,
                    )
                    if v:
                        year_total += v
            row[year] = year_total
            if display == "Net Operating Income":
                noi_by_year[year] = year_total
        rows[display] = row

    # Add Adjusted EBITDA (consolidated only — add-backs apply at consolidated level)
    if is_consolidated and ds is not None:
        ebitda_data = ds.actuals.get("adjusted_ebitda_addbacks", {})
        if ebitda_data:
            # Sum exact monthly add-backs per year from the per-category schedule
            addback_by_year = {}
            for year, months in sorted(years.items()):
                year_total = 0
                for cat in ebitda_data.get("categories", []):
                    cat_monthly = cat.get("monthly", {})
                    for m in months:
                        year_total += float(cat_monthly.get(m, 0))
                addback_by_year[year] = year_total
            rows["Total Add Backs (one-time)"] = addback_by_year
            # Adjusted EBITDA = NOI + Add Backs per year
            rows["Adjusted EBITDA"] = {
                year: noi_by_year.get(year, 0) + addback_by_year.get(year, 0)
                for year in sorted(years.keys())
            }

    df = pd.DataFrame(rows).T
    df.index.name = "Line Item"

    def _style(row):
        styles = []
        bold_rows = ("Total Revenue", "Gross Profit", "Net Operating Income",
                     "Net Income", "Adjusted EBITDA")
        is_bold = row.name in bold_rows
        is_highlight = row.name == "Adjusted EBITDA"
        for val in row:
            s = "font-weight: bold; " if is_bold else ""
            if is_highlight:
                s += "background-color: #D5EAD0; "
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "
            styles.append(s)
        return styles

    st.dataframe(
        df.style.apply(_style, axis=1).format("${:,.0f}"),
        use_container_width=True, height=260,
    )


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
                        sales_forecast, is_consolidated, studio_code,
                        rev_forecast=None, forecast_ratios=None):
    """Compute a single forecast value for a P&L row."""
    rf = rev_forecast.get(month, {}) if rev_forecast else {}
    fr = forecast_ratios or {}

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

    # COGS & Merchant Fees — % of total revenue
    if "Cost of Goods Sold" in label_key and "Total" in label_key:
        total_rev = rf.get("total", 0)
        combined_pct = fr.get("combined_merchant_cogs_pct", 3.82) / 100
        return abs(total_rev) * combined_pct

    # Gross Profit
    if label_key == "Gross Profit":
        total_rev = rf.get("total", 0)
        combined_pct = fr.get("combined_merchant_cogs_pct", 3.82) / 100
        cogs = abs(total_rev) * combined_pct
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

    # Total expenses (exclude COGS — already above the line)
    if "Total for Expenses" in label_key or "Total Expenses" in label_key:
        return sum(
            _get_forecast_opex(opex_assumptions, cat, month, is_consolidated, studio_code)
            for cat in OPEX_CATEGORIES if cat not in ("taxes", "finance", "startup")
        )

    # NOI
    if label_key == "Net Operating Income":
        total_rev = rf.get("total", 0)
        combined_pct = fr.get("combined_merchant_cogs_pct", 3.82) / 100
        cogs = abs(total_rev) * combined_pct
        total_opex = sum(
            _get_forecast_opex(opex_assumptions, cat, month, is_consolidated, studio_code)
            for cat in OPEX_CATEGORIES if cat not in ("taxes", "finance", "startup")
        )
        return total_rev - cogs - total_opex

    # Below the line
    if label_key == "810000 Depreciation":
        return below_avg.get("depreciation", 0)
    if "901000 Interest" in label_key:
        # Interest from projected loan schedule
        interest_sched = fr.get("_interest_schedule", {})
        if month in interest_sched:
            return interest_sched[month]
        return fr.get("monthly_interest_base", below_avg.get("interest", 0))
    if label_key == "902000 Taxes Paid":
        return below_avg.get("taxes", 0)
    if label_key == "903000 Property taxes":
        return below_avg.get("prop_taxes", 0)
    if "Total for Other Expenses" in label_key or "Total Other Expenses" in label_key:
        dep = below_avg.get("depreciation", 0)
        interest_sched = fr.get("_interest_schedule", {})
        interest = interest_sched.get(month, fr.get("monthly_interest_base", below_avg.get("interest", 0)))
        taxes = below_avg.get("taxes", 0)
        prop_taxes = below_avg.get("prop_taxes", 0)
        return dep + interest + taxes + prop_taxes

    # Net Income
    if label_key == "Net Income":
        noi = _build_forecast_row("Net Operating Income", month, ratios, below_avg,
                                  opex_assumptions, sales_forecast, is_consolidated, studio_code,
                                  rev_forecast=rev_forecast, forecast_ratios=forecast_ratios)
        dep = below_avg.get("depreciation", 0)
        interest_sched = fr.get("_interest_schedule", {})
        interest = interest_sched.get(month, fr.get("monthly_interest_base", below_avg.get("interest", 0)))
        taxes = below_avg.get("taxes", 0)
        prop_taxes = below_avg.get("prop_taxes", 0)
        return noi - dep - interest - taxes - prop_taxes

    return 0


def _render_summary_table(pl_df, actuals_months, fc_months, ratios, below_avg,
                          opex_assumptions, sales_forecast, is_consolidated, studio_code,
                          rev_forecast=None, forecast_ratios=None):
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
                rev_forecast=rev_forecast, forecast_ratios=forecast_ratios,
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
                         rev_forecast=None, forecast_ratios=None):
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
                        rev_forecast=rev_forecast, forecast_ratios=forecast_ratios,
                    )
                    matched = True
                    break
            if not matched:
                table.loc[label, col_name] = np.nan

    # Distribute summary forecasts to ALL detail rows proportionally
    parent_children = {
        # Revenue
        "Total for 401000 Sessions": [
            "401001 Machine", "401002 Private Pilates", "401003 Class Pass",
            "401004 Mighty Teacher Training", "401005 Livestream Classes", "401006 Wellhub",
        ],
        "Total for 403000 Breakage Revenue": [
            "403001 Machine Breakage", "403002 Mighty Teacher Training Breakage",
            "403003 Private Pilates Breakage", "403004 Other Breakage",
        ],
        # COGS
        "Total for Cost of Goods Sold": [
            "506000 Merchant Account Fees", "501000 Product Cost",
            "Total for Cost of goods sold",
        ],
        # Expenses
        "Total for 601000 Sales & Marketing": [
            "601001 Paid Ads", "601005 Content Creation", "601006 General Marketing",
            "601007 Marketing Contractors", "601010 Website Development", "601011 Trade Shows",
        ],
        "Total for 602000 Payroll": [
            "602001 Wages", "602002 1099 Compensation", "602003 Bonus",
            "602004 Payroll Taxes", "602005 Employee Benefits", "602010 Payroll Processing Fees",
        ],
        "Total for 604000 Professional Fees": [
            "604100 Legal Fees", "604200 Accounting", "604300 Recruiting",
            "604400 Other Professional Fees",
        ],
        "Total for 616000 Utilities": [
            "616001 Electricity", "616002 Internet", "616003 Phone",
            "616004 Water", "616005 Disposal",
        ],
        "Total for 700000 Property Costs": [
            "701000 Rent", "702000 Security", "703000 Cleaning",
            "704000 Studio Repairs", "705000 Property Maintenance",
        ],
    }

    # Use last 3 actuals months to compute child ratios
    ratio_cols = [c for c in pl_df.columns
                  if parse_accountant_month(c) in actuals_months[-3:]]
    for parent_key, children in parent_children.items():
        # Find the parent row in the table (may use variant labels)
        parent_variants = STUDIO_LABEL_VARIANTS.get(parent_key, [parent_key])
        parent_label = None
        for v in parent_variants:
            if v in table.index:
                parent_label = v
                break
        if parent_label is None:
            continue

        # Compute child totals from actuals to derive ratios
        child_totals = {}
        for child in children:
            # Match child label loosely in the table index
            matched = [idx for idx in table.index if child.lower() in str(idx).lower()]
            if not matched:
                continue
            child_idx = matched[0]
            total = 0.0
            for rc in ratio_cols:
                mk = parse_accountant_month(rc)
                display_col = month_display(mk)
                if display_col in table.columns:
                    v = table.loc[child_idx, display_col]
                    if pd.notna(v):
                        total += float(v)
            child_totals[child_idx] = total

        grand_total = sum(child_totals.values())
        if grand_total == 0:
            continue

        # Apply ratios to forecast columns
        for m in fc_months:
            col_name = month_display(m)
            parent_val = table.loc[parent_label, col_name]
            if pd.isna(parent_val):
                continue
            parent_val = float(parent_val)
            for child_idx, child_total in child_totals.items():
                ratio = child_total / grand_total
                table.loc[child_idx, col_name] = parent_val * ratio

    # Forecast standalone rows (no parent total) from trailing average
    standalone_rows = [
        "605000 Travel", "606000 Meals", "607000 Entertainment",
        "608000 Insurance", "609000 Business licenses",
        "610000 Office Supplies", "610100 Furniture", "611000 Shipping",
        "613000 Bank fees", "615000 Parking Lot Rental",
        "630000 Studio Start Up", "900000 Other Expense",
        "603000 Software",
    ]
    ratio_cols = [c for c in pl_df.columns if parse_accountant_month(c) in actuals_months[-3:]]
    for m in fc_months:
        col_name = month_display(m)
        for label in table.index:
            ls = str(label).strip()
            # Skip if already has a forecast value
            val = table.loc[label, col_name]
            if val is not None and not (isinstance(val, float) and pd.isna(val)) and val != 0:
                continue
            # Check if this is a standalone row
            is_standalone = any(s in ls for s in standalone_rows)
            if is_standalone and ratio_cols:
                # Use trailing average
                avg = 0
                n = 0
                for rc in ratio_cols:
                    mk = parse_accountant_month(rc)
                    dc = month_display(mk)
                    if dc in table.columns:
                        v = table.loc[label, dc]
                        if isinstance(v, (int, float)) and not pd.isna(v):
                            avg += abs(v)
                            n += 1
                if n > 0:
                    table.loc[label, col_name] = round(avg / n, 0)

    # Convert to object dtype so we can mix numbers and empty strings
    table = table.astype(object)
    # Blank out header rows and replace NaN with empty string
    for label in table.index:
        if str(label).strip() in HEADER_ROWS:
            for col in table.columns:
                table.at[label, col] = ""
    table = table.fillna("")
    # Convert remaining NaN-like values
    table = table.replace({None: "", "nan": "", "None": ""})

    # Determine which columns are actuals vs forecast for styling
    actuals_display_cols = set(month_display(mk) for mk in actuals_months)

    def _style(row):
        styles = []
        label = str(row.name).strip()
        is_header = label in HEADER_ROWS
        is_total = any(x in label for x in ["Total", "Gross Profit", "Net"])
        for i, val in enumerate(row):
            s = ""
            col_name = table.columns[i] if i < len(table.columns) else ""
            is_actuals = col_name in actuals_display_cols
            is_forecast = col_name and not is_actuals

            if is_header:
                s += "color: #aaa; font-style: italic; "
            elif is_total:
                s += "font-weight: bold; "
                s += "background-color: #e8eaed; " if is_actuals else "background-color: #e3edf7; "
            else:
                if is_forecast:
                    s += "background-color: #f5f9ff; "

            # Negative values in red
            if isinstance(val, (int, float)) and val < 0:
                s += "color: #e74c3c; "

            styles.append(s)
        return styles

    def _fmt(val):
        if val == "" or val is None:
            return ""
        if isinstance(val, str):
            return val
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
