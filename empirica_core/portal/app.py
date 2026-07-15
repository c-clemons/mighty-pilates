"""Shared app harness — the router every client dashboard's ``app.py`` reduces to.

Each client entrypoint becomes::

    from empirica_core.portal import chrome
    chrome.configure_page("Client | Cash Flow")     # MUST be first st call

    from empirica_core.portal.app import run_app
    from client_dash.data_store import DataStore

    PAGES = {"Overview": "client_dash.pages.overview", ...}

    run_app(
        app_name="Client Co",
        subtitle="Financial Model",
        pages=PAGES,
        primary_color="#1B2A4A",
        password_default="client2026",     # dev only; set secret in prod
        datastore_get=DataStore.get,
        sidebar_meta=lambda sb, ds: sb.markdown(f"**Actuals through:** {ds.get_last_actuals_month()}"),
    )

Each page module exposes a zero-arg ``def show():`` and reads state via
``DataStore.get()``.
"""
from __future__ import annotations

import importlib
from typing import Callable, Mapping, Optional

from empirica_core.portal import auth, chrome


def run_app(
    *,
    app_name: str,
    pages: Mapping[str, str],
    subtitle: str = "",
    primary_color: str = "#1B2A4A",
    password_default: Optional[str] = None,
    datastore_get: Optional[Callable] = None,
    sidebar_meta: Optional[Callable] = None,
    sidebar_extra: Optional[Callable] = None,
    hide_chrome: bool = True,
) -> None:
    """Render the gated, branded, sidebar-navigated app.

    ``configure_page`` must already have been called by the entrypoint.

    Parameters
    ----------
    pages : ordered ``{"Human Label": "import.path.to.module"}``; each module
        exposes ``show()``.
    datastore_get : e.g. ``DataStore.get`` — called once, passed to the
        sidebar/meta callbacks.
    sidebar_meta : ``fn(sidebar, ds)`` for the "Actuals through / Forecast
        through" metadata block.
    sidebar_extra : ``fn(sidebar, ds)`` for extra sidebar controls (e.g. an
        upload widget) rendered below the metadata.
    """
    import streamlit as st

    if not auth.require_access(app_name, subtitle, default=password_default):
        st.stop()

    chrome.inject_brand_css(primary_color, hide_chrome=hide_chrome)

    ds = datastore_get() if datastore_get else None

    st.sidebar.title(app_name)
    if subtitle:
        st.sidebar.caption(subtitle)
    st.sidebar.divider()

    page = st.sidebar.radio(
        "Navigate", list(pages.keys()), label_visibility="collapsed"
    )

    st.sidebar.divider()
    if sidebar_meta:
        sidebar_meta(st.sidebar, ds)
        st.sidebar.divider()
    if sidebar_extra:
        sidebar_extra(st.sidebar, ds)

    module = importlib.import_module(pages[page])
    module.show()


def render_sync_status(container, status: Optional[dict]) -> None:
    """Surface a ``save_committed`` status dict in a Streamlit container."""
    if not status:
        return
    if status.get("ok"):
        url = status.get("url")
        container.success(
            f"Synced to GitHub — [view commit]({url})" if url else "Synced to GitHub"
        )
        return
    msg = status.get("message", "unknown error")
    if msg in ("no token configured", "github sync not configured"):
        container.warning(
            "Saved locally, but not synced to GitHub — values may be lost on the "
            "next redeploy. Configure `github_token` in Streamlit secrets."
        )
    else:
        container.warning(f"Saved locally, but GitHub sync failed: {msg}")


__all__ = ["run_app", "render_sync_status"]
