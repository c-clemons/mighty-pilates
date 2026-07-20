"""In-app user administration — the client's Clerk-equivalent.

Renders a page where an admin grants/changes/revokes roles and approves pending
access requests. Backed by :class:`empirica_core.portal.roles.RoleStore`.
"""
from __future__ import annotations

from empirica_core.portal.roles import ROLES, RoleStore


def render_user_admin(store: RoleStore, current_admin_email: str = "") -> None:
    import pandas as pd
    import streamlit as st

    st.header("User Management")
    st.caption(
        "Grant people access by email and set what they can see. Changes take "
        "effect on their next page load."
    )

    # --- pending access requests -------------------------------------------
    pend = store.pending()
    if pend:
        st.subheader(f"Pending requests ({len(pend)})")
        for email in pend:
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.write(email)
            role = c2.selectbox(
                "Role", ROLES, index=ROLES.index("investor"),
                key=f"pend_role_{email}", label_visibility="collapsed",
            )
            if c3.button("Approve", key=f"pend_ok_{email}"):
                store.set_role(email, role, current_admin_email)
                st.rerun()
        st.divider()

    # --- current users ------------------------------------------------------
    st.subheader("Current users")
    users = store.all_users()
    if users:
        df = pd.DataFrame(users)[["email", "role", "added_by", "added_at"]]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No users yet. Add the first one below.")

    # --- add / update -------------------------------------------------------
    st.subheader("Add or update a user")
    c1, c2, c3 = st.columns([3, 2, 1])
    email = c1.text_input("Email", key="admin_add_email", placeholder="person@company.com")
    role = c2.selectbox("Role", ROLES, key="admin_add_role")
    if c3.button("Grant access", type="primary"):
        if email and "@" in email:
            store.set_role(email.strip(), role, current_admin_email)
            st.success(f"{email} is now **{role}**.")
            st.rerun()
        else:
            st.error("Enter a valid email.")

    st.caption(
        "**Roles:** admin (everything + this page) · management (all financials) · "
        "employee (operations, no payroll) · investor (summary only)."
    )

    # --- revoke -------------------------------------------------------------
    revocable = [u["email"] for u in users if u.get("added_by") != "bootstrap"]
    if revocable:
        st.subheader("Revoke access")
        c1, c2 = st.columns([4, 1])
        target = c1.selectbox(
            "User", revocable, key="admin_revoke", label_visibility="collapsed"
        )
        if c2.button("Revoke"):
            store.revoke(target)
            st.warning(f"Revoked {target}.")
            st.rerun()


__all__ = ["render_user_admin"]
