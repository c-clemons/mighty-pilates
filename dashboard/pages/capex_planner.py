"""
CapEx & Studio Buildout Planner — tracks leasehold improvements and equipment
for existing and future studios. Feeds into the Cash Flow Forecast investing section.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from dashboard.data_store import DataStore
from dashboard.constants import month_display, month_key


def show():
    ds = DataStore.get()
    st.header("CapEx & Studio Buildout")
    st.caption("Plan leasehold improvements and equipment purchases. Active projects flow into the Cash Flow Forecast.")

    capex = ds.get_capex_projects()
    forecast_months = ds.get_forecast_months()

    # --- Add New Project ---
    with st.expander("Add New Project", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_name = st.text_input("Project Name", placeholder="e.g., West Portal Buildout")
        with col2:
            new_location = st.text_input("Location", placeholder="e.g., West Portal")
        with col3:
            new_priority = st.number_input("Priority", 1, 50, len(capex) + 1)

        col4, col5, col6 = st.columns(3)
        with col4:
            new_total = st.number_input("Total Budget", 0, 5000000, 100000, step=10000)
        with col5:
            new_start = st.selectbox("Start Month",
                                      [month_display(m) for m in forecast_months[:24]],
                                      key="capex_start")
        with col6:
            new_duration = st.number_input("Duration (months)", 1, 24, 6)

        new_active = st.checkbox("Active", value=True)

        if st.button("Add Project", type="primary"):
            if new_name:
                # Parse start month back to key
                start_idx = [month_display(m) for m in forecast_months[:24]].index(new_start)
                start_key = forecast_months[start_idx]

                # Spread budget evenly across months
                monthly = round(new_total / new_duration, 2)
                schedule = {}
                y, mo = map(int, start_key.split("-"))
                for i in range(new_duration):
                    mk = month_key(y, mo)
                    schedule[mk] = monthly
                    mo += 1
                    if mo > 12:
                        mo, y = 1, y + 1

                project = {
                    "name": new_name,
                    "location": new_location,
                    "priority": new_priority,
                    "total_budget": new_total,
                    "active": new_active,
                    "start_month": start_key,
                    "duration_months": new_duration,
                    "schedule": schedule,
                }
                ds.add_capex_project(project)
                st.success(f"Added: {new_name}")
                st.rerun()

    st.divider()

    # --- Project List ---
    if not capex:
        st.info("No CapEx projects planned. Add one above.")
        return

    st.subheader("Planned Projects")

    # Summary chart
    monthly_totals = {}
    for proj in capex:
        if proj.get("active"):
            for m, val in proj.get("schedule", {}).items():
                monthly_totals[m] = monthly_totals.get(m, 0) + val

    if monthly_totals:
        sorted_months = sorted(monthly_totals.keys())
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=[month_display(m) for m in sorted_months],
            y=[monthly_totals[m] for m in sorted_months],
            marker_color="#e67e22",
        ))
        fig.update_layout(
            height=250, margin=dict(t=10, b=30),
            yaxis_tickformat="$,.0f",
            title_text="Monthly CapEx Spend (Active Projects)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Project table
    rows = []
    for i, proj in enumerate(capex):
        spent = sum(v for m, v in proj.get("schedule", {}).items()
                    if m <= ds.get_last_actuals_month_key())
        remaining = proj.get("total_budget", 0) - spent
        rows.append({
            "#": proj.get("priority", i + 1),
            "Project": proj.get("name", ""),
            "Location": proj.get("location", ""),
            "Active": "Yes" if proj.get("active") else "No",
            "Budget": proj.get("total_budget", 0),
            "Spent": spent,
            "Remaining": remaining,
            "Start": month_display(proj.get("start_month", "")),
            "Duration": f"{proj.get('duration_months', 0)}mo",
        })

    proj_df = pd.DataFrame(rows)
    st.dataframe(
        proj_df.style.format({
            "Budget": "${:,.0f}", "Spent": "${:,.0f}", "Remaining": "${:,.0f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # --- Edit / Delete ---
    st.divider()
    st.subheader("Edit Project Schedule")

    edit_options = [f"{p.get('name', f'Project {i}')}" for i, p in enumerate(capex)]
    edit_idx = st.selectbox("Select project to edit", range(len(edit_options)),
                            format_func=lambda i: edit_options[i], key="capex_edit")

    proj = capex[edit_idx]
    schedule = proj.get("schedule", {})

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("Delete Project", type="secondary"):
            ds.remove_capex_project(edit_idx)
            st.rerun()

        new_active_state = st.checkbox("Active", value=proj.get("active", True),
                                        key="capex_active_toggle")
        if new_active_state != proj.get("active"):
            ds.update_capex_project(edit_idx, {"active": new_active_state})
            st.rerun()

    with col_a:
        if schedule:
            sched_df = pd.DataFrame([
                {"Month": month_display(m), "Amount": v}
                for m, v in sorted(schedule.items())
            ])
            edited = st.data_editor(
                sched_df, hide_index=True, key=f"capex_sched_{edit_idx}",
                column_config={
                    "Month": st.column_config.TextColumn(disabled=True),
                    "Amount": st.column_config.NumberColumn(
                        "Monthly Spend", min_value=0, step=1000, format="$%d"
                    ),
                },
                use_container_width=True,
            )

            # Check for changes
            new_schedule = {}
            for _, row in edited.iterrows():
                # Parse month display back to key
                for m in sorted(schedule.keys()):
                    if month_display(m) == row["Month"]:
                        new_schedule[m] = row["Amount"]
                        break

            if new_schedule != schedule:
                ds.update_capex_project(edit_idx, {
                    "schedule": new_schedule,
                    "total_budget": sum(new_schedule.values()),
                })
                st.rerun()

    # Total summary
    st.divider()
    total_active = sum(p.get("total_budget", 0) for p in capex if p.get("active"))
    total_all = sum(p.get("total_budget", 0) for p in capex)
    col1, col2, col3 = st.columns(3)
    col1.metric("Active Projects", sum(1 for p in capex if p.get("active")))
    col2.metric("Active Budget", f"${total_active:,.0f}")
    col3.metric("Total Pipeline", f"${total_all:,.0f}")
