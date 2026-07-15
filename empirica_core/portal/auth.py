"""Access control for client portals.

Two layers, in order of preference:

1. :func:`proxy_identity` — when the app runs behind an identity proxy
   (Cloudflare Access or Google IAP), the proxy authenticates the user and
   forwards their verified email in a header. This is the recommended,
   professional option: clients sign in with their own SSO and never see a
   shared password.

2. :func:`password_gate` — a simple shared-password gate for a public
   Streamlit Community Cloud deploy where no proxy is in front. Lower
   assurance; use only when a proxy isn't available.
"""
from __future__ import annotations

from typing import Optional


def proxy_identity() -> Optional[str]:
    """Return the verified email from an identity proxy, or ``None``.

    Recognizes Cloudflare Access (``Cf-Access-Authenticated-User-Email``) and
    Google IAP (``X-Goog-Authenticated-User-Email``). Returns ``None`` in
    local/dev where no proxy sets these headers.
    """
    try:
        import streamlit as st

        headers = st.context.headers  # Streamlit >= 1.37
    except Exception:
        return None
    if not headers:
        return None

    cf = headers.get("Cf-Access-Authenticated-User-Email")
    if cf:
        return cf
    goog = headers.get("X-Goog-Authenticated-User-Email")
    if goog:
        # Format is "accounts.google.com:user@example.com"
        return goog.split(":")[-1]
    return None


def password_gate(
    app_name: str,
    subtitle: str = "",
    *,
    secret_key: str = "app_password",
    default: Optional[str] = None,
) -> bool:
    """Render a password gate. Returns True once authenticated.

    The correct password is read from ``st.secrets[secret_key]`` and falls back
    to ``default`` (intended for local dev only — set the secret in prod). If
    neither is set, the gate stays closed and shows a configuration error.
    """
    import streamlit as st

    if st.session_state.get("authenticated"):
        return True

    try:
        correct = st.secrets[secret_key]
    except (KeyError, FileNotFoundError):
        correct = default

    st.title(app_name)
    if subtitle:
        st.caption(subtitle)

    if not correct:
        st.error(
            f"No password configured. Set `{secret_key}` in Streamlit secrets."
        )
        return False

    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        if password == correct:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


def require_access(
    app_name: str,
    subtitle: str = "",
    *,
    secret_key: str = "app_password",
    default: Optional[str] = None,
) -> Optional[str]:
    """Gate the app. Returns the identity string once access is granted, else ``None``.

    Prefers proxy identity (SSO) and falls back to the password gate. Callers
    typically do::

        who = auth.require_access("Client Portal")
        if not who:
            st.stop()
    """
    who = proxy_identity()
    if who:
        return who
    return app_name if password_gate(
        app_name, subtitle, secret_key=secret_key, default=default
    ) else None


__all__ = ["proxy_identity", "password_gate", "require_access"]
