"""
Financial calculation engine for the Mighty Pilates dashboard.
Pure functions — no Streamlit imports, no I/O.
"""

import pandas as pd
import numpy as np

from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS,
    PL_LABEL_MAP, STUDIO_PL_LABEL_MAP, PL_TO_OPEX_CATEGORY,
    OPEX_CATEGORIES,
    CF_OPERATIONS_INFLOW, CF_OPERATIONS_OUTFLOW,
    CF_INVESTING, CF_FINANCING,
    parse_accountant_month, month_key, month_display,
)


# ---------------------------------------------------------------------------
# Revenue helpers
# ---------------------------------------------------------------------------

def _extract_pl_row(pl_df: pd.DataFrame, label: str, month_key_str: str) -> float:
    """Extract a value from the accountant P&L by row label and month key.
    Tries both 'Total for XXX' and 'Total XXX' variants."""
    if pl_df.empty:
        return 0.0
    # Build label variants
    labels_to_try = [label]
    if "Total for " in label:
        labels_to_try.append(label.replace("Total for ", "Total "))
    elif label.startswith("Total ") and "Total for " not in label:
        labels_to_try.append(label.replace("Total ", "Total for ", 1))

    for col in pl_df.columns:
        mk = parse_accountant_month(col)
        if mk == month_key_str:
            for lbl in labels_to_try:
                if lbl in pl_df.index:
                    val = pl_df.loc[lbl, col]
                    return float(val) if pd.notna(val) else 0.0
    return 0.0


def _extract_studio_cash_sales(studio_pl: pd.DataFrame, month_key_str: str) -> float:
    """
    Extract cash sales from a studio P&L for a given month.
    Cash sales = Total Sessions + Total Breakage + Retail + Refunds + Discounts
    """
    if studio_pl.empty:
        return 0.0
    label_map = STUDIO_PL_LABEL_MAP
    total = 0.0
    for label, key in label_map.items():
        if key in ("sessions", "breakage", "retail", "refunds", "discounts", "old_mighty"):
            for col in studio_pl.columns:
                mk = parse_accountant_month(col)
                if mk == month_key_str and label in studio_pl.index:
                    val = studio_pl.loc[label, col]
                    total += float(val) if pd.notna(val) else 0.0
                    break
    return total


def get_actuals_cash_sales_by_studio(
    studio_pls: dict,
    months: list,
) -> pd.DataFrame:
    """
    Build a studio × month grid of cash sales from accountant actuals.
    studio_pls: {code: {name, data: DataFrame}}
    """
    studios = list(ACTIVE_STUDIOS.keys()) + list(DEVELOPMENT_STUDIOS.keys())
    rows = {}
    for code in studios:
        row = {}
        if code in studio_pls:
            sp = studio_pls[code]["data"]
            for m in months:
                row[m] = _extract_studio_cash_sales(sp, m)
        else:
            for m in months:
                row[m] = 0.0
        rows[code] = row
    return pd.DataFrame.from_dict(rows, orient="index")


def get_actuals_revenue_breakdown(
    pl_df: pd.DataFrame,
    months: list,
) -> dict:
    """
    Extract revenue line items from consolidated P&L for cash flow display.
    Returns {line_key: {month: value}} where line_key matches CF_OPERATIONS_INFLOW keys.
    """
    result = {}
    label_to_cf = {
        "Total for 401000 Sessions": "sessions",
        "Total for 403000 Breakage Revenue": "breakage",
        "404000 Retail Sales": "retail",
        "402000 Revenue from Old Mighty": "old_mighty",
        "406000 Refunds": "refunds",
        "407000 Discounts": "discounts",
    }
    for label, cf_key in label_to_cf.items():
        month_vals = {}
        for m in months:
            month_vals[m] = _extract_pl_row(pl_df, label, m)
        result[cf_key] = month_vals
    return result


def get_actuals_opex_breakdown(
    pl_df: pd.DataFrame,
    months: list,
) -> dict:
    """
    Extract operating expense categories from consolidated P&L.
    Returns {opex_category: {month: value}}.
    """
    label_to_pl = {
        "Total for 700000 Property Costs": "property_costs",
        "Total for 602000 Payroll": "payroll",
        "Total for 616000 Utilities": "utilities",
        "Total for 601000 Sales & Marketing": "marketing",
        "603000 Software & Web Services": "software",
        "608000 Insurance": "insurance",
        "609000 Business licenses": "licenses",
        "610000 Office Supplies & General Expense": "office_supplies",
        "610100 Furniture & Equipment": "furniture_equip",
        "611000 Shipping & postage": "shipping",
        "613000 Bank fees & Service Charges": "bank_fees",
        "615000 Parking Lot Rental": "parking",
        "Total for 604000 Professional Fees": "professional_fees",
        "605000 Travel (Airfare/hotel/ground trans/etc)": "travel",
        "606000 Meals": "meals",
        "607000 Entertainment": "entertainment",
        "630000 Studio Start Up Costs": "startup_costs",
    }

    # Aggregate into opex categories
    result = {cat: {m: 0.0 for m in months} for cat in OPEX_CATEGORIES}

    for label, pl_key in label_to_pl.items():
        opex_cat = PL_TO_OPEX_CATEGORY.get(pl_key)
        if not opex_cat:
            continue
        for m in months:
            val = _extract_pl_row(pl_df, label, m)
            result[opex_cat][m] += abs(val)  # expenses stored as positive in CF

    # Merchant fees & COGS
    for label in ["506000 Merchant Account Fees", "Total for Cost of goods sold"]:
        for m in months:
            val = _extract_pl_row(pl_df, label, m)
            result["finance"][m] += abs(val)

    return result


def get_actuals_other_items(pl_df: pd.DataFrame, months: list) -> dict:
    """Extract taxes, depreciation, interest from P&L."""
    items = {
        "taxes": ["902000 Taxes Paid", "903000 Property taxes"],
        "depreciation": ["810000 Depreciation"],
        "interest": ["901000 Interest Expense/(Income)"],
    }
    result = {}
    for key, labels in items.items():
        month_vals = {m: 0.0 for m in months}
        for label in labels:
            for m in months:
                month_vals[m] += abs(_extract_pl_row(pl_df, label, m))
        result[key] = month_vals
    return result


# ---------------------------------------------------------------------------
# Cash flow forecast
# ---------------------------------------------------------------------------

def build_monthly_cash_sales(
    sales_forecast: pd.DataFrame,
    actuals_pl: pd.DataFrame,
    studio_pls: dict,
    last_actuals_month: str,
) -> pd.DataFrame:
    """
    Return per-studio × month cash sales grid.

    Cash sales (what customers actually paid this month) = client_sales_forecast
    for all months — actuals AND forecast. The client provides confirmed monthly
    sales numbers; those are the source of truth for cash flow.

    Note: prior versions derived actuals from accountant P&L (Sessions + Breakage
    + Retail + Refunds + Discounts), but that's net recognized revenue, not cash
    received. For Cash Flow Forecasts we want actual cash, which is the
    client-provided sales number.
    """
    if sales_forecast is None or sales_forecast.empty:
        return pd.DataFrame()
    # sales_forecast already has confirmed actuals (Jan-Apr 2026) AND forecast
    # months. Just return it as-is.
    return sales_forecast.copy()


def build_cash_flow_forecast(
    cash_sales: pd.DataFrame,
    opex_assumptions: dict,
    loans: list,
    actuals_pl: pd.DataFrame,
    actuals_scf: pd.DataFrame,
    actuals_bs: pd.DataFrame,
    last_actuals_month: str,
    revenue_adj: float = 0.0,
    opex_adj: float = 0.0,
    **kwargs,
) -> pd.DataFrame:
    """
    Build the full cash flow statement.

    Args:
        cash_sales: studio × month grid of cash sales
        opex_assumptions: {studio: {category: {month: value}}}
        loans: list of loan dicts
        actuals_pl: consolidated P&L from accountant
        actuals_scf: SCF from accountant
        last_actuals_month: e.g. "February 2026"
        revenue_adj: % adjustment to forecast revenue (0.0 = none, 0.1 = +10%)
        opex_adj: % adjustment to forecast opex

    Returns:
        DataFrame with cash flow line items as index, months as columns.
    """
    last_key = parse_accountant_month(last_actuals_month) if last_actuals_month else "2026-02"
    all_months = sorted(cash_sales.columns)
    actuals_months = [m for m in all_months if m <= last_key]
    forecast_months = [m for m in all_months if m > last_key]

    # Initialize result dict: {row_label: {month: value}}
    rows = {}

    # --- REVENUE (actuals from P&L, forecast from sales grid) ---
    actuals_rev = get_actuals_revenue_breakdown(actuals_pl, actuals_months)

    # The sales forecast is TOTAL cash sales (sessions + breakage + retail
    # + refunds + discounts already netted together). For actuals months,
    # we show the P&L breakdown. For forecast months, the total goes on the
    # "Sessions Revenue" line and all other revenue lines are $0 since the
    # forecast already nets everything.
    for cf_key, cf_label in CF_OPERATIONS_INFLOW:
        row = {}
        for m in actuals_months:
            row[m] = actuals_rev.get(cf_key, {}).get(m, 0.0)
        for m in forecast_months:
            if cf_key == "sessions":
                # The sales forecast already represents total net cash sales
                row[m] = cash_sales[m].sum() * (1 + revenue_adj)
            else:
                # All other revenue lines are $0 in forecast — already included
                # in the sessions/total sales number above
                row[m] = 0.0
        rows[cf_label] = row

    # Total Cash Sales
    total_sales = {}
    for m in all_months:
        total_sales[m] = sum(rows[label].get(m, 0) for _, label in CF_OPERATIONS_INFLOW)
    rows["Total Cash Sales"] = total_sales

    # --- OPERATING EXPENSES ---
    actuals_opex = get_actuals_opex_breakdown(actuals_pl, actuals_months)
    actuals_other = get_actuals_other_items(actuals_pl, actuals_months)

    for cf_key, cf_label in CF_OPERATIONS_OUTFLOW:
        row = {}
        for m in actuals_months:
            if cf_key == "taxes":
                row[m] = actuals_other.get("taxes", {}).get(m, 0.0)
            else:
                row[m] = actuals_opex.get(cf_key, {}).get(m, 0.0)
        for m in forecast_months:
            if cf_key == "taxes":
                row[m] = actuals_other.get("taxes", {}).get(actuals_months[-1], 0.0) if actuals_months else 0.0
            else:
                # Use opex assumptions if available, else trailing 6-month avg
                assumption_val = _get_opex_forecast(opex_assumptions, cf_key, m)
                if assumption_val > 0:
                    row[m] = assumption_val * (1 + opex_adj)
                elif actuals_months:
                    # Fallback: 6-month trailing average (smooths outliers)
                    recent = actuals_months[-6:]
                    avg = np.mean([actuals_opex.get(cf_key, {}).get(rm, 0) for rm in recent])
                    row[m] = avg * (1 + opex_adj)
                else:
                    row[m] = 0.0
        rows[cf_label] = row

    # Total OpEx
    total_opex = {}
    for m in all_months:
        total_opex[m] = sum(rows[label].get(m, 0) for _, label in CF_OPERATIONS_OUTFLOW)
    rows["Total Operating Expenses"] = total_opex

    # Net Cash from Operations
    net_ops = {}
    for m in all_months:
        net_ops[m] = total_sales[m] - total_opex[m]
    rows["Net Cash from Operations"] = net_ops

    # --- INVESTING ---
    capex_by_month = kwargs.get("capex_by_month", {})

    for cf_key, cf_label in CF_INVESTING:
        row = {}
        for m in all_months:
            if m in actuals_months:
                row[m] = _extract_scf_investing(actuals_scf, cf_key, m)
            elif cf_key == "leasehold" and m in capex_by_month:
                row[m] = -abs(capex_by_month[m])  # capex is cash outflow
            else:
                row[m] = 0.0
        rows[cf_label] = row

    net_investing = {}
    for m in all_months:
        net_investing[m] = sum(rows[label].get(m, 0) for _, label in CF_INVESTING)
    rows["Net Cash from Investing"] = net_investing

    # --- FINANCING ---
    for cf_key, cf_label in CF_FINANCING:
        row = {}
        for m in all_months:
            if m in actuals_months:
                row[m] = _extract_scf_financing(actuals_scf, cf_key, m)
            else:
                row[m] = _get_loan_cash_flow(loans, cf_key, m)
        rows[cf_label] = row

    net_financing = {}
    for m in all_months:
        net_financing[m] = sum(rows[label].get(m, 0) for _, label in CF_FINANCING)
    rows["Net Cash from Financing"] = net_financing

    # --- TOTALS ---
    # For actuals months, use actual SCF net change (accounts for working capital)
    # For forecast months, compute from our P&L-based flows
    actual_scf_net = _get_scf_net_change(actuals_scf, actuals_months)

    net_change = {}
    for m in all_months:
        if m in actuals_months and m in actual_scf_net:
            net_change[m] = actual_scf_net[m]
        else:
            net_change[m] = net_ops[m] + net_investing[m] + net_financing[m]
    rows["Net Change in Cash"] = net_change

    # Beginning/ending cash
    # For actuals months: use BS bank account balances directly
    # For forecast months: chain forward from last actuals ending balance
    bs_cash = _get_bs_cash_by_month(actuals_bs, actuals_months)
    last_actuals_cash = bs_cash.get(actuals_months[-1], 265417) if actuals_months else 265417

    beg = {}
    end = {}
    for i, m in enumerate(all_months):
        if m in actuals_months and m in bs_cash:
            # Use actual BS balance
            end[m] = bs_cash[m]
            if i == 0:
                beg[m] = end[m] - net_change[m]
            else:
                prev_m = all_months[i - 1]
                beg[m] = bs_cash.get(prev_m, end.get(prev_m, 0))
        else:
            # Forecast: chain from prior month
            if i == 0:
                beg[m] = last_actuals_cash
            else:
                beg[m] = end[all_months[i - 1]]
            end[m] = beg[m] + net_change[m]
    rows["Beginning Cash"] = beg
    rows["Ending Cash"] = end

    # Build DataFrame
    row_order = (
        [label for _, label in CF_OPERATIONS_INFLOW]
        + ["Total Cash Sales"]
        + [label for _, label in CF_OPERATIONS_OUTFLOW]
        + ["Total Operating Expenses", "Net Cash from Operations"]
        + [label for _, label in CF_INVESTING]
        + ["Net Cash from Investing"]
        + [label for _, label in CF_FINANCING]
        + ["Net Cash from Financing"]
        + ["Net Change in Cash", "Beginning Cash", "Ending Cash"]
    )

    df = pd.DataFrame(rows).T
    df = df.reindex(row_order)
    df.index.name = "Line Item"
    return df


# ---------------------------------------------------------------------------
# Loan calculations
# ---------------------------------------------------------------------------

def calculate_loan_schedule(
    principal: float,
    annual_rate: float,
    start_month: str,
    maturity_month: str,
    amortization: str = "fully_amortizing",
    custom_payments: dict = None,
) -> pd.DataFrame:
    """
    Generate a monthly loan amortization schedule.

    Args:
        principal: Original loan amount
        annual_rate: Annual interest rate (e.g., 0.085 for 8.5%)
        start_month: First month of the loan ("YYYY-MM")
        maturity_month: Last month of the loan ("YYYY-MM")
        amortization: "fully_amortizing", "interest_only", or "custom"
        custom_payments: {month_key: payment_amount} for custom schedules

    Returns:
        DataFrame with columns: month, beginning_balance, interest,
        principal_payment, total_payment, ending_balance
    """
    monthly_rate = annual_rate / 12

    # Build month list
    months = []
    y, m = map(int, start_month.split("-"))
    ey, em = map(int, maturity_month.split("-"))
    while (y, m) <= (ey, em):
        months.append(month_key(y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    n_months = len(months)
    if n_months == 0:
        return pd.DataFrame()

    # Calculate fixed payment for fully amortizing
    if amortization == "fully_amortizing" and monthly_rate > 0:
        pmt = principal * monthly_rate / (1 - (1 + monthly_rate) ** -n_months)
    elif amortization == "fully_amortizing" and monthly_rate == 0:
        pmt = principal / n_months
    else:
        pmt = None  # computed per month

    rows = []
    balance = principal
    for i, mk in enumerate(months):
        interest = balance * monthly_rate
        if amortization == "fully_amortizing":
            total = pmt
            princ_pay = total - interest
        elif amortization == "interest_only":
            if i == n_months - 1:  # balloon at maturity
                princ_pay = balance
                total = interest + princ_pay
            else:
                princ_pay = 0
                total = interest
        elif amortization == "custom" and custom_payments:
            total = custom_payments.get(mk, 0)
            princ_pay = max(total - interest, 0)
        else:
            total = 0
            princ_pay = 0

        end_balance = max(balance - princ_pay, 0)
        rows.append({
            "month": mk,
            "beginning_balance": balance,
            "interest": interest,
            "principal_payment": princ_pay,
            "total_payment": total,
            "ending_balance": end_balance,
        })
        balance = end_balance

    return pd.DataFrame(rows)


def build_loan_from_bs_history(
    name: str,
    loan_id: str,
    balance_history: dict,
    contra_history: dict = None,
) -> dict:
    """
    Build a loan dict from BS balance history.
    balance_history: {month_key: balance}
    contra_history: {month_key: contra_amount} (for MindBody loans)
    """
    sorted_months = sorted(balance_history.keys())
    if not sorted_months:
        return None

    # Net balance = gross - contra
    net_history = {}
    for m in sorted_months:
        gross = balance_history.get(m, 0)
        contra = contra_history.get(m, 0) if contra_history else 0
        net_history[m] = gross + contra  # contra is negative

    # Calculate monthly payments from balance changes
    payments = {}
    for i in range(1, len(sorted_months)):
        prior = net_history[sorted_months[i - 1]]
        current = net_history[sorted_months[i]]
        payment = prior - current
        if payment > 0:
            payments[sorted_months[i]] = payment

    avg_payment = np.mean(list(payments.values())) if payments else 0

    return {
        "id": loan_id,
        "name": name,
        "original_amount": net_history[sorted_months[0]],
        "current_balance": net_history[sorted_months[-1]],
        "rate": 0.0,  # MindBody loans are effectively 0% (contra offsets)
        "start_date": sorted_months[0],
        "balance_by_month": net_history,
        "avg_monthly_payment": avg_payment,
        "payment_history": payments,
    }


def get_total_debt_service(loans: list, months: list) -> dict:
    """Calculate total monthly debt service (principal + interest) across all loans."""
    result = {m: 0.0 for m in months}
    for loan in loans:
        payments = loan.get("payment_history", {})
        avg = loan.get("avg_monthly_payment", 0)
        balance = loan.get("current_balance", 0)

        for m in months:
            if m in payments:
                result[m] += payments[m]
            elif balance > 0:
                # Forecast: use average payment, don't exceed remaining balance
                pay = min(avg, balance)
                result[m] += pay
                balance -= pay
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_historical_ratio(revenue_data: dict, numerator_key: str, denominator_key: str, months: list) -> float:
    """Calculate average ratio of numerator/denominator over given months."""
    num_total = sum(revenue_data.get(numerator_key, {}).get(m, 0) for m in months)
    den_total = sum(revenue_data.get(denominator_key, {}).get(m, 0) for m in months)
    if den_total == 0:
        return 0.0
    return num_total / den_total


def _get_opex_forecast(opex_assumptions: dict, category: str, month: str) -> float:
    """Sum a category across all studios for a forecast month."""
    total = 0.0
    for studio_data in opex_assumptions.values():
        if isinstance(studio_data, dict) and category in studio_data:
            cat_data = studio_data[category]
            if isinstance(cat_data, dict):
                total += float(cat_data.get(month, 0))
    return total


def _extract_scf_investing(scf_df: pd.DataFrame, cf_key: str, month_key_str: str) -> float:
    """Extract investing activity from SCF."""
    if scf_df.empty:
        return 0.0
    label_map = {
        "equipment": ["151000", "152000", "153000", "154000"],
        "leasehold": ["155"],
        "deposits": ["171000"],
        "depreciation": ["159"],
    }
    patterns = label_map.get(cf_key, [])
    total = 0.0
    for col in scf_df.columns:
        mk = parse_accountant_month(col)
        if mk != month_key_str:
            continue
        for idx_label in scf_df.index:
            for pat in patterns:
                if pat in str(idx_label):
                    val = scf_df.loc[idx_label, col]
                    total += float(val) if pd.notna(val) else 0.0
    return total


def _extract_scf_financing(scf_df: pd.DataFrame, cf_key: str, month_key_str: str) -> float:
    """Extract financing activity from SCF.
    Splits loan flows: positive = proceeds, negative = repayments."""
    if scf_df.empty:
        return 0.0

    # Loan-related patterns (MindBody, Samson, Specialty)
    loan_patterns = ["243000", "244000", "242"]
    intercompany_patterns = ["241000", "251000", "Due to", "Opening balance"]

    if cf_key == "intercompany":
        patterns = intercompany_patterns
    elif cf_key in ("loan_proceeds", "loan_repayments"):
        patterns = loan_patterns
    else:
        return 0.0

    total = 0.0
    for col in scf_df.columns:
        mk = parse_accountant_month(col)
        if mk != month_key_str:
            continue
        for idx_label in scf_df.index:
            for pat in patterns:
                if pat in str(idx_label):
                    val = scf_df.loc[idx_label, col]
                    v = float(val) if pd.notna(val) else 0.0
                    # For loans: split positive (proceeds) from negative (repayments)
                    if cf_key == "loan_proceeds" and v > 0:
                        total += v
                    elif cf_key == "loan_repayments" and v < 0:
                        total += v  # keeps negative
                    elif cf_key == "intercompany":
                        total += v
    return total


def _get_loan_cash_flow(loans: list, cf_key: str, month: str) -> float:
    """Get loan-related cash flow for a forecast month."""
    total = 0.0
    for loan in loans:
        if cf_key == "loan_repayments":
            # Use payment_history if available, else project from avg
            payments = loan.get("payment_history", {})
            avg_payment = loan.get("avg_monthly_payment", 0)

            if month in payments:
                total -= payments[month]  # negative = cash outflow
            elif avg_payment > 0:
                # Project: estimate remaining balance and apply avg payment
                bal_hist = loan.get("balance_by_month", {})
                sorted_m = sorted(bal_hist.keys())
                if sorted_m:
                    last_known = bal_hist[sorted_m[-1]]
                    # How many forecast months since last known?
                    forecast_idx = 0
                    y, m_int = map(int, sorted_m[-1].split("-"))
                    m_int += 1
                    if m_int > 12:
                        m_int, y = 1, y + 1
                    while month_key(y, m_int) < month:
                        forecast_idx += 1
                        m_int += 1
                        if m_int > 12:
                            m_int, y = 1, y + 1
                    if month_key(y, m_int) == month:
                        forecast_idx += 1
                    remaining = last_known - (avg_payment * (forecast_idx - 1))
                    if remaining > 0:
                        total -= min(avg_payment, remaining)
        elif cf_key == "loan_proceeds":
            # New loans: proceeds in start month
            if loan.get("start_date") == month and "user_" in loan.get("id", ""):
                total += loan.get("original_amount", 0)
    return total


def _get_scf_net_change(scf_df: pd.DataFrame, months: list) -> dict:
    """Extract actual SCF net cash change for each month."""
    result = {}
    if scf_df.empty:
        return result
    for col in scf_df.columns:
        mk = parse_accountant_month(col)
        if mk and mk in months:
            for label in scf_df.index:
                if "NET CASH INCREASE" in str(label).upper():
                    val = scf_df.loc[label, col]
                    if pd.notna(val):
                        result[mk] = float(val)
                    break
    return result


def _get_bs_cash_by_month(bs_df: pd.DataFrame, months: list) -> dict:
    """Extract bank account balances from Balance Sheet for each month."""
    result = {}
    if bs_df.empty:
        return result
    for col in bs_df.columns:
        mk = parse_accountant_month(col)
        if mk and mk in months:
            # Look for "Total for Bank Accounts" row
            for label in bs_df.index:
                if "Total for Bank" in str(label):
                    val = bs_df.loc[label, col]
                    if pd.notna(val):
                        result[mk] = float(val)
                    break
    return result


def calculate_opex_totals(opex_assumptions: dict, months: list) -> pd.DataFrame:
    """Aggregate opex by category across all studios."""
    result = {}
    for cat_key, cat_label in OPEX_CATEGORIES.items():
        row = {}
        for m in months:
            total = 0.0
            for studio_data in opex_assumptions.values():
                if isinstance(studio_data, dict) and cat_key in studio_data:
                    total += float(studio_data[cat_key].get(m, 0))
            row[m] = total
        result[cat_label] = row
    return pd.DataFrame(result).T


def calculate_studio_contribution(
    cash_sales: pd.DataFrame,
    opex_assumptions: dict,
    studio_code: str,
) -> pd.DataFrame:
    """Single studio: revenue - direct costs = contribution."""
    if studio_code not in cash_sales.index:
        return pd.DataFrame()

    months = list(cash_sales.columns)
    rows = {"Revenue": {m: cash_sales.loc[studio_code, m] for m in months}}

    studio_opex = opex_assumptions.get(studio_code, {})
    total_costs = {m: 0.0 for m in months}
    for cat_key, cat_label in OPEX_CATEGORIES.items():
        cat_data = studio_opex.get(cat_key, {})
        row = {}
        for m in months:
            val = float(cat_data.get(m, 0))
            row[m] = val
            total_costs[m] += val
        rows[cat_label] = row

    rows["Total Costs"] = total_costs
    rows["Contribution"] = {m: rows["Revenue"][m] - total_costs[m] for m in months}

    df = pd.DataFrame(rows).T
    df.index.name = "Line Item"
    return df
