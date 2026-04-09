#!/usr/bin/env python3
"""
Mighty Pilates Cash Flow Forecasting Dashboard

Usage:
    cd /Users/chandlerclemons/mighty-pilates
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Add project root so we can import from pipeline/ and dashboard/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# Must be the very first Streamlit call — only called once
st.set_page_config(
    page_title="Mighty Pilates | Cash Flow",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

from dashboard.data_store import DataStore


PAGES = {
    "Cash Flow Forecast": "dashboard.pages.cash_flow",
    "Sales Forecast": "dashboard.pages.sales_forecast",
    "Studio Assumptions": "dashboard.pages.assumptions",
    "Financing & Loans": "dashboard.pages.financing",
    "New Studio Planner": "dashboard.pages.new_studio",
    "Actuals & Variance": "dashboard.pages.actuals",
    "Studio P&L": "dashboard.pages.studio_pl",
    "Scenarios": "dashboard.pages.scenarios",
}


def check_password() -> bool:
    """Simple password gate for Streamlit Cloud public deployment."""
    if st.session_state.get("authenticated"):
        return True

    # Get password from secrets, fall back to default
    try:
        correct_password = st.secrets["app_password"]
    except (KeyError, FileNotFoundError):
        correct_password = "mighty2026"

    st.title("Mighty Pilates")
    st.caption("Cash Flow Forecasting Model")

    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        if password == correct_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


def main():
    if not check_password():
        return

    # Custom CSS
    st.markdown("""
    <style>
    .main-header {font-size: 1.8rem; font-weight: 700; margin-bottom: 0.3rem;}
    .sub-header {font-size: 1rem; color: #666; margin-bottom: 1.5rem;}
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        padding: 12px 16px;
        border-radius: 8px;
        border: 1px solid #e9ecef;
    }
    </style>
    """, unsafe_allow_html=True)

    # Initialize data store on first run
    if "initialized" not in st.session_state:
        ds = DataStore.get()
        ds.load()
        st.session_state.initialized = True

    ds = DataStore.get()

    # --- Sidebar ---
    st.sidebar.title("Mighty Pilates")
    st.sidebar.caption("Cash Flow Forecasting Model")
    st.sidebar.divider()

    # Navigation
    page = st.sidebar.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")

    st.sidebar.divider()

    # Metadata
    st.sidebar.markdown(f"**Actuals through:** {ds.get_last_actuals_month()}")
    forecast_months = ds.get_forecast_months()
    if forecast_months:
        from dashboard.constants import month_display
        st.sidebar.markdown(f"**Forecast through:** {month_display(forecast_months[-1])}")

    st.sidebar.divider()

    # Accountant package import (only works locally with pipeline installed)
    try:
        from pipeline.accountant_import import import_financials
        st.sidebar.markdown("**Import Financials**")
        uploaded = st.sidebar.file_uploader(
            "Upload accountant package", type=["xlsx"],
            label_visibility="collapsed",
        )
        if uploaded:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                result = import_financials(tmp_path)
                ds.reload()
                st.sidebar.success(f"Imported {result['metadata']['last_actuals_month']}")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Import failed: {e}")
    except ImportError:
        pass  # Pipeline not available (Streamlit Cloud)

    # --- Route to page ---
    module_path = PAGES[page]
    import importlib
    module = importlib.import_module(module_path)
    module.show()


if __name__ == "__main__":
    main()
