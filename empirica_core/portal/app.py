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


ADMIN_PAGE = "⚙ User Management"


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
    role_store=None,
    page_roles: Optional[Mapping[str, str]] = None,
    default_page_role: str = "investor",
) -> None:
    """Render the gated, branded, sidebar-navigated app.

    ``configure_page`` must already have been called by the entrypoint.

    Parameters
    ----------
    pages : ordered ``{"Human Label": "import.path.to.module"}``; each module
        exposes ``show()``.
    datastore_get : e.g. ``DataStore.get`` — called once, passed to the
        sidebar/meta callbacks.
    sidebar_meta : ``fn(sidebar, ds)`` for the metadata block.
    sidebar_extra : ``fn(sidebar, ds)`` for extra sidebar controls.
    role_store : optional ``RoleStore``. When given, adds the roles gate:
        no-role users see the landing page; pages are filtered by
        ``page_roles``; admins get a User Management page.
    page_roles : ``{page_label: min_role}``. Pages absent default to
        ``default_page_role`` (visible to any role).
    """
    import streamlit as st

    if not auth.require_access(app_name, subtitle, default=password_default):
        st.stop()

    chrome.inject_brand_css(primary_color, hide_chrome=hide_chrome)

    # --- role gate (opt-in) ------------------------------------------------
    email = None
    role = None
    if role_store is not None:
        from empirica_core.portal import roles as _roles

        email = _roles.resolve_identity()
        role = role_store.role_for(email)
        if role is None:
            _roles.render_landing(email, app_name, role_store)
            st.stop()

    ds = datastore_get() if datastore_get else None

    # Pages this role may see (+ admin page for admins).
    if role_store is not None:
        from empirica_core.portal import roles as _roles

        visible = [
            p for p in pages
            if _roles.can_view(role, (page_roles or {}).get(p, default_page_role))
        ]
        nav = visible + ([ADMIN_PAGE] if role == "admin" else [])
    else:
        nav = list(pages.keys())

    st.sidebar.title(app_name)
    if subtitle:
        st.sidebar.caption(subtitle)
    if role_store is not None:
        st.sidebar.caption(f"{email} · **{role}**")
    st.sidebar.divider()

    page = st.sidebar.radio("Navigate", nav, label_visibility="collapsed")

    st.sidebar.divider()
    if sidebar_meta:
        sidebar_meta(st.sidebar, ds)
        st.sidebar.divider()
    if sidebar_extra:
        sidebar_extra(st.sidebar, ds)

    if page == ADMIN_PAGE:
        from empirica_core.portal.admin import render_user_admin

        render_user_admin(role_store, current_admin_email=email or "")
        return

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
