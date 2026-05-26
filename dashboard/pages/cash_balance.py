"""Cash Flow, Debt & Owner Equity — management view of SCF, loans, and tax liability."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from dashboard.data_store import DataStore
from dashboard.constants import parse_accountant_month


def _fmt(val):
    """Format currency."""
    if val is None or pd.isna(val):
        return "$0"
    return f"${val:,.0f}"


def _fmt_signed(val):
    """Format with sign."""
    if val is None or pd.isna(val):
        return "$0"
    return f"${val:+,.0f}" if val != 0 else "$0"


def _extract_bs_value(bs_df, account_substr, month, alt_substrs=None):
    """Find a BS value by partial account name match.

    If alt_substrs is provided, try each alternative substring as a fallback.
    """
    if bs_df.empty or month not in bs_df.columns:
        return 0
    substrs_to_try = [account_substr] + (alt_substrs or [])
    for substr in substrs_to_try:
        for idx in bs_df.index:
            if substr.lower() in str(idx).lower():
                val = bs_df.at[idx, month]
                return float(val) if pd.notna(val) else 0
    return 0


def _extract_scf_value(scf_df, account_substr, month):
    """Find a SCF value by partial account name match."""
    if scf_df.empty or month not in scf_df.columns:
        return 0
    for idx in scf_df.index:
        if account_substr.lower() in str(idx).lower():
            val = scf_df.at[idx, month]
            return float(val) if pd.notna(val) else 0
    return 0


def show():
    ds = DataStore.get()
    st.header("Cash Flow, Debt & Owner Equity")

    bs_df = ds.get_actuals_bs()
    scf_df = ds.get_actuals_scf()
    months = ds.get_actuals_months()
    month_labels = sorted(bs_df.columns.tolist(),
                          key=lambda m: parse_accountant_month(m) or "") if not bs_df.empty else []

    if not month_labels:
        st.warning("No actuals data available. Import a financials package first.")
        return

    # ─── Cash Position ───────────────────────────────────────────────
    st.subheader("Cash Position")

    cash_data = []
    for m in month_labels:
        chase = _extract_bs_value(bs_df, "Chase Checking", m)
        classpass_clearing = _extract_bs_value(bs_df, "Merchant Clearing - Classpass", m)
        mindbody_clearing = _extract_bs_value(bs_df, "Merchant Clearing - Mindbody", m)
        wellhub_clearing = _extract_bs_value(bs_df, "Merchant Clearing - Wellhub", m)
        total_bank = _extract_bs_value(bs_df, "Total for Bank Accounts", m,
                                       alt_substrs=["Total Bank Accounts"])
        net_change = _extract_scf_value(scf_df, "NET CASH INCREASE", m)

        cash_data.append({
            "Month": m,
            "Chase Checking": chase,
            "ClassPass Clearing": classpass_clearing,
            "MindBody Clearing": mindbody_clearing,
            "Wellhub Clearing": wellhub_clearing,
            "Total Cash": total_bank,
            "Net Cash Change": net_change,
        })

    cash_df = pd.DataFrame(cash_data).set_index("Month")

    # KPI metrics
    latest = cash_data[-1]
    prev = cash_data[-2] if len(cash_data) > 1 else cash_data[0]
    cols = st.columns(4)
    cols[0].metric("Total Cash", _fmt(latest["Total Cash"]),
                   _fmt_signed(latest["Total Cash"] - prev["Total Cash"]))
    cols[1].metric("Chase Checking", _fmt(latest["Chase Checking"]))
    cols[2].metric("Net Cash Change", _fmt_signed(latest["Net Cash Change"]))
    cols[3].metric("Merchant Clearing",
                   _fmt(latest["ClassPass Clearing"] + latest["MindBody Clearing"] + latest["Wellhub Clearing"]))

    # Cash trend chart
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=cash_df.index, y=cash_df["Chase Checking"],
        name="Chase Checking", marker_color="#2c3e50",
    ))
    fig.add_trace(go.Bar(
        x=cash_df.index, y=cash_df["ClassPass Clearing"] + cash_df["MindBody Clearing"] + cash_df["Wellhub Clearing"],
        name="Merchant Clearing", marker_color="#3498db",
    ))
    fig.add_trace(go.Scatter(
        x=cash_df.index, y=cash_df["Total Cash"],
        name="Total Cash", line=dict(color="#e74c3c", width=2), mode="lines+markers",
    ))
    fig.update_layout(barmode="stack", height=300, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)

    # Cash flow waterfall — transposed (months as columns)
    st.caption("Monthly Cash Flow Summary")
    scf_rows = {"Operating": {}, "Investing": {}, "Financing": {}, "Net Change": {}}
    for m in month_labels:
        scf_rows["Operating"][m] = _extract_scf_value(scf_df, "Net cash provided by operating", m)
        scf_rows["Investing"][m] = _extract_scf_value(scf_df, "Net cash provided by investing", m)
        scf_rows["Financing"][m] = _extract_scf_value(scf_df, "Net cash provided by financing", m)
        scf_rows["Net Change"][m] = _extract_scf_value(scf_df, "NET CASH INCREASE", m)
    scf_sum_df = pd.DataFrame(scf_rows).T
    scf_sum_df.index.name = "Cash Flow"
    st.dataframe(scf_sum_df.style.format("${:,.0f}"), use_container_width=True)

    st.divider()

    # ─── Debt Schedule ───────────────────────────────────────────────
    st.subheader("Debt Schedule")

    loan_accounts = [
        ("MindBody - SM", "Total for 242001 MindBody Loan - SM",
         ["Total 242001 MindBody Loan - SM"]),
        ("MindBody - PH", "Total for 242002 MindBody Loan - PH",
         ["Total 242002 MindBody Loan - PH"]),
        ("MindBody - LF", "Total for 242003 MindBody Loan - LF",
         ["Total 242003 MindBody Loan - LF"]),
        ("MindBody - MR", "Total for 242004 MindBody Loan - MR",
         ["Total 242004 MindBody Loan - MR"]),
        ("Samson Loan", "243000 Samson Loan", []),
        ("Specialty Capital", "244000 Specialty Capital Loan", []),
        ("Norbrook Inc", "241000 Loan from Norbrook Inc", []),
    ]

    loan_data = []
    for display_name, bs_key, alts in loan_accounts:
        row = {"Loan": display_name}
        for m in month_labels:
            row[m] = _extract_bs_value(bs_df, bs_key, m, alt_substrs=alts)
        loan_data.append(row)

    # Add totals row
    totals = {"Loan": "TOTAL DEBT"}
    for m in month_labels:
        totals[m] = sum(row[m] for row in loan_data)
    loan_data.append(totals)

    loan_df = pd.DataFrame(loan_data).set_index("Loan")
    st.dataframe(loan_df.style.format("${:,.0f}"), use_container_width=True)

    # Debt trend chart
    fig2 = go.Figure()
    colors = ["#2c3e50", "#3498db", "#e67e22", "#e74c3c", "#9b59b6", "#1abc9c", "#34495e"]
    for i, (display_name, _) in enumerate(loan_accounts):
        vals = [loan_df.at[display_name, m] for m in month_labels]
        fig2.add_trace(go.Bar(
            x=month_labels, y=vals, name=display_name,
            marker_color=colors[i % len(colors)],
        ))
    fig2.update_layout(barmode="stack", height=300, margin=dict(t=10, b=30),
                       legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig2, use_container_width=True)

    # Monthly debt service (from SCF)
    st.caption("Monthly Debt Service (from SCF)")
    debt_service = []
    debt_scf_accounts = [
        ("MindBody - SM (net)", ["242001 MindBody Loan:MindBody Loan - SM",
                                  "242001-1 MindBody Loan:MindBody Loan - SM:MindBody Contra"]),
        ("MindBody - PH (net)", ["242002 MindBody Loan:MindBody Loan - PH",
                                  "242002-1 MindBody Loan:MindBody Loan - PH:MindBody Contra"]),
        ("MindBody - LF (net)", ["242003 MindBody Loan:MindBody Loan - LF",
                                  "242003-1 MindBody Loan:MindBody Loan - LF:MindBody Contra"]),
        ("MindBody - MR (net)", ["242004 MindBody Loan:MindBody Loan - MR",
                                  "242004-1 MindBody Loan:MindBody Loan - MR:MindBody Contra"]),
        ("Samson Loan", ["243000 Samson Loan"]),
        ("Specialty Capital", ["244000 Specialty Capital Loan"]),
    ]
    for display_name, scf_keys in debt_scf_accounts:
        row = {"Payment": display_name}
        for m in month_labels:
            total = sum(_extract_scf_value(scf_df, k, m) for k in scf_keys)
            row[m] = total
        debt_service.append(row)

    # Total
    ds_totals = {"Payment": "TOTAL DEBT SERVICE"}
    for m in month_labels:
        ds_totals[m] = sum(row[m] for row in debt_service)
    debt_service.append(ds_totals)

    ds_df = pd.DataFrame(debt_service).set_index("Payment")
    st.dataframe(ds_df.style.format("${:,.0f}"), use_container_width=True)

    st.divider()

    # ─── Owner / Financing ───────────────────────────────────────────
    st.subheader("Owner & Financing")

    owner_accounts = [
        ("Due to Cricket", "251000 Due to Cricket"),
        ("Due to Khary", "Due to Khary"),
        ("Norbrook Inc Investment", "309000 Norbrook Inc Investment"),
        ("Contingent Liability", "245000 Contingent  Liability"),
    ]

    owner_data = []
    for display_name, bs_key in owner_accounts:
        row = {"Account": display_name}
        for m in month_labels:
            row[m] = _extract_bs_value(bs_df, bs_key, m)
        owner_data.append(row)

    owner_df = pd.DataFrame(owner_data).set_index("Account")
    st.dataframe(owner_df.style.format("${:,.0f}"), use_container_width=True)

    # Financing activity from SCF
    st.caption("Financing Activity (from SCF)")
    fin_items = []
    fin_scf = [
        ("ROU Lease Payments", "239500 ROU - Studio Lease Liabilities"),
        ("Norbrook Inc Loan", "241000 Loan from Norbrook"),
        ("Khary Distribution", "Due to Khary"),
    ]
    for name, key in fin_scf:
        row = {"Item": name}
        for m in month_labels:
            row[m] = _extract_scf_value(scf_df, key, m)
        fin_items.append(row)
    fin_df = pd.DataFrame(fin_items).set_index("Item")
    st.dataframe(fin_df.style.format("${:,.0f}"), use_container_width=True)

    st.divider()

    # ─── Owner Tax Liability ─────────────────────────────────────────
    st.subheader("Estimated Owner Tax Liability")
    st.caption("37% blended rate on cumulative net income | 35% Cricket / 65% Khary")

    tax_data = ds.get_owner_tax_liability()
    if tax_data:
        tax_rows = []
        for m in sorted(tax_data.keys()):
            vals = tax_data[m]
            tax_rows.append({
                "Month": m,
                "Cumulative Net Income": vals.get("Cumulative Net Income", 0),
                "Estimated Tax (37%)": vals.get("Estimated Tax (37%)", 0),
                "Cricket (35%)": vals.get("Cricket (35%)", 0),
                "Khary (65%)": vals.get("Khary (65%)", 0),
            })
        tax_df = pd.DataFrame(tax_rows).set_index("Month")
        st.dataframe(tax_df.style.format("${:,.0f}"), use_container_width=True)

        latest_tax = tax_rows[-1]
        if latest_tax["Estimated Tax (37%)"] > 0:
            st.warning(
                f"Estimated tax liability: **{_fmt(latest_tax['Estimated Tax (37%)'])}** "
                f"(Cricket: {_fmt(latest_tax['Cricket (35%)'])}, "
                f"Khary: {_fmt(latest_tax['Khary (65%)'])})"
            )
        else:
            st.info("Cumulative net income is negative — no estimated tax liability.")
    else:
        st.info("Owner tax liability data not available. Run `scripts/update_actuals.py` to generate.")
