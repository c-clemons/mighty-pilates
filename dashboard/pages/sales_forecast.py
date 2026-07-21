"""
Sales Forecast page — editable per-studio monthly cash sales grid.
Matches the Excel model's "Sales FCST" tab.
"""

import streamlit as st
import pandas as pd

from dashboard.data_store import DataStore
from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS,
    month_display, parse_accountant_month,
)
from dashboard.financial_calcs import get_actuals_cash_sales_by_studio


def show():
    ds = DataStore.get()

    last_actuals = ds.get_last_actuals_month()
    last_key = ds.get_last_actuals_month_key()
    st.caption(f"Actuals through **{last_actuals}** | Forecast columns are editable")

    # Build combined grid: actuals + forecast
    actuals_months = ds.get_actuals_months()
    forecast_months = ds.get_forecast_months()
    all_months = actuals_months + forecast_months

    # Actuals from accountant
    studio_pls = ds.get_actuals_studio_pls()
    actuals_grid = get_actuals_cash_sales_by_studio(studio_pls, actuals_months)

    # Forecast from data store
    forecast_df = ds.get_sales_forecast()

    # Combine into single DataFrame
    studios = list(ACTIVE_STUDIOS.keys()) + list(DEVELOPMENT_STUDIOS.keys())
    display_df = pd.DataFrame(0.0, index=studios, columns=all_months)

    for studio in studios:
        for m in actuals_months:
            if studio in actuals_grid.index and m in actuals_grid.columns:
                display_df.loc[studio, m] = actuals_grid.loc[studio, m]
        for m in forecast_months:
            if studio in forecast_df.index and m in forecast_df.columns:
                display_df.loc[studio, m] = forecast_df.loc[studio, m]

    # Add studio names as first visible column
    display_df.insert(0, "Studio", [
        ACTIVE_STUDIOS.get(s, DEVELOPMENT_STUDIOS.get(s, s)) for s in studios
    ])

    # Controls: how many months to show
    col1, col2 = st.columns(2)
    with col1:
        show_actuals = st.checkbox("Show actuals months", value=False)
    with col2:
        forecast_horizon = st.slider("Forecast months to show", 6, 24, 12)

    # Filter columns
    visible_months = []
    if show_actuals:
        visible_months += actuals_months[-6:]  # last 6 actuals months
    visible_months += forecast_months[:forecast_horizon]

    # Prepare display columns with readable headers
    col_config = {"Studio": st.column_config.TextColumn("Studio", width=140, disabled=True)}
    for m in visible_months:
        display_name = month_display(m)
        is_actual = m <= last_key
        col_config[m] = st.column_config.NumberColumn(
            display_name,
            format="%.0f",
            disabled=is_actual,
            width=95,
        )

    visible_cols = ["Studio"] + visible_months
    edit_df = display_df[visible_cols].copy()

    # Editable grid
    edited = st.data_editor(
        edit_df,
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="sales_editor",
    )

    # Add totals row
    total_row = {}
    for m in visible_months:
        total_row[m] = edited[m].sum()
    total_row["Studio"] = "TOTAL"
    st.dataframe(
        pd.DataFrame([total_row])[visible_cols],
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
    )

    # Save button
    if st.button("Save Forecast", type="primary"):
        # Extract forecast values back into a clean DataFrame
        save_df = pd.DataFrame(0.0, index=studios, columns=forecast_months)
        for studio in studios:
            for m in forecast_months:
                if m in edited.columns:
                    row_idx = studios.index(studio)
                    save_df.loc[studio, m] = edited.iloc[row_idx][m]

        ds.set_sales_forecast_bulk(save_df)
        st.success("Forecast saved.")
        st.rerun()
