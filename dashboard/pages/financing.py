"""
Financing & Loans page — view existing debt, add new loans, see debt service impact.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import uuid

from dashboard.data_store import DataStore
from dashboard.constants import month_display, month_key
from dashboard.financial_calcs import (
    calculate_loan_schedule,
    get_total_debt_service,
)


def show():
    ds = DataStore.get()

    loans = ds.get_loans()
    forecast_months = ds.get_forecast_months()
    all_months = ds.get_actuals_months() + forecast_months

    # --- Summary KPIs ---
    total_balance = sum(l.get("current_balance", 0) for l in loans)
    total_monthly = sum(l.get("avg_monthly_payment", 0) for l in loans)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Outstanding Debt", f"${total_balance:,.0f}")
    with col2:
        st.metric("Est. Monthly Debt Service", f"${total_monthly:,.0f}")
    with col3:
        months_to_payoff = total_balance / total_monthly if total_monthly > 0 else 0
        st.metric("Est. Months to Payoff", f"{months_to_payoff:.0f}")

    st.divider()

    # --- Existing Loans Table ---
    st.subheader("Active Loans")

    for loan in loans:
        with st.expander(f"**{loan['name']}** — Balance: ${loan.get('current_balance', 0):,.0f}"):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.caption("Original Amount")
                st.markdown(f"**${loan.get('original_amount', 0):,.0f}**")
            with col2:
                st.caption("Current Balance")
                st.markdown(f"**${loan.get('current_balance', 0):,.0f}**")
            with col3:
                st.caption("Avg Monthly Payment")
                st.markdown(f"**${loan.get('avg_monthly_payment', 0):,.0f}**")
            with col4:
                st.caption("Start Date")
                st.markdown(f"**{loan.get('start_date', 'N/A')}**")

            # Balance history chart
            bal_hist = loan.get("balance_by_month", {})
            if bal_hist:
                # Extend with projected paydown
                projected = _project_paydown(
                    bal_hist, loan.get("avg_monthly_payment", 0), forecast_months
                )
                all_bal = {**bal_hist, **projected}
                sorted_m = sorted(all_bal.keys())

                fig = go.Figure()
                # Split actuals vs projected
                last_actual = max(bal_hist.keys())
                actual_m = [m for m in sorted_m if m <= last_actual]
                proj_m = [m for m in sorted_m if m > last_actual]

                fig.add_trace(go.Scatter(
                    x=[month_display(m) for m in actual_m],
                    y=[all_bal[m] for m in actual_m],
                    mode="lines+markers", name="Actual",
                    line=dict(color="#2c3e50", width=2),
                    marker=dict(size=5),
                ))
                if proj_m:
                    # Connect with last actual point
                    proj_x = [month_display(actual_m[-1])] + [month_display(m) for m in proj_m]
                    proj_y = [all_bal[actual_m[-1]]] + [all_bal[m] for m in proj_m]
                    fig.add_trace(go.Scatter(
                        x=proj_x, y=proj_y,
                        mode="lines", name="Projected",
                        line=dict(color="#3498db", width=2, dash="dash"),
                    ))

                fig.update_layout(
                    height=250, margin=dict(t=10, b=30, l=50, r=20),
                    yaxis_tickformat="$,.0f",
                    showlegend=True, legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Debt Service Waterfall ---
    st.subheader("Total Debt Service Forecast")
    debt_service = get_total_debt_service(loans, forecast_months[:18])

    fig = go.Figure()
    display_months = [month_display(m) for m in forecast_months[:18]]
    fig.add_trace(go.Bar(
        x=display_months,
        y=[debt_service[m] for m in forecast_months[:18]],
        marker_color="#e74c3c", opacity=0.8, name="Debt Service",
    ))
    fig.update_layout(
        height=300, margin=dict(t=10, b=30),
        yaxis_tickformat="$,.0f",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Add New Loan ---
    st.subheader("Add New Loan / Credit Line")

    with st.form("new_loan_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Loan Name", placeholder="e.g., New Credit Line")
            amount = st.number_input("Loan Amount", min_value=0, step=10000, value=0)
            rate = st.number_input("Annual Interest Rate (%)", min_value=0.0, max_value=30.0,
                                    step=0.25, value=8.0) / 100
        with col2:
            start_y = st.selectbox("Start Year", [2026, 2027, 2028])
            start_m = st.selectbox("Start Month", list(range(1, 13)), index=2)
            term_months = st.number_input("Term (months)", min_value=1, max_value=120, value=24)
            amort_type = st.selectbox("Amortization", [
                "Fully Amortizing", "Interest Only", "Custom"
            ])

        submitted = st.form_submit_button("Add Loan", type="primary")

        if submitted and name and amount > 0:
            start = month_key(start_y, start_m)
            end_y, end_m = start_y, start_m + term_months - 1
            while end_m > 12:
                end_m -= 12
                end_y += 1
            maturity = month_key(end_y, end_m)

            amort_map = {
                "Fully Amortizing": "fully_amortizing",
                "Interest Only": "interest_only",
                "Custom": "custom",
            }

            schedule = calculate_loan_schedule(
                principal=amount,
                annual_rate=rate,
                start_month=start,
                maturity_month=maturity,
                amortization=amort_map[amort_type],
            )

            # Build loan dict
            new_loan = {
                "id": f"user_{uuid.uuid4().hex[:8]}",
                "name": name,
                "original_amount": amount,
                "current_balance": amount,
                "rate": rate,
                "start_date": start,
                "maturity_date": maturity,
                "amortization": amort_map[amort_type],
                "balance_by_month": dict(zip(schedule["month"], schedule["ending_balance"])),
                "avg_monthly_payment": schedule["total_payment"].mean(),
                "payment_history": dict(zip(schedule["month"], schedule["total_payment"])),
            }

            ds.add_loan(new_loan)
            st.success(f"Added {name}: ${amount:,.0f} at {rate*100:.1f}% for {term_months} months")
            st.rerun()


def _project_paydown(balance_history: dict, avg_payment: float, forecast_months: list) -> dict:
    """Project loan balance forward using average payment."""
    if not balance_history or avg_payment <= 0:
        return {}
    last_month = max(balance_history.keys())
    balance = balance_history[last_month]
    result = {}
    for m in forecast_months:
        if m <= last_month:
            continue
        payment = min(avg_payment, balance)
        balance = max(balance - payment, 0)
        result[m] = balance
        if balance == 0:
            break
    return result
