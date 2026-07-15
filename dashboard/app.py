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

from empirica_core.portal import chrome  # noqa: E402

# Must be the very first Streamlit call.
chrome.configure_page("Mighty Pilates | Cash Flow")

from empirica_core.portal.app import run_app, render_sync_status  # noqa: E402
from dashboard.data_store import DataStore  # noqa: E402


PAGES = {
    "Cash Flow Forecast": "dashboard.pages.cash_flow",
    "P&L": "dashboard.pages.studio_pl",
    "Cash, Debt & Equity": "dashboard.pages.cash_balance",
    "Sales Forecast": "dashboard.pages.sales_forecast",
    "Studio Assumptions": "dashboard.pages.assumptions",
    "CapEx & Studio Buildout": "dashboard.pages.capex_planner",
    "Financing & Loans": "dashboard.pages.financing",
    "Actuals & Variance": "dashboard.pages.actuals",
    "Scenarios": "dashboard.pages.scenarios",
}


def _sidebar_meta(sb, ds):
    sb.markdown(f"**Actuals through:** {ds.get_last_actuals_month()}")
    forecast_months = ds.get_forecast_months()
    if forecast_months:
        from dashboard.constants import month_display
        sb.markdown(f"**Forecast through:** {month_display(forecast_months[-1])}")


def _sidebar_extra(sb, ds):
    """Accountant package import — only works locally with the pipeline installed."""
    try:
        from pipeline.accountant_import import import_financials
    except ImportError:
        return  # pipeline not available (Streamlit Cloud)

    sb.markdown("**Import Financials**")
    uploaded = sb.file_uploader(
        "Upload accountant package", type=["xlsx"], label_visibility="collapsed",
    )
    if not uploaded:
        return

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name
    try:
        result = import_financials(tmp_path)
        ds.reload()
        sb.success(f"Imported {result['metadata']['last_actuals_month']}")
        # Commit to GitHub for durability
        status = ds.save_committed(
            f"import {result['metadata']['last_actuals_month']} actuals"
        )
        render_sync_status(sb, status)
        import streamlit as st
        st.rerun()
    except Exception as e:
        sb.error(f"Import failed: {e}")


run_app(
    app_name="Mighty Pilates",
    subtitle="Cash Flow Forecasting Model",
    pages=PAGES,
    primary_color="#1a1a2e",
    password_default="mighty2026",   # DEV ONLY — set `app_password` secret in prod
    datastore_get=DataStore.get,
    sidebar_meta=_sidebar_meta,
    sidebar_extra=_sidebar_extra,
)
